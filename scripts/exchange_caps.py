"""Mapped BSE company caps; quote prices/changes keep their original listing."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
import requests

LISTINGS = json.loads(Path(__file__).with_name('bse_listings.json').read_text(encoding='utf8'))


def normalized(name):
    words = re.findall(r'[a-z0-9]+', name.lower())
    return [w for w in words if w not in {'limited', 'ltd'}]


def parse_bse(symbol, header, trade):
    listing = LISTINGS[symbol]
    company = header['Cmpname']
    if (str(company['EquityScrips']) != listing['code']
            or normalized(company['FullN']) != normalized(listing['issuer'])):
        raise ValueError('BSE_COMPANY_IDENTITY_MISMATCH')
    cap = Decimal(str(trade['MktCapFull']).replace(',', '')) * Decimal('10000000')
    price = Decimal(str(header['CurrRate']['LTP']).replace(',', ''))
    if not cap.is_finite() or not price.is_finite() or min(cap, price) <= 0:
        raise ValueError('BSE_INVALID_CAP_OR_PRICE')
    # Ason is an aggregate quote-header time, not a cap-specific trading time.
    ts = datetime.strptime(header['Header']['Ason'], '%d %b %y | %H:%M').replace(tzinfo=ZoneInfo('Asia/Kolkata'))
    return dict(symbol=symbol, code=listing['code'], company_name=company['FullN'],
        marketCap=cap, price=price, timestamp=ts.isoformat(), currency='INR', source='BSE',
        reference='https://www.bseindia.com/stock-share-price/company/' + symbol.split('.')[0].lower() + '/' + listing['code'] + '/')


def fetch_bse(symbol):
    code = LISTINGS[symbol]['code']
    headers = {'User-Agent':'Mozilla/5.0', 'Referer':'https://www.bseindia.com/'}
    root = 'https://api.bseindia.com/BseIndiaAPI/api/'
    def read(endpoint):
        r = requests.get(root+endpoint+'/w', params={'scripcode':code}, headers=headers, timeout=(2,4))
        r.raise_for_status()
        return r.json()
    q = parse_bse(symbol, read('GetScripHeaderData'), read('StockTrading'))
    q['retrieved_at'] = datetime.now(ZoneInfo('UTC')).isoformat()
    return q


def apply_bse(row, symbol, quote, now):
    if quote.get('symbol') != symbol or quote.get('code') != LISTINGS[symbol]['code'] or quote.get('currency') != 'INR':
        raise ValueError('BSE_COMPANY_IDENTITY_MISMATCH')
    ts = datetime.fromisoformat(quote['timestamp'])
    if ts.tzinfo is None:
        raise ValueError('BSE_TIMEZONE_MISSING')
    limit = 1800 if row.get('market_status') == 'OPEN' else 7200 if row.get('market_status') == 'BREAK' else 604800
    if not -120 <= (now-ts).total_seconds() <= limit:
        raise ValueError('BSE_CAP_NOT_CURRENT')
    row_ts = row.get('source_timestamp')
    if row_ts and ts.astimezone(ZoneInfo('Asia/Kolkata')).date() < datetime.fromisoformat(row_ts.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Kolkata')).date():
        raise ValueError('BSE_CAP_OLDER_SESSION')
    old = row.get('field_metadata', {}).get('marketCap', {})
    if old.get('source') == 'BSE' and old.get('source_timestamp') and ts < datetime.fromisoformat(old['source_timestamp']):
        raise ValueError('OLDER_BSE_CAP_OBSERVATION')
    cap = Decimal(str(quote['marketCap']))
    if not cap.is_finite() or cap <= 0:
        raise ValueError('BSE_INVALID_CAP_OR_PRICE')
    out = deepcopy(row)
    out.update(marketCap=cap, currency='INR', marketCapUSD=None)
    out.setdefault('field_metadata', {})['marketCap'] = dict(validation_status='INDICATIVE',
        quality='INDICATIVE', source='BSE', source_timestamp=ts.isoformat(), retrieved_at=quote['retrieved_at'],
        decimal=format(cap,'f'), currency='INR', verification_sources=[], exchange_code=quote['code'],
        reference=quote['reference'], max_quote_age_seconds=limit,
        valuation_basis='BSE full company market cap; INR crore converted to INR; not a cap derived from NSE price',
        timestamp_scope='BSE quote-header as-of time; no separate market-cap timestamp',
        exchange_price=quote['price'], source_check=deepcopy(old.get('source_check', {})),
        reconciliation='Official BSE full cap selected; NSE price/change remain independent')
    out['field_metadata']['marketCapUSD'] = {'validation_status':'DATA_UNAVAILABLE', 'reason':'INR_LISTING'}
    return out


def retain_primary_cap(row, previous, sources, now, reason, force_stale=False):
    old = previous.get('field_metadata', {}).get('marketCap', {})
    if old.get('source') not in sources or previous.get('marketCap') is None:
        return row
    out = deepcopy(row)
    ts = datetime.fromisoformat(old['source_timestamp'].replace('Z','+00:00'))
    limit = 1800 if row.get('market_status') == 'OPEN' else 604800
    stale = force_stale or (now-ts).total_seconds() > limit
    out.update(marketCap=previous['marketCap'], currency=previous['currency'])
    for field in ['marketCap', 'marketCapUSD']:
        if field in previous.get('field_metadata', {}):
            out[field] = previous.get(field)
            out.setdefault('field_metadata', {})[field] = dict(deepcopy(previous['field_metadata'][field]),
                validation_status=('STALE' if stale else old['validation_status']) if previous.get(field) is not None else previous['field_metadata'][field]['validation_status'], retention_reason=reason,
                max_quote_age_seconds=limit)
    return out
