"""Latest official Hub repositories with explicitly declared open licences."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import re
import requests

PUBLISHERS = ('Qwen', 'deepseek-ai', 'mistralai', 'allenai', 'HuggingFaceTB',
              'HuggingFaceH4', 'microsoft', 'moonshotai', 'ibm-granite', 'zai-org', 'MiniMaxAI',
              'openai', 'nvidia', 'tiiuae')
LICENCES = {'apache-2.0', 'mit', 'bsd-2-clause', 'bsd-3-clause', 'isc', 'cc0-1.0'}
API = 'https://huggingface.co/api/models'


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Missing timezone')
    return result.astimezone(timezone.utc)


def model_item(model, author, now):
    ident = model.get('id', '')
    if not isinstance(ident, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', ident):
        return None
    if ident.split('/')[0] != author or model.get('private') is not False or model.get('gated') is not False:
        return None
    if model.get('pipeline_tag') != 'text-generation':
        return None
    if any(tag in {'peft', 'adapter', 'gguf', 'ggml'} for tag in (model.get('tags') or [])):
        return None
    card = model.get('cardData') or {}
    licence = card.get('license') if isinstance(card, dict) else None
    if not isinstance(licence, str) or licence.lower() not in LICENCES:
        return None
    try:
        created = timestamp(model['createdAt'])
        if created > now + timedelta(minutes=2):
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return dict(id=ident, name=ident.split('/')[1], publisher=author,
                licence=licence.lower(), published=created.isoformat(),
                url='https://huggingface.co/' + ident, source_status='CURRENT')


def fetch_publisher(author, now):
    response = requests.get(API, params={
        'author': author, 'pipeline_tag': 'text-generation', 'sort': 'createdAt',
        'direction': -1, 'limit': 20,
        'expand': ['author', 'createdAt', 'cardData', 'pipeline_tag', 'private', 'gated', 'tags'],
    }, timeout=(4, 10))
    response.raise_for_status()
    models = response.json()
    if not isinstance(models, list) or any(not isinstance(m, dict) for m in models):
        raise ValueError('Invalid model list')
    return [item for model in models if (item := model_item(model, author, now))]


def refresh_open_llms(existing=None, now=None):
    now = now or datetime.now(timezone.utc)
    existing = existing or {}
    def check(author):
        try:
            return author, fetch_publisher(author, now), None
        except (requests.RequestException, ValueError, TypeError) as exc:
            return author, [], type(exc).__name__
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for author, fetched, error in pool.map(check, PUBLISHERS):
            if error:
                errors.append(dict(publisher=author, reason=error))
                # Keep the saved publication time; never pretend a failed fetch is fresh.
                fetched = [dict(item, source_status='STALE') for item in existing.get('items', [])
                           if item.get('publisher') == author]
            items.extend(fetched)
    unique = {item['id']: item for item in items}
    latest = sorted(unique.values(), key=lambda item: timestamp(item['published']), reverse=True)[:20]
    status = 'STALE' if len(errors) == len(PUBLISHERS) else 'PARTIAL' if errors else 'CURRENT'
    return dict(items=latest, checked_at=now.isoformat(), status=status, errors=errors,
                publishers=list(PUBLISHERS), source='Hugging Face official publisher model cards',
                date_basis='Hub repository creation date, not an independently verified release date',
                licence_basis='Publisher-declared open licence for weights; training data/code availability not certified')
