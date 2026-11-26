#!/usr/bin/env python3
"""Datia gold-rate WhatsApp alert. Python standard library only."""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo
from delivery_ledger import DeliveryLedger
from datia_rates import fetch_datia_quote, format_datia_message, PriceDataNotReady  # noqa: F401
from backup_rates import fetch_backup_quote, cross_check
from market_brief import fetch_market_quotes
from ai_market_insights import generate_ai_insights
from daily_message import build_daily_message
from owner_alert import send_owner_alert
from rate_history import HISTORY_PATH
from tips import tip_for
import rate_history
import weekly_chart

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


def _shape(value):
    """Describe a bad phone value without revealing it."""
    raw = value.strip()
    digits = re.sub(r'\D', '', raw)
    other = sorted({c for c in raw if not c.isdigit()} - set('+ -'))
    hints = [f'{len(digits)} digits']
    if not raw:
        hints = ['empty']
    if raw.endswith('@c.us') or raw.endswith('@g.us'):
        hints.append('has @ suffix')
    elif other:
        hints.append('other characters present')
    if digits.startswith('0'):
        hints.append('starts with 0')
    if len(digits) == 10:
        hints.append('looks like it is missing country code 91')
    return ', '.join(hints)


def recipient(value):
    digits = value.strip().replace('+', '').replace(' ', '').replace('-', '')
    if not re.fullmatch(r'[1-9][0-9]{10,14}', digits):  # 11-15: country code is required
        raise ValueError('Recipient must include country code (11-15 digits, e.g. 91XXXXXXXXXX) '
                         f'({_shape(value)})')
    return digits + '@c.us'


def group_chat_id(value):
    """Validate a WhatsApp group chat ID obtained from GREEN-API getChats."""
    chat = value.strip()
    if (len(chat) > 45 or
        not re.fullmatch(r'[0-9]{10,25}(?:-[0-9]{4,15})?@g\.us', chat)):
        raise ValueError('GROUP_CHAT_ID must be a valid WhatsApp group chat ID ending @g.us')
    return chat


def destination_chat(value):
    """A numbered destination may be either a phone number or WhatsApp group ID."""
    raw = value.strip()
    if raw.endswith('@g.us'):
        return group_chat_id(raw)
    return recipient(raw)


RECIPIENT_1_START = '2026-12-01'  # owner asked: RECIPIENT_1 (a group) receives from 1 Dec 2026


def recipient_1_start():
    return date.fromisoformat((os.environ.get('RECIPIENT_1_START') or RECIPIENT_1_START).strip())


def destination_chats(day=None, warnings=None):
    """Daily destinations: RECIPIENT_2, optional GROUP_CHAT_ID, and from
    RECIPIENT_1_START also RECIPIENT_1.

    A bad RECIPIENT_1 value never blocks the other two: it is skipped and reported
    in `warnings` (the caller alerts the owner).
    """
    day = day or datetime.now(TZ).date()
    chats = [destination_chat(os.environ['RECIPIENT_2'])]
    group = (os.environ.get('GROUP_CHAT_ID') or '').strip()
    if group:
        chats.append(group_chat_id(group))
    extra = (os.environ.get('RECIPIENT_1') or '').strip()
    if extra and day >= recipient_1_start():
        try:
            chat = destination_chat(extra)
            if chat in chats:
                raise ValueError('same as another destination')
            chats.append(chat)
        except ValueError as exc:
            msg = f'RECIPIENT_1 skip hua: {exc}'
            print(msg)
            if warnings is not None:
                warnings.append(msg)
    if len(chats) != len(set(chats)):
        raise ValueError('WhatsApp destination slots must all be different')
    return chats


def destination_label(chat):
    if chat == (os.environ.get('GROUP_CHAT_ID') or '').strip():
        return 'GROUP_CHAT_ID'
    raw = (os.environ.get('RECIPIENT_1') or '').strip()
    if raw and (chat == raw or chat == raw.replace('+', '').replace(' ', '') + '@c.us'):
        return 'RECIPIENT_1'
    return 'RECIPIENT_2'


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


