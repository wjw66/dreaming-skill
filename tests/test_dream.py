import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

SPEC = importlib.util.spec_from_file_location("dream", Path(__file__).parents[1] / "scripts/dream.py")
dream = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dream)


class DreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wiki = self.root / "wiki"
        self.source = self.root / "session.jsonl"
        self.append({"type": "message", "role": "user", "text": "For Atlas only, keep CSV.", "timestamp": "2026-11-24T09:00:00+08:00"})
        self.registry = self.root / "registry.json"
        self.call("init", "--wiki", str(self.wiki), "--host", "files", "--scope", "selected", "--input", str(self.source))

    def call(self, command, *flags):
        args = dream.parser().parse_args([command, "--registry", str(self.registry), *flags])
        return args.handler(args)

    def append(self, *events):
        with self.source.open("a") as stream:
            for event in events:
                stream.write(json.dumps(event) + "\n")

    def state(self):
        return dream.load(dream.state_path(self.wiki))

    def prepare(self, scan=None, failed=(), extra=None, groups=None):
        scan = scan or self.call("scan")
        directory = Path(scan["directory"])
        files = {"index.md": b"# Wiki\n\n[Atlas](semantic/projects/atlas.md)\n",
                 "current.md": b"# Current\n\n[Atlas](semantic/projects/atlas.md)\n",
                 "evidence/atlas.md": b"# Evidence\n\nUser, session.jsonl, line 1: For Atlas only, keep CSV.\n",
                 "semantic/projects/atlas.md": b"# Atlas\n\nKeep CSV for Atlas only. [Evidence](../../evidence/atlas.md).\n"}
        if extra:
            files.update(extra)
        edits = []
        for name, value in files.items():
            target = directory / "draft" / name
            if target.exists() and target.read_bytes() != value and not name.startswith("evidence/"):
                edits.append({"path": name, "old": target.read_text(), "new": value.decode(), "kind": "knowledge", "fact_ids": ["atlas-rule"]})
            else:
                dream.atomic(target, value)
        if edits:
            dream.atomic(directory / "edits.json", dream.encoded(edits))
            self.call("patch", "--run", scan["run"], "--edits", str(directory / "edits.json"))
        record = dream.load(directory / "scan.json")
        processed = [s["source_id"] for s in record["sources"] if s["source_id"] not in failed]
        changed = [name for name, data in dream.pages(directory / "draft").items() if dream.pages(self.wiki).get(name) != data]
        review = {"summary": "Record scoped Atlas requirements.", "processed": processed,
                  "failures": [{"source_id": source, "reason": "Analysis unavailable"} for source in failed],
                  "organized": True, "groups": groups if groups is not None else ([{"id": "atlas", "summary": "Scoped CSV preference with evidence", "paths": changed, "depends_on": []}] if changed else [])}
        self.account_review(review, directory)
        dream.atomic(directory / "review.json", dream.encoded(review))
        return scan, directory

    def account_review(self, review, directory):
        basis = dream.load(directory / "basis.json")
        entry = next((e for e in basis.values() if not e.get("context_only")), None)
        original = next((e for e in dream.load(directory.parent / entry["origin_run"] / "inputs" / (entry["source_id"] + ".json"))["events"] if e["ref"] == entry["ref"]), None) if entry else None
        review["input_decisions"] = [{"source_id": source, "reason": "Analyzed the scoped Atlas requirement."} for source in review["processed"]]
        for group in review["groups"]:
            group.setdefault("kind", "knowledge")
            group.setdefault("fact_ids", ["atlas-rule"])
        review["facts"] = [{"id": "atlas-rule", "statement": "For Atlas only, keep CSV.", "subject": "Atlas", "facet": "export", "scope": "Atlas only", "status": "explicit", "action": "add", "reason": "Explicit user requirement", "evidence": [{"source_id": entry["source_id"], "ref": entry["ref"], "quote": original["text"], "page": "evidence/atlas.md"}], "targets": ["semantic/projects/atlas.md"]}] if review["groups"] else []
        formal = dream.pages(self.wiki)
        review["consistency_checks"] = [{"path": name, "outcome": "updated" if data != formal.get(name) else "unchanged", "reason": "Checked the scoped rule and navigation."} for name, data in dream.pages(directory / "draft").items()]

    def stage_initial(self):
        scan, directory = self.prepare()
        staged = self.call("stage", "--run", scan["run"])
        return staged, directory

    def test_initialization_and_staging_never_mutate_formal_wiki(self):
        self.assertEqual({}, dream.pages(self.wiki))
        staged, directory = self.stage_initial()
        self.assertEqual({}, dream.pages(self.wiki))
        self.assertTrue(self.state()["cursors"])
        self.assertTrue((directory / "changes.diff").is_file())
        self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertIn("semantic/projects/atlas.md", dream.pages(self.wiki))
        self.assertIsNone(self.state()["pending"])

    def test_only_new_turn_is_emitted_and_pending_draft_is_inherited(self):
        staged, directory = self.stage_initial()
        self.append({"type": "message", "role": "user", "text": "Also preserve column order."})
        scan = self.call("scan")
        self.assertTrue(scan["pending_inherited"])
        inputs = list((Path(scan["directory"]) / "inputs").glob("*.json"))
        events = dream.load(inputs[0])["events"]
        self.assertEqual(["Also preserve column order."], [e["text"] for e in events])
        self.assertEqual((directory / "draft/semantic/projects/atlas.md").read_bytes(), (Path(scan["directory"]) / "draft/semantic/projects/atlas.md").read_bytes())
        self.assertEqual({}, dream.pages(self.wiki))

    def test_rejected_changes_do_not_repeat_without_new_evidence(self):
        staged, _ = self.stage_initial()
        self.call("reject", "--revision", staged["revision"], "--reason", "Too broad")
        scan = self.call("scan")
        self.assertEqual(0, scan["new_inputs"])
        self.assertNotIn("run", scan)
        self.assertEqual({}, dream.pages(self.wiki))
        self.assertTrue(list((self.wiki / ".dreaming/history").glob("*.json")))

    def test_pending_can_be_revised_without_new_transcript_content(self):
        first, _ = self.stage_initial()
        scan = self.call("scan", "--revise")
        scan, directory = self.prepare(scan, extra={"semantic/projects/atlas.md": b"# Atlas\n\nKeep CSV only for Atlas, not every project. [Evidence](../../evidence/atlas.md).\n"})
        second = self.call("stage", "--run", scan["run"])
        self.assertNotEqual(first["revision"], second["revision"])
        with self.assertRaises(dream.DreamError):
            self.call("apply", "--revision", first["revision"], "--groups", "all")

    def test_failed_input_retains_its_analysis_position(self):
        scan = self.call("scan")
        record = dream.load(Path(scan["directory"]) / "scan.json")
        source = record["sources"][0]["source_id"]
        directory = Path(scan["directory"])
        dream.atomic(directory / "review.json", dream.encoded({"summary": "Analysis failed", "processed": [], "failures": [{"source_id": source, "reason": "Read failed"}], "organized": True, "groups": [], "facts": [], "input_decisions": []}))
        self.call("stage", "--run", scan["run"])
        self.assertNotIn(source, self.state()["cursors"])
        retry = self.call("scan")
        self.assertEqual(1, retry["new_inputs"])

    def test_unaccounted_input_cannot_advance_progress(self):
        scan, directory = self.prepare()
        review = dream.load(directory / "review.json")
        review["processed"] = []
        dream.atomic(directory / "review.json", dream.encoded(review))
        with self.assertRaises(dream.DreamError):
            self.call("stage", "--run", scan["run"])
        self.assertEqual({}, self.state()["cursors"])

    def test_draft_edit_invalidates_sealed_approval(self):
        staged, directory = self.stage_initial()
        dream.atomic(directory / "draft/current.md", b"# Changed after review\n")
        with self.assertRaises(dream.DreamError):
            self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertEqual({}, dream.pages(self.wiki))

    def test_external_formal_edit_blocks_merge(self):
        staged, _ = self.stage_initial()
        dream.atomic(self.wiki / "current.md", b"# External edit\n")
        with self.assertRaises(dream.DreamError):
            self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertEqual(b"# External edit\n", (self.wiki / "current.md").read_bytes())

    def test_unfinished_tool_exchange_and_partial_line_are_deferred(self):
        self.append({"type": "tool_call", "call_id": "c1", "name": "test", "input": {}})
        first = dream.read_delta(self.source, {}, None)
        self.assertEqual(["message"], [e["kind"] for e in first["events"]])
        self.assertTrue(first["deferred_tool_call"])
        with self.source.open("a") as stream:
            stream.write('{"type":"tool_result","call_id":"c1","output":"passed"}')
        still = dream.read_delta(self.source, first["next_cursor"], None)
        self.assertEqual([], still["events"])
        with self.source.open("a") as stream:
            stream.write("\n")
        final = dream.read_delta(self.source, first["next_cursor"], None)
        self.assertEqual(["tool_call", "tool_result"], [e["kind"] for e in final["events"]])

    def test_later_appends_are_outside_the_frozen_scan(self):
        scan = self.call("scan")
        self.append({"type": "message", "role": "user", "text": "Arrived later"})
        self.prepare(scan)
        self.call("stage", "--run", scan["run"])
        next_scan = self.call("scan")
        item = dream.load(next((Path(next_scan["directory"]) / "inputs").glob("*.json")))
        self.assertEqual(["Arrived later"], [e["text"] for e in item["events"]])

    def test_native_archival_keeps_source_identity_and_cursor(self):
        native = self.root / "native.jsonl"
        native.write_text(json.dumps({"type": "session_meta", "payload": {"id": "stable-session"}}) + "\n" + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Hi"}]}}) + "\n")
        identity = dream.source_identity(native)
        delta = dream.read_delta(native, {}, None)
        moved = self.root / "archived.jsonl"
        native.rename(moved)
        self.assertEqual(identity, dream.source_identity(moved))
        self.assertEqual([], dream.read_delta(moved, delta["next_cursor"], None)["events"])

    def test_invalid_source_does_not_silently_advance(self):
        self.append({"unknown": "unrecognized export"})
        scan = self.call("scan")
        self.assertEqual(0, scan["new_inputs"])
        self.assertEqual(1, len(scan["failures"]))
        self.assertEqual({}, self.state()["cursors"])

    def test_broken_links_and_symlink_drafts_are_rejected(self):
        scan, directory = self.prepare(extra={"current.md": b"[Missing](events/missing.md)\n"})
        with self.assertRaises(dream.DreamError):
            self.call("stage", "--run", scan["run"])
        (directory / "draft/current.md").unlink()
        (directory / "draft/current.md").symlink_to(self.source)
        with self.assertRaises(dream.DreamError):
            self.call("stage", "--run", scan["run"])

    def test_stale_parallel_scan_cannot_replace_pending_state(self):
        scan1, _ = self.prepare()
        scan2, _ = self.prepare()
        self.call("stage", "--run", scan1["run"])
        with self.assertRaises(dream.DreamError):
            self.call("stage", "--run", scan2["run"])

    def test_partial_acceptance_requires_dependencies_and_valid_links(self):
        scan, directory = self.prepare()
        review = dream.load(directory / "review.json")
        review["groups"] = [{"id": "entry", "summary": "Navigation", "paths": ["index.md", "current.md"], "depends_on": ["content"]}, {"id": "content", "summary": "Content", "paths": ["evidence/atlas.md", "semantic/projects/atlas.md"], "depends_on": []}]
        self.account_review(review, directory)
        dream.atomic(directory / "review.json", dream.encoded(review))
        staged = self.call("stage", "--run", scan["run"])
        for groups in ("entry", "content"):
            with self.assertRaises(dream.DreamError):
                self.call("apply", "--revision", staged["revision"], "--groups", groups)
        self.assertEqual({}, dream.pages(self.wiki))
        self.call("apply", "--revision", staged["revision"], "--groups", "all")

    def test_write_failure_restores_formal_pages_and_pending_review(self):
        staged, _ = self.stage_initial()
        original = dream.atomic
        calls = []

        def fail_once(path, data):
            if path.parent.resolve() == self.wiki.resolve():
                calls.append(str(path))
                if len(calls) == 2:
                    raise OSError("Simulated disk write failure")
            return original(path, data)

        with patch.object(dream, "atomic", side_effect=fail_once):
            with self.assertRaises(OSError):
                self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertEqual({}, dream.pages(self.wiki))
        self.assertEqual(staged["revision"], self.state()["pending"]["revision"])
        self.assertFalse((self.wiki / ".dreaming/transaction.json").exists())

    def test_interrupted_merge_can_be_recovered(self):
        staged, _ = self.stage_initial()
        original = dream.atomic
        writes = []

        def fail(path, data):
            if path.parent.resolve() == self.wiki.resolve():
                writes.append(path)
                if len(writes) == 2:
                    raise OSError("Interrupted")
            return original(path, data)

        with patch.object(dream, "atomic", side_effect=fail), patch.object(dream, "restore", side_effect=OSError("Process stopped before recovery")):
            with self.assertRaises(OSError):
                self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertTrue((self.wiki / ".dreaming/transaction.json").exists())
        self.call("recover")
        self.assertEqual({}, dream.pages(self.wiki))
        self.assertEqual(staged["revision"], self.state()["pending"]["revision"])

    def test_date_filter_and_text_limitations_are_explicit(self):
        delta = dream.read_delta(self.source, {}, dream.parse_time("2026-11-24T10:00:00+08:00"))
        self.assertEqual([], delta["events"])
        text = self.root / "notes.md"
        text.write_text("A dated scope cannot be verified here.\n")
        with self.assertRaises(dream.DreamError):
            dream.read_delta(text, {}, dream.parse_time("2026-11-24T00:00:00+08:00"))
        delta = dream.read_delta(text, {}, None)
        self.assertIn("not verifiable", delta["coverage"])

    def test_valid_partial_acceptance_logs_unselected_changes(self):
        initial, _ = self.stage_initial()
        self.call("apply", "--revision", initial["revision"], "--groups", "all")
        self.append({"type": "message", "role": "user", "text": "Atlas keeps CSV; review the column order later."})
        scan, directory = self.prepare(extra={"current.md": b"# Current\n\nReview column order later. [Atlas](semantic/projects/atlas.md).\n", "semantic/projects/atlas.md": b"# Atlas\n\nKeep CSV for Atlas only; column order remains undecided. [Evidence](../../evidence/atlas.md).\n"})
        review = dream.load(directory / "review.json")
        review["groups"] = [{"id": "status", "summary": "Current reminder", "paths": ["current.md"], "depends_on": []}, {"id": "scope", "summary": "Qualify current project rule", "paths": ["semantic/projects/atlas.md"], "depends_on": []}]
        self.account_review(review, directory)
        dream.atomic(directory / "review.json", dream.encoded(review))
        staged = self.call("stage", "--run", scan["run"])
        before = (self.wiki / "current.md").read_bytes()
        result = self.call("apply", "--revision", staged["revision"], "--groups", "scope")
        self.assertEqual(["status"], result["rejected_groups"])
        self.assertEqual(before, (self.wiki / "current.md").read_bytes())
        self.assertIn("undecided", (self.wiki / "semantic/projects/atlas.md").read_text())
        self.assertIsNone(self.state()["pending"])

    def test_read_failure_does_not_prevent_other_inputs_from_progressing(self):
        bad = self.root / "bad.jsonl"
        bad.write_text("not json\n")
        scan = self.call("scan", "--input", str(self.source), "--input", str(bad))
        self.assertEqual(1, len(scan["failures"]))
        self.prepare(scan)
        self.call("stage", "--run", scan["run"])
        retry = self.call("scan", "--input", str(self.source), "--input", str(bad))
        self.assertEqual(0, retry["new_inputs"])
        self.assertEqual(1, len(retry["failures"]))

    def test_native_agent_author_is_not_a_conversation_role(self):
        event = {"type": "response_item", "payload": {"type": "agent_message", "author": "agent-identifier", "content": [{"type": "input_text", "text": "Observed a failure, not a verified rule."}]}}
        result = dream.normalize(event, 7)
        self.assertEqual("assistant", result["role"])
        self.assertEqual("Observed a failure, not a verified rule.", result["text"])

    def test_parallel_tool_exchanges_are_not_split_across_increments(self):
        suffix = [{"type": "tool_call", "call_id": "a", "name": "first"}, {"type": "tool_call", "call_id": "b", "name": "second"}, {"type": "tool_result", "call_id": "a", "output": "done"}]
        self.append(*suffix)
        first = dream.read_delta(self.source, {}, None)
        self.assertEqual(["message"], [e["kind"] for e in first["events"]])
        self.append({"type": "tool_result", "call_id": "b", "output": "done"})
        second = dream.read_delta(self.source, first["next_cursor"], None)
        self.assertEqual(["a", "b", "a", "b"], [e["call_id"] for e in second["events"]])
        exported = self.root / "parallel.json"
        events = [{"type": "message", "role": "user", "text": "Start"}] + suffix
        exported.write_text(json.dumps({"events": events}))
        first = dream.read_delta(exported, {}, None)
        self.assertEqual(1, first["next_cursor"]["event_count"])
        events.append({"type": "tool_result", "call_id": "b", "output": "done"})
        exported.write_text(json.dumps({"events": events}))
        second = dream.read_delta(exported, first["next_cursor"], None)
        self.assertEqual(["a", "b", "a", "b"], [e["call_id"] for e in second["events"]])

    def test_ordinary_markdown_punctuation_is_not_part_of_a_link(self):
        dream.check_links({"index.md": b"- [Current](current.md): open decisions.\n- [Evidence](evidence/a.md)\n", "current.md": b"# Current\n", "evidence/a.md": b"# Evidence\n"})

    def test_rollback_preserves_external_edits_and_journal(self):
        staged, _ = self.stage_initial()
        original = dream.atomic
        writes = []

        def fail_after_edit(path, data):
            if path.parent.resolve() == self.wiki.resolve():
                writes.append(path)
                if len(writes) == 2:
                    writes[0].write_text("External editor must survive\n")
                    raise OSError("Write interrupted")
            return original(path, data)

        with patch.object(dream, "atomic", side_effect=fail_after_edit):
            with self.assertRaises(dream.DreamError):
                self.call("apply", "--revision", staged["revision"], "--groups", "all")
        self.assertEqual("External editor must survive\n", writes[0].read_text())
        self.assertTrue((self.wiki / ".dreaming/transaction.json").exists())
        with self.assertRaises(dream.DreamError):
            self.call("reject", "--revision", staged["revision"], "--reason", "Not during recovery")

    def test_pending_rebase_preserves_unrelated_external_changes(self):
        staged, _ = self.stage_initial()
        self.call("apply", "--revision", staged["revision"], "--groups", "all")
        scan, directory = self.prepare(self.call("scan", "--revise"), extra={"semantic/projects/atlas.md": b"# Atlas\n\nNew pending rule. [Evidence](../../evidence/atlas.md).\n"})
        self.call("stage", "--run", scan["run"])
        dream.atomic(self.wiki / "current.md", b"# An unrelated external edit\n")
        revision = self.call("scan", "--revise")
        self.assertEqual(b"# An unrelated external edit\n", (Path(revision["directory"]) / "draft/current.md").read_bytes())
        self.assertIn(b"New pending rule", (Path(revision["directory"]) / "draft/semantic/projects/atlas.md").read_bytes())

    def test_unreadable_tail_is_reported_even_without_new_complete_messages(self):
        first, _ = self.stage_initial()
        with self.source.open("a") as stream:
            stream.write('{"type":"message","role":"user","text":"unfinished')
        scan = self.call("scan")
        self.assertEqual(0, scan["new_inputs"])
        self.assertEqual(1, len(scan["deferred"]))
        self.assertTrue(scan["deferred"][0]["unconsumed_tail"])
        self.assertEqual(first["revision"], self.state()["pending"]["revision"])

    def test_unknown_json_export_events_cannot_be_marked_processed(self):
        path = self.root / "unknown.json"
        path.write_text(json.dumps({"events": [{"type": "unexpected", "text": "Do not discard"}]}))
        with self.assertRaises(dream.DreamError):
            dream.read_delta(path, {}, None)

    def test_json_export_uses_event_count_increment(self):
        path = self.root / "export.json"
        obj = {"session_id": "test", "events": [{"type": "message", "role": "user", "text": "First"}]}
        path.write_text(json.dumps(obj))
        first = dream.read_delta(path, {}, None)
        obj["events"].append({"type": "message", "role": "user", "text": "Second"})
        path.write_text(json.dumps(obj))
        second = dream.read_delta(path, first["next_cursor"], None)
        self.assertEqual(["Second"], [e["text"] for e in second["events"]])


if __name__ == "__main__":
    unittest.main()
