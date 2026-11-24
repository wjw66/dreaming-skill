import json
from pathlib import Path
import unittest

import test_dream as fixtures


dream = fixtures.dream


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.DreamTests('test_initialization_and_staging_never_mutate_formal_wiki')
        self.fx.setUp()
        self.addCleanup(self.fx.temp.cleanup)

    def existing(self, text):
        staged, _ = self.fx.stage_initial()
        self.fx.call('apply', '--revision', staged['revision'], '--groups', 'all')
        self.fx.append({'type': 'message', 'role': 'user', 'text': text, 'id': 'new-user-message'})
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        item = dream.load(next((directory / 'inputs').glob('*.json')))
        fact = {'id': 'new-rule', 'statement': text, 'subject': 'Atlas', 'facet': 'export', 'scope': 'Atlas only', 'status': 'explicit', 'action': 'add', 'reason': 'Explicit new user requirement.', 'evidence': [{'source_id': item['source_id'], 'ref': item['events'][0]['ref']}], 'targets': ['semantic/projects/atlas.md']}
        review = {'summary': 'Analyze new requirement.', 'processed': [item['source_id']], 'failures': [], 'organized': True, 'facts': [fact], 'input_decisions': [{'source_id': item['source_id'], 'reason': 'Extracted the user requirement.'}], 'groups': [], 'consistency_checks': []}
        return scan, directory, review

    def stage(self, scan, directory, review):
        dream.atomic(directory / 'review.json', dream.encoded(review))
        return self.fx.call('stage', '--run', scan['run'])

    def test_reselection_keeps_evidence_and_cursors_without_copying_unapproved_pages(self):
        first, old = self.fx.stage_initial()
        before = self.fx.state()
        old_files = {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()}
        scan = self.fx.call('scan', '--revise', '--reselect-pending')
        directory = Path(scan['directory'])
        self.assertEqual(0, scan['new_inputs'])
        self.assertFalse(scan['pending_inherited'])
        self.assertEqual({}, dream.pages(directory / 'draft'))
        self.assertEqual(dream.load(old / 'basis.json'), dream.load(directory / 'basis.json'))
        self.assertEqual(before, self.fx.state())
        self.assertEqual(old_files, {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()})
        self.fx.prepare(scan)
        second = self.fx.call('stage', '--run', scan['run'])
        self.assertEqual(before['cursors'], self.fx.state()['cursors'])
        self.assertNotEqual(first['revision'], second['revision'])
        self.assertEqual({}, dream.pages(self.fx.wiki))

    def test_reselection_preserves_formal_pages_and_requires_an_explicit_revision(self):
        with self.assertRaises(dream.DreamError):
            self.fx.call('scan', '--revise', '--reselect-pending')
        first, _ = self.fx.stage_initial()
        self.fx.call('apply', '--revision', first['revision'], '--groups', 'all')
        self.fx.append({'type': 'message', 'role': 'user', 'text': 'Temporary experiment.'})
        scan, directory = self.fx.prepare(extra={'semantic/projects/experiment.md': b'# Unapproved experiment\n'})
        review = dream.load(directory / 'review.json')
        review['facts'][0]['targets'].append('semantic/projects/experiment.md')
        dream.atomic(directory / 'review.json', dream.encoded(review))
        self.fx.call('stage', '--run', scan['run'])
        before = dream.pages(self.fx.wiki)
        with self.assertRaises(dream.DreamError):
            self.fx.call('scan', '--reselect-pending')
        revised = self.fx.call('scan', '--revise', '--reselect-pending')
        self.assertEqual(before, dream.pages(Path(revised['directory']) / 'draft'))
        self.assertEqual(before, dream.pages(self.fx.wiki))
        self.assertTrue((directory / 'draft/semantic/projects/experiment.md').is_file())

    def test_new_fact_cannot_be_marked_added_without_a_page_change(self):
        scan, directory, review = self.existing('Preserve column order in Atlas CSV exports.')
        state = self.fx.state()
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)
        self.assertEqual(state, self.fx.state())

    def test_repeated_fact_can_support_existing_page_without_rewriting_it(self):
        scan, directory, review = self.existing('For Atlas only, keep CSV.')
        review['facts'][0]['action'] = 'support'
        review['facts'][0]['reason'] = 'The existing page already records the same scoped rule.'
        result = self.stage(scan, directory, review)
        self.assertEqual(0, result['changed_pages'])
        self.assertIsNone(result['pending'])

    def test_changed_semantic_page_needs_a_fact_targeting_that_page(self):
        scan, directory, review = self.existing('Preserve column order in Atlas CSV exports.')
        dream.atomic(directory / 'draft/semantic/projects/beacon.md', b'# Beacon\n\nUse Markdown.\n')
        review['facts'][0]['action'] = 'support'
        review['groups'] = [{'id': 'wrong-project', 'kind': 'knowledge', 'fact_ids': ['new-rule'], 'summary': 'Change Beacon using an Atlas claim.', 'paths': ['semantic/projects/beacon.md'], 'depends_on': []}]
        review['consistency_checks'] = [{'path': name, 'outcome': 'updated' if name == 'semantic/projects/beacon.md' else 'unchanged', 'reason': 'Checked page.'} for name in ('index.md', 'current.md', 'semantic/projects/beacon.md')]
        with self.assertRaises(ValueError):
            self.stage(scan, directory, review)

    def test_malformed_native_message_does_not_abort_other_sessions(self):
        bad = self.fx.root / 'bad.jsonl'
        malformed = [
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': None}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': ['not-a-block']}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': None}]}},
            {'type': 'message', 'role': 'USER', 'text': 'Unsupported role must not vanish'},
            {'type': 'tool_call', 'call_id': ['not-a-string'], 'name': 'test'}
        ]
        for event in malformed:
            with self.subTest(event=event):
                bad.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'bad-session'}}) + '\n' + json.dumps(event) + '\n')
                scan = self.fx.call('scan', '--input', str(self.fx.source), '--input', str(bad))
                self.assertEqual(1, scan['new_inputs'])
                self.assertEqual(1, len(scan['failures']))
                self.assertEqual({}, self.fx.state()['cursors'])


    def mismatched_patch(self, extra_owner_fact=False, structural_owner=False):
        scan, directory, review = self.existing('Atlas must use JSON. Beacon needs Markdown export.')
        review['facts'][0].update(statement='Atlas must use JSON.', action='support' if structural_owner else 'correct', supersedes=['semantic/projects/atlas.md'])
        beacon = {**review['facts'][0], 'id': 'beacon', 'statement': 'Beacon needs Markdown.', 'subject': 'Beacon', 'scope': 'Beacon only', 'action': 'add', 'targets': ['semantic/projects/beacon.md']}
        beacon.pop('supersedes', None)
        review['facts'].append(beacon)
        dream.atomic(directory / 'draft/semantic/projects/beacon.md', b'# Beacon\n\nUse Markdown.\n')
        edits = [{'path': 'semantic/projects/atlas.md', 'old': 'Keep CSV for Atlas only.', 'new': 'Atlas must use JSON.', 'kind': 'knowledge', 'fact_ids': ['beacon']}]
        dream.atomic(directory / 'edits.json', dream.encoded(edits))
        self.fx.call('patch', '--run', scan['run'], '--edits', str(directory / 'edits.json'))
        atlas_group = {'id': 'atlas', 'kind': 'structure' if structural_owner else 'knowledge', 'reason': 'Synthetic ownership check', 'fact_ids': ['new-rule', 'beacon'] if extra_owner_fact else ['new-rule'], 'summary': 'Atlas change', 'paths': ['semantic/projects/atlas.md'], 'depends_on': []}
        review['groups'] = [atlas_group, {'id': 'beacon', 'kind': 'knowledge', 'fact_ids': ['beacon'], 'summary': 'Beacon change', 'paths': ['semantic/projects/beacon.md'], 'depends_on': []}]
        review['consistency_checks'] = [{'path': name, 'outcome': 'unchanged' if name in ('index.md', 'current.md') else 'updated', 'reason': 'Checked page.'} for name in ('index.md', 'current.md', 'semantic/projects/atlas.md', 'semantic/projects/beacon.md')]
        return scan, directory, review

    def test_patch_fact_must_belong_to_the_owning_group(self):
        scan, directory, review = self.mismatched_patch()
        with self.assertRaisesRegex(ValueError, 'owning review group'):
            self.stage(scan, directory, review)

    def test_patch_fact_must_target_the_edited_content_page(self):
        scan, directory, review = self.mismatched_patch(extra_owner_fact=True)
        with self.assertRaisesRegex(ValueError, 'different content page'):
            self.stage(scan, directory, review)

    def test_knowledge_patch_cannot_hide_inside_structural_group(self):
        scan, directory, review = self.mismatched_patch(structural_owner=True)
        with self.assertRaisesRegex(ValueError, 'knowledge review group'):
            self.stage(scan, directory, review)

