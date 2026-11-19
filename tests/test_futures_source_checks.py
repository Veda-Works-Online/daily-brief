"""Conflicting Google futures pages must not silently choose a price."""
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m


class FuturesSourceChecks(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 19, 3, 20, tzinfo=timezone.utc)
        self.q = dict(id='SIW00:COMEX', name='Silver', exchange='COMEX', currency='USD',
                      price=Decimal('44.49'), previousClose=Decimal('45.059'),
                      reportedChangePercent=Decimal('-1.2516905'),
                      timestamp=(self.now-timedelta(minutes=10)).isoformat(),
                      retrieved_at=self.now.isoformat())

    def fetch(self, quotes):
        with patch.object(m.requests, 'get', return_value=Mock(text='page')), \
             patch.object(m, 'parse_google', side_effect=quotes):
            return m.fetch_google('SIW00:COMEX')

    def test_equal_timestamp_price_or_percent_conflicts_are_rejected(self):
        for changes in [dict(price=Decimal('44.50')),
                        dict(reportedChangePercent=Decimal('-1.20'))]:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'FUTURES_SNAPSHOT_CONFLICT'):
                self.fetch([self.q, dict(self.q, **changes)])
        self.assertEqual(self.fetch([self.q, deepcopy(self.q)]), self.q)

    def test_newer_quote_is_selected_and_failed_alternate_keeps_valid_quote(self):
        newer = dict(self.q, price=Decimal('44.50'), timestamp=self.now.isoformat())
        for quotes in [[self.q, newer], [newer, self.q]]:
            self.assertEqual(self.fetch(quotes), newer)
        self.assertEqual(self.fetch([self.q, ValueError('SCHEMA_CHANGED')]), self.q)

    def test_reported_percentage_and_stale_age_are_preserved(self):
        old = dict(self.q, timestamp=(self.now-timedelta(minutes=40)).isoformat())
        out = m.google_observation({'ticker':'SI=F','name':'Silver','currency':'USD'},
                                   'SI=F', old, {}, self.now)
        self.assertEqual(out['changePercent'], old['reportedChangePercent'])
        self.assertEqual(out['field_metadata']['changePercent']['source_timestamp'], old['timestamp'])
        self.assertEqual(out['field_metadata']['changePercent']['validation_status'], 'STALE')
        self.assertEqual(out['quote_policy']['max_quote_age_seconds'], 1800)
        self.assertEqual(out['source_timestamp'], old['timestamp'])

    def test_conflict_retains_saved_value_with_explicit_failed_source_check(self):
        saved = m.google_observation({'ticker':'SI=F','name':'Silver','currency':'USD'},
                                     'SI=F', self.q, {}, self.now)
        with patch.object(m, 'yahoo_quotes', return_value={}), \
             patch.object(m, 'fetch_google', side_effect=ValueError('GOOGLE_FUTURES_SNAPSHOT_CONFLICT')):
            output, _ = m.refresh_markets({'regions':{'commodities':[saved]}})
        row = output['regions']['commodities'][0]
        self.assertEqual(row['indexValue'], saved['indexValue'])
        self.assertEqual(row['source_timestamp'], saved['source_timestamp'])
        self.assertEqual(row['validation_status'], 'STALE')
        self.assertEqual(row['futures_source_check']['status'], 'CONFLICT')


if __name__ == '__main__':
    unittest.main()
