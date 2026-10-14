import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from trading_sessions import annotate_sessions


class TradingSessionTests(unittest.TestCase):
    def row(self):
        return dict(indexValue=2695, previousClose=2630, changePercent=2.471483,
            marketCap=3110000000000, market_status='CLOSED', market_timezone='Asia/Kolkata',
            source_timestamp='2026-10-14T03:39:34+00:00',
            field_metadata={
                'changePercent': dict(source='Yahoo Finance', validation_status='INDICATIVE',
                    source_timestamp='2026-10-14T03:39:34+00:00'),
                'marketCap': dict(source='Google Finance', validation_status='STALE',
                    source_timestamp='2026-10-13T10:00:00+00:00')})

    def google(self):
        return dict(price=2695, previousClose=2630, timestamp='2026-10-13T10:00:00+00:00')

    def test_adani_preopen_observation_is_previous_session(self):
        row = self.row()
        original = deepcopy(row)
        annotate_sessions(row, self.google(), datetime(2026, 10, 14, 3, 44, tzinfo=timezone.utc))
        for field in ('changePercent', 'marketCap'):
            self.assertEqual(row['field_metadata'][field]['trading_session']['date'], '2026-10-13')
            self.assertEqual(row['field_metadata'][field]['source_timestamp'], original['field_metadata'][field]['source_timestamp'])
        self.assertEqual(row['source_timestamp'], original['source_timestamp'])
        self.assertEqual(row['field_metadata']['marketCap']['validation_status'], 'STALE')

    def test_missing_mismatched_old_future_or_offhours_evidence_stays_unknown(self):
        now = datetime(2026, 10, 14, 3, 44, tzinfo=timezone.utc)
        for quote in (None, dict(self.google(), price=2696), dict(self.google(), previousClose=2600),
                      dict(self.google(), timestamp='2026-09-01T10:00:00Z'),
                      dict(self.google(), timestamp='2026-10-14T10:00:00Z'),
                      dict(self.google(), timestamp='2026-10-13T03:00:00Z')):
            row = annotate_sessions(self.row(), quote, now)
            self.assertIsNone(row['field_metadata']['changePercent']['trading_session']['date'])

    def test_exchange_date_and_dst_not_regional_display_date(self):
        for zone, timestamp, expected in (
            ('America/New_York', '2026-01-15T21:00:00Z', '2026-01-15'),
            ('America/New_York', '2026-07-15T20:00:00Z', '2026-07-15'),
            ('Asia/Seoul', '2026-10-14T06:00:00Z', '2026-10-14'),
            ('Asia/Hong_Kong', '2026-10-14T08:00:00Z', '2026-10-14')):
            row = self.row()
            row.update(market_timezone=zone, display_timezone='Asia/Singapore')
            row['field_metadata']['changePercent']['source_timestamp'] = timestamp
            annotate_sessions(row)
            self.assertEqual(row['field_metadata']['changePercent']['trading_session']['date'], expected)

    def test_field_dates_are_independent_and_retained_evidence_survives(self):
        row = self.row()
        row['field_metadata']['changePercent']['source_timestamp'] = '2026-10-14T04:00:00Z'
        annotate_sessions(row)
        self.assertEqual(row['field_metadata']['changePercent']['trading_session']['date'], '2026-10-14')
        self.assertEqual(row['field_metadata']['marketCap']['trading_session']['date'], '2026-10-13')
        row = annotate_sessions(self.row(), self.google(), datetime(2026, 10, 14, 3, 44, tzinfo=timezone.utc))
        annotate_sessions(row)
        self.assertEqual(row['field_metadata']['changePercent']['trading_session']['date'], '2026-10-13')
        row['field_metadata']['changePercent']['source_timestamp'] = '2026-10-15T03:00:00Z'
        annotate_sessions(row)
        self.assertIsNone(row['field_metadata']['changePercent']['trading_session']['date'])

    def test_invalid_missing_weekend_and_unavailable(self):
        for value in (None, 'invalid', '2026-10-13T10:00:00', '2026-10-11T10:00:00Z'):
            row = self.row()
            row['field_metadata']['marketCap']['source_timestamp'] = value
            annotate_sessions(row)
            self.assertIsNone(row['field_metadata']['marketCap']['trading_session']['date'])
        row = self.row()
        row['marketCap'] = None
        annotate_sessions(row)
        self.assertEqual(row['field_metadata']['marketCap']['trading_session']['basis'], 'Data unavailable')
