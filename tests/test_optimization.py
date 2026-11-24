import json
from pathlib import Path
import tempfile
import unittest

from test_dream import dream


class IncrementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exports = self.root / 'exports'
        self.exports.mkdir()
        self.wiki = self.root / 'wiki'
        self.registry = self.root / 'registry.json'
        self.call('init', '--wiki', str(self.wiki), '--host', 'files', '--scope', 'selected', '--input', str(self.exports))

    def call(self, command, *flags):
        args = dream.parser().parse_args([command, '--registry', str(self.registry), *flags])
        return args.handler(args)

    def native(self, name, events, session='logical-session'):
        path = self.exports / name
        rows = [{'type': 'session_meta', 'payload': {'id': session}}]
        rows.extend(events)
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        return path

    def message(self, text, identity):
        return {'type': 'response_item', 'payload': {'type': 'message', 'id': identity, 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}}

    def input(self, scan):
        directory = Path(scan['directory'])
        return dream.load(next((directory / 'inputs').glob('*.json')))

    def checkpoint(self, scan):
        directory = Path(scan['directory'])
        record = dream.load(directory / 'scan.json')
        review = {'summary': 'Synthetic input bookkeeping; no retained knowledge.', 'processed': [s['source_id'] for s in record['sources']], 'failures': [], 'organized': True, 'groups': [], 'facts': [], 'input_decisions': [{'source_id': s['source_id'], 'reason': 'Synthetic bookkeeping only.'} for s in record['sources']]}
        dream.atomic(directory / 'review.json', dream.encoded(review))
        return self.call('stage', '--run', scan['run'])

    def test_shorter_continuation_is_not_ignored(self):
        self.native('a.jsonl', [self.message('Old text ' * 40, 'old')])
        self.checkpoint(self.call('scan'))
        self.native('b.jsonl', [self.message('New', 'new')])
        scan = self.call('scan')
        self.assertEqual(1, scan['new_inputs'])
        self.assertEqual(['New'], [e['text'] for e in self.input(scan)['events']])

    def test_each_segment_can_append_without_replaying_the_other(self):
        a = self.native('a.jsonl', [self.message('A', 'a')])
        b = self.native('b.jsonl', [self.message('B', 'b')])
        self.checkpoint(self.call('scan'))
        for path, text, identity in ((a, 'A2', 'a2'), (b, 'B2', 'b2')):
            with path.open('a') as stream:
                stream.write(json.dumps(self.message(text, identity)) + '\n')
        scan = self.call('scan')
        self.assertEqual({'A2', 'B2'}, {e['text'] for e in self.input(scan)['events']})
        self.checkpoint(scan)
        self.assertNotIn('run', self.call('scan'))

    def test_cross_segment_tool_exchange_is_emitted_together(self):
        self.native('a.jsonl', [self.message('Run a check', 'a'), {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'c1', 'name': 'test', 'arguments': '{}'}}])
        first = self.call('scan')
        self.assertEqual(['message'], [e['kind'] for e in self.input(first)['events']])
        self.checkpoint(first)
        self.native('b.jsonl', [{'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'c1', 'output': 'passed'}}])
        second = self.call('scan')
        self.assertEqual({'tool_call', 'tool_result'}, {e['kind'] for e in self.input(second)['events']})

    def test_copied_prefix_and_archival_do_not_duplicate_processed_events(self):
        a = self.native('a.jsonl', [self.message('A', 'a')])
        self.checkpoint(self.call('scan'))
        b = self.exports / 'b.jsonl'
        b.write_bytes(a.read_bytes() + (json.dumps(self.message('B', 'b')) + '\n').encode())
        scan = self.call('scan')
        self.assertEqual(['B'], [e['text'] for e in self.input(scan)['events']])
        self.checkpoint(scan)
        a.rename(self.exports / 'archived-a.jsonl')
        b.rename(self.exports / 'archived-b.jsonl')
        scan = self.call('scan')
        if 'run' in scan:
            self.assertEqual(0, scan['new_inputs'])

    def test_increment_has_context_only_preceding_proposal(self):
        path = self.native('a.jsonl', [self.message('Q19: Adopt the semantic directory?', 'proposal')])
        self.checkpoint(self.call('scan'))
        with path.open('a') as stream:
            stream.write(json.dumps(self.message('Q19: Agreed.', 'approval')) + '\n')
        item = self.input(self.call('scan'))
        self.assertEqual(['Q19: Agreed.'], [e['text'] for e in item['events']])
        self.assertIn('semantic', item['context'][0]['text'])
        self.assertTrue(item['context'][0]['context_only'])

    def test_legacy_cursor_recovers_segment_from_saved_run(self):
        a = self.native('a.jsonl', [self.message('Old ' * 40, 'a')])
        first = self.call('scan')
        source = self.input(first)['source_id']
        self.checkpoint(first)
        state = dream.load(dream.state_path(self.wiki))
        legacy = dream.read_delta(a, {}, None)['next_cursor']
        state['version'] = 1
        state['cursors'][source] = legacy
        dream.atomic(dream.state_path(self.wiki), dream.encoded(state))
        record_path = Path(first['directory']) / 'scan.json'
        record = dream.load(record_path)
        record['sources'][0]['next_cursor'] = legacy
        record['sources'][0]['source_path'] = str(a)
        dream.atomic(record_path, dream.encoded(record))
        self.native('b.jsonl', [self.message('New', 'b')])
        scan = self.call('scan')
        self.assertEqual(['New'], [e['text'] for e in self.input(scan)['events']])
        self.checkpoint(scan)
        self.assertEqual(2, dream.load(dream.state_path(self.wiki))['version'])
        self.assertTrue((self.wiki / '.dreaming/state-v1-backup.json').is_file())

    def test_copied_unfinished_exchange_survives_original_segment_moving_away(self):
        a = self.native('a.jsonl', [self.message('Old message', 'old'), {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'pending', 'name': 'check', 'arguments': '{}'}}])
        b = self.exports / 'b.jsonl'
        b.write_bytes(a.read_bytes())
        first = self.call('scan')
        self.assertEqual(['message'], [e['kind'] for e in self.input(first)['events']])
        self.checkpoint(first)
        a.rename(self.root / 'outside-selection.jsonl')
        with b.open('a') as stream:
            stream.write(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'pending', 'output': 'done'}}) + '\n')
        second = self.call('scan')
        self.assertEqual(['tool_call', 'tool_result'], [e['kind'] for e in self.input(second)['events']])

    def test_legacy_migration_deduplicates_copy_that_sorts_before_original(self):
        original = self.native('z-original.jsonl', [self.message('Already processed', 'old')])
        first = self.call('scan')
        source = self.input(first)['source_id']
        self.checkpoint(first)
        legacy = dream.read_delta(original, {}, None)['next_cursor']
        state = dream.load(dream.state_path(self.wiki))
        state['version'] = 1
        state['cursors'][source] = legacy
        dream.atomic(dream.state_path(self.wiki), dream.encoded(state))
        record_path = Path(first['directory']) / 'scan.json'
        record = dream.load(record_path)
        record['sources'][0].update(next_cursor=legacy, source_path=str(original))
        dream.atomic(record_path, dream.encoded(record))
        copied = self.exports / 'a-copy.jsonl'
        copied.write_bytes(original.read_bytes() + (json.dumps(self.message('New continuation', 'new')) + '\n').encode())
        scan = self.call('scan')
        self.assertEqual(['New continuation'], [e['text'] for e in self.input(scan)['events']])

    def test_legacy_cursor_is_not_applied_to_a_single_unrelated_continuation(self):
        original = self.native('a.jsonl', [self.message('OLD', 'old')])
        first = self.call('scan')
        source = self.input(first)['source_id']
        self.checkpoint(first)
        legacy = dream.read_delta(original, {}, None)['next_cursor']
        state = dream.load(dream.state_path(self.wiki))
        state['version'] = 1
        state['cursors'][source] = legacy
        dream.atomic(dream.state_path(self.wiki), dream.encoded(state))
        record_path = Path(first['directory']) / 'scan.json'
        record = dream.load(record_path)
        record['sources'][0].update(next_cursor=legacy, source_path=str(original))
        dream.atomic(record_path, dream.encoded(record))
        original.rename(self.root / 'outside.jsonl')
        self.native('b.jsonl', [self.message('NEW', 'new'), self.message('FRESH', 'fresh')])
        scan = self.call('scan')
        self.assertTrue(any('legacy' in f['reason'].lower() for f in scan['failures']))
        self.assertEqual(state, dream.load(dream.state_path(self.wiki)))

    def test_byte_identical_no_id_messages_and_tools_are_emitted_once(self):
        message = self.message('Only once', 'remove-id')
        del message['payload']['id']
        events = [message, {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'once', 'name': 'check', 'arguments': '{}'}}, {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'once', 'output': 'done'}}]
        a = self.native('a.jsonl', events)
        (self.exports / 'b.jsonl').write_bytes(a.read_bytes())
        scan = self.call('scan')
        self.assertEqual(['message', 'tool_call', 'tool_result'], [e['kind'] for e in self.input(scan)['events']])

    def test_committed_prefix_advances_a_lagging_copy_without_replaying_no_id_message(self):
        message = self.message('Already emitted', 'remove-id')
        del message['payload']['id']
        a = self.native('a.jsonl', [message, {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'pending', 'name': 'check', 'arguments': '{}'}}])
        b = self.exports / 'b.jsonl'
        b.write_bytes(a.read_bytes())
        first = self.call('scan')
        self.assertEqual(['message'], [e['kind'] for e in self.input(first)['events']])
        self.checkpoint(first)
        a.rename(self.root / 'outside-selection.jsonl')
        with b.open('a') as stream:
            stream.write(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'pending', 'output': 'done'}}) + '\n')
        second = self.call('scan')
        self.assertEqual(['tool_call', 'tool_result'], [e['kind'] for e in self.input(second)['events']])

    def test_ambiguous_legacy_cursor_is_reported_without_reset(self):
        a = self.native('a.jsonl', [self.message('A', 'a')])
        self.native('b.jsonl', [self.message('B', 'b')])
        source = dream.source_identity(a)
        state = dream.load(dream.state_path(self.wiki))
        state['version'] = 1
        state['cursors'][source] = dream.read_delta(a, {}, None)['next_cursor']
        dream.atomic(dream.state_path(self.wiki), dream.encoded(state))
        scan = self.call('scan')
        self.assertEqual(0, scan['new_inputs'])
        self.assertTrue(any('legacy' in f['reason'].lower() for f in scan['failures']))
        self.assertEqual(state, dream.load(dream.state_path(self.wiki)))


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        import test_dream as fixtures
        self.fx = fixtures.DreamTests('test_initialization_and_staging_never_mutate_formal_wiki')
        self.fx.setUp()
        self.addCleanup(self.fx.temp.cleanup)

    def prepare(self):
        scan, directory = self.fx.prepare()
        return scan, directory, dream.load(directory / 'review.json')

    def stage(self, scan, directory, review):
        dream.atomic(directory / 'review.json', dream.encoded(review))
        return self.fx.call('stage', '--run', scan['run'])

    def test_missing_processing_reason_does_not_advance_progress(self):
        scan, directory, review = self.prepare()
        review['input_decisions'] = []
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)
        self.assertEqual({}, self.fx.state()['cursors'])

    def test_zero_change_with_explicit_reason_is_valid(self):
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        source = dream.load(directory / 'scan.json')['sources'][0]['source_id']
        review = {'summary': 'All facts were outside the chosen retention purpose.', 'processed': [source], 'failures': [], 'organized': True, 'groups': [], 'facts': [], 'input_decisions': [{'source_id': source, 'reason': 'No durable knowledge for this scoped bookkeeping exercise.'}]}
        result = self.stage(scan, directory, review)
        self.assertEqual(0, result['changed_pages'])
        self.assertIsNone(result['pending'])
        self.assertTrue(self.fx.state()['cursors'])

    def test_unknown_evidence_reference_is_rejected(self):
        scan, directory, review = self.prepare()
        review['facts'][0]['evidence'][0]['ref'] = 'invented-event'
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_context_only_reference_cannot_create_a_fact(self):
        scan, directory, review = self.prepare()
        basis = dream.load(directory / 'basis.json')
        for event in basis.values():
            event['context_only'] = True
        dream.atomic(directory / 'basis.json', dream.encoded(basis))
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_failed_input_cannot_contribute_new_knowledge(self):
        scan, directory, review = self.prepare()
        source = review['processed'].pop()
        review['input_decisions'] = []
        review['failures'] = [{'source_id': source, 'reason': 'Analysis failed'}]
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_correction_requires_prior_claim(self):
        scan, directory, review = self.prepare()
        review['facts'][0]['action'] = 'correct'
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_structural_changes_do_not_need_invented_facts(self):
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        source = dream.load(directory / 'scan.json')['sources'][0]['source_id']
        dream.atomic(directory / 'draft/index.md', b'# Index\n\n[Current](current.md)\n')
        dream.atomic(directory / 'draft/current.md', b'# Current\n')
        review = {'summary': 'Set up navigation only.', 'processed': [source], 'failures': [], 'organized': True, 'facts': [], 'input_decisions': [{'source_id': source, 'reason': 'No durable fact retained in this structural setup.'}], 'groups': [{'id': 'navigation', 'kind': 'structure', 'reason': 'Create wiki entry points', 'summary': 'Navigation', 'paths': ['index.md', 'current.md'], 'depends_on': []}]}
        self.assertEqual(2, self.stage(scan, directory, review)['changed_pages'])

    def test_knowledge_changes_require_navigation_consistency_checks(self):
        scan, directory, review = self.prepare()
        review['consistency_checks'] = []
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_evidence_basis_is_bound_to_reviewed_revision(self):
        staged, directory = self.fx.stage_initial()
        dream.atomic(directory / 'basis.json', b'{}\n')
        with self.assertRaises(dream.DreamError):
            self.fx.call('apply', '--revision', staged['revision'], '--groups', 'all')

    def test_source_snapshot_tampering_invalidates_review(self):
        staged, directory = self.fx.stage_initial()
        source = next((directory / 'inputs').glob('*.json'))
        source.write_text('{}\n')
        with self.assertRaises(dream.DreamError):
            self.fx.call('apply', '--revision', staged['revision'], '--groups', 'all')

    def existing(self):
        staged, _ = self.fx.stage_initial()
        self.fx.call('apply', '--revision', staged['revision'], '--groups', 'all')
        scan = self.fx.call('scan', '--revise')
        return scan, Path(scan['directory'])

    def test_exact_patch_preserves_unmentioned_text(self):
        scan, directory = self.existing()
        name = 'semantic/projects/atlas.md'
        before = (directory / 'draft' / name).read_text()
        edits = [{'path': name, 'old': 'Keep CSV for Atlas only.', 'new': 'Keep CSV for Atlas PRE only.', 'kind': 'knowledge', 'fact_ids': ['atlas-rule']}]
        dream.atomic(directory / 'edits.json', dream.encoded(edits))
        self.fx.call('patch', '--run', scan['run'], '--edits', str(directory / 'edits.json'))
        after = (directory / 'draft' / name).read_text()
        self.assertEqual(before.replace('Keep CSV for Atlas only.', 'Keep CSV for Atlas PRE only.'), after)

    def test_non_unique_or_missing_patch_anchor_changes_nothing(self):
        scan, directory = self.existing()
        before = dream.pages(directory / 'draft')
        edits = [{'path': 'current.md', 'old': 'NOT PRESENT', 'new': 'Wrong', 'kind': 'structure', 'reason': 'Test'}]
        dream.atomic(directory / 'edits.json', dream.encoded(edits))
        with self.assertRaises(ValueError):
            self.fx.call('patch', '--run', scan['run'], '--edits', str(directory / 'edits.json'))
        self.assertEqual(before, dream.pages(directory / 'draft'))

    def test_direct_rewrite_of_existing_page_is_not_accepted(self):
        scan, directory = self.existing()
        dream.atomic(directory / 'draft/current.md', b'# Silently regenerated\n')
        review = {'summary': 'Unlogged edit', 'processed': [], 'failures': [], 'organized': True, 'facts': [], 'input_decisions': [], 'groups': [{'id': 'rewrite', 'kind': 'structure', 'reason': 'Navigation', 'summary': 'Rewrite', 'paths': ['current.md'], 'depends_on': []}]}
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_interrupted_draft_patch_cannot_be_staged_as_an_unchanged_result(self):
        from unittest.mock import patch
        scan, directory = self.existing()
        edit = [{'path': 'current.md', 'old': '# Current', 'new': '# Updated current', 'kind': 'structure', 'reason': 'Navigation title'}]
        dream.atomic(directory / 'edits.json', dream.encoded(edit))
        original = dream.atomic

        def fail_on_page(path, data):
            if path.resolve() == (directory / 'draft/current.md').resolve():
                raise OSError('Interrupted before patch data landed')
            return original(path, data)

        with patch.object(dream, 'atomic', side_effect=fail_on_page):
            with self.assertRaises(OSError):
                self.fx.call('patch', '--run', scan['run'], '--edits', str(directory / 'edits.json'))
        review = {'summary': 'No actual content changes', 'processed': [], 'failures': [], 'organized': True, 'facts': [], 'input_decisions': [], 'groups': []}
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_existing_evidence_must_keep_original_excerpt(self):
        scan, directory = self.existing()
        dream.atomic(directory / 'draft/evidence/atlas.md', b'# Replaced original evidence\n')
        review = {'summary': 'Alter evidence', 'processed': [], 'failures': [], 'organized': True, 'facts': [], 'input_decisions': [], 'groups': [{'id': 'evidence', 'kind': 'structure', 'reason': 'Test', 'summary': 'Evidence', 'paths': ['evidence/atlas.md'], 'depends_on': []}]}
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)


if __name__ == '__main__':
    unittest.main()
