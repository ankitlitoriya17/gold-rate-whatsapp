"""Read dated Datia gold/silver quotations from Aaj Tak's published price cards.

This is a *city quotation*, NOT an IBJA bullion benchmark.
The caller may send only when both independently fetched pages have today's date.
"""
import html
import re
from datetime import date, datetime
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GOLD_URL = 'https://www.aajtak.in/commodity/gold-rate-in-datia-today'
SILVER_URL = 'https://www.aajtak.in/commodity/silver-rate-in-datia-today'

DATE_RE = re.compile(r'class="gs-info__last-updated"[^>]*>\s*Last Updated @\s*(\d{2}/\d{2}/\d{4})\s*<', re.I)
CARD_RE = re.compile(r'<div\s+class="gs-price-card">', re.I)
CELL_RE = re.compile(r'<div\s+class="gs-karat-cell">', re.I)
LABEL_RE = re.compile(r'<span\s+class="gs-karat-cell__label">\s*([^<]+?)\s*</span>')
PRICE_RE = re.compile(r'<span\s+class="gs-karat-cell__price">\s*₹\s*([0-9,]+)\s*</span>')
CHANGE_RE = re.compile(r'gs-karat-cell__badge--(up|down|neutral)"[^>]*>.*?₹\s*([0-9,]+)', re.S)


class PriceDataNotReady(RuntimeError):
    """Do not send and do not claim the daily ledger; retry at the next check."""


def fetch_html(url):
    if url not in (GOLD_URL, SILVER_URL):
        raise ValueError('Unexpected rate URL')
    request = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; DatiaGoldRateAlert/1.0)',
        'Accept': 'text/html',
        'Cache-Control': 'no-cache',
    })
    try:
        with urlopen(request, timeout=25) as response:
            if response.status != 200:
                raise PriceDataNotReady(f'Datia source returned HTTP {response.status}')
            raw = response.read(3_000_001)
            if len(raw) > 3_000_000:
                raise PriceDataNotReady('Datia page too large')
            return raw.decode('utf-8', 'replace')
    except (HTTPError, URLError):
        raise PriceDataNotReady('Datia rate source unavailable') from None


def extract_price_card(page, expected_type):
    """Only reads the named price card; ignores sidebar, history and other cities."""
    matches = DATE_RE.findall(page)
    if len(matches) != 1:
        raise PriceDataNotReady('Cannot uniquely identify published Datia rate date')
    try:
        published = datetime.strptime(matches[0], '%d/%m/%Y').date()
    except ValueError:
        raise PriceDataNotReady('Invalid published rate date') from None
    marker = CARD_RE.search(page)
    if not marker:
        raise PriceDataNotReady('Datia price card not found')
    section = page[marker.end():marker.end() + 18000]
    if f'gs-price-card__heading">{expected_type} Price</h3>' not in section[:1800]:
        raise PriceDataNotReady(f'Not the expected {expected_type} price card')
    if 'aria-label="Location: Datia"' not in section[:2200]:
        raise PriceDataNotReady('Price card location is not Datia')
    found = {}
    cells = list(CELL_RE.finditer(section))
    for i, cell in enumerate(cells):
        nxt = cells[i + 1].start() if i + 1 < len(cells) else len(section)
        content = section[cell.end():nxt]
        name_match = LABEL_RE.search(content)
        price_match = PRICE_RE.search(content)
        if not (name_match and price_match):
            continue
        name = html.unescape(name_match.group(1)).strip()
        if name in found:
            raise PriceDataNotReady('Duplicate price card label')
        price = Decimal(price_match.group(1).replace(',', ''))
        change_match = CHANGE_RE.search(content[:price_match.start()])
        delta = None
        if change_match:
            action, raw = change_match.groups()
            value = Decimal(raw.replace(',', ''))
            delta = -value if action == 'down' else (Decimal(0) if action == 'neutral' else value)
        found[name] = (price, delta)
    return published, found


def fetch_datia_quote(today=None):
    today = today or date.today()
    gold_date, gold = extract_price_card(fetch_html(GOLD_URL), 'Gold')
    silver_date, silver = extract_price_card(fetch_html(SILVER_URL), 'Silver')
    if gold_date != today or silver_date != today:
        raise PriceDataNotReady(
            f'Datia local rates not yet updated for {today.isoformat()}: '
            f'gold={gold_date.isoformat()}, silver={silver_date.isoformat()}')
    for needed, data in [('24 Karat', gold), ('22 Karat', gold), ('1 kg', silver)]:
        if needed not in data:
            raise PriceDataNotReady(f'Missing {needed} in Datia price card')
    gold24, delta24 = gold['24 Karat']
    gold22, delta22 = gold['22 Karat']
    silverkg, delta_silver = silver['1 kg']
    if not (Decimal(60000) < gold22 <= gold24 < Decimal(400000) and
            Decimal('0.85') < gold22 / gold24 < Decimal('0.97') and
            Decimal(80000) < silverkg < Decimal(600000)):
        raise PriceDataNotReady('Implausible Datia rates; do not send')
    return {
        'published': today,
        'gold24': gold24,
        'gold22': gold22,
        'silverkg': silverkg,
        'delta24': delta24,
        'delta22': delta22,
        'delta_silver': delta_silver,
    }


def format_datia_message(quote):
    published = quote['published']
    def money(value):
        digits = str(int(value))
        if len(digits) <= 3:
            return '₹' + digits
        rest, suffix = digits[:-3], digits[-3:]
        groups = []
        while rest:
            groups.append(rest[-2:])
            rest = rest[:-2]
        return '₹' + ','.join(reversed(groups)) + ',' + suffix
    def movement(value):
        if value is None:
            return ''
        if value == 0:
            return '  ↔️ Same'
        return ('  🔺 +' if value > 0 else '  🔻 -') + money(abs(value))
    return '\n'.join([
        '🌟 *Datia Gold & Silver Rates*',
        f'📅 {published.strftime("%d %b %Y")} | Datia City Quote',
        '',
        f"🟡 *24K Gold:* {money(quote['gold24'])}/10g{movement(quote['delta24'])}",
        f"🟡 *22K Gold:* {money(quote['gold22'])}/10g{movement(quote['delta22'])}",
        f"⚪ *Silver (999):* {money(quote['silverkg'])}/kg{movement(quote['delta_silver'])}",
        '',
        '↕️ Change vs pichhla quoted rate',
        'ℹ️ Indicative Datia rates; local jeweller prices alag ho sakte hain.',
        'GST & making charges extra. Source: Aaj Tak (Datia).',
        GOLD_URL,
        SILVER_URL,
    ])
