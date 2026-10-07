"""Samsung company cap estimate with an explicit, dated two-class basis."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SHARES_URL = 'https://www.samsung.com/global/ir/stock-information/listing-Info/'
BASIS = 'Common + preferred; estimate using latest published share counts'


def parse_share_counts(body, now):
    soup = BeautifulSoup(body, 'html.parser')
    text = soup.get_text(' ', strip=True)
    if 'Samsung Electronics' not in text or not all(x in text for x in ['005930', '005935']):
        raise ValueError('SAMSUNG_SHARE_IDENTITY_MISMATCH')
    candidates = []
    for table in soup.find_all('table'):
        title = table.get_text(' ', strip=True)
        if 'Treasury shares' not in title or 'Shares outstanding' not in title:
            continue
        for tr in table.find_all('tr'):
            cells = [cell.get_text(' ', strip=True) for cell in tr.find_all(['th', 'td'])]
            if len(cells) != 7 or not re.fullmatch(r'[A-Za-z]{3} \d{1,2}, \d{4}', cells[0]):
                continue
            date = datetime.strptime(cells[0], '%b %d, %Y').date()
            counts = [int(x.replace(',', '')) for x in cells[1:4]]
            if min(counts) <= 0 or counts[0] + counts[1] != counts[2]:
                raise ValueError('SAMSUNG_SHARE_TOTAL_MISMATCH')
            candidates.append((date, counts))
    if not candidates:
        raise ValueError('SAMSUNG_SHARE_SCHEMA_CHANGED')
    date, counts = max(candidates)
    age = (now.astimezone(ZoneInfo('Asia/Seoul')).date() - date).days
    if not 0 <= age <= 180:
        raise ValueError('SAMSUNG_SHARE_REPORT_NOT_CURRENT')
    return dict(common=counts[0], preferred=counts[1], total=counts[2],
                as_of=date.isoformat(), source=SHARES_URL, retrieved_at=now.isoformat())


def fetch_share_counts():
    response = requests.get(SHARES_URL, timeout=12)
    response.raise_for_status()
    return parse_share_counts(response.text, datetime.now(timezone.utc))


def yahoo_class_quote(quote, symbol):
    """Normalize an explicitly identified KRX class, retaining its source."""
    if (symbol not in {'005930.KS', '005935.KS'} or quote.get('symbol') != symbol
            or quote.get('quoteType') != 'EQUITY' or quote.get('exchange') != 'KSC'
            or quote.get('currency') != 'KRW' or quote.get('exchangeTimezoneName') != 'Asia/Seoul'):
        raise ValueError('SAMSUNG_CLASS_QUOTE_IDENTITY_MISMATCH')
    return dict(id=symbol[:6] + ':KRX', exchange='KRX', currency='KRW',
                name=quote.get('longName') or quote.get('shortName', ''),
                price=quote['regularMarketPrice'],
                timestamp=datetime.fromtimestamp(quote['regularMarketTime'], timezone.utc).isoformat(),
                session=quote.get('marketState'), source='Yahoo Finance', source_symbol=symbol)


def apply_company_cap(row, common, preferred, shares, now, max_quote_age):
    """Never claim quarterly counts are live counts or add a provider total twice."""
    observations = []
    for quote, code, count in [(common, '005930', shares['common']),
                               (preferred, '005935', shares['preferred'])]:
        if (quote.get('id') != code + ':KRX' or quote.get('exchange') != 'KRX'
                or quote.get('currency') != 'KRW' or quote.get('session') != 'REGULAR'
                or 'samsung electronics' not in quote.get('name', '').lower()):
            raise ValueError('SAMSUNG_CLASS_QUOTE_IDENTITY_MISMATCH')
        price = Decimal(str(quote['price']))
        ts = datetime.fromisoformat(quote['timestamp'].replace('Z', '+00:00'))
        if ts.tzinfo is None or not price.is_finite() or price <= 0 or count <= 0:
            raise ValueError('SAMSUNG_CLASS_INPUT_INVALID')
        age = (now - ts).total_seconds()
        if not -120 <= age <= max_quote_age:
            raise ValueError('SAMSUNG_CLASS_QUOTE_NOT_CURRENT')
        observations.append((price, ts))
    (cp, ct), (pp, pt) = observations
    if (ct.astimezone(ZoneInfo('Asia/Seoul')).date() != pt.astimezone(ZoneInfo('Asia/Seoul')).date()
            or abs((ct - pt).total_seconds()) > 1200):
        raise ValueError('SAMSUNG_CLASS_QUOTE_TIME_MISMATCH')
    # The cap has its own two-class input timestamps; a retained display price
    # must neither replace these inputs nor prevent a current cap observation.
    report_age = (now.astimezone(ZoneInfo('Asia/Seoul')).date()
                  - datetime.fromisoformat(shares['as_of']).date()).days
    if (not 0 <= report_age <= 180 or shares['source'] != SHARES_URL
            or shares['common'] + shares['preferred'] != shares['total']):
        raise ValueError('SAMSUNG_SHARE_REPORT_NOT_CURRENT')
    cap = cp * shares['common'] + pp * shares['preferred']
    out = deepcopy(row)
    out.update(marketCap=cap, marketCapUSD=None, currency='KRW')
    meta = dict(validation_status='INDICATIVE', quality='INDICATIVE',
                source='Samsung IR + ' + ' / '.join(dict.fromkeys(q.get('source', 'Google Finance') for q in [common, preferred])), source_timestamp=min(ct, pt).isoformat(),
                retrieved_at=now.isoformat(), decimal=format(cap, 'f'), currency='KRW',
                verification_sources=[], valuation_basis=BASIS, share_class_reference=SHARES_URL,
                calculation='common price * reported common shares + preferred price * reported preferred shares',
                shares_as_of=shares['as_of'], share_counts=deepcopy(shares),
                class_inputs=[dict(symbol=q['id'], price=p, shares=n,
                                   source_timestamp=q['timestamp'], source=q.get('source', 'Google Finance'))
                              for q, p, n in [(common, cp, shares['common']),
                                               (preferred, pp, shares['preferred'])]],
                timestamp_scope='class quote times; share counts are a dated report, not a live feed')
    # Keep source disagreements as evidence, without using their ambiguous totals.
    if row.get('field_metadata', {}).get('marketCap', {}).get('source_check'):
        meta['source_check'] = deepcopy(row['field_metadata']['marketCap']['source_check'])
    out.setdefault('field_metadata', {})['marketCap'] = meta
    out['field_metadata']['marketCapUSD'] = {'validation_status': 'DATA_UNAVAILABLE', 'reason': 'FX_PENDING'}
    return out


def cap_unavailable(row, previous, reason):
    out = deepcopy(row)
    old = previous.get('field_metadata', {}).get('marketCap', {})
    if old.get('valuation_basis') == BASIS and previous.get('marketCap') is not None:
        for key in ['marketCap', 'marketCapUSD', 'currency', 'nativeMarketCap',
                    'native_market_cap_metadata', 'fxRate', 'fxTimestamp', 'fx_metadata', 'fxValidation']:
            if key in previous:
                out[key] = deepcopy(previous[key])
            else:
                out.pop(key, None)
        for field in ['marketCap', 'marketCapUSD']:
            out['field_metadata'][field] = dict(deepcopy(previous['field_metadata'][field]),
                                                validation_status='STALE', reason=reason)
        out['fxValidation'] = 'STALE'
        if out.get('native_market_cap_metadata'):
            out['native_market_cap_metadata'].update(validation_status='STALE', reason=reason)
    else:
        out.update(marketCap=None, marketCapUSD=None)
        for key in ['nativeMarketCap', 'native_market_cap_metadata', 'fxRate', 'fxTimestamp', 'fx_metadata']:
            out.pop(key, None)
        for field in ['marketCap', 'marketCapUSD']:
            out['field_metadata'][field] = dict(validation_status='DATA_UNAVAILABLE', reason=reason,
                                                valuation_basis=BASIS)
    return out
