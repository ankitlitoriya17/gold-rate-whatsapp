#!/usr/bin/env python3
"""Datia gold-rate WhatsApp alert. Python standard library only."""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo
from delivery_ledger import DeliveryLedger
from datia_rates import fetch_datia_quote, format_datia_message, PriceDataNotReady

TZ = ZoneInfo('Asia/Kolkata')
SOURCE = 'https://trackliveprice.com'
API_GOLD = SOURCE + '/api/gold/{purity}.json'
API_SILVER = SOURCE + '/api/silver.json'
IBJA = 'https://www.ibjarates.com/'


def fetch_json(url):
    req = Request(url, headers={
        'User-Agent': 'DatiaGoldAlert/1.0 (daily low-volume personal rate notification)',
        'Accept': 'application/json'
    })
    try:
        with urlopen(req, timeout=20) as resp:
            if resp.status != 200:
                raise RuntimeError(f'Data provider HTTP {resp.status}')
            if int(resp.headers.get('Content-Length', '0')) > 5_000_000:
                raise RuntimeError('Data response too large')
            raw = resp.read(5_000_001)
            if len(raw) > 5_000_000:
                raise RuntimeError('Data response too large')
            return json.loads(raw.decode('utf-8'))
    except (HTTPError, URLError):
        raise RuntimeError('Could not retrieve market data') from None


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        num = Decimal(str(value))
        return num if num.is_finite() and num > 0 else None
    except (InvalidOperation, ValueError):
        return None


def validated_rows(doc, purity, today, metal='gold'):
    if (doc.get('metal') != metal or
        str(doc.get('purity')) != purity or
        doc.get('unit') != 'INR per gram' or
        doc.get('source') not in ('IBJA', 'India Bullion and Jewellers Association')):
        raise ValueError('Unexpected gold feed schema; refusing to send unchecked rate')
    rows = {}
    for entry in doc.get('rows', []):
        try:
            day = date.fromisoformat(entry['date'])
        except (KeyError, TypeError, ValueError):
            continue
        if day > today:
            continue
        pm = number(entry.get('pm') if entry.get('pm') is not None else entry.get('close'))
        # At 9 AM IST use the latest *confirmed PM* benchmark, never a future AM quote.
        if pm and ((metal == 'gold' and Decimal('1000') <= pm <= Decimal('100000')) or
                   (metal == 'silver' and Decimal('1') <= pm <= Decimal('10000'))):
            rows[day] = pm
    return rows


def latest_common_close(docs, today):
    a = validated_rows(docs['999'], '999', today)
    b = validated_rows(docs['916'], '916', today)
    silver = validated_rows(docs['silver'], '999', today, metal='silver')
    available = sorted(set(a).intersection(b).intersection(silver))
    if not available:
        raise ValueError('No matching 22K and 24K PM sessions')
    latest = available[-1]
    if (today - latest).days > 10:
        raise ValueError('Market source is older than 10 days; skipping stale rates')
    previous = available[-2] if len(available) >= 2 else None
    anchor = latest - timedelta(days=7)
    week = max((d for d in available if d <= anchor and (anchor - d).days <= 5),
               default=None)
    return latest, previous, week, {'999': a, '916': b, 'silver': silver}


def rupees(value):
    rounded = Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    neg = rounded < 0
    digits = str(abs(int(rounded)))
    if len(digits) > 3:
        rest, last3 = digits[:-3], digits[-3:]
        chunks = []
        while rest:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        digits = ','.join(reversed(chunks)) + ',' + last3
    return ('-' if neg else '') + '₹' + digits


def change(current, previous):
    if previous is None:
        return 'N/A'
    delta = (current - previous) * 10
    return ('+' if delta > 0 else '') + rupees(delta)


def short_change(now, old, multiplier=1):
    if old is None:
        return '—'
    delta = (now - old) * multiplier
    if delta == 0:
        return '→ Same'
    return ('🔺 ' if delta > 0 else '🔻 ') + rupees(abs(delta))


def build_message(docs, today=None):
    today = today or datetime.now(TZ).date()
    latest, previous, _week, history = latest_common_close(docs, today)
    age_days = (today - latest).days
    # At 09:00 IST it is normal to quote yesterday's official PM benchmark.
    # On Sunday/Monday the last Friday benchmark is also expected.
    normal_weekend_gap = today.weekday() in (6, 0) and latest.weekday() == 4 and age_days <= 3
    no_fresh_rate = age_days > 1 and not normal_weekend_gap

    lines = [
        '🌟 *Datia Gold & Silver Rates*',
        f'📅 Report: {today.strftime("%d %b %Y")}',
        f'📌 Latest IBJA rate: *{latest.strftime("%d %b %Y")} (PM)*',
        '',
    ]
    if no_fresh_rate:
        lines += ['⚠️ *Naya IBJA rate abhi available nahi hai.*', 'Neeche latest published rates hain, aaj ke naye rates nahi.', '']
    elif normal_weekend_gap:
        lines += ['ℹ️ Weekend ke baad naya IBJA benchmark abhi due hai.', '']

    for purity, label in (('999', '24K Gold'), ('916', '22K Gold')):
        now = history[purity][latest]
        old = history[purity].get(previous) if previous else None
        movement = ('  ' + short_change(now, old, 10)) if not no_fresh_rate and not normal_weekend_gap else ''
        lines.append(f'🟡 *{label}:* {rupees(now * 10)}/10g{movement}')
    silver = history['silver'][latest]
    old_silver = history['silver'].get(previous) if previous else None
    movement = ('  ' + short_change(silver, old_silver, 1000)) if not no_fresh_rate and not normal_weekend_gap else ''
    lines += [
        f'⚪ *Silver (999):* {rupees(silver * 1000)}/kg{movement}',
        '',
    ]
    if not no_fresh_rate and not normal_weekend_gap:
        lines.append('↕️ Change vs pichhle published closing rate')
    lines += [
        'ℹ️ India-wide IBJA benchmark; Datia shop rates alag ho sakte hain.',
        'GST aur making charges extra. Source: IBJA via TrackLivePrice.',
    ]
    return '\n'.join(lines)


