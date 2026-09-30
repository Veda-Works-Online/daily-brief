"""Bounded, explicitly mapped public feeds. No keys or paid subscriptions."""
from datetime import datetime, timezone
from decimal import Decimal
import requests
import simplejson as json
import re


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('INVALID_NUMBER')
    result = Decimal(str(value).replace(',', '').replace('$', ''))
    if not result.is_finite():
        raise ValueError('INVALID_NUMBER')
    return result


def get(url, params=None):
    response = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=(4, 10))
    response.raise_for_status()
    return json.loads(response.text, use_decimal=True)


def parse_shenzhen(payload):
    d = payload.get('data') or {}
    if payload.get('rc') != 0 or d.get('f57') != '399001' or d.get('f58') != '深证成指' or d.get('f59') != 2:
        raise ValueError('EASTMONEY_IDENTITY_OR_SCALE_MISMATCH')
    price, previous = number(d['f43']) / 100, number(d['f60']) / 100
    if price <= 0 or previous <= 0:
        raise ValueError('NONPOSITIVE_PRICE')
    change = number(d['f170']) / 100
    if abs((price / previous - 1) * 100 - change) > Decimal('0.02'):
        raise ValueError('EASTMONEY_CHANGE_MISMATCH')
    if not isinstance(d.get('f86'), int) or isinstance(d['f86'], bool):
        raise ValueError('EASTMONEY_TIMESTAMP_MISSING')
    return dict(price=price, previousClose=previous, changePercent=change,
                timestamp=datetime.fromtimestamp(d['f86'], timezone.utc).isoformat())


def fetch_shenzhen():
    quote = parse_shenzhen(get('https://push2.eastmoney.com/api/qt/stock/get',
        {'secid':'0.399001', 'fields':'f57,f58,f43,f60,f170,f86,f59'}))
    quote['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    return quote


def parse_nasdaq_cap(symbol, info_payload, summary_payload):
    info, summary = info_payload.get('data') or {}, summary_payload.get('data') or {}
    exchange = {'NASDAQ-GS':'NASDAQ', 'NASDAQ-GM':'NASDAQ', 'NASDAQ-CM':'NASDAQ'}.get(info.get('exchange'), info.get('exchange'))
    if (info.get('symbol') != symbol or summary.get('symbol') != symbol
            or exchange not in {'NYSE', 'NASDAQ', 'NYSEAMERICAN'} or info.get('assetClass') != 'STOCKS'
            or summary.get('assetClass') != 'STOCKS'
            or not info.get('companyName')):
        raise ValueError('NASDAQ_IDENTITY_MISMATCH')
    if symbol == 'TSM' and ('Taiwan Semiconductor' not in info['companyName']
            or 'Depositary' not in info.get('stockType', '')):
        raise ValueError('NASDAQ_TSM_IDENTITY_MISMATCH')
    stats, primary = summary['summaryData'], info['primaryData']
    if stats['Exchange']['value'] != info['exchange']:
        raise ValueError('NASDAQ_EXCHANGE_MISMATCH')
    # Date-only closing observations are useful for cap corroboration. Never
    # turn a retrieval timestamp into a supposedly real-time quote timestamp.
    date = re.match(r'^([A-Z][a-z]{2} \d{1,2}, \d{4})(?:\s|$)', primary['lastTradeTimestamp'])
    if not date or not primary['lastSalePrice'].startswith('$'):
        raise ValueError('NASDAQ_DATE_OR_CURRENCY_MISSING')
    day = datetime.strptime(date[1], '%b %d, %Y').date().isoformat()
    cap, price = number(stats['MarketCap']['value']), number(primary['lastSalePrice'])
    if cap <= 0 or price <= 0:
        raise ValueError('NONPOSITIVE_PRICE')
    return dict(marketCap=cap, price=price, source_date=day, symbol=symbol,
                exchange=exchange, company_name=info['companyName'],
                stock_type=info.get('stockType'), source='Nasdaq')


def parse_tsm(info_payload, summary_payload):
    return parse_nasdaq_cap('TSM', info_payload, summary_payload)


def fetch_nasdaq_cap(symbol):
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', symbol):
        raise ValueError('INVALID_NASDAQ_SYMBOL')
    root = 'https://api.nasdaq.com/api/quote/' + symbol + '/'
    quote = parse_nasdaq_cap(symbol, get(root + 'info', {'assetclass':'stocks'}),
                            get(root + 'summary', {'assetclass':'stocks'}))
    quote['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    return quote


def fetch_tsm():
    return fetch_nasdaq_cap('TSM')
