import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m


class GoogleEquityReferenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026,10,14,7,45,tzinfo=timezone.utc)
        self.identity = dict(symbol='ADANIENT.NS', quoteType='EQUITY', exchange='NSI',
            currency='INR', exchangeTimezoneName='Asia/Kolkata', marketState='REGULAR',
            _retrieved_at=self.now.isoformat())
        self.row = dict(ticker='ADANIENT.NS', name='Adani Enterprises',currency='INR',quote_currency='INR',
            marketCap=Decimal('3130000000000'),indexValue=Decimal('2710'),changePercent=Decimal('2'),field_metadata={})
        self.quote = dict(id='ADANIENT:NSE',name='Adani Enterprises Limited',exchange='NSE',currency='INR',
            price=Decimal('2713.90'),previousClose=Decimal('2695'),marketCap=Decimal('3920000000000'),
            reportedChangePercent=Decimal('0.7013001'),cap_resolution=Decimal('10000000000'),
            timestamp=(self.now-timedelta(seconds=10)).isoformat(),retrieved_at=self.now.isoformat())

    def apply(self, row=None, previous=None, quote=None, identity=None, symbol='ADANIENT.NS'):
        return m.google_equity_reference(row or self.row, previous or self.row, symbol,
            self.quote if quote is None else quote, identity or self.identity, self.now)

    def test_reference_fields_come_from_same_google_quote(self):
        result=self.apply()
        self.assertEqual(result['marketCap'],self.quote['marketCap'])
        self.assertEqual(result['indexValue'],self.quote['price'])
        self.assertEqual(result['changePercent'],self.quote['reportedChangePercent'])
        for field in ('marketCap','changePercent'):
            self.assertEqual(result['field_metadata'][field]['source'],'Google Finance')
            self.assertEqual(result['field_metadata'][field]['source_timestamp'],self.quote['timestamp'])
        self.assertEqual(result['field_metadata']['marketCap']['validation_status'],'INDICATIVE')

    def test_older_google_fields_retained_stale_without_timestamp_upgrade(self):
        previous=self.apply()
        result=self.apply(previous=previous,quote=dict(self.quote,timestamp=(self.now-timedelta(minutes=5)).isoformat(),marketCap=1,price=1))
        self.assertEqual(result['marketCap'],previous['marketCap'])
        self.assertEqual(result['source_timestamp'],previous['source_timestamp'])
        self.assertEqual(result['field_metadata']['marketCap']['validation_status'],'STALE')

    def test_missing_google_never_substitutes_yahoo_or_nasdaq(self):
        result=self.apply(quote={})
        self.assertIsNone(result['marketCap'])
        self.assertIsNone(result['changePercent'])
        previous=self.apply()
        result=self.apply(previous=previous,quote={})
        self.assertEqual(result['marketCap'],previous['marketCap'])
        self.assertEqual(result['changePercent'],previous['changePercent'])
        self.assertEqual(result['field_metadata']['changePercent']['validation_status'],'STALE')

    def test_invalid_identity_currency_and_retrieval_are_not_published(self):
        for change in (dict(id='HDFCBANK:NSE'),dict(name='HDFC Bank'),dict(currency='USD'),
                       dict(retrieved_at=(self.now-timedelta(minutes=6)).isoformat())):
            with self.subTest(change=change):
                out=self.apply(quote=dict(self.quote,**change))
                self.assertIsNone(out['marketCap'])
                self.assertIsNone(out['changePercent'])

    def test_native_cap_retention_not_divided_twice(self):
        ident=dict(self.identity,symbol='0700.HK',exchange='HKG',currency='HKD',exchangeTimezoneName='Asia/Hong_Kong')
        row=dict(self.row,ticker='0700.HK',name='Tencent',currency='HKD',quote_currency='HKD')
        quote=dict(self.quote,id='0700:HKG',exchange='HKG',name='Tencent Holdings',currency='HKD',marketCap=Decimal('3850000000000'))
        previous=self.apply(row=row,previous=row,quote=quote,identity=ident,symbol='0700.HK')
        fx=dict(validation_status='INDICATIVE',base_currency='USD',quote_currency='HKD',indexValue=Decimal('7.8'),
            source_timestamp=self.quote['timestamp'],source='Google Finance')
        converted=m.convert_usd(deepcopy(previous),fx)
        retained=self.apply(row=converted,previous=converted,quote={},identity=ident,symbol='0700.HK')
        self.assertEqual(retained['currency'],'HKD')
        self.assertEqual(retained['marketCap'],quote['marketCap'])
        self.assertEqual(m.convert_usd(retained,fx)['marketCap'],converted['marketCap'])

    def test_beta_parser_uses_regular_header_not_extended_hours(self):
        body=(Path(__file__).parent/'fixtures/google_beta/ADANIENT_NSE.html').read_text()
        result=m.parse_google(body,'ADANIENT:NSE')
        self.assertEqual(result['reportedChangePercent'],Decimal('0.04452222'))

    def test_header_change_survives_rolled_previous_close(self):
        out=self.apply(quote=dict(self.quote,previousClose=self.quote['price'],reportedChangePercent=Decimal('3.25')))
        self.assertEqual(out['changePercent'],Decimal('3.25'))

    def test_fresh_first_page_does_not_hide_newer_beta_page(self):
        from unittest.mock import patch, Mock
        newer=dict(self.quote,timestamp=self.now.isoformat(),marketCap=Decimal('3930000000000'))
        with patch.object(m.requests,'get',return_value=Mock(text='quote')) as get, \
             patch.object(m,'parse_google',side_effect=[self.quote,newer]):
            selected=m.fetch_google('ADANIENT:NSE')
        self.assertEqual(get.call_count,2)
        self.assertEqual(selected['marketCap'],newer['marketCap'])

    def test_recent_sources_can_confirm_an_old_current_session_trade(self):
        quote=dict(self.quote,timestamp=(self.now-timedelta(hours=1)).isoformat())
        identity=dict(self.identity,longName='Adani Enterprises Limited',
            regularMarketTime=int((self.now-timedelta(hours=1)).timestamp()),
            regularMarketPrice=quote['price'],regularMarketPreviousClose=quote['previousClose'],regularMarketVolume=133)
        out=self.apply(quote=quote,identity=identity)
        self.assertEqual(out['validation_status'],'STALE')
        self.assertEqual(out['field_metadata']['marketCap']['validation_status'],'STALE')
        self.assertEqual(out['source_timestamp'],quote['timestamp'])
        self.assertEqual(out['quote_activity']['kind'],'MATCHING_LAST_REPORTED_TRADE')
        self.assertEqual(out['quote_activity']['last_trade_timestamp'],quote['timestamp'])
        self.assertEqual(out['quote_activity']['reported_volume'],133)

    def test_disagreement_old_checks_or_prior_session_do_not_confirm_activity(self):
        quote=dict(self.quote,timestamp=(self.now-timedelta(hours=1)).isoformat())
        identity=dict(self.identity,longName='Adani Enterprises Limited',
            regularMarketTime=int((self.now-timedelta(hours=1)).timestamp()),
            regularMarketPrice=quote['price'],regularMarketPreviousClose=quote['previousClose'])
        for change in (dict(regularMarketPrice=Decimal('1')),dict(regularMarketPreviousClose=Decimal('1')),
                       dict(regularMarketTime=int(self.now.timestamp())),dict(longName='Unrelated company'),
                       dict(_retrieved_at=(self.now-timedelta(minutes=6)).isoformat())):
            with self.subTest(change=change):
                self.assertNotIn('quote_activity',self.apply(quote=quote,identity=dict(identity,**change)))
        old=dict(quote,timestamp=(self.now-timedelta(days=1)).isoformat())
        self.assertNotIn('quote_activity',self.apply(quote=old,identity=dict(identity,regularMarketTime=int((self.now-timedelta(days=1)).timestamp()))))

