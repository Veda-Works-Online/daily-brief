"""October 23: beta index denominations and consistent Google FX references."""
import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m


class IndexFxReferenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 9, 16, tzinfo=timezone.utc)

    def beta(self, identifier, currency):
        quote = [None] * 22
        quote[1], quote[2], quote[4] = identifier.split(':'), 'BSE SENSEX', currency
        quote[5], quote[7] = [72804.99, -444.4, -0.6066923, 2], 73249.39
        quote[17], quote[21] = [int(self.now.timestamp())], identifier
        return ('<link rel="canonical" href="https://www.google.com/finance/quote/' + identifier + '">'
                "<script>AF_initDataCallback({key: 'ds:2', data:" + json.dumps([quote]) + ', sideChannel:{}});</script>')

    def test_beta_indexes_with_null_currency_refresh_without_weakening_equities(self):
        for identifier, currency in m.INDEX_CURRENCIES.items():
            quote = m.parse_google(self.beta(identifier, None), identifier)
            self.assertEqual(quote['currency'], currency)
            symbol = next(k for k, v in m.INDEX_IDS.items() if v == identifier)
            out = m.google_observation({'ticker': symbol, 'currency': currency}, symbol, quote, {}, self.now)
            self.assertEqual(out['indexValue'], Decimal('72804.99'))
            self.assertEqual(out['source_timestamp'], self.now.isoformat())
            self.assertEqual(out['validation_status'], 'INDICATIVE')
        quote = m.parse_google(self.beta('ADANIENT:NSE', None), 'ADANIENT:NSE')
        with self.assertRaisesRegex(ValueError, 'CURRENCY_MISMATCH'):
            m.google_observation({'name': 'BSE SENSEX', 'currency': 'INR'}, 'ADANIENT.NS', quote,
                                 {'exchange': 'NSE', 'quoteType': 'EQUITY'}, self.now)
        quote = m.parse_google(self.beta('SENSEX:INDEXBOM', 'USD'), 'SENSEX:INDEXBOM')
        with self.assertRaisesRegex(ValueError, 'CURRENCY_MISMATCH'):
            m.google_observation({'currency': 'INR'}, '^BSESN', quote, {}, self.now)

    def test_index_and_fx_always_compare_both_routes_and_keep_newer_time(self):
        for identifier in ['SENSEX:INDEXBOM', 'USD-INR', 'ALIW00:COMEX', 'CLW00:NYMEX']:
            for times in [(0, 30), (30, 0)]:
                quotes = [dict(timestamp=(self.now+timedelta(seconds=s)).isoformat()) for s in times]
                with patch.object(m.requests, 'get', return_value=Mock(text='page')) as get, \
                     patch.object(m, 'parse_google', side_effect=quotes):
                    self.assertEqual(m.fetch_google(identifier), quotes[times.index(30)])
                    self.assertEqual(get.call_count, 2)

    def test_future_alternate_failure_preserves_the_valid_actual_quote(self):
        quote = dict(id='ALIW00:COMEX', timestamp=self.now.isoformat(), price=Decimal('3245'))
        with patch.object(m.requests, 'get', return_value=Mock(text='page')) as get, \
             patch.object(m, 'parse_google', side_effect=[quote, ValueError('GOOGLE_IDENTITY_MISMATCH')]):
            self.assertEqual(m.fetch_google('ALIW00:COMEX'), quote)
            self.assertEqual(get.call_count, 2)

    def test_google_fx_regression_checks_yahoo_before_retaining_stale_data(self):
        google = dict(id='GBP-USD', currency='USD', price=Decimal('1.3491'),
                      previousClose=Decimal('1.347685'),
                      timestamp=(self.now-timedelta(minutes=3)).isoformat(),
                      retrieved_at=self.now.isoformat())
        previous = m.google_fx({'ticker':'GBPUSD=X'}, 'GBPUSD=X',
                              dict(google, timestamp=(self.now-timedelta(minutes=2)).isoformat()), self.now)
        yahoo = dict(symbol='GBPUSD=X', quoteType='CURRENCY', currency='USD',
                     regularMarketPrice=Decimal('1.3492364'), regularMarketPreviousClose=Decimal('1.3471643'),
                     regularMarketTime=int(self.now.timestamp()), _retrieved_at=self.now.isoformat())
        selected = m.freshest_fx(previous, 'GBPUSD=X', google, yahoo, self.now)
        out = m.prevent_quote_regression(previous, selected)
        self.assertEqual(out['source'], 'Yahoo Finance')
        self.assertEqual(out['validation_status'], 'INDICATIVE')
        self.assertEqual(out['indexValue'], yahoo['regularMarketPrice'])
        self.assertEqual(out['previousClose'], yahoo['regularMarketPreviousClose'])
        self.assertEqual(out['source_timestamp'], self.now.isoformat())
        self.assertIn('predates the saved observation', out['reference_fallback'])
        self.assertEqual(out['quote_policy']['max_quote_age_seconds'], 480)
        # When Google catches up, restore the primary reference.
        caught_up = dict(google, timestamp=previous['source_timestamp'])
        self.assertEqual(m.freshest_fx(previous, 'GBPUSD=X', caught_up, yahoo, self.now)['source'], 'Google Finance')
        # No usable newer source: preserve the guard and actual saved time.
        candidate = m.freshest_fx(previous, 'GBPUSD=X', google, {}, self.now)
        retained = m.prevent_quote_regression(previous, candidate)
        self.assertEqual(retained['validation_status'], 'STALE')
        self.assertEqual(retained['source_timestamp'], previous['source_timestamp'])

    def test_google_fx_keeps_reported_change_instead_of_using_rounded_rate(self):
        quote = dict(id='GBP-USD', currency='USD', price=Decimal('1.3436'),
                     previousClose=Decimal('1.345575'), reportedChangePercent=Decimal('-0.1448822'),
                     timestamp=self.now.isoformat(), retrieved_at=self.now.isoformat())
        out = m.google_fx({'ticker': 'GBPUSD=X'}, 'GBPUSD=X', quote, self.now)
        self.assertEqual(out['changePercent'], Decimal('-0.1448822'))
        self.assertEqual(out['indexValue'], Decimal('1.3436'))
        self.assertEqual(out['field_metadata']['changePercent']['source_timestamp'], out['source_timestamp'])
        self.assertEqual(out['field_metadata']['changePercent']['decimal'], '-0.1448822')
        without_header = dict(quote, reportedChangePercent=None)
        self.assertEqual(m.google_fx({}, 'GBPUSD=X', without_header, self.now)['changePercent'],
                         Decimal('-0.146777'))

    def test_fx_prefers_fresh_google_even_when_yahoo_is_later(self):
        google = dict(id='USD-INR', currency='INR', price=Decimal('94.9258'),
                      previousClose=Decimal('94.71155'), timestamp=(self.now-timedelta(minutes=3)).isoformat(),
                      retrieved_at=self.now.isoformat())
        yahoo = dict(symbol='INR=X', quoteType='CURRENCY', currency='INR',
                     regularMarketPrice=Decimal('94.9625'), regularMarketPreviousClose=Decimal('94.808'),
                     regularMarketTime=int(self.now.timestamp()), _retrieved_at=self.now.isoformat())
        out = m.freshest_fx({'reference_fallback': 'old fallback'}, 'INR=X', google, yahoo, self.now)
        self.assertEqual(out['source'], 'Google Finance')
        self.assertEqual(out['indexValue'], google['price'])
        self.assertEqual(out['previousClose'], google['previousClose'])
        self.assertEqual(out['source_timestamp'], google['timestamp'])
        self.assertNotIn('reference_fallback', out)
        # A stale Google quote does not hide a usable, explicitly labelled fallback.
        old = dict(google, timestamp=(self.now-timedelta(minutes=9)).isoformat())
        out = m.freshest_fx({}, 'INR=X', old, yahoo, self.now)
        self.assertEqual(out['source'], 'Yahoo Finance')
        self.assertIn('Yahoo Finance observation', out['reference_fallback'])
        self.assertEqual(out['previousClose'], yahoo['regularMarketPreviousClose'])


if __name__ == '__main__':
    unittest.main()
