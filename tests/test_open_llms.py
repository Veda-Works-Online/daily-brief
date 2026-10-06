import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import open_llms as models


class OpenLlmTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.model = dict(id='Qwen/Example', private=False, gated=False,
            pipeline_tag='text-generation', cardData={'license':'apache-2.0'},
            createdAt='2026-10-05T12:00:00Z', tags=[])

    def test_rejects_restricted_unknown_and_non_llm_repositories(self):
        self.assertIsNotNone(models.model_item(self.model, 'Qwen', self.now))
        for changes in [dict(cardData={'license':'other'}), dict(cardData={'license':'gemma'}),
                        dict(cardData={}), dict(gated='auto'), dict(private=True),
                        dict(id='Fake/Example'), dict(id='Qwen/Bad?query'),
                        dict(pipeline_tag='feature-extraction'), dict(tags=['peft']),
                        dict(createdAt='2027-01-01T00:00:00Z')]:
            with self.subTest(changes=changes):
                self.assertIsNone(models.model_item(dict(self.model, **changes), 'Qwen', self.now))

    def test_uses_publication_date_not_a_recent_edit(self):
        item = models.model_item(dict(self.model, lastModified='2026-10-06T12:00:00Z'), 'Qwen', self.now)
        self.assertEqual(item['published'], '2026-10-05T12:00:00+00:00')

    def test_provider_failure_retains_saved_models_and_original_dates(self):
        saved = models.model_item(self.model, 'Qwen', self.now)
        with patch.object(models, 'PUBLISHERS', ('Qwen',)), \
             patch.object(models, 'fetch_publisher', side_effect=requests.Timeout):
            output = models.refresh_open_llms({'items':[saved]}, self.now)
        self.assertEqual(output['status'], 'STALE')
        self.assertEqual(output['items'][0]['source_status'], 'STALE')
        self.assertEqual(output['items'][0]['published'], saved['published'])

    def test_latest_models_are_sorted_deduplicated_and_bounded(self):
        items = [models.model_item(dict(self.model, id=f'Qwen/Model-{i}',
                 createdAt=f'2026-09-{i+1:02}T12:00:00Z'), 'Qwen', self.now) for i in range(25)]
        with patch.object(models, 'PUBLISHERS', ('Qwen',)), \
             patch.object(models, 'fetch_publisher', return_value=items + items):
            output = models.refresh_open_llms(now=self.now)
        self.assertEqual(output['status'], 'CURRENT')
        self.assertEqual(len(output['items']), 20)
        self.assertEqual(output['items'][0]['id'], 'Qwen/Model-24')


if __name__ == '__main__':
    unittest.main()