def send(message, now=None, ledger=None, image=None, slot='daily', warnings=None):
    """Deliver to RECIPIENT_2 and the group, once per IST day per slot.

    slot='daily' sends text; slot='weekly' uploads `image` (PNG bytes) with
    `message` as caption. Each (day, chat, slot) is claimed in the ledger BEFORE
    calling GREEN-API, so a retry or second trigger never sends duplicates.
    """
    needed = ('GREEN_API_INSTANCE_ID', 'GREEN_API_TOKEN',
              'RECIPIENT_2')
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        raise ValueError('Missing GitHub Actions secrets: ' + ', '.join(missing))
    instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
    token = os.environ['GREEN_API_TOKEN'].strip()
    if not re.fullmatch(r'[0-9]{1,12}', instance) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('Malformed GREEN-API instance credentials')
    alert_date = (now or datetime.now(TZ)).date()
    chats = destination_chats(alert_date, warnings)
    prefix = f'{api_base()}/waInstance{instance}'
    state = call_api(f'{prefix}/getStateInstance/{token}')
    if state.get('stateInstance') != 'authorized':
        raise RuntimeError('GREEN-API is not authorized; no messages queued')

    if ledger is None:
        ledger = DeliveryLedger(os.environ.get('GITHUB_REPOSITORY'),
                                os.environ.get('GITHUB_TOKEN'))
    alert_day = (now or datetime.now(TZ)).date().isoformat()

    for chat in chats:
        label = destination_label(chat)
        if slot != 'daily':
            label += f' ({slot})'
        claim_key = chat if slot == 'daily' else f'{chat}#{slot}'
        # Commit attempt BEFORE calling GREEN-API. Avoid resending on uncertain
        # timeout/crash: a claimed destination requires manual review.
        if not ledger.claim(alert_day, claim_key):
            print(f'{label}: already attempted today; skipping duplicate')
            continue
        try:
            if image is None:
                result = call_api(f'{prefix}/sendMessage/{token}',
                                  {'chatId': chat, 'message': message})
            else:
                from weekly_chart import upload_with_fallback
                result = upload_with_fallback(api_base(), instance, token, chat, message,
                                              f'datia-gold-{alert_day}.png', image)
            message_id = result.get('idMessage')
            if not message_id:
                raise RuntimeError(f'{label}: API did not confirm queue acceptance')
            ledger.update(alert_day, claim_key, 'queued', message_id)
        except Exception:
            # An unsuccessful POST may still have reached the provider;
            # do not blindly retry and accidentally deliver duplicates.
            try:
                ledger.update(alert_day, claim_key, 'review')
            except Exception:
                pass
            raise
        print(f'{label}: accepted by API and receipt recorded (delivery unconfirmed)')


def _flag(name):
    return os.environ.get(name, '').strip().lower() in ('1', 'true', 'yes')


def get_quote(now, dry, notes, sleep=time.sleep):
    """Aaj Tak Datia first; if it fails, wait HOLD_MINUTES and retry; then backup city."""
    today = now.date()
    try:
        quote = fetch_datia_quote(today)
    except PriceDataNotReady as exc:
        print(f'DATIA SOURCE UNAVAILABLE/INVALID: {exc}')
        hold = int(os.environ.get('HOLD_MINUTES', '10') or 0)
        quote = None
        if hold > 0 and not dry:
            print(f'DATIA: holding {hold} min before one more try')
            sleep(hold * 60)
            try:
                quote = fetch_datia_quote(today)
                notes.append(f'Aaj Tak pehli baar fail hua ({exc}), {hold} min baad mil gaya.')
            except PriceDataNotReady as again:
                print(f'DATIA SOURCE still unavailable: {again}')
                exc = again
        if quote is None:
            try:
                quote = fetch_backup_quote(today)
                notes.append(f'Aaj Tak Datia fail ({exc}). Backup Goodreturns Bhopal ka rate bheja gaya.')
            except PriceDataNotReady as backup_exc:
                notes.append(f'Aaj Tak Datia fail ({exc}) aur backup bhi fail ({backup_exc}). '
                             'Message bina gold rate ke gaya.')
                print(f'BACKUP SOURCE UNAVAILABLE: {backup_exc}')
            return quote
    # Primary worked: best-effort cross-check against the backup city.
    try:
        warning = cross_check(quote, fetch_backup_quote(today))
        if warning:
            notes.append(warning)
            print('CROSS-CHECK: ' + warning)
        else:
            print('CROSS-CHECK: Datia 24K within range of Bhopal')
    except PriceDataNotReady as exc:
        print(f'CROSS-CHECK skipped: {exc}')
    return quote


def load_history(dry, notes):
    repo, token = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GITHUB_TOKEN')
    if not repo or not token:
        return None, {}, None
    try:
        store = DeliveryLedger(repo, token, path=HISTORY_PATH)
        history, sha = store.read()
        return store, history, sha
    except Exception as exc:
        notes.append(f'Rate history read nahi hui ({exc}); trend sirf aaj ki table se.')
        return None, {}, None


