import json
from pathlib import Path
import unittest

import test_dream as fixtures


dream = fixtures.dream


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.DreamTests('test_initialization_and_staging_never_mutate_formal_wiki')
        self.fx.setUp()
        self.addCleanup(self.fx.temp.cleanup)

    def snapshot(self):
        return {str(p.relative_to(self.fx.wiki)): p.read_bytes() for p in self.fx.wiki.rglob('*') if p.is_file()}

    def test_scan_and_handwritten_state_are_not_a_completed_run(self):
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        dream.atomic(directory / 'review.json', b'{"status":"pending_review"}\n')
        before = self.snapshot()
        with self.assertRaisesRegex(dream.DreamError, 'successfully staged'):
            self.fx.call('status', '--run', scan['run'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual({}, self.fx.state()['cursors'])

    def test_scan_scaffold_cannot_be_staged_without_analysis(self):
        scan = self.fx.call('scan')
        self.assertEqual(str(Path(scan['directory']) / 'draft'), scan['draft'])
        scaffold = dream.load(Path(scan['review']))
        self.assertEqual([], scaffold['processed'])
        self.assertFalse(scaffold['organized'])
        self.assertFalse(any(d['reason'] for d in scaffold['input_decisions']))
        with self.assertRaises(dream.DreamError):
            self.fx.call('stage', '--run', scan['run'])
        self.assertEqual({}, self.fx.state()['cursors'])
        self.assertIsNone(self.fx.state()['pending'])

    def test_unapproved_formal_write_blocks_stage_without_adopting_the_write(self):
        scan, directory = self.fx.prepare()
        dream.atomic(self.fx.wiki / 'index.md', b'# Written outside the draft\n')
        before = self.snapshot()
        with self.assertRaisesRegex(dream.DreamError, 'do not rescan'):
            self.fx.call('stage', '--run', scan['run'])
        self.assertEqual(before, self.snapshot())
        self.assertFalse((directory / 'sealed.json').exists())
        self.assertEqual({}, self.fx.state()['cursors'])

    def test_processed_source_objects_are_rejected_without_checkpoint_changes(self):
        scan, directory = self.fx.prepare()
        review = dream.load(directory / 'review.json')
        review['processed'] = [{'source_id': review['processed'][0]}]
        dream.atomic(directory / 'review.json', dream.encoded(review))
        with self.assertRaisesRegex(dream.DreamError, 'list of source_id strings'):
            self.fx.call('stage', '--run', scan['run'])
        self.assertEqual({}, self.fx.state()['cursors'])

    def test_pending_scaffold_keeps_candidates_without_claiming_fresh_processing(self):
        first, old = self.fx.stage_initial()
        before = self.fx.state()
        scan = self.fx.call('scan', '--revise')
        scaffold = dream.load(Path(scan['review']))
        previous = dream.load(old / 'review.json')
        self.assertEqual(previous['facts'], scaffold['facts'])
        self.assertEqual(previous['groups'], scaffold['groups'])
        self.assertEqual([], scaffold['processed'])
        self.assertFalse(scaffold['organized'])
        self.assertEqual(before, self.fx.state())
        reselected = self.fx.call('scan', '--revise', '--reselect-pending')
        blank = dream.load(Path(reselected['review']))
        self.assertEqual([], blank['facts'])
        self.assertEqual([], blank['groups'])
        self.assertEqual(first['revision'], self.fx.state()['pending']['revision'])

    def test_verified_delivery_is_read_only_and_names_real_artifacts(self):
        staged, directory = self.fx.stage_initial()
        before = self.snapshot()
        result = self.fx.call('status', '--run', self.fx.state()['analysis_run'])['verification']
        self.assertEqual('pending_review', result['status'])
        self.assertEqual(staged['revision'], result['revision'])
        self.assertEqual(str(directory / 'draft'), result['draft'])
        self.assertTrue(Path(result['review']).is_file())
        self.assertTrue(Path(result['diff']).is_file())
        self.assertFalse(result['semantic_truth_verified'])
        self.assertFalse(result['human_approval_verified'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual({}, dream.pages(self.fx.wiki))

    def test_readable_review_and_diff_tampering_block_delivery_and_merge(self):
        staged, directory = self.fx.stage_initial()
        for name in ('review.md', 'changes.diff'):
            with self.subTest(name=name):
                original = (directory / name).read_bytes()
                dream.atomic(directory / name, b'Everything approved, no changes.\n')
                for command, args in [('status', ['--run', directory.name]), ('apply', ['--revision', staged['revision'], '--groups', 'all'])]:
                    with self.assertRaisesRegex(dream.DreamError, 'Readable review or diff'):
                        self.fx.call(command, *args)
                self.assertEqual({}, dream.pages(self.fx.wiki))
                self.assertEqual(staged['revision'], self.fx.state()['pending']['revision'])
                dream.atomic(directory / name, original)

    def test_modified_draft_cannot_be_reported_as_verified(self):
        _, directory = self.fx.stage_initial()
        dream.atomic(directory / 'draft/semantic/projects/atlas.md', b'# A changed claim\n')
        with self.assertRaisesRegex(dream.DreamError, 'modified'):
            self.fx.call('status', '--run', directory.name)
        self.assertEqual({}, dream.pages(self.fx.wiki))

    def test_scan_metadata_cannot_be_changed_with_a_matching_rewritten_summary(self):
        staged, directory = self.fx.stage_initial()
        record = dream.load(directory / 'scan.json')
        record['failures'].append({'source': 'unreadable.json', 'reason': 'Invented coverage change'})
        dream.atomic(directory / 'scan.json', dream.encoded(record))
        dream.atomic(directory / 'review.md', dream.review_document(record, dream.load(directory / 'review.json'), staged['revision']))
        for command, args in [('status', ['--run', directory.name]), ('apply', ['--revision', staged['revision'], '--groups', 'all'])]:
            with self.assertRaisesRegex(dream.DreamError, 'scan record was modified'):
                self.fx.call(command, *args)
        self.assertEqual({}, dream.pages(self.fx.wiki))

    def test_premature_formal_writes_are_detected_without_overwriting_them(self):
        _, directory = self.fx.stage_initial()
        dream.atomic(self.fx.wiki / 'index.md', b'# External edit\n')
        before = self.snapshot()
        with self.assertRaisesRegex(dream.DreamError, 'reviewed base'):
            self.fx.call('status', '--run', directory.name)
        self.assertEqual(before, self.snapshot())

    def test_analysis_checkpoint_must_match_the_sealed_run(self):
        staged, directory = self.fx.stage_initial()
        state = self.fx.state()
        state['cursors'][next(iter(state['cursors']))] = {}
        dream.atomic(dream.state_path(self.fx.wiki), dream.encoded(state))
        for command, args in [('status', ['--run', directory.name]), ('apply', ['--revision', staged['revision'], '--groups', 'all'])]:
            with self.assertRaisesRegex(dream.DreamError, 'checkpoint'):
                self.fx.call(command, *args)
        self.assertEqual({}, dream.pages(self.fx.wiki))

    def test_superseded_runs_cannot_be_presented_as_current_delivery(self):
        first, old = self.fx.stage_initial()
        scan, _ = self.fx.prepare(self.fx.call('scan', '--revise'))
        self.fx.call('stage', '--run', scan['run'])
        with self.assertRaisesRegex(dream.DreamError, 'latest'):
            self.fx.call('status', '--run', old.name)
        result = self.fx.call('status', '--run', scan['run'])['verification']
        self.assertNotEqual(first['revision'], result['revision'])

    def test_justified_empty_result_can_be_verified_without_pending_approval(self):
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        record = dream.load(directory / 'scan.json')
        ids = [s['source_id'] for s in record['sources']]
        review = {'summary': 'No durable memory selected.', 'organized': True, 'processed': ids, 'failures': [], 'facts': [], 'groups': [], 'input_decisions': [{'source_id': i, 'reason': 'No lasting value.'} for i in ids]}
        dream.atomic(directory / 'review.json', dream.encoded(review))
        self.fx.call('stage', '--run', scan['run'])
        result = self.fx.call('status', '--run', scan['run'])['verification']
        self.assertEqual('no_changes', result['status'])
        self.assertIsNone(self.fx.state()['pending'])

    def test_non_content_checkpoint_is_verified_without_inventing_memories(self):
        self.fx.source.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'empty-session'}}) + '\n')
        scan = self.fx.call('scan')
        directory = Path(scan['directory'])
        self.assertTrue(dream.load(directory / 'scan.json')['empty_advances'])
        dream.atomic(directory / 'review.json', dream.encoded({'summary': 'No content events.', 'organized': True, 'processed': [], 'failures': [], 'facts': [], 'groups': [], 'input_decisions': []}))
        self.fx.call('stage', '--run', scan['run'])
        self.assertEqual('no_changes', self.fx.call('status', '--run', scan['run'])['verification']['status'])
        state = self.fx.state()
        state['cursors'][next(iter(state['cursors']))] = {}
        dream.atomic(dream.state_path(self.fx.wiki), dream.encoded(state))
        with self.assertRaisesRegex(dream.DreamError, 'empty-input checkpoint'):
            self.fx.call('status', '--run', scan['run'])

    def test_interrupted_transaction_cannot_be_delivered_as_complete(self):
        _, directory = self.fx.stage_initial()
        dream.atomic(self.fx.wiki / '.dreaming/transaction.json', b'{}\n')
        before = self.snapshot()
        with self.assertRaisesRegex(dream.DreamError, 'interrupted merge'):
            self.fx.call('status', '--run', directory.name)
        self.assertEqual(before, self.snapshot())


class VerbatimEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.DreamTests('test_initialization_and_staging_never_mutate_formal_wiki')
        self.fx.setUp()
        self.addCleanup(self.fx.temp.cleanup)

    def stage(self, scan, directory, review):
        dream.atomic(directory / 'review.json', dream.encoded(review))
        return self.fx.call('stage', '--run', scan['run'])

    def test_missing_or_paraphrased_quote_cannot_advance_progress(self):
        scan, directory = self.fx.prepare()
        for quote in (None, '', 'CSV is universally preferred.'):
            with self.subTest(quote=quote):
                review = dream.load(directory / 'review.json')
                review['facts'][0]['evidence'][0]['quote'] = quote
                with self.assertRaisesRegex(ValueError, 'verbatim quote'):
                    self.stage(scan, directory, review)
                self.assertEqual({}, self.fx.state()['cursors'])
                self.assertIsNone(self.fx.state()['pending'])

    def test_ignored_legacy_excerpts_are_not_promoted_or_forced_into_the_wiki(self):
        scan, directory = self.fx.prepare()
        review = dream.load(directory / 'review.json')
        ignored = {**review['facts'][0], 'id': 'legacy-ignored', 'action': 'ignore', 'targets': [], 'evidence': [{**review['facts'][0]['evidence'][0], 'quote': 'An old unverified paraphrase.'}]}
        review['facts'].append(ignored)
        self.stage(scan, directory, review)
        self.assertNotIn('An old unverified paraphrase.', '\n'.join(p.decode() for p in dream.pages(directory / 'draft').values()))
        revised = self.fx.call('scan', '--revise')
        draft = Path(revised['directory'])
        self.fx.prepare(revised)
        promoted = dream.load(draft / 'review.json')
        promoted['facts'][0]['evidence'] = ignored['evidence']
        with self.assertRaisesRegex(ValueError, 'verbatim quote'):
            self.stage(revised, draft, promoted)

    def test_translation_is_not_a_verbatim_quote(self):
        self.fx.source.write_text(json.dumps({'type': 'message', 'role': 'user', 'text': '页面适配内容，不为模板牺牲内容。'}, ensure_ascii=False) + '\n')
        scan = self.fx.call('scan')
        scan, directory = self.fx.prepare(scan, extra={'evidence/atlas.md': '# Evidence\n\n页面适配内容，不为模板牺牲内容。\n'.encode()})
        review = dream.load(directory / 'review.json')
        review['facts'][0]['evidence'][0]['quote'] = 'Adapt the page to the content.'
        with self.assertRaisesRegex(ValueError, 'verbatim quote'):
            self.stage(scan, directory, review)

    def test_quote_from_another_source_cannot_be_attached_to_this_source(self):
        other = self.fx.root / 'beacon.json'
        other.write_text(json.dumps({'session_id': 'beacon', 'events': [{'type': 'message', 'role': 'user', 'text': 'Beacon uses Markdown.'}]}) + '\n')
        scan = self.fx.call('scan', '--input', str(self.fx.source), '--input', str(other))
        scan, directory = self.fx.prepare(scan)
        item = next(dream.load(p) for p in (directory / 'inputs').glob('*.json') if dream.load(p)['events'][0]['text'] == 'For Atlas only, keep CSV.')
        review = dream.load(directory / 'review.json')
        review['facts'][0]['evidence'][0].update(source_id=item['source_id'], ref=item['events'][0]['ref'], quote='Beacon uses Markdown.')
        with self.assertRaisesRegex(ValueError, 'verbatim quote'):
            self.stage(scan, directory, review)

    def test_correct_review_quote_must_also_exist_on_the_published_evidence_page(self):
        scan, directory = self.fx.prepare()
        dream.atomic(directory / 'draft/evidence/atlas.md', b'# Verbatim excerpt\n\nThe user likes exports.\n')
        with self.assertRaisesRegex(ValueError, 'absent from its evidence page'):
            self.fx.call('stage', '--run', scan['run'])
        self.assertEqual({}, self.fx.state()['cursors'])

    def test_valid_source_quote_cannot_point_to_a_different_evidence_page(self):
        scan, directory = self.fx.prepare()
        review = dream.load(directory / 'review.json')
        review['facts'][0]['evidence'][0]['page'] = 'semantic/projects/atlas.md'
        with self.assertRaisesRegex(ValueError, 'local evidence page'):
            self.stage(scan, directory, review)

    def test_structured_tool_output_can_supply_a_verifiable_excerpt(self):
        self.fx.append({'type': 'tool_call', 'call_id': 'tests', 'name': 'test', 'input': {}}, {'type': 'tool_result', 'call_id': 'tests', 'output': {'exit_code': 0, 'message': '2 tests passed'}})
        scan, directory = self.fx.prepare(extra={'evidence/atlas.md': b'# Test output\n\n"message": "2 tests passed"\n'})
        item = dream.load(next((directory / 'inputs').glob('*.json')))
        event = next(e for e in item['events'] if e['kind'] == 'tool_result')
        review = dream.load(directory / 'review.json')
        review['facts'][0].update(statement='Two tests passed locally; deployment is unverified.', status='observed')
        review['facts'][0]['evidence'][0].update(ref=event['ref'], quote='"message": "2 tests passed"')
        self.stage(scan, directory, review)
        self.assertEqual('pending_review', self.fx.call('status', '--run', scan['run'])['verification']['status'])


class QuotedMarkdownTests(unittest.TestCase):
    def test_source_links_and_nested_fences_are_literal_evidence(self):
        quote = '[Historical skill](/outside/old-skill.md)\n```python\n[[not-navigation]]\n```'
        pages = {'evidence/source.md': ('# Source\n\n````text\n' + quote + '\n````\n\n[Wiki](../index.md)\n').encode(), 'index.md': b'# Wiki\n'}
        dream.check_links(pages)
        self.assertIn(quote, pages['evidence/source.md'].decode())

    def test_real_broken_links_after_a_long_fence_are_still_rejected(self):
        text = b'````text\n```\n[Original](/outside/source)\n```\n````\n\n[Broken](missing.md)\n'
        with self.assertRaisesRegex(dream.DreamError, 'Broken link'):
            dream.check_links({'index.md': text})

    def test_tilde_fences_do_not_turn_source_wiki_links_into_navigation(self):
        dream.check_links({'index.md': b'~~~text\n[[original-source]]\n[Original](/outside/source)\n~~~\n'})


if __name__ == '__main__':
    unittest.main()
