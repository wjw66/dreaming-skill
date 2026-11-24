"""Evidence accounting and exact, review-bound edits for proposed wiki pages."""

import hashlib
import json
import re


ACTIONS = {'add', 'support', 'correct', 'end', 'conflict', 'ignore'}
STATUSES = {'explicit', 'observed', 'inferred', 'unverified', 'conflict'}


def evidence_text(event):
    value = event.get('text')
    if value is None:
        value = event.get('output', event.get('input', event.get('reason')))
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def basis_for_run(directory, parent_directory=None):
    basis = {}
    if parent_directory:
        inherited = parent_directory / 'basis.json'
        if inherited.exists():
            basis.update(json.loads(inherited.read_text()))
        else:
            basis.update(basis_for_run(parent_directory))
    for path in (directory / 'inputs').glob('*.json'):
        item = json.loads(path.read_text())
        for event in item.get('context', []) + item['events']:
            ref = event.get('ref', f'legacy:{event["position"]}')
            key = item['source_id'] + '/' + ref
            entry = {k: event[k] for k in ('kind', 'role', 'position', 'timestamp', 'stable_id', 'source_path', 'segment_id', 'context_only') if k in event}
            entry.update(source_id=item['source_id'], ref=ref, origin_run=directory.name, payload_sha256=hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
            if key in basis and not basis[key].get('context_only'):
                continue
            basis[key] = entry
    return basis


def checked_replace(text, old, new):
    if not isinstance(old, str) or not old or not isinstance(new, str) or text.count(old) != 1:
        raise ValueError('An exact edit requires non-empty old text matching exactly once; no edit was applied')
    return text.replace(old, new, 1)


def apply_edits(directory, edits, page_reader, write, encode, hash_bytes, safe_page):
    if (directory / 'sealed.json').exists():
        raise ValueError('A sealed proposal cannot be patched; prepare a fresh scan --revise')
    record = json.loads((directory / 'scan.json').read_text())
    log_path = directory / 'patches.json'
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    content = page_reader(directory / 'draft')
    prepared = []
    for edit in edits:
        name = edit.get('path', '')
        if not safe_page(name) or name not in content:
            raise ValueError('Exact edits target an existing safe wiki page; author new pages in draft instead')
        if edit.get('kind') not in ('knowledge', 'structure'):
            raise ValueError('Each edit needs kind knowledge or structure')
        if edit['kind'] == 'knowledge' and not edit.get('fact_ids'):
            raise ValueError('A knowledge edit needs fact_ids')
        if edit['kind'] == 'structure' and not edit.get('reason', '').strip():
            raise ValueError('A structural edit needs a reason')
        before = content[name]
        prior = next((item for item in reversed(log + prepared) if item['path'] == name), None)
        expected = prior['after'] if prior else record['draft_base'].get(name)
        if hash_bytes(before) != expected:
            raise ValueError(f'Unlogged edit detected in {name}; start a fresh revision')
        after = checked_replace(before.decode(), edit.get('old'), edit.get('new')).encode()
        prepared.append({**edit, 'before': hash_bytes(before), 'after': hash_bytes(after)})
        content[name] = after
    for item in prepared:
        preimage = directory / 'patch-preimages' / item['path']
        if not preimage.exists():
            write(preimage, (directory / 'draft' / item['path']).read_bytes())
    write(log_path, encode(log + prepared))
    for name in {item['path'] for item in prepared}:
        write(directory / 'draft' / name, content[name])
    return {'edited_pages': sorted({item['path'] for item in prepared}), 'operations': len(prepared)}


def validate_knowledge(directory, review, record, proposed, hash_bytes):
    facts = review.get('facts')
    decisions = review.get('input_decisions')
    if not isinstance(facts, list) or not isinstance(decisions, list):
        raise ValueError('Review requires facts and input_decisions; a justified zero-change result is allowed')
    processed = set(review['processed'])
    listed = [d.get('source_id') for d in decisions]
    if len(listed) != len(set(listed)) or set(listed) != processed or any(not d.get('reason', '').strip() for d in decisions):
        raise ValueError('Every successfully analyzed input requires exactly one non-empty processing reason')
    basis = json.loads((directory / 'basis.json').read_text())
    known = {}
    snapshots = {}
    for fact in facts:
        identity = fact.get('id')
        if not isinstance(identity, str) or not identity or identity in known:
            raise ValueError('Candidate facts require unique non-empty IDs')
        known[identity] = fact
        if any(not isinstance(fact.get(k), str) or not fact[k].strip() for k in ('statement', 'subject', 'facet', 'scope', 'reason')):
            raise ValueError(f'Fact {identity} requires statement, subject, facet, scope and reason')
        if fact.get('action') not in ACTIONS or fact.get('status') not in STATUSES:
            raise ValueError(f'Invalid action or epistemic status for fact {identity}; action must be one of {sorted(ACTIONS)}, status one of {sorted(STATUSES)}')
        evidence = fact.get('evidence', [])
        if not evidence:
            raise ValueError(f'Fact {identity} requires source evidence')
        substantive = False
        for citation in evidence:
            key = citation.get('source_id', '') + '/' + citation.get('ref', '')
            entry = basis.get(key)
            if entry is None:
                raise ValueError(f'Fact {identity} cites an unknown frozen event: {key}')
            origin = entry['origin_run']
            source = entry['source_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', origin) or not re.fullmatch(r'[a-f0-9]{24}', source):
                raise ValueError('Evidence must refer to an actual local run and source ID')
            snapshot_key = origin + '/' + source
            if snapshot_key not in snapshots:
                source_path = directory.parent / origin / 'inputs' / (source + '.json')
                original = json.loads(source_path.read_text())
                snapshots[snapshot_key] = {e.get('ref', f'legacy:{e["position"]}'): e for e in original.get('context', []) + original['events']}
            original = snapshots[snapshot_key].get(entry['ref'])
            if original is None or hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != entry['payload_sha256']:
                raise ValueError('Cited evidence no longer matches its frozen source snapshot')
            quote = citation.get('quote')
            if fact['action'] != 'ignore':
                if not isinstance(quote, str) or not quote.strip() or quote not in evidence_text(original):
                    raise ValueError(f'Fact {identity} requires a non-empty verbatim quote from its cited frozen event; translations and paraphrases are not source quotations')
                evidence_pages = [citation['page']] if citation.get('page') else [t.split('#', 1)[0] for t in fact.get('targets', []) if isinstance(t, str) and t.startswith('evidence/')]
                if not evidence_pages or any(not isinstance(p, str) or not p.startswith('evidence/') or p not in proposed for p in evidence_pages):
                    raise ValueError(f'Fact {identity} requires a local evidence page for each retained quotation')
                if not any(quote in proposed[p].decode('utf-8') for p in evidence_pages):
                    raise ValueError(f'Fact {identity} quotation is absent from its evidence page; publish the original excerpt, not only a paraphrase')
            if entry['origin_run'] == record['run'] and entry['source_id'] not in processed:
                raise ValueError('A failed input cannot supply newly analyzed facts')
            substantive = substantive or not entry.get('context_only', False)
        if not substantive:
            raise ValueError('Context-only material cannot by itself create a newly extracted fact')
        targets = fact.get('targets', [])
        if fact['action'] != 'ignore' and (not targets or any(t.split('#', 1)[0] not in proposed for t in targets)):
            raise ValueError(f'Fact {identity} requires existing target pages')
        if fact['action'] == 'correct' and (not fact.get('supersedes') or any(p.split('#', 1)[0] not in record['draft_base'] for p in fact['supersedes'])):
            raise ValueError('A correction must identify an existing prior claim it replaces')
    knowledge_paths = set()
    covered = {identity: set() for identity in known}
    changed = {name for name, data in proposed.items() if hash_bytes(data) != record['base_wiki'].get(name)}
    for group in review['groups']:
        if group.get('kind') == 'structure':
            if not group.get('reason', '').strip():
                raise ValueError('Structural review groups require a reason, not invented new facts')
        elif group.get('kind') == 'knowledge':
            ids = group.get('fact_ids', [])
            if not ids or any(i not in known or known[i]['action'] == 'ignore' for i in ids):
                raise ValueError('Knowledge groups must cite non-ignored candidate facts')
            for identity in ids:
                targets = {target.split('#', 1)[0] for target in known[identity].get('targets', [])}
                covered[identity].update(targets.intersection(group['paths'], changed))
            for name in group['paths']:
                if name.startswith(('semantic/', 'events/')) and not any(name in {target.split('#', 1)[0] for target in known[identity].get('targets', [])} for identity in ids):
                    raise ValueError(f'Changed content page has no candidate targeting it: {name}')
            knowledge_paths.update(group['paths'])
        else:
            raise ValueError('Each review group requires kind knowledge or structure')
    for identity, fact in known.items():
        if fact['action'] in ('add', 'correct', 'end', 'conflict') and not covered[identity]:
            raise ValueError(f'Fact {identity} claims a material change without a cited target in a knowledge review group; use support for an unchanged existing claim')
    checks = review.get('consistency_checks', [])
    checked = {}
    for check in checks:
        name = check.get('path')
        if name in checked or name not in proposed or not check.get('reason', '').strip():
            raise ValueError('Consistency checks need unique existing pages and non-empty reasons')
        outcome = 'updated' if hash_bytes(proposed[name]) != record['base_wiki'].get(name) else 'unchanged'
        if check.get('outcome') != outcome:
            raise ValueError(f'Consistency outcome does not match the actual page diff: {name}; expected {outcome} relative to the formal base, not a previous draft')
        checked[name] = check
    required = {p for p in knowledge_paths if p.startswith(('events/', 'semantic/'))}
    if knowledge_paths:
        required.update(('index.md', 'current.md'))
    if not required.issubset(checked):
        raise ValueError('Knowledge changes require consistency checks for changed content pages, index.md and current.md')
    log_path = directory / 'patches.json'
    log = json.loads(log_path.read_text()) if log_path.exists() else []
    reconstructed = {}
    owners = {name: group for group in review['groups'] for name in group['paths']}
    for edit in log:
        name = edit['path']
        if name not in reconstructed:
            original = (directory / 'patch-preimages' / name).read_bytes()
            if hash_bytes(original) != record['draft_base'].get(name):
                raise ValueError('Patch preimage does not match the frozen draft base')
            reconstructed[name] = original
        if hash_bytes(reconstructed[name]) != edit['before']:
            raise ValueError('Patch chain does not match its preimage')
        if edit['kind'] == 'knowledge':
            owner = owners.get(name)
            if owner is None or owner.get('kind') != 'knowledge':
                raise ValueError('A knowledge patch must belong to a knowledge review group')
            ids = edit.get('fact_ids', [])
            if not ids or any(i not in known or known[i]['action'] == 'ignore' or i not in owner.get('fact_ids', []) for i in ids):
                raise ValueError('Knowledge patch facts must belong to its owning review group')
            if name.startswith(('semantic/', 'events/')) and any(name not in {t.split('#', 1)[0] for t in known[i].get('targets', [])} for i in ids):
                raise ValueError('A knowledge patch cannot cite facts targeting a different content page')
        reconstructed[name] = checked_replace(reconstructed[name].decode(), edit['old'], edit['new']).encode()
        if hash_bytes(reconstructed[name]) != edit['after']:
            raise ValueError('Patch after-image does not match its operation')
    if any(proposed.get(name) != data for name, data in reconstructed.items()):
        raise ValueError('An exact edit did not land completely; restart from a fresh scan')
    for name, original_hash in record['draft_base'].items():
        if name not in proposed or hash_bytes(proposed[name]) == original_hash:
            continue
        if name.startswith('evidence/'):
            original = (directory / 'evidence-preimages' / name).read_bytes()
            if hash_bytes(original) != original_hash or not proposed[name].startswith(original):
                raise ValueError('Existing evidence excerpts are append-only; preserve the original and add correcting evidence')
        elif reconstructed.get(name) != proposed[name]:
            raise ValueError(f'Existing page changed without exact logged edits: {name}')
    return {'candidate_facts': len(facts), 'ignored_facts': sum(f['action'] == 'ignore' for f in facts)}


def evidence_manifest(directory, review):
    basis = json.loads((directory / 'basis.json').read_text())
    result = {}
    for fact in review['facts']:
        for citation in fact['evidence']:
            entry = basis[citation['source_id'] + '/' + citation['ref']]
            relative = entry['origin_run'] + '/inputs/' + entry['source_id'] + '.json'
            if relative not in result:
                result[relative] = hashlib.sha256((directory.parent / relative).read_bytes()).hexdigest()
    return result
