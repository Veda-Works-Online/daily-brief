import sys
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, Mock
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

    def test_google_cap_preserves_price_without_exchange_reference(self):
        out = self.apply()
        self.assertEqual(out['marketCap'], self.quote['marketCap'])
        self.assertEqual(out['indexValue'], self.row['indexValue'])
        self.assertEqual(out['changePercent'], self.row['changePercent'])
        meta = out['field_metadata']['marketCap']
        self.assertEqual(meta['source'], 'Google Finance')
        self.assertEqual(meta['validation_status'], 'INDICATIVE')
        self.assertEqual(meta['source_timestamp'], self.quote['timestamp'])
        self.assertNotIn('bse_reference', meta)
        self.assertEqual(self.apply(previous=out)['marketCap'], self.quote['marketCap'])

    def test_wrong_identity_currency_stale_future_and_invalid_numbers_rejected(self):
        for change in [dict(id='HDFCBANK:NSE'), dict(currency='USD'), dict(name='HDFC Bank'),
                       dict(marketCap='NaN'), dict(price=0), dict(marketCap=-1),
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

    def test_caps_do_not_depend_on_bse_reference_or_share_count(self):
        out = self.apply(previous=dict(self.row, field_metadata={}),
            quote=dict(self.quote, marketCap=Decimal('309650000000')))
        self.assertEqual(out['marketCap'], Decimal('309650000000'))
        self.assertNotIn('bse_reference', out['field_metadata']['marketCap'])

    def test_failures_never_publish_bse_or_yahoo_caps(self):
        out = m.indian_cap_unavailable(self.row, self.row, 'GOOGLE_UNAVAILABLE', self.now)
        self.assertIsNone(out['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'], 'DATA_UNAVAILABLE')
        google = self.apply()
        google['field_metadata']['marketCap']['bse_reference'] = {'source':'BSE'}
        out = m.indian_cap_unavailable(self.row, google, 'GOOGLE_UNAVAILABLE', self.now)
        self.assertEqual(out['marketCap'], google['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'], 'STALE')
        self.assertNotIn('bse_reference', out['field_metadata']['marketCap'])

    def test_google_quote_uses_only_current_same_symbol_session_metadata(self):
        out = m.google_observation(self.row, 'ATGL.NS', self.quote, self.identity, self.now)
        self.assertEqual(out['market_status'], 'CLOSED')
        self.assertEqual(out['validation_status'], 'INDICATIVE')
        self.assertEqual(out['market_timezone'], 'Asia/Kolkata')
        for change in [dict(symbol='HDFCBANK.NS'),
                dict(_retrieved_at=(self.now-timedelta(minutes=6)).isoformat())]:
            out = m.google_observation(self.row, 'ATGL.NS', self.quote,
                dict(self.identity, **change), self.now)
            self.assertEqual(out['market_status'], 'UNKNOWN')
            self.assertEqual(out['validation_status'], 'STALE')

    def test_stale_nse_page_retries_alternate_route_without_regressing(self):
        now = datetime.now(timezone.utc)
        old = dict(self.quote, timestamp=(now-timedelta(days=1)).isoformat())
        fresh = dict(self.quote, timestamp=(now-timedelta(minutes=2)).isoformat())
        response = Mock(text='quote body')
        with patch.object(m.requests, 'get', return_value=response) as get, \
                patch.object(m, 'parse_google', side_effect=[old, fresh]):
            self.assertEqual(m.fetch_google('ATGL:NSE')['timestamp'], fresh['timestamp'])
            self.assertEqual(get.call_count, 2)
        older = dict(old, timestamp=(now-timedelta(days=2)).isoformat())
        with patch.object(m.requests, 'get', return_value=response), \
                patch.object(m, 'parse_google', side_effect=[old, older]):
            self.assertEqual(m.fetch_google('ATGL:NSE')['timestamp'], old['timestamp'])
