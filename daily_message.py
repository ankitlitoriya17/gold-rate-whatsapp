"""The daily group message: short Hinglish, data-first, every number verified.

Layout: header -> one-line headline -> rates (+ per gram) -> trend -> jewellery
estimate -> compact market line -> AI (2 lines) -> tip (Mon/Wed/Fri) -> footer.
"""
from decimal import Decimal, ROUND_HALF_UP

MAKING_LOW, MAKING_HIGH = Decimal('0.08'), Decimal('0.15')
GST = Decimal('0.03')
BIG_MOVE_PCT = Decimal('1.5')
SOURCE_LABELS = {
    'aajtak-datia': 'Aaj Tak (Datia)',
    'goodreturns-bhopal': 'Goodreturns (Bhopal) — Datia source aaj fail tha',
}


def money(value):
    digits = str(abs(int(Decimal(value).quantize(Decimal(1), ROUND_HALF_UP))))
    if len(digits) > 3:
        rest, tail = digits[:-3], digits[-3:]
        groups = []
        while rest:
            groups.append(rest[-2:])
            rest = rest[:-2]
        digits = ','.join(reversed(groups)) + ',' + tail
    return '₹' + digits


def signed_money(value):
    value = Decimal(value)
    if value == 0:
        return '₹0'
    return ('+' if value > 0 else '−') + money(abs(value))


def pct(value, places=2):
    value = Decimal(value)
    sign = '+' if value > 0 else ('−' if value < 0 else '')
    return sign + format(abs(value).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP), 'f') + '%'


def _round100(value):
    return (Decimal(value) / 100).quantize(Decimal(1), ROUND_HALF_UP) * 100


def _fresh(quote, now):
    return bool(quote) and quote['published'] == now.date()


def headline(quote, trend, now):
    if not quote:
        return '⚠️ *Aaj Datia ka gold rate nahi mil paya*'
    if not _fresh(quote, now):
        return f"ℹ️ *Aaj rate update nahi hua — {quote['published'].strftime('%d %b')} ka rate*"
    delta = quote.get('delta24')
    if delta is None and trend and trend.get('prev') is not None:
        delta = trend['latest'] - trend['prev']
    if delta is None:
        return '🟡 *Aaj ka gold rate*'
    if delta == 0:
        return '↔️ *Gold aaj sthir — koi badlav nahi*'
    word = 'sasta' if delta < 0 else 'mehenga'
    text = f"{'🔻' if delta < 0 else '🔺'} *Aaj gold {money(abs(delta))} {word}"
    extra = ''
    if trend and trend.get('window_points', 0) >= 5:
        days = trend['window_days']
        if trend.get('is_low'):
            extra = f' — {days} din ka sabse kam rate'
        elif trend.get('is_high'):
            extra = f' — {days} din ka sabse uncha rate'
    if not extra and trend and trend.get('streak', 0) >= 3:
        extra = f" — lagataar {trend['streak']} din se {'gir raha' if delta < 0 else 'badh raha'}"
    previous = quote['gold24'] - delta
    if not extra and previous > 0 and abs(delta) / previous * 100 >= BIG_MOVE_PCT:
        extra = f' ({pct(delta / previous * 100, 1)}, bada move)'
    return text + extra + '*'


def _rate_line(label, value, unit, delta, fresh):
    line = f'{label} {money(value)}{unit}'
    if fresh and delta is not None:
        line += '  (koi badlav nahi)' if delta == 0 else f'  ({signed_money(delta)})'
    return line


def rate_block(quote, now):
    if not quote:
        return ['24K / 22K / Chandi: unavailable',
                'Rate verify nahi ho paya, isliye koi number nahi diya.']
    fresh = _fresh(quote, now)
    lines = [
        _rate_line('🟡 *24K:*', quote['gold24'], '/10g', quote.get('delta24'), fresh),
        _rate_line('🟡 *22K:*', quote['gold22'], '/10g', quote.get('delta22'), fresh),
    ]
    if quote.get('gold18') is not None:
        lines.append(_rate_line('🟡 *18K:*', quote['gold18'], '/10g', quote.get('delta18'), fresh))
    per_gram = f"      1 gram: 24K {money(quote['gold24'] / 10)} · 22K {money(quote['gold22'] / 10)}"
    if quote.get('gold18') is not None:
        per_gram += f" · 18K {money(quote['gold18'] / 10)}"
    lines.append(per_gram)
    if quote.get('silverkg') is not None:
        silver_fresh = quote.get('silver_published') == now.date()
        lines.append(_rate_line('⚪ *Chandi:*', quote['silverkg'], '/kg',
                                quote.get('delta_silver'), silver_fresh)
                     + f" · {money(quote['silverkg'] / 100)}/10g")
        if not silver_fresh and quote.get('silver_published'):
            lines.append(f"      (chandi ka rate {quote['silver_published'].strftime('%d %b')} ka)")
    else:
        lines.append('⚪ *Chandi:* unavailable')
    return lines