def build_report(now, preview, notes, sleep=time.sleep):
    """Everything the daily run sends, without sending. Shared with the owner test."""
    quote = get_quote(now, preview, notes, sleep)
    store, history, sha = load_history(preview, notes)
    merged = rate_history.merge(history, quote)
    trend = rate_history.stats(merged, 'gold24', quote['published']) if quote else None

    markets = fetch_market_quotes(now)
    if quote and quote['published'] == now.date():
        merged = rate_history.merge_market(merged, markets, now.date())
    invest = rate_history.investment(merged, quote, markets)
    insights = generate_ai_insights(quote, markets, now, trend=trend, invest=invest)
    message = build_daily_message(quote, trend, markets, now, ai_insights=insights,
                                  tip=tip_for(now.date()), invest=invest)

    weekly = None
    if weekly_chart.is_weekly_day(now.date()) or preview:
        caption = weekly_chart.weekly_caption(merged, now.date())
        image = weekly_chart.render_chart(merged, now.date()) if caption else None
        if caption and image:
            weekly = (caption, image)
        elif weekly_chart.is_weekly_day(now.date()):
            notes.append('Sunday chart nahi bana (history kam hai ya matplotlib missing).')
    return {'message': message, 'weekly': weekly, 'store': store,
            'history': history, 'merged': merged, 'sha': sha}


def already_sent(day, ledger=None):
    """True if every destination already has a claim (any status) for `day`."""
    ledger = ledger or DeliveryLedger(os.environ.get('GITHUB_REPOSITORY'),
                                      os.environ.get('GITHUB_TOKEN'))
    state, _ = ledger.read()
    rows = state.get(day.isoformat(), {})
    return all(ledger.key(chat) in rows for chat in destination_chats(day))


def in_backup_window(now):
    return 22 <= now.hour <= 23


def main(sleep=time.sleep):
    now = datetime.now(TZ)
    # External and manual workflow dispatches may run at any time. Never skip a
    # report solely because the scheduler was late or a source lagged. All rates
    # carry their actual publication dates. Claims are per IST day and recipient.
    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and not in_backup_window(now):
        # GitHub's own schedule is only a backup for cron-job.org and often runs hours
        # late. Outside the evening window it would send at the wrong time; skip.
        print(f'BACKUP SCHEDULE: {now.strftime("%H:%M")} IST is outside 22:00-23:59; skipping')
        return
    dry = _flag('DRY_RUN')
    enabled = os.environ.get('SEND_ENABLED', '').strip().lower() == 'true'
    preview = dry or not enabled
    notes = []
    if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and not preview:
        if already_sent(now.date()):
            print('BACKUP SCHEDULE: today already sent by the main trigger; nothing to do')
            return
        notes.append('cron-job.org ka trigger nahi aaya tha; GitHub backup schedule ne bheja. '
                     'cron-job.org job history aur GitHub token check karein.')

    report = build_report(now, preview, notes, sleep)
    message, weekly = report['message'], report['weekly']
    store, history, merged, sha = report['store'], report['history'], report['merged'], report['sha']

    if preview:
        print('PREVIEW ONLY — no WhatsApp messages sent')
        if os.environ.get('RECIPIENT_2'):
            start, warn = recipient_1_start(), []
            try:
                planned = [destination_label(c) + (' (group)' if c.endswith('@g.us') else ' (phone)')
                           for c in destination_chats(max(now.date(), start), warn)]
                print(f'DESTINATIONS from {max(now.date(), start)}: ' + ', '.join(planned)
                      + ('; ' + '; '.join(warn) if warn else ''))
            except ValueError as exc:
                print(f'DESTINATIONS check failed: {exc}')
        print(message)
        if weekly:
            with open('weekly_preview.png', 'wb') as handle:
                handle.write(weekly[1])
            print('\n--- Weekly caption (Sunday only; image saved as weekly_preview.png) ---')
            print(weekly[0])
        for note in notes:
            print('NOTE: ' + note)
        return

    if now.date() == recipient_1_start() and os.environ.get('RECIPIENT_1'):
        notes.append('Aaj se RECIPIENT_1 wale group ko bhi daily message jaana shuru hua.')
    # Log exactly what goes out, so a sent message can be audited later.
    print('MESSAGE SENT TO DESTINATIONS:\n' + message)
    try:
        send(message, now=now, warnings=notes)
    except Exception as exc:
        # Earlier destinations may already have gone; tell the owner, then fail the run.
        notes.append(f'Send mein error: {exc}')
        send_owner_alert('\n'.join('- ' + n for n in notes), now)
        raise

    if weekly and weekly_chart.is_weekly_day(now.date()):
        try:
            send(weekly[0], now=now, image=weekly[1], slot='weekly', warnings=[])
        except Exception as exc:
            notes.append(f'Sunday chart bhejne mein problem: {exc}')

    if store is not None and merged != history:
        try:
            store.write(rate_history.encode(merged), sha,
                        message='Update Datia rate history [skip ci]')
            print(f'HISTORY: saved {len(merged)} days')
        except Exception as exc:
            notes.append(f'Rate history save nahi hui ({exc}).')

    if notes:
        send_owner_alert('\n'.join('- ' + n for n in notes), now)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
