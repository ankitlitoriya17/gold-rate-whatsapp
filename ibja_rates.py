"""Primary gold/silver source: IBJA (India Bullion and Jewellers Association) benchmark.

IBJA rates are the official national benchmark used by RBI (SGB), banks and NBFCs
(gold loans). Published on trading days (AM ~12:00, PM ~17:00 IST), per 10g gold and
per kg silver, without GST and making charges.

Replaced Aaj Tak Datia on 2026-11-26: Aaj Tak's "today" rate was found to be the
previous day's market rate (one day lag), so it showed wrong daily moves.

The page embeds dated series (hidden inputs HdnGold / HdnSilver) with the PM rate per
date; the latest label is the rate date. The headline label values (lblGold999_PM etc.)
must match that latest series value, otherwise the page is treated as inconsistent.
"""
import html
import json
import re
import time
from datetime import date, datetime
from decimal import Decimal
from urllib.request import Request, urlopen

from datia_rates import BROWSER_HEADERS, PriceDataNotReady, _describe

URL = 'https://www.ibjarates.com/'
SOURCE = 'ibja'
RETRY_DELAYS = (5, 15)

HIDDEN_RE = r'<input[^>]*id="{id}"[^>]*value="([^"]*)"'
LABEL_RE = r'id="{id}"[^>]*>\s*([0-9]+)\s*<'


def _fetch(sleep=time.sleep):
    reasons = []
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            sleep(RETRY_DELAYS[attempt - 1])
        try:
            with urlopen(Request(URL, headers=BROWSER_HEADERS), timeout=30) as response:
                if response.status != 200:
                    raise PriceDataNotReady(f'HTTP {response.status}')
                page = response.read(3_000_001).decode('utf-8', 'replace')
            if 'HdnGold' not in page:
                raise PriceDataNotReady('page without rate data (possible block)')
            return page
        except (OSError, PriceDataNotReady) as exc:
            reasons.append(_describe(exc))
            print(f'IBJA FETCH attempt {attempt + 1} failed: {reasons[-1]}')
    raise PriceDataNotReady('IBJA unavailable after retries: ' + '; '.join(reasons))


def _hidden(page, element_id):
    match = re.search(HIDDEN_RE.format(id=re.escape(element_id)), page)
    if not match:
        raise PriceDataNotReady(f'{element_id} not found')
    try:
        return json.loads(html.unescape(match.group(1)))
    except ValueError:
        raise PriceDataNotReady(f'{element_id} is not valid JSON') from None


def _label(page, element_id):
    match = re.search(LABEL_RE.format(id=re.escape(element_id)), page)
    return Decimal(match.group(1)) if match else None


def _series(labels, values):
    out = {}
    for label, value in zip(labels, values, strict=False):
        try:
            day = datetime.strptime(label, '%d/%m/%Y').date()
            number = Decimal(str(value))
        except (ValueError, TypeError, ArithmeticError):
            continue
        if number > 0:
            out[day] = number
    return out


def parse_page(page, today):
    gold = _hidden(page, 'HdnGold')
    silver = _hidden(page, 'HdnSilver')
    g24 = _series(gold.get('labels', []), gold.get('purity999', []))
    g22 = _series(gold.get('labels', []), gold.get('purity916', []))
    sk = _series(silver.get('labels', []), silver.get('silverRate', []))
    days = sorted(d for d in g24 if d in g22 and d <= today)
    if not days:
        raise PriceDataNotReady('no dated IBJA gold rates')
    latest = days[-1]
    # Headline PM (or AM if PM not out yet) must equal the latest dated value.
    headline = _label(page, 'lblGold999_PM') or _label(page, 'lblGold999_AM')
    if headline is not None and headline != g24[latest]:
        raise PriceDataNotReady('IBJA headline rate does not match latest dated rate')
    gold24, gold22 = g24[latest], g22[latest]
    if not (Decimal(60000) < gold22 <= gold24 < Decimal(400000)
            and Decimal('0.88') < gold22 / gold24 < Decimal('0.95')):
        raise PriceDataNotReady('implausible IBJA gold rate')
    gold18 = _label(page, 'lblGold750_PM') or _label(page, 'lblGold750_AM')
    if headline is None or gold18 is None or not Decimal('0.70') < gold18 / gold24 < Decimal('0.80'):
        gold18 = None
    prev = days[-2] if len(days) >= 2 else None

    s_days = sorted(d for d in sk if d <= today)
    silver_day = s_days[-1] if s_days else None
    silverkg = sk[silver_day] if silver_day else None
    if silverkg is not None and not Decimal(50000) < silverkg < Decimal(600000):
        silverkg, silver_day = None, None
    s_prev = s_days[-2] if len(s_days) >= 2 and silverkg is not None else None

    return {
        'published': latest,
        'report_date': today,
        'silver_published': silver_day,
        'gold24': gold24,
        'gold22': gold22,
        'gold18': gold18,
        'silverkg': silverkg,
        'delta24': gold24 - g24[prev] if prev else None,
        'delta22': gold22 - g22[prev] if prev else None,
        'delta18': None,
        'delta_silver': silverkg - sk[s_prev] if s_prev else None,
        'source': SOURCE,
        'gold_table': {d: {'gold24': g24[d], 'gold22': g22[d]} for d in days},
        'silver_table': {d: {'silverkg': sk[d]} for d in s_days
                         if Decimal(50000) < sk[d] < Decimal(600000)},
    }


def fetch_ibja_quote(today=None, sleep=time.sleep):
    today = today or date.today()
    return parse_page(_fetch(sleep), today)
