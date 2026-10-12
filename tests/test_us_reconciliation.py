import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m


class USReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 12, 13, tzinfo=timezone.utc)
        self.ts = '2026-10-09T20:00:01+00:00'
        self.row = dict(ticker='ADBE', name='Adobe Inc', currency='USD')
        self.yahoo = dict(symbol='ADBE', longName='Adobe Inc', quoteType='EQUITY',
            currency='USD', exchange='NMS', exchangeTimezoneName='America/New_York',
            marketState='PRE', regularMarketTime=int(m.timestamp(self.ts).timestamp()),
            regularMarketPrice=Decimal('242.27'), regularMarketPreviousClose=Decimal('241.05'),
            marketCap=Decimal('94291484672'), _retrieved_at=self.now.isoformat())
        self.google = dict(id='ADBE:NASDAQ', name='Adobe Inc', exchange='NASDAQ',
            currency='USD', timestamp=self.ts, retrieved_at=self.now.isoformat(),
            price=Decimal('242.27'), previousClose=Decimal('242.27'),
            marketCap=Decimal('94290000000'), cap_resolution=Decimal('10000000'))

    def test_rolled_google_close_does_not_zero_regular_session_change(self):
        out = m.accepted(self.row, 'ADBE', self.yahoo, self.google, self.now)
        out = m.fill_google_fields(out, self.google, self.now)
        self.assertEqual(out['changePercent'], Decimal('0.506119'))
        self.assertEqual(out['previousClose'], Decimal('241.05'))
        self.assertEqual(out['field_metadata']['changePercent']['source'], 'Yahoo Finance')
        self.assertEqual(out['field_metadata']['changePercent']['validation_status'], 'INDICATIVE')
        self.assertEqual(out['field_metadata']['changePercent']['source_timestamp'], self.ts)

    def test_different_prices_do_not_mix_regular_session_change_inputs(self):
        self.yahoo['regularMarketPrice'] = Decimal('242.28')
        out = m.accepted(self.row, 'ADBE', self.yahoo, self.google, self.now)
        self.assertIsNone(out['changePercent'])

    def test_new_corroborated_cap_replaces_saved_nasdaq_but_conflict_retains_it(self):
        old = dict(self.row, marketCap=Decimal('90000000000'), marketCapUSD=Decimal('90000000000'),
            quote_currency='USD', field_metadata={'marketCap':dict(source='Nasdaq',
                source_timestamp='2026-10-09T19:00:00+00:00', decimal='90000000000',
                validation_status='INDICATIVE')})
        now = self.now
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now
        with patch.object(m, 'yahoo_quotes', return_value={'ADBE':self.yahoo}), \
                patch.object(m, 'fetch_google', return_value=self.google), \
                patch.object(m, 'datetime', FrozenDatetime):
            out, _ = m.refresh_markets({'regions':{'us':[old]}})
        self.assertEqual(out['regions']['us'][0]['marketCap'], self.yahoo['marketCap'])
        self.assertEqual(out['regions']['us'][0]['field_metadata']['marketCap']['source'], 'Yahoo Finance')
        conflict = dict(self.google, marketCap=Decimal('80000000000'))
        with patch.object(m, 'yahoo_quotes', return_value={'ADBE':self.yahoo}), \
                patch.object(m, 'fetch_google', return_value=conflict), \
                patch.object(m, 'fetch_nasdaq_cap', side_effect=TimeoutError), \
                patch.object(m, 'datetime', FrozenDatetime):
            out, _ = m.refresh_markets({'regions':{'us':[old]}})
        self.assertEqual(out['regions']['us'][0]['marketCap'], old['marketCap'])
        self.assertEqual(out['regions']['us'][0]['field_metadata']['marketCap']['source'], 'Nasdaq')
