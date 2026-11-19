#!/usr/bin/env python3
"""Private alerts to the owner (RECIPIENT_2, a personal number) when something needs attention.

Used by gold_alert.py (data/delivery problems), by the workflow's failure step
and by the nightly watchdog. Never raises: an alert failure must not break the
group delivery. In dry runs alerts are only printed.

CLI: python owner_alert.py "message"          send a one-off alert
     python owner_alert.py --watchdog         alert if today's send is missing
     python owner_alert.py --test             test alert + chart to the owner only
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Kolkata')


def _dry():
    return (os.environ.get('DRY_RUN', '').strip().lower() in ('1', 'true', 'yes')
            or os.environ.get('SEND_ENABLED', '').strip().lower() != 'true')


def send_owner_alert(text, now=None):
    """Returns True if GREEN-API accepted the alert."""
    now = now or datetime.now(TZ)
    body = f'🚨 *Gold bot alert* · {now.strftime("%d %b %I:%M %p")}\n{text}'
    run_url = _run_url()
    if run_url:
        body += f'\nRun: {run_url}'
    if _dry():
        print('OWNER ALERT (dry run, not sent):\n' + body)
        return False
    try:
        import gold_alert  # local import: avoid circular import at module load
        owner = owner_chat()
        instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
        token = os.environ['GREEN_API_TOKEN'].strip()
        url = f'{gold_alert.api_base()}/waInstance{instance}/sendMessage/{token}'
        result = gold_alert.call_api(url, {'chatId': owner, 'message': body})
        ok = bool(result.get('idMessage'))
        print('OWNER ALERT: sent' if ok else 'OWNER ALERT: not confirmed by API')
        return ok
    except Exception as exc:
        print(f'OWNER ALERT: failed ({type(exc).__name__}: {exc})')
        return False


def owner_chat():
    """Owner's personal chat. OWNER_RECIPIENT if set, else RECIPIENT_2.

    Must be a phone number: gold_alert.recipient() rejects group IDs, so a private
    alert can never land in a group.
    """
    import gold_alert
    value = (os.environ.get('OWNER_RECIPIENT') or os.environ.get('RECIPIENT_2') or '').strip()
    return gold_alert.recipient(value)


def _run_url():
    server = os.environ.get('GITHUB_SERVER_URL')
    repo = os.environ.get('GITHUB_REPOSITORY')
    run = os.environ.get('GITHUB_RUN_ID')
    return f'{server}/{repo}/actions/runs/{run}' if server and repo and run else ''


def watchdog(now=None, ledger=None):
    """Alert if today's group/recipient send has no 'queued' receipt."""
    now = now or datetime.now(TZ)
    day = now.date().isoformat()
    try:
        import gold_alert
        from delivery_ledger import DeliveryLedger
        ledger = ledger or DeliveryLedger(os.environ.get('GITHUB_REPOSITORY'),
                                          os.environ.get('GITHUB_TOKEN'))
        state, _ = ledger.read()
        rows = state.get(day, {})
        missing = []
        for chat in gold_alert.destination_chats():
            row = rows.get(ledger.key(chat))
            status = row.get('status') if row else 'not attempted'
            if status != 'queued':
                label = 'Group' if chat.endswith('@g.us') else 'RECIPIENT_2'
                missing.append(f'{label}: {status}')
    except Exception as exc:
        missing = [f'watchdog could not read state ({type(exc).__name__})']
    if missing:
        send_owner_alert('Aaj ka gold update nahi gaya ya confirm nahi hua:\n- '
                         + '\n- '.join(missing)
                         + '\nCheck karein: cron-job.org history, GitHub token expiry, Actions run.',
                         now)
        return False
    print('WATCHDOG: today delivered to all destinations')
    return True


def send_test(now=None):
    """Owner-only end-to-end test: one text alert, then a chart image. Never the group."""
    import gold_alert
    import rate_history
    import weekly_chart
    from datia_rates import fetch_datia_quote
    now = now or datetime.now(TZ)
    if _dry():
        raise RuntimeError('SEND_ENABLED must be true and DRY_RUN false for the owner test')
    ok_text = send_owner_alert('TEST: ye sirf aapke number par aaya hai. Asli alerts isi tarah aayenge.', now)
    quote = fetch_datia_quote(now.date())
    history = rate_history.merge({}, quote)
    caption = weekly_chart.weekly_caption(history, quote['published'])
    image = weekly_chart.render_chart(history, quote['published'])
    if not caption or not image:
        raise RuntimeError('chart could not be built')
    owner = owner_chat()
    instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
    token = os.environ['GREEN_API_TOKEN'].strip()
    media = weekly_chart.media_base(gold_alert.api_base())
    print(f'OWNER TEST: uploading chart via media host {media.split("//", 1)[1]}')
    result = weekly_chart.upload_file(f'{media}/waInstance{instance}/sendFileByUpload/{token}',
                                      owner, '🧪 *TEST — Sunday chart preview*\n\n' + caption,
                                      'datia-gold-test.png', image)
    ok_image = bool(result.get('idMessage'))
    print(f'OWNER TEST: text {"accepted" if ok_text else "FAILED"}, chart {"accepted" if ok_image else "FAILED"}')
    if not (ok_text and ok_image):
        raise RuntimeError('owner test not fully accepted')


if __name__ == '__main__':
    if sys.argv[1:] == ['--watchdog']:
        watchdog()
    elif sys.argv[1:] == ['--test']:
        send_test()
    elif len(sys.argv) > 1:
        send_owner_alert(' '.join(sys.argv[1:]))
    else:
        print(__doc__)
