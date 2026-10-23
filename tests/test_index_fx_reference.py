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
        for identifier in ['SENSEX:INDEXBOM', 'USD-INR']:
            for times in [(0, 30), (30, 0)]:
                quotes = [dict(timestamp=(self.now+timedelta(seconds=s)).isoformat()) for s in times]
                with patch.object(m.requests, 'get', return_value=Mock(text='page')) as get, \
                     patch.object(m, 'parse_google', side_effect=quotes):
                    self.assertEqual(m.fetch_google(identifier), quotes[times.index(30)])
                    self.assertEqual(get.call_count, 2)

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
