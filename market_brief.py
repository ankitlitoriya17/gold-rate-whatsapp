"""Best-effort read-only market snapshots for a concise personal investor brief.

Public Yahoo Finance chart access is unofficial and may throttle or change.
Quote failures never block sending the Datia Gold/Silver message.
No extra packages, keys, or inferred/backfilled prices are required.
"""
import json
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
ASSETS = {
    'nifty': {'symbol': '^NSEI', 'currency': 'INR', 'lo': 8000, 'hi': 80000},
    'sensex': {'symbol': '^BSESN', 'currency': 'INR', 'lo': 20000, 'hi': 250000},
    'usdinr': {'symbol': 'INR=X', 'currency': 'INR', 'lo': 40, 'hi': 250},
    'brent': {'symbol': 'BZ=F', 'currency': 'USD', 'lo': 10, 'hi': 350},
    # International gold futures (USD per troy ounce) and Nippon India Gold BeES ETF (NSE).
    'goldusd': {'symbol': 'GC=F', 'currency': 'USD', 'lo': 500, 'hi': 20000},
    'goldbees': {'symbol': 'GOLDBEES.NS', 'currency': 'INR', 'lo': 10, 'hi': 2000},
}


class MarketQuoteError(ValueError):
    pass


def positive(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return result if result.is_finite() and result > 0 else None


def fetch_chart(symbol):
    last_error = None
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        url = ('https://' + host + '/v8/finance/chart/'
               + quote(symbol, safe='') + '?interval=1d&range=5d')
        request = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; DatiaInvestorBrief/1.0)',
            'Accept': 'application/json',
        })
        try:
            with urlopen(request, timeout=8) as response:
                if response.status != 200:
                    raise MarketQuoteError('unexpected provider response')
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise MarketQuoteError('market response too large')
            return json.loads(raw.decode('utf-8'))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = type(exc).__name__
    raise MarketQuoteError('market provider temporarily unavailable: ' + str(last_error))


def previous_day_close(result, today):
    """Last non-empty daily close dated before `today` (IST), or None."""
    stamps = result.get('timestamp') or []
    quotes = ((result.get('indicators') or {}).get('quote') or [{}])[0]
    closes = quotes.get('close') or []
    best = None
    for stamp, close in zip(stamps, closes, strict=False):
        value = positive(close)
        if value is None:
            continue
        if datetime.fromtimestamp(int(stamp), IST).date() < today:
            best = value
    return best


def parse_chart(doc, key, now=None):
    now = now or datetime.now(IST)
    spec = ASSETS[key]
    try:
        results = doc['chart']['result']
        result = results[0]
        meta = result['meta']
        if str(meta.get('currency', '')).upper() != spec['currency']:
            raise MarketQuoteError('unexpected currency')
        price = positive(meta.get('regularMarketPrice'))
        stamp = meta.get('regularMarketTime')
        if price is None or stamp is None:
            raise MarketQuoteError('quote price or timestamp missing')
        when = datetime.fromtimestamp(int(stamp), IST)
        if when > now + timedelta(minutes=10) or (now - when) > timedelta(days=8):
            raise MarketQuoteError('market quote missing or too old')
        if not (Decimal(spec['lo']) < price < Decimal(spec['hi'])):
            raise MarketQuoteError('implausible quote')
        # Previous TRADING-DAY close from the daily bars. Do not use meta
        # previousClose/chartPreviousClose: with range=5d Yahoo returns the close
        # before the 5-day window there, which made every "daily" % a ~5-day move.
        previous = previous_day_close(result, when.date())
        pct = None
        if previous is not None:
            raw_pct = (price - previous) / previous * 100
            if abs(raw_pct) <= 40:
                pct = raw_pct
        return {
            'value': price,
            'change_pct': pct,
            'as_of': when,
            'currency': spec['currency'],
            'symbol': spec['symbol'],
            'source': 'Yahoo Finance (unofficial)',
        }
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, MarketQuoteError):
            raise
        raise MarketQuoteError('unexpected provider schema') from None


def fetch_market_quotes(now=None):
    now = now or datetime.now(IST)
    output = {}
    for key, spec in ASSETS.items():
        try:
            output[key] = parse_chart(fetch_chart(spec['symbol']), key, now)
        except (MarketQuoteError, OSError, ValueError) as exc:
            # A rate source failure is not a reason to suppress the daily Gold alert.
            print(f'MARKET DATA UNAVAILABLE: {key} ({type(exc).__name__})')
            output[key] = None
    return output


def _number(value, places=2):
    return format(value, f',.{places}f')


def _pct(change):
    if change is None:
        return ''
    if change > 0:
        return ' ↑ +' + _number(change) + '%'
    if change < 0:
        return ' ↓ −' + _number(abs(change)) + '%'
    return ' → 0.00%'