def api_base():
    base = (os.environ.get('GREEN_API_BASE_URL') or 'https://api.green-api.com').rstrip('/')
    parsed = urlparse(base)
    host = parsed.hostname or ''
    valid = (host in ('green-api.com', 'greenapi.com') or
             host.endswith(('.green-api.com', '.greenapi.com')))
    if (parsed.scheme != 'https' or not valid or parsed.username or parsed.password or
        parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise ValueError('GREEN_API_BASE_URL must be an official GREEN-API HTTPS hostname')
    return base


def recipient(value):
    digits = value.strip().replace('+', '').replace(' ', '').replace('-', '')
    if not re.fullmatch(r'[1-9][0-9]{9,14}', digits):
        raise ValueError('Recipient must include country code and 10-15 digits')
    return digits + '@c.us'


def group_chat_id(value):
    """Validate a WhatsApp group chat ID obtained from GREEN-API getChats."""
    chat = value.strip()
    if (len(chat) > 45 or
        not re.fullmatch(r'[0-9]{10,25}(?:-[0-9]{4,15})?@g\.us', chat)):
        raise ValueError('GROUP_CHAT_ID must be a valid WhatsApp group chat ID ending @g.us')
    return chat


def destination_chats():
    """Two individual recipients plus an optional third group destination."""
    chats = [recipient(os.environ['RECIPIENT_1']),
             recipient(os.environ['RECIPIENT_2'])]
    if chats[0] == chats[1]:
        raise ValueError('Both individual recipients must be different')
    group = (os.environ.get('GROUP_CHAT_ID') or '').strip()
    if group:
        chats.append(group_chat_id(group))
    return chats


def call_api(url, payload=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = Request(url, data=data, method='POST' if data else 'GET',
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=25) as response:
            if response.status != 200:
                raise RuntimeError(f'GREEN-API returned HTTP {response.status}')
            return json.loads(response.read(100000).decode('utf-8'))
    except HTTPError as exc:
        raise RuntimeError(f'GREEN-API returned HTTP {exc.code}') from None
    except URLError:
        raise RuntimeError('GREEN-API network connection failed') from None


def in_delivery_window(now):
    """External scheduled checks may send from 11:00 to 18:45 IST."""
    return (11 <= now.hour <= 17 or (now.hour == 18 and now.minute <= 45))


def send(message, now=None, ledger=None):
    needed = ('GREEN_API_INSTANCE_ID', 'GREEN_API_TOKEN',
              'RECIPIENT_1', 'RECIPIENT_2')
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        raise ValueError('Missing GitHub Actions secrets: ' + ', '.join(missing))
    instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
    token = os.environ['GREEN_API_TOKEN'].strip()
    if not re.fullmatch(r'[0-9]{1,12}', instance) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('Malformed GREEN-API instance credentials')
    chats = destination_chats()
    prefix = f'{api_base()}/waInstance{instance}'
    state = call_api(f'{prefix}/getStateInstance/{token}')
    if state.get('stateInstance') != 'authorized':
        raise RuntimeError('GREEN-API is not authorized; no messages queued')

    if ledger is None:
        ledger = DeliveryLedger(os.environ.get('GITHUB_REPOSITORY'),
                                os.environ.get('GITHUB_TOKEN'))
    alert_day = (now or datetime.now(TZ)).date().isoformat()

    for index, chat in enumerate(chats, start=1):
        label = 'WhatsApp group' if chat.endswith('@g.us') else f'Recipient {index}'
        # Commit attempt BEFORE calling GREEN-API. Avoid resending on uncertain
        # timeout/crash: a claimed destination requires manual review.
        if not ledger.claim(alert_day, chat):
            print(f'{label}: already attempted today; skipping duplicate')
            continue
        try:
            result = call_api(f'{prefix}/sendMessage/{token}',
                              {'chatId': chat, 'message': message})
            message_id = result.get('idMessage')
            if not message_id:
                raise RuntimeError(f'{label}: API did not confirm queue acceptance')
            ledger.update(alert_day, chat, 'queued', message_id)
        except Exception:
            # An unsuccessful POST may still have reached the provider;
            # do not blindly retry and accidentally deliver duplicates.
            try:
                ledger.update(alert_day, chat, 'review')
            except Exception:
                pass
            raise
        print(f'{label}: accepted by API and receipt recorded (delivery unconfirmed)')


def main():
    now = datetime.now(TZ)
    external = os.environ.get('ENFORCE_DELIVERY_WINDOW', '').strip().lower() in ('1', 'true', 'yes')
    if (os.environ.get('GITHUB_EVENT_NAME') == 'schedule' or external) and not in_delivery_window(now):
        print('Automated trigger outside 11:00–18:45 IST; no messages sent')
        return

    # Do not claim the day's recipient ledger until BOTH Datia pages carry today's date.
    # Old IBJA benchmark feeds are intentionally not used for WhatsApp delivery.
    try:
        quote = fetch_datia_quote(now.date())
    except PriceDataNotReady as exc:
        print(f'DATIA RATES NOT READY: {exc}; no sends or daily ledger claims; later runs may retry')
        return
    message = format_datia_message(quote)
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    enabled = os.environ.get('SEND_ENABLED', '').strip().lower() == 'true'
    if dry or not enabled:
        print('PREVIEW ONLY — no WhatsApp messages sent')
        print(message)
        return
    send(message, now=now)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
