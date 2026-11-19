"""Read dated Datia gold/silver quotations from Aaj Tak's published price cards.

This is a *city quotation*, NOT an IBJA bullion benchmark.
Send latest available dated quotations, even on weekends or when sources lag, and label each metal's publication date.
"""
import html
import re
import time
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


BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
    'Cache-Control': 'no-cache',
}
RETRY_DELAYS = (5, 15)  # seconds to wait before attempt 2 and attempt 3


def _describe(exc):
    """Short, secret-free reason for logs (HTTP code or exception type)."""
    if isinstance(exc, HTTPError):
        return f'HTTP {exc.code}'
    if isinstance(exc, URLError):
        return f'network error ({type(exc.reason).__name__})'
    if isinstance(exc, PriceDataNotReady):
        return str(exc)
    return type(exc).__name__


def _fetch_once(url):
    request = Request(url, headers=BROWSER_HEADERS)
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise PriceDataNotReady(f'HTTP {response.status}')
        raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            raise PriceDataNotReady('Datia page too large')
        page = raw.decode('utf-8', 'replace')
    if 'gs-price-card' not in page:
        # Bot-check / error pages come back as 200 without the price card.
        raise PriceDataNotReady('page without price card (possible bot block)')
    return page


def fetch_html(url, sleep=time.sleep):
    if url not in (GOLD_URL, SILVER_URL):
        raise ValueError('Unexpected rate URL')
    reasons = []
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            sleep(RETRY_DELAYS[attempt - 1])
        try:
            return _fetch_once(url)
        except (OSError, PriceDataNotReady) as exc:  # URLError/HTTPError/timeouts are OSError
            reason = _describe(exc)
            reasons.append(reason)
            print(f'DATIA FETCH attempt {attempt + 1} failed for '
                  f'{url.rsplit("/", 1)[-1]}: {reason}')
    raise PriceDataNotReady('Datia rate source unavailable after '
                            f'{len(reasons)} attempts: ' + '; '.join(reasons))


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
    gold_page = fetch_html(GOLD_URL)
    silver_page = fetch_html(SILVER_URL)
    gold_date, gold = extract_price_card(gold_page, 'Gold')
    silver_date, silver = extract_price_card(silver_page, 'Silver')
    # Never claim an old quotation is today's price. Send it only with its
    # actual source date visibly displayed. Reject impossible future dates.
    if gold_date > today or silver_date > today:
        raise PriceDataNotReady(
            f'Datia source has future-dated quotation: '
            f'gold={gold_date.isoformat()}, silver={silver_date.isoformat()}, '
            f'report={today.isoformat()}')
    for needed, data in [('24 Karat', gold), ('22 Karat', gold), ('1 kg', silver)]:
        if needed not in data:
            raise PriceDataNotReady(f'Missing {needed} in Datia price card')
    gold24, delta24 = gold['24 Karat']
    gold22, delta22 = gold['22 Karat']
    gold18, delta18 = gold.get('18 Karat', (None, None))
    if gold18 is not None and not (Decimal('0.70') < gold18 / gold24 < Decimal('0.80')):
        gold18, delta18 = None, None  # optional; drop if implausible
    silverkg, delta_silver = silver['1 kg']
    if not (Decimal(60000) < gold22 <= gold24 < Decimal(400000) and
            Decimal('0.85') < gold22 / gold24 < Decimal('0.97') and
            Decimal(80000) < silverkg < Decimal(600000)):
        raise PriceDataNotReady('Implausible Datia rates; do not send')
    return {
        'published': gold_date,
        'report_date': today,
        'silver_published': silver_date,
        'gold24': gold24,
        'gold22': gold22,
        'silverkg': silverkg,
        'delta24': delta24,
        'delta22': delta22,
        'gold18': gold18,
        'delta18': delta18,
        'delta_silver': delta_silver,
        'source': 'aajtak-datia',
        # Up to ~10 previous days published on the same pages (best effort).
        'gold_table': _safe_table(gold_page, 'gold', today),
        'silver_table': _safe_table(silver_page, 'silver', today),
    }


TABLE_RE = re.compile(r'<table\s+class="gh-table"[^>]*>(.*?)</table>', re.S | re.I)
ROW_RE = re.compile(r'<tr>(.*?)</tr>', re.S | re.I)
TD_RE = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)
YEAR_RE = re.compile(r'<th[^>]*>\s*Datia\s*<br\s*/?>\s*(\d{4})\s*</th>', re.I)
MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}