def _time_label(quote):
    return quote['as_of'].strftime('%d %b %H:%M IST')


def _line(label, quote, prefix='', suffix='', places=2, show_time=False):
    if not quote:
        return f'{label}: unavailable'
    value = prefix + _number(quote['value'], places) + suffix
    label_time = _time_label(quote) if show_time else quote['as_of'].strftime('%d %b')
    return f'{label}: {value}{_pct(quote["change_pct"])}  ({label_time})'


def _pulse(data):
    notes = []
    nifty, sensex = data.get('nifty'), data.get('sensex')
    if nifty and sensex:
        a, b = nifty['change_pct'], sensex['change_pct']
        if a is not None and b is not None:
            if a > 0 and b > 0:
                notes.append('Indian indices higher')
            elif a < 0 and b < 0:
                notes.append('Indian indices lower')
            else:
                notes.append('Indian indices mixed/flat')
    usd = data.get('usdinr')
    if usd and usd['change_pct'] is not None:
        if usd['change_pct'] > 0:
            notes.append('INR weaker vs USD')
        elif usd['change_pct'] < 0:
            notes.append('INR stronger vs USD')
    return ' · '.join(notes) if notes else None


def format_investor_brief(gold, market, now, ai_insights=None):
    """Readable WhatsApp markdown; optional validated AI commentary is additive."""
    report = now.strftime('%d %b %Y')

    def money(amount):
        digits = str(int(amount))
        if len(digits) <= 3:
            return '₹' + digits
        rest, tail = digits[:-3], digits[-3:]
        groups = []
        while rest:
            groups.append(rest[-2:])
            rest = rest[:-2]
        return '₹' + ','.join(reversed(groups)) + ',' + tail

    def move(amount, fresh):
        if not fresh or amount is None:
            return ''
        if amount == 0:
            return ' → Same'
        return (' ↑ +' if amount > 0 else ' ↓ −') + money(abs(amount))

    lines = [
        '📊 *DATIA | DAILY INVESTOR BRIEF*',
        f'📅 {report} • {_clock(now)} IST',
        '',
        '🟡 *GOLD & SILVER · Datia*',
    ]
    if gold is None:
        lines += [
            '24K Gold: unavailable',
            '22K Gold: unavailable',
            'Silver 999: unavailable',
            '⚠️ Datia source unavailable; prices not verified.',
        ]
    else:
        gold_date = gold['published']
        silver_date = gold.get('silver_published', gold_date)
        gold_today = gold_date == now.date()
        silver_today = silver_date == now.date()
        lines += [
            f"24K Gold  {money(gold['gold24'])}/10g{move(gold.get('delta24'), gold_today)}",
            f"22K Gold  {money(gold['gold22'])}/10g{move(gold.get('delta22'), gold_today)}",
            f"Silver 999  {money(gold['silverkg'])}/kg{move(gold.get('delta_silver'), silver_today)}",
            f"🗓️ Gold {gold_date.strftime('%d %b')} · Silver {silver_date.strftime('%d %b')}",
        ]
        if not gold_today or not silver_today:
            lines.append('⚠️ Older published quotes shown above; not today’s rates.')

    lines.extend([
        '',
        '📈 *INDIAN EQUITIES · Last quote*',
        _line('Nifty 50', market.get('nifty'), show_time=True),
        _line('Sensex', market.get('sensex'), show_time=True),
        '',
        '🌍 *GLOBAL INDICATORS · Latest quote*',
        _line('USD/INR', market.get('usdinr'), prefix='₹', suffix='/USD', show_time=True),
        _line('Brent futures', market.get('brent'), prefix='$', suffix='/bbl', show_time=True),
    ])
    pulse = _pulse(market)
    if pulse:
        lines.extend(['', f'🧭 *Market pulse:* {pulse}.'])
    if gold is None and not any(market.values()):
        lines += ['', '⚠️ All price sources are temporarily unavailable.']
    if ai_insights:
        lines += [
            '',
            '🧠 *AI MARKET INSIGHTS · Observations only*',
            '📌 ' + ai_insights['summary'],
        ] + (['🟡 ' + ai_insights['gold']] if ai_insights.get('gold') else []) + [
            '🔎 Kal dekhein: ' + ai_insights['watch'],
        ]
    lines.extend([
        '',
        'ℹ️ Moves vs previous provider close. Quotes may be delayed; GST/making extra on jewellery.',
        'Sources: Aaj Tak (Datia) · Yahoo Finance (unofficial).',
        'No investment recommendation.',
    ])
    return '\n'.join(lines)


def _clock(now):
    return now.strftime('%I:%M %p').lstrip('0')