class CoverageAndCancellationTests(unittest.TestCase):
    def setUp(self):
        import test_optimization as optimization
        self.fx = optimization.IncrementTests('test_shorter_continuation_is_not_ignored')
        self.fx.setUp()
        self.addCleanup(self.fx.temp.cleanup)

    def native_call(self, call='cancel-me'):
        return {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': call, 'name': 'test', 'arguments': '{}'}}

    def abort(self, turn=None):
        return {'type': 'event_msg', 'payload': {'type': 'turn_aborted', 'reason': 'User interrupted', **({'turn_id': turn} if turn else {})}}

    def test_explicit_abort_unblocks_later_messages_without_faking_a_result(self):
        self.fx.native('a.jsonl', [self.fx.message('Before', 'before'), self.native_call(), self.abort(), self.fx.message('After cancellation', 'after')])
        scan = self.fx.call('scan')
        events = self.fx.input(scan)['events']
        self.assertEqual(['message', 'tool_call', 'interruption', 'message'], [e['kind'] for e in events])
        self.assertEqual('cancelled', events[1]['outcome'])
        self.assertEqual(events[2]['ref'], events[1]['cancelled_by'])
        self.assertFalse(scan['deferred'])
        self.fx.checkpoint(scan)
        self.assertNotIn('run', self.fx.call('scan'))

    def test_abort_of_another_turn_does_not_settle_unrelated_work(self):
        self.fx.native('a.jsonl', [{'type': 'turn_context', 'payload': {'turn_id': 'turn-a'}}, self.native_call(), self.abort('turn-b'), self.fx.message('Later', 'later')])
        scan = self.fx.call('scan')
        self.assertEqual(0, scan['new_inputs'])
        self.assertTrue(scan['deferred'])

    def test_scoped_abort_closes_a_call_in_another_segment(self):
        self.fx.native('z-call.jsonl', [{'type': 'turn_context', 'payload': {'turn_id': 'turn-a'}}, self.native_call()])
        self.fx.native('a-abort.jsonl', [self.abort('turn-a'), self.fx.message('After', 'after')])
        scan = self.fx.call('scan')
        events = self.fx.input(scan)['events']
        self.assertFalse(scan['deferred'])
        self.assertEqual('cancelled', next(e['outcome'] for e in events if e['kind'] == 'tool_call'))
        self.assertEqual(0, sum(e['kind'] == 'tool_result' for e in events))

    def test_turn_scope_survives_an_increment_checkpoint(self):
        path = self.fx.native('a.jsonl', [{'type': 'turn_context', 'payload': {'turn_id': 'active-turn'}}, self.fx.message('First', 'first')])
        self.fx.checkpoint(self.fx.call('scan'))
        with path.open('a') as stream:
            for event in (self.native_call(), self.abort(), self.fx.message('After', 'after')):
                stream.write(json.dumps(event) + '\n')
        scan = self.fx.call('scan')
        events = self.fx.input(scan)['events']
        self.assertFalse(scan['deferred'])
        self.assertEqual('active-turn', events[0]['turn_id'])
        self.assertEqual('cancelled', events[0]['outcome'])

    def test_mixed_and_image_only_messages_report_omissions_without_media_bytes(self):
        marker = 'SYNTHETIC_MEDIA_BYTES_MUST_NOT_BE_COPIED'
        self.fx.native('a.jsonl', [{'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'See screenshot'}, {'type': 'input_image', 'image_url': marker}]}}, {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_image', 'image_url': marker}]}}])
        scan = self.fx.call('scan')
        item = self.fx.input(scan)
        self.assertEqual({'input_image': 2}, item['omitted_content'])
        self.assertEqual({'input_image': 2}, scan['omissions'][0]['types'])
        self.assertEqual(['message', 'omission'], [e['kind'] for e in item['events']])
        self.assertNotIn(marker, json.dumps(item))
        result = self.fx.checkpoint(scan)
        self.assertIn('input_image', Path(result['review']).read_text())


if __name__ == '__main__':
    unittest.main()
