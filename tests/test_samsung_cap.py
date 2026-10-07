import sys
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import samsung_cap as s
import market_data as m


REPORT = '''<h1>Samsung Electronics</h1>005930 005935
<table><caption>Shares outstanding and Treasury shares</caption>
<tr><td>Mar 31, 2026</td><td>5,919,637,922</td><td>815,974,664</td><td>6,735,612,586</td><td>127,074,618</td><td>13,603,461</td><td>140,678,079</td></tr>
<tr><td>Jun 30, 2026</td><td>5,846,278,608</td><td>802,371,203</td><td>6,648,649,811</td><td>82,086,705</td><td>-</td><td>82,086,705</td></tr></table>'''


class SamsungCapTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 7, 0, 10, tzinfo=timezone.utc)
        self.common = dict(id='005930:KRX', exchange='KRX', currency='KRW',
            name='Samsung Electronics Co Ltd', price=Decimal('273000'),
            timestamp='2026-10-07T00:08:00+00:00', session='REGULAR', source='Google Finance')
        self.preferred = dict(self.common, id='005935:KRX', price=Decimal('198200'),
            name='Samsung Electronics Co Ltd Preference Shares Non Voting')
        self.shares = s.parse_share_counts(REPORT, self.now)
        self.row = dict(ticker='005930.KS', indexValue=Decimal('273000'),
            source_timestamp=self.common['timestamp'], validation_status='VERIFIED',
            currency='KRW', quote_currency='KRW', field_metadata={}, marketCap=Decimal('1757170000000000'))

    def calculate(self):
        return s.apply_company_cap(self.row, self.common, self.preferred, self.shares, self.now, 1800)

    def test_latest_dated_counts_and_exact_two_class_sum(self):
        out = self.calculate()
        self.assertEqual(self.shares['as_of'], '2026-06-30')
        expected = Decimal(273000) * 5846278608 + Decimal(198200) * 802371203
        self.assertEqual(out['marketCap'], expected)
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'], 'INDICATIVE')
        self.assertEqual(out['field_metadata']['marketCap']['verification_sources'], [])
        self.assertNotEqual(self.row['marketCap'], expected)
        fx = dict(validation_status='INDICATIVE', base_currency='USD', quote_currency='KRW',
            indexValue=Decimal('1340.18'), source_timestamp=self.common['timestamp'], source='Google Finance')
        converted = m.convert_usd(out, fx)
        self.assertEqual(converted['nativeMarketCap'], expected)
        self.assertEqual(converted['field_metadata']['marketCap']['shares_as_of'], '2026-06-30')
        self.assertAlmostEqual(float(converted['marketCap']), 1309573365084.2424, places=2)

    def test_report_identity_total_age_and_future_fail_closed(self):
        for body, now in [(REPORT.replace('Samsung Electronics', 'Other'), self.now),
                          (REPORT.replace('6,648,649,811', '6,648,649,810'), self.now),
                          (REPORT, self.now + timedelta(days=365)),
                          (REPORT, self.now - timedelta(days=365))]:
            with self.subTest(body=body, now=now), self.assertRaises(ValueError):
                s.parse_share_counts(body, now)

    def test_quote_identity_age_and_class_time_fail_closed(self):
        for changes in [dict(id='005930:KRX'), dict(currency='USD'), dict(exchange='NYSE'),
                        dict(price=Decimal('NaN')), dict(price=0), dict(session='AFTER_HOURS'),
                        dict(timestamp='2026-10-06T00:08:00+00:00'),
                        dict(timestamp='2026-10-07T01:08:00+00:00')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                s.apply_company_cap(self.row, self.common, dict(self.preferred, **changes),
                                    self.shares, self.now, 1800)
        with self.assertRaisesRegex(ValueError, 'TIME_MISMATCH'):
            s.apply_company_cap(self.row, self.common,
                dict(self.preferred, timestamp='2026-10-07T00:30:00+00:00'), self.shares,
                self.now + timedelta(minutes=30), 7200)

    def test_retained_display_price_does_not_replace_cap_inputs(self):
        out = s.apply_company_cap(dict(self.row, indexValue=274000), self.common,
            self.preferred, self.shares, self.now, 1800)
        self.assertEqual(out['marketCap'], self.calculate()['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['class_inputs'][0]['price'], 273000)

    def test_yahoo_class_fallback_identity_and_source(self):
        raw = dict(symbol='005930.KS', quoteType='EQUITY', exchange='KSC',
            currency='KRW', exchangeTimezoneName='Asia/Seoul', marketState='REGULAR',
            longName='Samsung Electronics Co., Ltd.', regularMarketPrice=273000,
            regularMarketTime=datetime.fromisoformat(self.common['timestamp']).timestamp())
        common = s.yahoo_class_quote(raw, '005930.KS')
        preferred = s.yahoo_class_quote(dict(raw, symbol='005935.KS', regularMarketPrice=198200), '005935.KS')
        out = s.apply_company_cap(self.row, common, preferred, self.shares, self.now, 1800)
        self.assertEqual(out['marketCap'], self.calculate()['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['source'], 'Samsung IR + Yahoo Finance')
        for changes in [dict(symbol='005935.KS'), dict(quoteType='INDEX'), dict(exchange='NYQ'),
                        dict(currency='USD'), dict(exchangeTimezoneName='America/New_York')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                s.yahoo_class_quote(dict(raw, **changes), '005930.KS')

    def test_failure_retains_only_dated_company_estimate_as_stale(self):
        previous = self.calculate()
        previous['field_metadata']['marketCapUSD'] = deepcopy(previous['field_metadata']['marketCap'])
        out = s.cap_unavailable(self.row, previous, 'PRICE_UNAVAILABLE')
        self.assertEqual(out['marketCap'], previous['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'], 'STALE')
        self.assertEqual(out['field_metadata']['marketCapUSD']['validation_status'], 'STALE')
        out = s.cap_unavailable(self.row, self.row, 'PRICE_UNAVAILABLE')
        self.assertIsNone(out['marketCap'])
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'], 'DATA_UNAVAILABLE')


if __name__ == '__main__':
    unittest.main()