def _rupee_cell(cell):
    text = re.sub(r'<[^>]+>', '', cell)
    match = re.fullmatch(r'\s*₹\s*([0-9,]+)\s*', text)
    return Decimal(match.group(1).replace(',', '')) if match else None


def extract_history_table(page, metal, today):
    """Parse the 'last 10 days' table. Returns {date: {...}}; only plausible rows.

    Gold columns: 24K (col 1), 22K (col 3) per 10g. Silver: 1 kg (col 1).
    The change badges on this table are inconsistent, so changes are derived
    from prices later, never read from the badges.
    """
    match = TABLE_RE.search(page)
    if not match:
        return {}
    table = match.group(1)
    year_match = YEAR_RE.search(table)
    year = int(year_match.group(1)) if year_match else today.year
    rows = {}
    for row in ROW_RE.findall(table):
        cells = TD_RE.findall(row)
        if len(cells) < 4:
            continue
        label = re.sub(r'<[^>]+>', '', cells[0]).strip()
        parts = label.split()
        if len(parts) != 2 or parts[0][:3] not in MONTHS or not parts[1].isdigit():
            continue
        month, day_no = MONTHS[parts[0][:3]], int(parts[1])
        row_year = year - 1 if month > today.month + 1 else year  # Dec rows seen in Jan
        try:
            day = date(row_year, month, day_no)
        except ValueError:
            continue
        if day > today:
            continue
        if metal == 'gold':
            g24, g22 = _rupee_cell(cells[1]), _rupee_cell(cells[3])
            if g24 and g22 and Decimal(60000) < g22 <= g24 < Decimal(400000):
                rows[day] = {'gold24': g24, 'gold22': g22}
                g18 = _rupee_cell(cells[5]) if len(cells) > 5 else None
                if g18 and Decimal('0.70') < g18 / g24 < Decimal('0.80'):
                    rows[day]['gold18'] = g18
        else:
            kg = _rupee_cell(cells[1])
            if kg and Decimal(80000) < kg < Decimal(600000):
                rows[day] = {'silverkg': kg}
    return rows


def _safe_table(page, metal, today):
    try:
        return extract_history_table(page, metal, today)
    except Exception as exc:  # history is optional; never block the daily rate
        print(f'DATIA HISTORY TABLE: {metal} not parsed ({type(exc).__name__})')
        return {}


def format_datia_message(quote):
    gold_date = quote['published']
    report_date = quote.get('report_date', gold_date)
    silver_date = quote.get('silver_published', gold_date)

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

    gold_fresh = gold_date == report_date
    silver_fresh = silver_date == report_date
    lines = [
        '🌟 *Datia Gold & Silver Daily Update*',
        f'📅 Report: {report_date.strftime("%d %b %Y")}',
        '',
        f"🟡 *24K Gold:* {money(quote['gold24'])}/10g"
        + (movement(quote['delta24']) if gold_fresh else ''),
        f"🟡 *22K Gold:* {money(quote['gold22'])}/10g"
        + (movement(quote['delta22']) if gold_fresh else ''),
        f"📌 Gold quote date: *{gold_date.strftime('%d %b %Y')}*"
        + (' (latest, NOT today)' if not gold_fresh else ''),
        '',
        f"⚪ *Silver (999):* {money(quote['silverkg'])}/kg"
        + (movement(quote['delta_silver']) if silver_fresh else ''),
        f"📌 Silver quote date: *{silver_date.strftime('%d %b %Y')}*"
        + (' (latest, NOT today)' if not silver_fresh else ''),
        '',
    ]
    if not gold_fresh or not silver_fresh:
        lines.append('⚠️ Kam se kam ek source aaj update nahi hua; purane quotes ko aaj ka rate na samjhein.')
    if gold_fresh or silver_fresh:
        lines.append('↕️ Arrows sirf aaj ke published quotes ka change vs previous quote dikhate hain.')
    lines += [
        'ℹ️ Datia ke indicative city quotes; jeweller prices alag ho sakte hain.',
        'GST & making charges extra. Source: Aaj Tak (Datia).',
        GOLD_URL,
        SILVER_URL,
    ]
    return '\n'.join(lines)
