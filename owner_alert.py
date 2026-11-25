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
from datetime import date, datetime, timedelta
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


DEADLINE = (22, 45)  # by 22:45 IST the day's message should be out (trigger ~22:00 + hold)


def report_day(now):
    """The day whose send should be finished: today after 22:45 IST, else yesterday.

    GitHub often runs scheduled jobs hours late (after midnight); checking 'today'
    then would raise a false alarm for a day that has not started sending yet.
    """
    if (now.hour, now.minute) >= DEADLINE:
        return now.date()
    return now.date() - timedelta(days=1)


def watchdog(now=None, ledger=None):
    """Alert once if the report day's sends have no 'queued' receipt."""
    now = now or datetime.now(TZ)
    day = report_day(now).isoformat()
    try:
        import gold_alert
        from delivery_ledger import DeliveryLedger
        ledger = ledger or DeliveryLedger(os.environ.get('GITHUB_REPOSITORY'),
                                          os.environ.get('GITHUB_TOKEN'))
        state, _ = ledger.read()
        rows = state.get(day, {})
        missing = []
        for chat in gold_alert.destination_chats(date.fromisoformat(day)):
            row = rows.get(ledger.key(chat))
            status = row.get('status') if row else 'not attempted'
            if status != 'queued':
                label = {'GROUP_CHAT_ID': 'Group', 'RECIPIENT_1': 'RECIPIENT_1 group'}.get(
                    gold_alert.destination_label(chat), 'RECIPIENT_2')
                missing.append(f'{label}: {status}')
    except Exception as exc:
        missing = [f'watchdog could not read state ({type(exc).__name__})']
        ledger = None
    if not missing:
        print(f'WATCHDOG: {day} delivered to all destinations')
        return True
    # Several watchdog runs per day: alert only once per report day.
    if ledger is not None:
        try:
            if not ledger.claim(day, WATCHDOG_SLOT):
                print(f'WATCHDOG: {day} problem already alerted')
                return False
        except Exception as exc:
            print(f'WATCHDOG: could not record alert ({type(exc).__name__}); alerting anyway')
    send_owner_alert(f'{day} ka gold update nahi gaya ya confirm nahi hua:\n- '
                     + '\n- '.join(missing)
                     + '\nCheck karein: cron-job.org job history (401 = GitHub token expire), '
                       'job enabled hai ya nahi, aur Actions run.', now)
    return False


WATCHDOG_SLOT = 'watchdog-alert'


def send_test(now=None, target='owner'):
    """Manual send of tonight's real daily message.

    target='owner': message (TEST label) + chart to the owner only.
    target='group': just the daily message to GROUP_CHAT_ID, on explicit manual request.
    Not recorded in the daily ledger.
    """
    import gold_alert
    import weekly_chart
    now = now or datetime.now(TZ)
    if _dry():
        raise RuntimeError('SEND_ENABLED must be true and DRY_RUN false for the owner test')
    notes = []
    # preview=True: no hold/wait, no history write, no ledger. Same message builder as live.
    report = gold_alert.build_report(now, True, notes)
    instance = os.environ['GREEN_API_INSTANCE_ID'].strip()
    token = os.environ['GREEN_API_TOKEN'].strip()
    send_url = f'{gold_alert.api_base()}/waInstance{instance}/sendMessage/{token}'
    if target == 'group':
        group = gold_alert.group_chat_id(os.environ['GROUP_CHAT_ID'])
        result = gold_alert.call_api(send_url, {'chatId': group, 'message': report['message']})
        print(report['message'])
        print('GROUP SEND: ' + ('accepted' if result.get('idMessage') else 'FAILED'))
        if not result.get('idMessage'):
            raise RuntimeError('group send not accepted')
        return
    owner = owner_chat()
    text = gold_alert.call_api(
        send_url, {'chatId': owner, 'message': '🧪 *TEST — sirf aapko, group ko nahi*\n\n' + report['message']})
    ok_text = bool(text.get('idMessage'))
    ok_image = False
    if report['weekly']:
        caption, image = report['weekly']
        result = weekly_chart.upload_with_fallback(
            gold_alert.api_base(), instance, token, owner,
            '🧪 *TEST — Sunday chart preview*\n\n' + caption, 'datia-gold-test.png', image)
        ok_image = bool(result.get('idMessage'))
    print(report['message'])
    for note in notes:
        print('NOTE: ' + note)
    print(f'OWNER TEST: daily message {"accepted" if ok_text else "FAILED"}, '
          f'chart {"accepted" if ok_image else "FAILED"}')
    if not (ok_text and ok_image):
        raise RuntimeError('owner test not fully accepted')


if __name__ == '__main__':
    if sys.argv[1:] == ['--watchdog']:
        watchdog()
    elif sys.argv[1:] == ['--test']:
        send_test()
    elif sys.argv[1:] == ['--send-group']:
        send_test(target='group')
    elif len(sys.argv) > 1:
        send_owner_alert(' '.join(sys.argv[1:]))
    else:
        print(__doc__)
