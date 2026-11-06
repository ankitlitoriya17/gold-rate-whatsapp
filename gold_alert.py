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

TZ = ZoneInfo('Asia/Kolkata')
SOURCE = 'https://trackliveprice.com'
API_GOLD = SOURCE + '/api/gold/{purity}.json'
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


def validated_rows(doc, purity, today):
    if (doc.get('metal') != 'gold' or
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
        pm = number(entry.get('pm'))
        # At 9 AM IST use the latest *confirmed PM* benchmark, never a future AM quote.
        if pm and Decimal('1000') <= pm <= Decimal('100000'):
            rows[day] = pm
    return rows


def latest_common_close(docs, today):
    a = validated_rows(docs['999'], '999', today)
    b = validated_rows(docs['916'], '916', today)
    available = sorted(set(a).intersection(b))
    if not available:
        raise ValueError('No matching 22K and 24K PM sessions')
    latest = available[-1]
    if (today - latest).days > 10:
        raise ValueError('Market source is older than 10 days; skipping stale rates')
    previous = available[-2] if len(available) >= 2 else None
    anchor = latest - timedelta(days=7)
    week = max((d for d in available if d <= anchor and (anchor - d).days <= 5),
               default=None)
    return latest, previous, week, {'999': a, '916': b}


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


def build_message(docs, today=None):
    today = today or datetime.now(TZ).date()
    latest, previous, week, history = latest_common_close(docs, today)
    lines = [
        '*Datia Gold Rate Update*',
        f'IBJA benchmark closing rates — *{latest.strftime("%d %b %Y")} (PM)*',
        ''
    ]
    for purity, label in (('999', '24K (999)'), ('916', '22K (916)')):
        now = history[purity][latest]
        old = history[purity].get(previous) if previous else None
        seven = history[purity].get(week) if week else None
        lines += [
            f'*{label}*',
            f'1 gram: {rupees(now)} | 10 grams: {rupees(now * 10)}',
            f'Vs previous close ({previous.strftime("%d %b") if previous else "N/A"}): {change(now, old)} / 10g',
            f'7-day change (vs {week.strftime("%d %b") if week else "N/A"}): {change(now, seven)} / 10g',
            ''
        ]
    lines += [
        '*Note:* These are India-wide IBJA benchmark rates, not verified Datia jeweller retail quotes.',
        '3% GST and making charges excluded. The current day AM rate is not assumed at 9 AM.',
        f'Source: IBJA ({IBJA}) via TrackLivePrice ({SOURCE}/api/gold/999.json)',
        'Published rate date shown above; may change later in the day.'
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


def send(message):
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
    for index, chat in enumerate(chats, start=1):
        result = call_api(f'{prefix}/sendMessage/{token}',
                          {'chatId': chat, 'message': message})
        label = 'WhatsApp group' if chat.endswith('@g.us') else f'Recipient {index}'
        if not result.get('idMessage'):
            raise RuntimeError(f'{label}: API did not confirm queue acceptance')
        print(f'{label}: message queued (delivery not independently confirmed)')


def main():
    docs = {p: fetch_json(API_GOLD.format(purity=p)) for p in ('999', '916')}
    message = build_message(docs)
    dry = os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
    enabled = os.environ.get('SEND_ENABLED', '').strip().lower() == 'true'
    if dry or not enabled:
        print('PREVIEW ONLY — no WhatsApp messages sent')
        print(message)
        return
    send(message)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
