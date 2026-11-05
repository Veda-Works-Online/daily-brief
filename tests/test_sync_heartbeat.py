"""Unchanged market observations must still publish successful source checks."""
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m
from local_gold import GOLD_ID


class SyncHeartbeatTests(unittest.TestCase):
    def test_unchanged_values_keep_new_retrieval_and_original_quote_time(self):
        old = '2026-11-05T03:30:00+00:00'
        new = '2026-11-05T03:35:00+00:00'
        gold = dict(ticker=GOLD_ID, name='Gold', indexValue=14742,
                    source_timestamp=old, retrieved_at=old, retrievedAt=old,
                    validation_status='INDICATIVE', verification_version=1)
        with patch.object(m, 'yahoo_quotes', return_value={}), \
             patch.object(m, 'fetch_google', side_effect=ValueError('UNAVAILABLE')), \
             patch.object(m, 'refresh_gold', return_value=gold):
            baseline, _ = m.refresh_markets({'regions': {'commodities': [gold]}})
        candidate = deepcopy(baseline['regions']['commodities'][0])
        candidate.update(retrieved_at=new, retrievedAt=new)
        original = deepcopy(baseline)
        with patch.object(m, 'yahoo_quotes', return_value={}), \
             patch.object(m, 'fetch_google', side_effect=ValueError('UNAVAILABLE')), \
             patch.object(m, 'refresh_gold', return_value=candidate):
            result, _ = m.refresh_markets(baseline)
        row = result['regions']['commodities'][0]
        self.assertEqual(row['retrieved_at'], new)
        self.assertEqual(row['retrievedAt'], new)
        self.assertEqual(row['source_timestamp'], old)
        self.assertEqual(row['indexValue'], gold['indexValue'])
        self.assertEqual(result['updated'], baseline['updated'])
        self.assertEqual(baseline, original)


if __name__ == '__main__':
    unittest.main()
