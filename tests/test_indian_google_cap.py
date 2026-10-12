import sys
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m


class IndianGoogleCapTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,12,11,tzinfo=timezone.utc)
        self.row = dict(name='Adani Total Gas Ltd', ticker='ATGL.NS', currency='INR',
            marketCap=Decimal('618200000000'), indexValue=Decimal('563'), changePercent=Decimal('1'),
            source_timestamp='2026-10-12T10:00:00+00:00',
            field_metadata={'marketCap':dict(source='BSE', validation_status='STALE',
                exchange_price=Decimal('562'), source_timestamp='2026-10-08T10:30:00+00:00')})
        self.quote = dict(id='ATGL:NSE', name='Adani Total Gas Ltd', exchange='NSE', currency='INR',
            price=Decimal('563'), marketCap=Decimal('619300000000'),
            timestamp=self.row['source_timestamp'], retrieved_at=self.now.isoformat())
        self.identity = dict(symbol='ATGL.NS', quoteType='EQUITY', exchange='NSI', currency='INR',
            marketState='POSTPOST', exchangeTimezoneName='Asia/Kolkata', _retrieved_at=self.now.isoformat())

    def apply(self, quote=None, previous=None, identity=None):
        return m.indian_google_cap(self.row, previous or self.row, 'ATGL.NS',
            self.quote if quote is None else quote, self.identity if identity is None else identity, self.now)

    def test_google_cap_preserves_price_and_reference_across_cycles(self):
        out = self.apply()
        self.assertEqual(out['marketCap'], self.quote['marketCap'])
        self.assertEqual(out['indexValue'], self.row['indexValue'])
        self.assertEqual(out['changePercent'], self.row['changePercent'])
        meta = out['field_metadata']['marketCap']
        self.assertEqual(meta['source'], 'Google Finance')
        self.assertEqual(meta['validation_status'], 'INDICATIVE')
        self.assertEqual(meta['source_timestamp'], self.quote['timestamp'])
        self.assertEqual(self.apply(previous=out)['field_metadata']['marketCap']['bse_reference'], meta['bse_reference'])

    def test_wrong_identity_currency_stale_future_and_share_counts_rejected(self):
        for change in [dict(id='HDFCBANK:NSE'), dict(currency='USD'), dict(name='HDFC Bank'),
                       dict(marketCap='NaN'), dict(price=0), dict(marketCap=Decimal('309650000000')),
                       dict(timestamp=(self.now+timedelta(minutes=3)).isoformat()),
                       dict(timestamp=(self.now-timedelta(days=9)).isoformat()),
                       dict(retrieved_at=(self.now-timedelta(minutes=6)).isoformat())]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.apply(quote=dict(self.quote, **change))

    def test_unknown_session_is_conservative_and_old_quote_cannot_regress(self):
        with self.assertRaisesRegex(ValueError, 'QUOTE_STALE'):
            self.apply(identity=dict(self.identity, _retrieved_at=(self.now-timedelta(minutes=6)).isoformat()))
        with self.assertRaisesRegex(ValueError, 'QUOTE_STALE'):
            self.apply(identity=dict(self.identity, marketState='REGULAR'))
        out = self.apply()
        with self.assertRaisesRegex(ValueError, 'OLDER_OBSERVATION'):
            self.apply(previous=out, quote=dict(self.quote, timestamp='2026-10-12T09:59:59+00:00'))

    def test_missing_reference_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'REFERENCE_UNAVAILABLE'):
            self.apply(previous=dict(self.row, field_metadata={}))