def trend_block(trend):
    if not trend or trend.get('points', 0) < 3:
        return []
    parts = []
    for days in (7, 30):
        if f'change_{days}d' in trend:
            parts.append(f"{days} din: {signed_money(trend[f'change_{days}d'])} "
                         f"({pct(trend[f'pct_{days}d'], 1)})")
    lines = ['📊 *Trend · 24K*']
    if parts:
        lines.append(' · '.join(parts))
    if trend.get('window_points', 0) >= 3:
        lines.append(f"{trend['window_days']} din ka range: {money(trend['low'])} – {money(trend['high'])}")
    if trend.get('streak', 0) >= 2:
        lines.append(f"Lagataar {trend['streak']} din se {'neeche' if trend['streak_dir'] < 0 else 'upar'}")
    return lines if len(lines) > 1 else []


def jewellery_block(quote):
    if not quote:
        return []
    base = quote['gold22']
    low = _round100(base * (1 + MAKING_LOW) * (1 + GST))
    high = _round100(base * (1 + MAKING_HIGH) * (1 + GST))
    return ['💍 *10g 22K jewellery ka andaaza*',
            f'{money(low)} – {money(high)} (making 8–15% + 3% GST maan kar)']


def grams(value):
    return format(Decimal(value).quantize(Decimal('0.01'), ROUND_HALF_UP), 'f') + 'g'


def investment_block(info):
    if not info:
        return []
    line = f"₹1 lakh = {grams(info['grams_per_lakh'])} 24K sona"
    if 'grams_per_lakh_7d' in info:
        line += f" (7 din pehle {grams(info['grams_per_lakh_7d'])})"
    lines = ['💰 *Investment nazar*', line]
    if 'ratio' in info:
        ratio = f"Gold:Silver ratio {info['ratio'].quantize(Decimal('0.1'), ROUND_HALF_UP)}"
        if 'ratio_7d' in info:
            ratio += f" (7 din pehle {info['ratio_7d'].quantize(Decimal('0.1'), ROUND_HALF_UP)})"
        lines.append(ratio + ' — 1g sone mein itne gram chandi')
    if 'nifty_pct_7d' in info:
        lines.append(f"7 din: Gold {pct(info['gold_pct_7d'], 1)} · Nifty {pct(info['nifty_pct_7d'], 1)}")
    return lines


def _market_item(label, quote, prefix='', places=0, suffix=''):
    if not quote:
        return None
    value = Decimal(quote['value']).quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    text = f'{label} {prefix}{value:,}{suffix}'
    change = quote.get('change_pct')
    if change is not None:
        arrow = '▲' if change > 0 else ('▼' if change < 0 else '•')
        text += f' {arrow}{pct(abs(change)).lstrip("+")}'
    return text


def market_block(market):
    market = market or {}
    first = [x for x in (_market_item('Nifty', market.get('nifty')),
                         _market_item('Sensex', market.get('sensex'))) if x]
    second = [x for x in (_market_item('$1 =', market.get('usdinr'), '₹', 2),
                          _market_item('Crude', market.get('brent'), '$', 1)) if x]
    third = [x for x in (_market_item('Intl gold', market.get('goldusd'), '$', suffix='/oz'),
                         _market_item('GoldBees ETF', market.get('goldbees'), '₹', 2)) if x]
    lines = []
    if first:
        lines.append('📈 ' + ' · '.join(first))
    if second:
        lines.append('🌍 ' + ' · '.join(second))
    if third:
        lines.append('🥇 ' + ' · '.join(third))
    return lines


def build_daily_message(quote, trend, market, now, ai_insights=None, tip=None, invest=None):
    lines = [f"🪙 *Datia Gold Update* · {now.strftime('%d %b, %a')}",
             headline(quote, trend, now), '']
    lines += rate_block(quote, now)
    for block in (trend_block(trend), investment_block(invest), jewellery_block(quote), market_block(market)):
        if block:
            lines += [''] + block
    if ai_insights:
        lines += ['', '🧠 *AI ki nazar se*', ai_insights['insight'],
                  '🔎 ' + ai_insights['watch']]
    if tip:
        lines += ['', '💡 *Kaam ki baat:* ' + tip]
    source = SOURCE_LABELS.get((quote or {}).get('source'), 'Aaj Tak (Datia)')
    lines += ['', f'_Source: {source}. Rate GST/making ke bina; dukaan ka rate alag ho sakta hai. '
                  'Investment salah nahi._']
    return '\n'.join(lines)
