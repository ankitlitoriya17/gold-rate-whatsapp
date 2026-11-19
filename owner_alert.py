#!/usr/bin/env python3
"""Private alerts to the owner (RECIPIENT_1) when something needs attention.

Used by gold_alert.py (data/delivery problems), by the workflow's failure step
and by the nightly watchdog. Never raises: an alert failure must not break the
group delivery. In dry runs alerts are only printed.

CLI: python owner_alert.py "message"          send a one-off alert
     python owner_alert.py --watchdog         alert if today's send is missing
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
        owner = gold_alert.recipient(os.environ['RECIPIENT_1'])
        instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
        token = os.environ['GREEN_API_TOKEN'].strip()
        url = f'{gold_alert.api_base()}/waInstance{instance}/sendMessage/{token}'
        result = gold_alert.call_api(url, {'chatId': owner, 'message': body})
        ok = bool(result.get('idMessage'))
        print('OWNER ALERT: sent' if ok else 'OWNER ALERT: not confirmed by API')
        return ok
    except Exception as exc:
        print(f'OWNER ALERT: failed ({type(exc).__name__})')
        return False


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


if __name__ == '__main__':
    if sys.argv[1:] == ['--watchdog']:
        watchdog()
    elif len(sys.argv) > 1:
        send_owner_alert(' '.join(sys.argv[1:]))
    else:
        print(__doc__)
