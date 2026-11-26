"""Daily Datia rate history (data/rate_history.json in this repo) and trend stats.

Each run merges Aaj Tak's 'last 10 days' table plus today's card, so gaps heal
themselves. Rows from the backup city source are stored with their source tag
but are excluded from trend maths (different city = different price level).
"""
from datetime import timedelta
from decimal import Decimal

HISTORY_PATH = 'data/rate_history.json'
PRIMARY = 'ibja'  # was 'aajtak-datia' until 2026-11-26 (lagged one day); old rows kept, not used for trends
KEEP_DAYS = 400
FIELDS = ('gold24', 'gold22', 'gold18', 'silverkg')
MARKET_FIELDS = {'nifty': 'nifty', 'goldusd': 'gold_usd', 'usdinr': 'usdinr'}


def _row(values, source):
    row = {k: str(values[k]) for k in FIELDS if values.get(k) is not None}
    row['source'] = source
    return row


def merge(history, quote):
    """Return a new history dict with the quote's card and table rows added."""
    merged = {day: dict(row) for day, row in (history or {}).items()}
    if not quote:
        return merged
    source = quote.get('source', 'aajtak-datia')

    def put(day, values):
        key = day.isoformat()
        existing = merged.get(key)
        if existing and existing.get('source') == PRIMARY and source != PRIMARY:
            return  # never overwrite Datia data with the backup city
        row = dict(existing or {})
        if row.get('source') and row.get('source') != source:
            # Different source for the same day: drop its prices, keep market closes.
            row = {k: v for k, v in row.items() if k in MARKET_FIELDS.values()}
        row.update(_row(values, source))
        merged[key] = row

    for day, values in (quote.get('gold_table') or {}).items():
        put(day, values)
    for day, values in (quote.get('silver_table') or {}).items():
        put(day, values)
    put(quote['published'], {'gold24': quote['gold24'], 'gold22': quote['gold22'],
                             'gold18': quote.get('gold18')})
    if quote.get('silverkg') is not None and quote.get('silver_published'):
        put(quote['silver_published'], {'silverkg': quote['silverkg']})

    if merged:
        newest = max(merged)
        cutoff = (_date(newest) - timedelta(days=KEEP_DAYS)).isoformat()
        merged = {d: r for d, r in merged.items() if d >= cutoff}
    return merged


def merge_market(history, market, day):
    """Store today's market closes on an existing primary row (for later comparisons)."""
    row = (history or {}).get(day.isoformat())
    if not row or row.get('source') != PRIMARY:
        return history
    merged = dict(history)
    row = dict(row)
    for key, field in MARKET_FIELDS.items():
        item = (market or {}).get(key)
        if item and item.get('value') is not None:
            row[field] = str(item['value'])
    merged[day.isoformat()] = row
    return merged


def value_days_ago(history, field, as_of, days, tolerance=3):
    """(date, value) of a primary-source field about `days` before as_of, else None."""
    return _value_near(series(history, field, upto=as_of), as_of - timedelta(days=days), tolerance)


def _date(text):
    from datetime import date
    return date.fromisoformat(text)


def series(history, field, upto=None):
    """Sorted [(date, Decimal)] of primary-source values for one field."""
    out = []
    for day, row in (history or {}).items():
        if row.get('source') != PRIMARY or field not in row:
            continue
        d = _date(day)
        if upto is None or d <= upto:
            out.append((d, Decimal(row[field])))
    return sorted(out)


def _value_near(points, target, tolerance=3):
    """Latest value on or before target, within `tolerance` days."""
    best = None
    for day, value in points:
        if day <= target and (target - day).days <= tolerance:
            best = (day, value)
    return best


def stats(history, field, as_of):
    """Trend facts for one metal up to `as_of` (the quote's published date)."""
    points = series(history, field, upto=as_of)
    if not points or points[-1][0] != as_of:
        return None
    latest = points[-1][1]
    result = {'latest': latest, 'as_of': as_of, 'points': len(points)}
    for days in (7, 30):
        old = _value_near(points[:-1], as_of - timedelta(days=days))
        if old:
            delta = latest - old[1]
            result[f'change_{days}d'] = delta
            result[f'pct_{days}d'] = delta / old[1] * 100
    window = [(d, v) for d, v in points if (as_of - d).days < 30]
    result['window_days'] = (as_of - window[0][0]).days + 1
    result['window_points'] = len(window)
    result['high'] = max(v for _, v in window)
    result['low'] = min(v for _, v in window)
    if len(window) >= 5:
        result['is_low'] = latest == result['low'] and latest < max(v for _, v in window[:-1])
        result['is_high'] = latest == result['high'] and latest > min(v for _, v in window[:-1])
    # Consecutive same-direction daily moves ending today.
    streak, direction = 0, 0
    for (_, a), (_, b) in zip(reversed(points[:-1]), reversed(points[1:]), strict=True):
        step = (b > a) - (b < a)
        if step == 0 or (direction and step != direction):
            break
        direction = step
        streak += 1
    result['streak'] = streak
    result['streak_dir'] = direction
    if len(points) >= 2:
        result['prev'] = points[-2][1]
    return result


def last_n_days(history, field, as_of, days=30):
    return [(d, v) for d, v in series(history, field, upto=as_of) if (as_of - d).days < days]


def encode(history):
    return {day: dict(row) for day, row in sorted(history.items())}


def investment(history, quote, market):
    """Data-only investment context for the message. Every value comes from stored rates."""
    if not quote:
        return None
    as_of = quote['published']
    gold_g = Decimal(quote['gold24']) / 10
    info = {'grams_per_lakh': Decimal(100000) / gold_g}
    old = value_days_ago(history, 'gold24', as_of, 7)
    if old:
        info['grams_per_lakh_7d'] = Decimal(100000) / (old[1] / 10)
    if quote.get('silverkg') and quote.get('silver_published') == as_of:
        info['ratio'] = gold_g / (Decimal(quote['silverkg']) / 1000)
        old_s = value_days_ago(history, 'silverkg', as_of, 7)
        if old and old_s:
            info['ratio_7d'] = (old[1] / 10) / (old_s[1] / 1000)
    old_n = value_days_ago(history, 'nifty', as_of, 7)
    nifty = (market or {}).get('nifty')
    if old and old_n and nifty and nifty.get('value'):
        info['gold_pct_7d'] = (Decimal(quote['gold24']) - old[1]) / old[1] * 100
        info['nifty_pct_7d'] = (Decimal(nifty['value']) - old_n[1]) / old_n[1] * 100
    return info
