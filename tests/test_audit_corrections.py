"""Regressions observed in production on 30 September 2026."""
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import market_data as m
import refresh_loop as worker


class AuditCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 30, 5, tzinfo=timezone.utc)
        self.row = dict(ticker='INR=X', name='USD/INR', verification_version=1,
            indexValue=Decimal('95.9475'), source='Yahoo Finance',
            source_timestamp=self.now.isoformat(), retrieved_at=self.now.isoformat(),
            validation_status='INDICATIVE', quote_quality='INDICATIVE',
            field_metadata={'indexValue': dict(validation_status='INDICATIVE', decimal='95.9475')})

    def test_older_response_preserves_value_time_and_marks_stale(self):
        older = dict(self.row, indexValue=Decimal('95.9242'), source='Google Finance',
            source_timestamp=(self.now-timedelta(minutes=6)).isoformat())
        original = deepcopy(self.row)
        out = m.prevent_quote_regression(self.row, older)
        self.assertEqual(out['indexValue'], original['indexValue'])
        self.assertEqual(out['source_timestamp'], original['source_timestamp'])
        self.assertEqual(out['validation_status'], 'STALE')
        self.assertEqual(out['error']['reason'], 'OLDER_SOURCE_OBSERVATION')
        self.assertEqual(out['rejected_observation']['source_timestamp'], older['source_timestamp'])
        self.assertEqual(self.row, original)

    def test_equal_newer_and_migrated_observations_are_allowed(self):
        for updates in [{}, {'source_timestamp':(self.now+timedelta(seconds=5)).isoformat()},
                        {'ticker':'GOLD_24K_HYDERABAD', 'source_timestamp':(self.now-timedelta(days=1)).isoformat()}]:
            candidate = dict(self.row, **updates)
            self.assertIs(m.prevent_quote_regression(self.row, candidate), candidate)

    def test_guard_is_applied_after_provider_selection(self):
        older = dict(self.row, source_timestamp=(self.now-timedelta(minutes=6)).isoformat(), indexValue=Decimal('94'))
        with patch.object(m, 'yahoo_quotes', return_value={}), \
             patch.object(m, 'fetch_google', return_value={}), \
             patch.object(m, 'freshest_fx', return_value=older):
            out, attempts = m.refresh_markets({'regions':{'currency':[self.row]}})
        self.assertEqual(out['regions']['currency'][0]['indexValue'], self.row['indexValue'])
        self.assertEqual(attempts[-1]['reason'], 'OLDER_SOURCE_OBSERVATION')

    def test_accepted_changes_use_google_price_and_previous_close(self):
        row = dict(ticker='DIVISLAB.NS', name="Divi's Labs")
        yahoo = dict(symbol='DIVISLAB.NS', longName="Divi's Laboratories", exchange='NSI',
            currency='INR', exchangeTimezoneName='Asia/Kolkata', quoteType='EQUITY', marketState='REGULAR',
            regularMarketTime=int(self.now.timestamp()), _retrieved_at=self.now.isoformat(),
            regularMarketPrice=Decimal('9366'), regularMarketPreviousClose=Decimal('9431'),
            regularMarketChange=Decimal('-65'), regularMarketChangePercent=Decimal('-0.6900212'))
        google = dict(id='DIVISLAB:NSE', name="Divi's Laboratories", exchange='NSE', currency='INR',
            timestamp=(self.now-timedelta(minutes=5)).isoformat(), retrieved_at=self.now.isoformat(),
            price=Decimal('9355'), previousClose=Decimal('9431'))
        out = m.accepted(row, row['ticker'], yahoo, google, self.now)
        self.assertEqual(out['absoluteChange'], Decimal('-76'))
        self.assertEqual(out['changePercent'], Decimal('-0.805853'))
        self.assertEqual(out['field_metadata']['changePercent']['source_timestamp'], out['source_timestamp'])
        self.assertEqual(out['field_metadata']['changePercent']['input_price'], out['indexValue'])
        self.assertEqual(out['field_metadata']['changePercent']['input_previous_close'], out['previousClose'])

    def test_failure_is_recorded_and_returns_nonzero(self):
        root = Path(__file__).resolve().parents[1] / 'work' / 'failure-test'
        with patch.object(worker, 'ROOT', root), patch.object(worker, 'run'), \
             patch.object(worker, 'cycle', side_effect=subprocess.TimeoutExpired('fetch',240)), \
             patch.dict(worker.os.environ, {'DEFAULT_BRANCH':'main'}), \
             patch.object(sys, 'argv', ['refresh_loop.py','--duration-seconds','1']):
            self.assertEqual(worker.main(), 1)
        evidence = json.loads((root/'work'/'refresh-failure.json').read_text())
        self.assertEqual(evidence['status'], 'FAILED')
        self.assertEqual(evidence['reason'], 'TimeoutExpired')
        workflow = (Path(__file__).resolve().parents[1]/'.github/workflows/update.yml').read_text()
        self.assertIn("!cancelled() && (steps.worker.outcome == 'success' || steps.worker.outcome == 'failure')", workflow)


if __name__ == '__main__':
    unittest.main()
