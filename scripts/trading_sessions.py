"""Field-level session evidence, separate from provider and retrieval timestamps."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

# Regular-session windows only. These are plausibility guards, not calendars:
# dates below are source-reported sessions, never inferred holiday schedules.
WINDOWS = {
    'Asia/Kolkata': (9 * 60 + 15, 15 * 60 + 30),
    'America/New_York': (9 * 60 + 30, 16 * 60 + 15),
    'Asia/Seoul': (9 * 60, 15 * 60 + 30),
    'Asia/Hong_Kong': (9 * 60 + 30, 16 * 60 + 15),
    'Asia/Shanghai': (9 * 60 + 30, 15 * 60),
}


def instant(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Naive source timestamp')
    return result


def session_date(value, zone):
    """Reject off-hours/weekend observation times as regular-session evidence."""
    local = instant(value).astimezone(ZoneInfo(zone))
    start, end = WINDOWS[zone]
    if local.weekday() >= 5 or not start <= local.hour * 60 + local.minute <= end:
        raise ValueError('Timestamp does not establish a regular session')
    return local.date().isoformat()


def annotate_sessions(row, google=None, now=None):
    """Keep raw provider timestamps; attach session evidence to each displayed field.

    A closed-market Yahoo observation outside regular hours cannot establish a
    session. A validated Google observation may identify it only when price AND
    previous close match exactly. Never roll a date back by guessing a weekday.
    """
    zone = row.get('market_timezone')
    metadata = row.get('field_metadata', {})
    for field in ('indexValue', 'changePercent', 'marketCap'):
        meta = metadata.get(field)
        if not meta:
            continue
        old = meta.pop('trading_session', None)
        ts = meta.get('market_cap_source_timestamp') if field == 'marketCap' else None
        ts = ts or meta.get('source_timestamp')
        session = {'date': None, 'timezone': zone, 'basis': 'Session unconfirmed',
                   'observation_timestamp': ts}
        try:
            session.update(date=session_date(ts, zone), timestamp=ts,
                source=meta.get('source'), basis='Source quote session')
        except (ValueError, TypeError, KeyError):
            # Preserve earlier explicit evidence only for the same observation.
            if old and old.get('observation_timestamp') == ts:
                session = old
        # Google must already have passed the caller's identity/freshness checks.
        if (field in {'indexValue', 'changePercent'} and not session['date']
                and row.get('market_status') in {'CLOSED', 'PRE_MARKET', 'AFTER_HOURS', 'WEEKEND', 'HOLIDAY'}
                and google and now):
            try:
                gt = instant(google['timestamp'])
                age = (now - gt).total_seconds()
                limit = row.get('quote_policy', {}).get('max_quote_age_seconds', 604800)
                price = Decimal(str(row['indexValue']))
                prev = Decimal(str(row['previousClose']))
                if (0 <= age <= limit and gt <= instant(ts) and price > 0 and prev > 0
                        and price == Decimal(str(google['price']))
                        and prev == Decimal(str(google['previousClose']))):
                    session.update(date=session_date(google['timestamp'], zone),
                        timestamp=google['timestamp'], source='Google Finance',
                        basis='Matching Google price and previous close')
            except (ValueError, TypeError, KeyError, InvalidOperation):
                pass
        if meta.get('validation_status') == 'DATA_UNAVAILABLE' or row.get(field) is None:
            session.update(date=None, basis='Data unavailable')
        meta['trading_session'] = session
    return row
