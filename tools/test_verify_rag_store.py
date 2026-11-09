import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_rag_store import KEY_BY_LEVEL, check_sources, compare_snapshot, expected_chunks, live_extraction_status, verify_snapshots


class RagStoreVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.expected = expected_chunks()

    def setUp(self):
        self.snapshots = []
        for level in ('all', 'staff'):
            rows = [dict(r) for r in self.expected if r['access_level'] == level]
            self.snapshots.append({'store_key': KEY_BY_LEVEL[level], 'exhaustive': True,
                                  'reported_total': len(rows),
                                  'enumeration_proof': {'method': 'native_full_enumeration', 'store_total': len(rows),
                                                        'extracted_total': len(rows), 'cursor_exhausted': True},
                                  'records': rows})

    def test_expected_source_documents_produce_37_public_5_staff_42_total(self):
        self.assertEqual((37, 5, 42), (sum(r['access_level']=='all' for r in self.expected),
                                      sum(r['access_level']=='staff' for r in self.expected), len(self.expected)))
        self.assertEqual(42, len({(r['doc'], r['section']) for r in self.expected}))

    def test_source_preflight_pass_is_limited_to_source_documents(self):
        result = check_sources()
        self.assertEqual('PASS', result['status'])
        self.assertEqual((8, 37, 5), (result['documents'], result['public'], result['staff']))
        self.assertFalse(result['store_records_verified'])

    def test_source_preflight_rejects_missing_documents(self):
        result = check_sources(Path('missing-ticketmoa-knowledge'))
        self.assertEqual('FAIL', result['status'])

    def test_workflow_template_uses_real_newline_escapes(self):
        workflow = json.loads((Path(__file__).resolve().parents[1] / 'workflows/ticketmoa-index.json').read_text(encoding='utf-8'))
        code = next(n['parameters']['jsCode'] for n in workflow['nodes'] if n['name'] == 'Validate and make chunks')
        expected = 'text: `# ${doc}\n## ${piece.section}\n${piece.text}`'
        broken = 'text: `# ${doc}' + chr(92) + 'n## ${piece.section}'
        self.assertIn(expected, code)
        self.assertNotIn(broken, code)

    def test_native_live_extraction_is_unverifiable(self):
        result = live_extraction_status()
        self.assertEqual('UNVERIFIABLE', result['status'])
        self.assertTrue(any('top-N' in issue for issue in result['issues']))

    def test_exhaustive_flag_without_enumeration_proof_is_unverifiable(self):
        del self.snapshots[0]['enumeration_proof']
        self.assertEqual('UNVERIFIABLE', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_top_n_results_cannot_claim_full_snapshot(self):
        self.snapshots[0]['exhaustive'] = False
        self.assertEqual('UNVERIFIABLE', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_exact_complete_snapshot_passes(self):
        self.assertEqual('PASS', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_missing_chunk_fails(self):
        self.snapshots[0]['records'].pop()
        self.snapshots[0]['reported_total'] -= 1
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_duplicate_chunk_fails(self):
        self.snapshots[0]['records'].append(copy.deepcopy(self.snapshots[0]['records'][0]))
        self.snapshots[0]['reported_total'] += 1
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_body_mismatch_fails(self):
        self.snapshots[0]['records'][0]['text'] += 'tampered'
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_access_level_mismatch_fails(self):
        self.snapshots[0]['records'][0]['access_level'] = 'staff'
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_staff_record_in_public_store_fails(self):
        staff = next(r for r in self.expected if r['access_level'] == 'staff')
        self.snapshots[0]['records'].append(dict(staff))
        self.snapshots[0]['reported_total'] += 1
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_missing_metadata_is_unverifiable(self):
        del self.snapshots[0]['records'][0]['section']
        self.assertEqual('UNVERIFIABLE', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_partial_result_is_unverifiable(self):
        self.snapshots[0]['exhaustive'] = False
        self.assertEqual('UNVERIFIABLE', verify_snapshots(self.expected, self.snapshots)['status'])

    def test_reported_count_mismatch_fails(self):
        self.snapshots[0]['reported_total'] += 1
        self.assertEqual('FAIL', verify_snapshots(self.expected, self.snapshots)['status'])


if __name__ == '__main__':
    unittest.main()
