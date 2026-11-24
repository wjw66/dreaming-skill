#!/usr/bin/env python3
"""Local, append-only inputs and review-gated Markdown wiki transactions."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
import uuid
from urllib.parse import unquote, urlsplit

from dream_inputs import read_group, tool_boundary
from dream_review import apply_edits, basis_for_run, evidence_manifest, validate_knowledge


class DreamError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise DreamError(f"Refusing symlink: {path}")
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def state_path(wiki):
    return wiki / ".dreaming/state.json"


@contextmanager
def locked(wiki, recovering=False):
    directory = wiki / ".dreaming"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise DreamError("The state directory must not be a symlink")
    lock = directory / "lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise DreamError("Another operation holds the wiki lock; do not remove it until that process has stopped") from exc
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(str(os.getpid()))
        if not recovering and (directory / "transaction.json").exists():
            raise DreamError("An interrupted merge requires recover before any further mutation")
        yield
    finally:
        lock.unlink()


def safe_page(name):
    path = Path(name)
    return (not path.is_absolute() and ".." not in path.parts
            and path.suffix == ".md"
            and (name in ("index.md", "current.md")
                 or (len(path.parts) > 1 and path.parts[0] in ("evidence", "events", "semantic"))))


def pages(root):
    result = {}
    if root.is_symlink():
        raise DreamError(f"Refusing symlink wiki root: {root}")
    if not root.exists():
        return result
    for directory, folders, files in os.walk(root, followlinks=False):
        base = Path(directory)
        if base == root and ".dreaming" in folders:
            folders.remove(".dreaming")
        for name in folders + files:
            if (base / name).is_symlink():
                raise DreamError(f"Wiki pages and directories cannot be symlinks: {base / name}")
        for name in files:
            path = base / name
            if path.suffix == ".md":
                relative = path.relative_to(root).as_posix()
                if not safe_page(relative):
                    raise DreamError(f"Unexpected wiki page: {relative}")
                result[relative] = path.read_bytes()
    return result


def manifest(content):
    return {name: digest(data) for name, data in sorted(content.items())}


def check_links(content):
    for name, data in content.items():
        text = data.decode("utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        for match in re.finditer(r"\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:[ \t]+[^)]*)?\)", text):
            target = match.group(1) or match.group(2)
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_path = Path(os.path.normpath(str(Path(name).parent / unquote(parsed.path))))
            if target_path.is_absolute() or ".." in target_path.parts:
                raise DreamError(f"Link escapes wiki in {name}: {target}")
            if target_path.as_posix() not in content:
                raise DreamError(f"Broken link in {name}: {target}")
        if re.search(r"\[\[[^\]]+\]\]", text):
            raise DreamError(f"Use portable relative Markdown links, not wiki-link syntax: {name}")


def audit(wiki, action, **fields):
    path = wiki / ".dreaming/history" / (uuid.uuid4().hex + ".json")
    atomic(path, encoded({"action": action, "at": datetime.now(timezone.utc).isoformat(), **fields}))


def initialize(args):
    wiki = Path(args.wiki).expanduser().resolve()
    wiki.mkdir(parents=True, exist_ok=True)
    with locked(wiki):
        if state_path(wiki).exists():
            raise DreamError("Wiki already initialized; use configure to change input selection")
        config = selection(args)
        atomic(state_path(wiki), encoded({"version": 2, "config": config, "cursors": {}, "pending": None}))
    registry = Path(args.registry).expanduser()
    atomic(registry, encoded({"wiki": str(wiki)}))
    return {"wiki": str(wiki), "registry": str(registry), "formal_pages_created": 0}


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise DreamError(f"Invalid ISO timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise DreamError("Use an ISO timestamp with an explicit timezone")
    return parsed


def selection(args):
    inputs = [str(Path(p).expanduser().resolve()) for p in args.input]
    if args.host == "files" and not inputs:
        raise DreamError("The files host requires --input")
    if args.scope == "selected" and not inputs:
        raise DreamError("Selected scope requires --input")
    if args.scope == "since" and not args.since:
        raise DreamError("Since scope requires --since")
    parse_time(args.since)
    return {"host": args.host, "scope": args.scope, "since": args.since, "inputs": inputs}


def discover(config, override):
    roots = [Path(p).expanduser().resolve() for p in (override or config["inputs"])]
    if not roots and config["host"] == "codex":
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        roots = [home / "sessions", home / "archived_sessions"]
    files, failures = set(), []
    for root in roots:
        if root.is_symlink():
            failures.append({"source": str(root), "reason": "Symlink input roots are unsupported"})
        elif not root.exists():
            if root.name != "archived_sessions":
                failures.append({"source": str(root), "reason": "Input does not exist"})
        elif root.is_file():
            files.add(root.resolve())
        else:
            for path in root.rglob("*"):
                if path.is_file() and not path.is_symlink() and ".dreaming" not in path.parts and path.suffix.lower() in (".jsonl", ".json", ".md", ".txt"):
                    files.add(path.resolve())
    return sorted(files), failures


def source_identity(path):
    identity = str(path)
    if path.suffix.lower() == ".jsonl":
        with path.open("rb") as stream:
            first = stream.readline()
        try:
            obj = json.loads(first)
            if obj.get("type") == "session_meta":
                payload = obj.get("payload", {})
                identity = "codex:" + str(payload.get("id") or payload.get("session_id") or path)
        except (ValueError, AttributeError):
            pass
    elif path.suffix.lower() == ".json":
        obj = load(path)
        if isinstance(obj, dict) and obj.get("session_id"):
            identity = "export:" + str(obj["session_id"])
    machine = digest(socket.gethostname().encode())[:12]
    return digest((machine + ":" + identity).encode())[:24]


def normalize(obj, number):
    kind, payload = obj.get("type"), obj.get("payload", {})
    if kind == "event_msg" and isinstance(payload, dict) and payload.get("type") == "turn_aborted":
        result = {"kind": "interruption", "reason": payload.get("reason", "Turn explicitly aborted"), "turn_id": payload.get("turn_id") or payload.get("root_turn_id")}
    elif kind == "response_item" and not isinstance(payload, dict):
        raise DreamError("A native response item requires an object payload")
    elif kind == "response_item" and isinstance(payload, dict):
        subtype = payload.get("type")
        if subtype in ("message", "agent_message"):
            role = payload.get("role", "assistant")
            if role in ("system", "developer"):
                return None
            if role not in ("user", "assistant"):
                raise DreamError("Unsupported native message role")
            blocks = payload.get("content", [])
            if not isinstance(blocks, list) or any(not isinstance(block, dict) for block in blocks):
                raise DreamError("Native message content must be an array of object blocks")
            texts = [c.get("text", "") for c in blocks if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text")]
            if any(not isinstance(text, str) for text in texts):
                raise DreamError("Native text blocks require string text")
            text = "\n".join(texts)
            omitted = {}
            for block in blocks:
                if isinstance(block, dict) and block.get("type") not in ("input_text", "output_text", "text"):
                    label = str(block.get("type", "unknown"))
                    omitted[label] = omitted.get(label, 0) + 1
            if not text and not omitted:
                return None
            result = {"kind": "message" if text else "omission", "role": role, "text": text}
            if omitted:
                result["omitted_content"] = omitted
        elif subtype in ("function_call", "custom_tool_call"):
            result = {"kind": "tool_call", "call_id": payload.get("call_id"), "name": payload.get("name"), "input": payload.get("arguments", payload.get("input"))}
        elif subtype in ("function_call_output", "custom_tool_call_output"):
            result = {"kind": "tool_result", "call_id": payload.get("call_id"), "output": payload.get("output")}
        else:
            return None
    elif kind in ("message", "tool_call", "tool_result", "interruption"):
        result = {key: value for key, value in obj.items() if key not in ("timestamp", "id", "ordinal")}
        result["kind"] = result.pop("type")
        if kind == "message" and result.get("role") in ("system", "developer"):
            return None
        if kind == "message" and result.get("role") not in ("user", "assistant"):
            raise DreamError("Unsupported normalized message role")
    elif obj.get("role") in ("user", "assistant"):
        result = {"kind": "message", "role": obj["role"], "text": obj.get("text", obj.get("content", ""))}
    else:
        return None
    if result["kind"] == "message" and not isinstance(result.get("text", result.get("content")), str):
        raise DreamError("Normalized message text must be a string")
    if result["kind"] in ("tool_call", "tool_result") and (not isinstance(result.get("call_id"), str) or not result["call_id"]):
        raise DreamError("Tool calls and results require a non-empty string call_id")
    if not result.get("turn_id"):
        turn = obj.get("turn_id") or (payload.get("turn_id") if isinstance(payload, dict) else None)
        if turn:
            result["turn_id"] = turn
    stable_id = obj.get("id") or (payload.get("id") if kind == "response_item" and isinstance(payload, dict) else None)
    if stable_id:
        result["stable_id"] = str(stable_id)
    result.update(position=number, timestamp=obj.get("timestamp"), event_id=stable_id or obj.get("ordinal"))
    return result


def read_delta(path, cursor, since, defer_tools=True):
    if path.suffix.lower() not in (".jsonl", ".json", ".md", ".txt"):
        raise DreamError("Supported input extensions: .jsonl, .json, .md, .txt")
    previous = cursor.get("offset", 0)
    size = path.stat().st_size
    if size < previous:
        raise DreamError("Input is shorter than its cursor; history edits are outside MVP support")
    events, positions, turns = [], [], {}
    active_turn = cursor.get("turn_id")
    session = None
    if path.suffix.lower() == ".json":
        obj = load(path)
        raw = obj.get("events") if isinstance(obj, dict) else None
        if not isinstance(raw, list):
            raise DreamError("JSON exports require an object with an events array")
        start = cursor.get("event_count", 0)
        if len(raw) < start:
            raise DreamError("The event array is shorter than its cursor")
        for index, event in enumerate(raw[start:], start + 1):
            if not isinstance(event, dict):
                raise DreamError(f"Event {index} is not an object")
            if event.get("type") not in ("message", "tool_call", "tool_result", "interruption") and event.get("role") not in ("user", "assistant"):
                raise DreamError(f"Unsupported normalized event type at event {index}")
            positions.append((index, index))
            normalized = normalize(event, index)
            if normalized and normalized.get("turn_id"):
                active_turn = normalized["turn_id"]
            if normalized and active_turn and not normalized.get("turn_id"):
                normalized["turn_id"] = active_turn
            turns[str(index)] = active_turn
            events.append((index, normalized))
        end = len(raw)
        session = obj.get("session_id")
        mode = "event_count"
    elif path.suffix.lower() == ".jsonl":
        with path.open("rb") as stream:
            first = stream.readline()
            try:
                meta = json.loads(first)
                if meta.get("type") == "session_meta":
                    session = meta.get("payload", {}).get("id", meta.get("payload", {}).get("session_id"))
            except (ValueError, AttributeError):
                pass
            stream.seek(previous)
            line_number = cursor.get("line", 0)
            end = previous
            while stream.tell() < size:
                line = stream.readline(size - stream.tell())
                if not line.endswith(b"\n"):
                    break
                line_number += 1
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise DreamError(f"Invalid JSON at line {line_number}") from exc
                if not isinstance(obj, dict):
                    raise DreamError(f"Line {line_number} is not an object")
                known = {"session_meta", "event_msg", "response_item", "turn_context", "world_state", "compacted", "token_usage_record", "inter_agent_communication_metadata", "message", "tool_call", "tool_result", "interruption"}
                if obj.get("type") not in known and obj.get("role") not in ("user", "assistant"):
                    raise DreamError(f"Unsupported record type at line {line_number}: {obj.get('type')}")
                pos = stream.tell()
                positions.append((line_number, pos))
                payload = obj.get("payload", {})
                if isinstance(payload, dict) and (obj.get("type") == "turn_context" or (obj.get("type") == "event_msg" and payload.get("type") == "task_started")):
                    active_turn = payload.get("turn_id") or active_turn
                normalized = normalize(obj, line_number)
                if normalized and active_turn and not normalized.get("turn_id"):
                    normalized["turn_id"] = active_turn
                turns[str(line_number)] = active_turn
                events.append((line_number, normalized))
                end = pos
        mode = "offset"
    else:
        if since:
            raise DreamError("Undated text cannot be filtered by date; import it explicitly without --since")
        with path.open("rb") as stream:
            stream.seek(previous)
            data = stream.read(size - previous)
        complete = data.rfind(b"\n") + 1
        if complete:
            events = [(cursor.get("line", 0) + 1, {"kind": "unstructured", "text": data[:complete].decode("utf-8"), "position": previous, "timestamp": None})]
            positions = [(events[0][0], previous + complete)]
        end = previous + complete
        mode = "offset"
    relevant = [(n, e) for n, e in events if e is not None]
    boundary_index, cancelled = tool_boundary([event for _, event in relevant])
    boundary = relevant[boundary_index][0] if boundary_index < len(relevant) else None
    if defer_tools:
        for index, terminal in cancelled.items():
            relevant[index][1].update(outcome="cancelled", cancelled_at=relevant[terminal][0])
    if not defer_tools:
        boundary = None
    if boundary is not None:
        relevant = [(n, e) for n, e in relevant if n < boundary]
        allowed = [(n, pos) for n, pos in positions if n < boundary]
        end = allowed[-1][1] if allowed else (cursor.get("event_count", 0) if mode == "event_count" else previous)
        positions = allowed
    filtered = []
    for _, event in relevant:
        if since:
            timestamp = parse_time(event.get("timestamp"))
            if timestamp is None:
                raise DreamError("A relevant event has no timestamp; date filtering cannot be verified")
            if timestamp < since:
                continue
        filtered.append(event)
    next_cursor = {mode: end}
    last_position = positions[-1][0] if positions else None
    final_turn = turns.get(str(last_position), cursor.get("turn_id"))
    if final_turn:
        next_cursor["turn_id"] = final_turn
    if mode == "offset":
        next_cursor["line"] = positions[-1][0] if positions else cursor.get("line", 0)
    return {"session_id": session, "events": filtered, "next_cursor": next_cursor, "deferred_tool_call": boundary is not None,
            "deferred_tail": (end < len(raw)) if mode == "event_count" else (end < size),
            "positions": positions, "turns": turns,
            "coverage": "unstructured text; tool/result completeness is not verifiable" if path.suffix.lower() in (".txt", ".md") else "supported messages, tool exchanges, interruption and omission markers; other reasoning/system/runtime events omitted"}


def wiki_argument(args):
    if args.wiki:
        return Path(args.wiki).expanduser().resolve()
    registry = Path(args.registry).expanduser()
    if not registry.exists():
        raise DreamError("No wiki configured; ask the user for a location and initial input scope, then run init")
    return Path(load(registry)["wiki"]).expanduser().resolve()


def scan(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        state = load(state_path(wiki))
        if args.reselect_pending and (not args.revise or not state["pending"]):
            raise DreamError("Reselecting pending memories requires --revise and a pending proposal")
        if (wiki / ".dreaming/transaction.json").exists():
            raise DreamError("An interrupted merge requires recover before continuing")
        config = state["config"]
        files, failures = discover(config, args.input)
        if any(wiki == path or wiki in path.parents for path in files):
            raise DreamError("The wiki cannot be used as its own transcript input")
        since = parse_time(args.since or config.get("since"))
        items, advances, deferred, omissions = [], {}, [], []
        candidates = {}
        for path in files:
            try:
                key = source_identity(path)
                candidates.setdefault(key, []).append(path)
            except (OSError, ValueError) as exc:
                failures.append({"source": str(path), "reason": str(exc)})
        for key, paths in candidates.items():
            path = paths[0]
            cursor = state["cursors"].get(key, {})
            try:
                item = read_group(wiki, key, paths, cursor, since, read_delta, normalize, parse_time)
                if item["omitted_content"]:
                    omissions.append({"source_id": key, "types": item["omitted_content"]})
                if item["deferred_tool_call"] or item["deferred_tail"]:
                    deferred.append({"source": str(path), "source_id": key, "unfinished_tools": item["deferred_tool_call"], "unconsumed_tail": item["deferred_tail"]})
                if item["events"]:
                    items.append(item)
                elif item["next_cursor"] != cursor:
                    advances[key] = item["next_cursor"]
            except (OSError, UnicodeError, ValueError, DreamError) as exc:
                failures.append({"source": str(path), "reason": str(exc)})
        if not items and not advances and not args.revise:
            return {"new_inputs": 0, "failures": failures, "deferred": deferred, "omissions": omissions, "pending": state["pending"], "message": "No analyzable increment; no cursor or formal page changed"}
        run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        directory = wiki / ".dreaming/runs" / run
        directory.mkdir(parents=True, mode=0o700)
        draft = directory / "draft"
        formal = pages(wiki)
        effective = dict(formal)
        parent_directory = None
        if state["pending"]:
            _, parent_directory, parent_seal = pending(wiki, state["pending"]["revision"])
            parent_pages = pages(parent_directory / "draft")
            for name, data in parent_pages.items() if not args.reselect_pending else ():
                if digest(data) != parent_seal["base_wiki"].get(name):
                    if manifest(formal).get(name) != parent_seal["base_wiki"].get(name):
                        raise DreamError(f"Formal page conflicts with a pending edit: {name}; reconcile before revising")
                    effective[name] = data
        for name, data in effective.items():
            atomic(draft / name, data)
            if name.startswith("evidence/"):
                atomic(directory / "evidence-preimages" / name, data)
        draft.mkdir(exist_ok=True)
        for item in items:
            atomic(directory / "inputs" / (item["source_id"] + ".json"), encoded(item))
        record = {"run": run, "base_state": digest(encoded(state)), "base_wiki": manifest(formal),
                  "parent_pending": state["pending"], "reselect_pending": args.reselect_pending, "sources": [{k: v for k, v in item.items() if k != "events"} for item in items],
                  "empty_advances": advances, "failures": failures, "deferred": deferred, "omissions": omissions, "discovered_files": len(files), "draft_base": manifest(effective)}
        atomic(directory / "scan.json", encoded(record))
        basis_parent = parent_directory or (run_path(wiki, state["analysis_run"]) if state.get("analysis_run") else None)
        atomic(directory / "basis.json", encoded(basis_for_run(directory, basis_parent)))
        return {"run": run, "directory": str(directory), "new_inputs": len(items), "failures": failures, "deferred": deferred, "omissions": omissions,
                "pending_inherited": bool(state["pending"]) and not args.reselect_pending, "evidence_inherited": bool(basis_parent), "next": "Analyze inputs, edit draft only, write review.json, then stage"}


def run_path(wiki, run):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run):
        raise DreamError("Invalid run ID")
    return wiki / ".dreaming/runs" / run


def validate_review(review, scan_record, formal, proposed):
    expected = {item["source_id"] for item in scan_record["sources"]}
    processed = review.get("processed", [])
    failures = review.get("failures", [])
    failed = [failure["source_id"] for failure in failures]
    if len(set(processed + failed)) != len(processed + failed) or set(processed + failed) != expected:
        raise DreamError("Every scan source must be accounted for exactly once as processed or failed")
    if review.get("organized") is not True:
        raise DreamError("The final organizer pass must complete before staging")
    if any(not failure.get("reason") for failure in failures):
        raise DreamError("Every failed input needs a reason")
    if set(formal) - set(proposed):
        raise DreamError("Do not delete pages in MVP; merge content and retain a linked redirect page")
    changed = {name for name in proposed if proposed[name] != formal.get(name)}
    groups = review.get("groups", [])
    ids, assigned = set(), []
    for group in groups:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", group["id"]) or group["id"] in ids:
            raise DreamError("Review groups require unique simple IDs")
        if not group.get("summary") or not group.get("paths"):
            raise DreamError("Each group requires a summary and changed paths")
        ids.add(group["id"])
        assigned.extend(group["paths"])
    if len(assigned) != len(set(assigned)) or set(assigned) != changed:
        raise DreamError("Assign every changed page to exactly one review group")
    for group in groups:
        if not set(group.get("depends_on", [])).issubset(ids - {group["id"]}):
            raise DreamError("Group dependencies must name other existing groups")
    if changed:
        if "index.md" not in proposed or "current.md" not in proposed:
            raise DreamError("A wiki requires index.md and current.md")
        check_links(proposed)
    return changed


def stage(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        state = load(state_path(wiki))
        directory = run_path(wiki, args.run)
        record = load(directory / "scan.json")
        if digest(encoded(state)) != record["base_state"]:
            raise DreamError("State changed since scan; scan again and inherit the latest pending draft")
        formal, proposed = pages(wiki), pages(directory / "draft")
        if manifest(formal) != record["base_wiki"]:
            raise DreamError("Formal wiki changed since scan; regenerate the proposal against current pages")
        review = load(directory / "review.json")
        changed = validate_review(review, record, formal, proposed)
        validate_knowledge(directory, review, record, proposed, digest)
        cursors = dict(state["cursors"])
        cursors.update(record["empty_advances"])
        for source in record["sources"]:
            if source["source_id"] in review["processed"]:
                cursors[source["source_id"]] = source["next_cursor"]
        seal = {"run": args.run, "review": review, "base_wiki": record["base_wiki"], "draft": manifest(proposed), "basis": digest((directory / "basis.json").read_bytes()), "snapshots": evidence_manifest(directory, review)}
        revision = digest(encoded(seal))
        atomic(directory / "sealed.json", encoded({**seal, "revision": revision}))
        differences = []
        for name in sorted(changed):
            differences.extend(difflib.unified_diff(formal.get(name, b"").decode().splitlines(True), proposed[name].decode().splitlines(True), fromfile="formal/" + name, tofile="proposed/" + name))
        atomic(directory / "changes.diff", "".join(differences).encode())
        summary = ["# Pending Dream Review", "", review.get("summary", ""), "", f"Revision: `{revision}`", "",
                   f"Inputs processed: {len(review['processed'])}; analysis failures: {len(review['failures'])}; discovery/read failures: {len(record['failures'])}; deferred inputs: {len(record['deferred'])}.", ""]
        summary += [f"- {group['id']}: {group['summary']} ({', '.join(group['paths'])})" for group in review["groups"]]
        if record.get("omissions"):
            summary += ["", "Non-text content was omitted: " + json.dumps(record["omissions"], ensure_ascii=False)]
        summary += ["", "See review.json for evidence and caveats, and changes.diff for the complete changes.", "", "No formal wiki page has been changed.", ""]
        atomic(directory / "review.md", "\n".join(summary).encode())
        if state.get("version") == 1 and not (wiki / ".dreaming/state-v1-backup.json").exists():
            atomic(wiki / ".dreaming/state-v1-backup.json", encoded(state))
        state.update(version=2, analysis_run=args.run, cursors=cursors, pending={"run": args.run, "revision": revision} if changed else None)
        atomic(state_path(wiki), encoded(state))
        return {"revision": revision, "changed_pages": len(changed), "pending": state["pending"], "review": str(directory / "review.md")}


def pending(wiki, revision):
    state = load(state_path(wiki))
    proposal = state.get("pending")
    if not proposal or proposal["revision"] != revision:
        raise DreamError("Approval must name the current pending revision")
    directory = run_path(wiki, proposal["run"])
    sealed = load(directory / "sealed.json")
    check = {k: v for k, v in sealed.items() if k != "revision"}
    if digest(encoded(check)) != revision or manifest(pages(directory / "draft")) != sealed["draft"]:
        raise DreamError("The reviewed proposal was modified; regenerate review and obtain fresh approval")
    if "basis" in sealed and digest((directory / "basis.json").read_bytes()) != sealed["basis"]:
        raise DreamError("The reviewed evidence basis was modified; obtain a fresh review")
    for relative, expected in sealed.get("snapshots", {}).items():
        if digest((directory.parent / relative).read_bytes()) != expected:
            raise DreamError("A reviewed evidence snapshot was modified; obtain a fresh review")
    if load(directory / "review.json") != sealed["review"]:
        raise DreamError("The review was modified after staging")
    return state, directory, sealed


def restore(wiki, transaction):
    directory = run_path(wiki, transaction["run"])
    current = manifest(pages(wiki))
    for name, before in transaction["before"].items():
        if current.get(name) not in (before, transaction["after"][name]):
            raise DreamError(f"External edit detected in {name}; retaining the transaction for manual reconciliation")
    for name, old_hash in transaction["before"].items():
        target = wiki / name
        if old_hash is None:
            if target.exists():
                target.unlink()
        else:
            data = (directory / "backup" / name).read_bytes()
            if digest(data) != old_hash:
                raise DreamError("Backup integrity check failed; stop and inspect the transaction")
            atomic(target, data)
    atomic(state_path(wiki), (directory / "backup-state.json").read_bytes())
    (wiki / ".dreaming/transaction.json").unlink()


def apply(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        if (wiki / ".dreaming/transaction.json").exists():
            raise DreamError("Run recover before another merge")
        state, directory, sealed = pending(wiki, args.revision)
        formal, proposed = pages(wiki), pages(directory / "draft")
        if manifest(formal) != sealed["base_wiki"]:
            raise DreamError("Formal wiki changed after review; do not overwrite it")
        groups = {g["id"]: g for g in sealed["review"]["groups"]}
        selected = set(groups) if args.groups == "all" else set(args.groups.split(","))
        if not selected or not selected.issubset(groups):
            raise DreamError("Select existing review group IDs or all")
        for group in selected:
            if not set(groups[group].get("depends_on", [])).issubset(selected):
                raise DreamError("Selected groups omit a required dependency; revise the proposal before approval")
        paths = {name for group in selected for name in groups[group]["paths"]}
        result = {**formal, **{name: proposed[name] for name in paths}}
        if not {"index.md", "current.md"}.issubset(result):
            raise DreamError("Partial acceptance omits wiki entry pages; revise the proposal")
        check_links(result)
        before = {name: digest(formal[name]) if name in formal else None for name in paths}
        for name in paths:
            if name in formal:
                atomic(directory / "backup" / name, formal[name])
        atomic(directory / "backup-state.json", encoded(state))
        transaction = {"run": sealed["run"], "revision": args.revision, "before": before,
                       "after": {name: digest(result[name]) for name in paths}}
        atomic(wiki / ".dreaming/transaction.json", encoded(transaction))
        try:
            for name in sorted(paths):
                atomic(wiki / name, proposed[name])
            state["pending"] = None
            atomic(state_path(wiki), encoded(state))
            audit(wiki, "approved", revision=args.revision, accepted=sorted(selected), rejected=sorted(set(groups) - selected), review=sealed["review"])
        except BaseException:
            restore(wiki, transaction)
            raise
        (wiki / ".dreaming/transaction.json").unlink()
        return {"applied": sorted(paths), "rejected_groups": sorted(set(groups) - selected), "revision": args.revision}


def reject(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        state, _, sealed = pending(wiki, args.revision)
        audit(wiki, "rejected", revision=args.revision, reason=args.reason, review=sealed["review"])
        state["pending"] = None
        atomic(state_path(wiki), encoded(state))
        return {"rejected": args.revision, "formal_wiki_changed": False}


def recover(args):
    wiki = wiki_argument(args)
    with locked(wiki, recovering=True):
        journal = wiki / ".dreaming/transaction.json"
        if not journal.exists():
            return {"message": "No interrupted merge"}
        transaction = load(journal)
        restore(wiki, transaction)
        audit(wiki, "recovered", revision=transaction["revision"])
        return {"restored": transaction["revision"], "message": "Formal pages restored; the proposal remains pending"}


def status(args):
    wiki = wiki_argument(args)
    state = load(state_path(wiki))
    return {"wiki": str(wiki), "config": state["config"], "tracked_sources": len(state["cursors"]),
            "pending": state["pending"], "recovery_required": (wiki / ".dreaming/transaction.json").exists()}


def configure(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        state = load(state_path(wiki))
        state["config"] = selection(args)
        atomic(state_path(wiki), encoded(state))
    return {"config": state["config"], "message": "Existing cursors retained; changing scope does not backfill already processed history"}


def patch_draft(args):
    wiki = wiki_argument(args)
    with locked(wiki):
        directory = run_path(wiki, args.run)
        return apply_edits(directory, load(Path(args.edits)), pages, atomic, encoded, digest, safe_page)


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    registry = str(Path.home() / ".config/dreaming-skill/config.json")
    for name, handler in (("init", initialize), ("configure", configure), ("scan", scan), ("stage", stage), ("patch", patch_draft), ("apply", apply), ("reject", reject), ("recover", recover), ("status", status)):
        command = commands.add_parser(name)
        command.set_defaults(handler=handler)
        command.add_argument("--wiki", required=name == "init")
        command.add_argument("--registry", default=registry)
        if name in ("init", "configure"):
            command.add_argument("--host", choices=("codex", "files"), required=True)
            command.add_argument("--scope", choices=("all", "since", "selected"), required=True)
        if name in ("init", "configure", "scan"):
            command.add_argument("--input", action="append", default=[])
            command.add_argument("--since")
        if name == "scan":
            command.add_argument("--revise", action="store_true", help="Prepare a fresh review even without new source content")
            command.add_argument("--reselect-pending", action="store_true", help="Start a user-requested reselection from formal pages; retain prior evidence and sealed drafts")
        if name == "patch":
            command.add_argument("--edits", required=True)
        if name in ("stage", "patch"):
            command.add_argument("--run", required=True)
        if name in ("apply", "reject"):
            command.add_argument("--revision", required=True)
        if name == "apply":
            command.add_argument("--groups", required=True)
        if name == "reject":
            command.add_argument("--reason", required=True)
    return cli


def main():
    args = parser().parse_args()
    try:
        print(json.dumps(args.handler(args), ensure_ascii=False, indent=2))
    except (DreamError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
