"""Backup gold quote from Goodreturns (Bhopal, MP), used only when Aaj Tak Datia fails.

Also used to cross-check the Datia gold rate. Goodreturns publishes per-gram
prices; they are converted to per-10g. Its silver rate differs a lot from Aaj
Tak's, so silver is taken from here only as a clearly labelled fallback and is
never cross-checked.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from datia_rates import PriceDataNotReady, _describe, BROWSER_HEADERS
from urllib.request import Request, urlopen

GOLD_URL = 'https://www.goodreturns.in/gold-rates/bhopal.html'
SILVER_URL = 'https://www.goodreturns.in/silver-rates/bhopal.html'
CITY = 'Bhopal'

TITLE_DATE_RE = re.compile(r'<title>[^<]*?on\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*-\s*Goodreturns</title>', re.I)
PRICE_ID_RE = r'id="{id}"[^>]*>\s*(?:&#x20b9;|₹)\s*([0-9,]+)\s*<'
CROSS_CHECK_LIMIT = Decimal('0.04')  # 4% gap between Datia and Bhopal 24K = alert


def _get(url):
    request = Request(url, headers=BROWSER_HEADERS)
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise PriceDataNotReady(f'HTTP {response.status}')
        return response.read(2_000_001).decode('utf-8', 'replace')


def _price(page, element_id):
    match = re.search(PRICE_ID_RE.format(id=re.escape(element_id)), page)
    if not match:
        raise PriceDataNotReady(f'{element_id} not found')
    return Decimal(match.group(1).replace(',', ''))


def _published(page):
    match = TITLE_DATE_RE.search(page)
    if not match:
        raise PriceDataNotReady('publication date not found')
    return datetime.strptime(match.group(1), '%d %B %Y').date()


def parse_gold(page):
    day = _published(page)
    g24 = _price(page, '24K-price') * 10
    g22 = _price(page, '22K-price') * 10
    if not (Decimal(60000) < g22 <= g24 < Decimal(400000)
            and Decimal('0.85') < g22 / g24 < Decimal('0.97')):
        raise PriceDataNotReady('implausible backup gold rate')
    return day, g24, g22


def parse_silver(page):
    day = _published(page)
    kg = _price(page, 'silver-1kg-price')
    if not Decimal(80000) < kg < Decimal(600000):
        raise PriceDataNotReady('implausible backup silver rate')
    return day, kg


def fetch_backup_quote(today=None):
    """Same shape as fetch_datia_quote(); deltas are unknown for this source."""
    today = today or date.today()
    try:
        gday, g24, g22 = parse_gold(_get(GOLD_URL))
    except (OSError, PriceDataNotReady, ValueError) as exc:
        raise PriceDataNotReady('backup gold unavailable: ' + _describe(exc)) from None
    if gday > today:
        raise PriceDataNotReady('backup gold is future-dated')
    try:
        sday, kg = parse_silver(_get(SILVER_URL))
        if sday > today:
            raise PriceDataNotReady('backup silver is future-dated')
    except (OSError, PriceDataNotReady, ValueError) as exc:
        print('BACKUP SILVER unavailable: ' + _describe(exc))
        sday, kg = None, None
    return {
        'published': gday,
        'report_date': today,
        'silver_published': sday,
        'gold24': g24,
        'gold22': g22,
        'silverkg': kg,
        'delta24': None,
        'delta22': None,
        'delta_silver': None,
        'source': 'goodreturns-bhopal',
        'gold_table': {},
        'silver_table': {},
    }


def cross_check(primary, backup):
    """Returns a warning string if Datia and Bhopal 24K differ too much, else None."""
    if not primary or not backup or primary['published'] != backup['published']:
        return None
    gap = abs(primary['gold24'] - backup['gold24']) / backup['gold24']
    if gap > CROSS_CHECK_LIMIT:
        return (f'Datia 24K Rs {primary["gold24"]} vs {CITY} Rs {backup["gold24"]} '
                f'({(gap * 100):.1f}% fark) — Datia rate galat ho sakta hai, check karein')
    return None
