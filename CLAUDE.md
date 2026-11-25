# Notes for agents working on this repo

Daily Datia gold-rate WhatsApp bot (GitHub Actions + GREEN-API). Read README.md for the flow.

## Must-remember rules

1. **This repo is PUBLIC.** Never commit or print phone numbers, group IDs, tokens or plain
   (unkeyed) hashes of them. `.delivery-state.json` keys are HMAC-SHA256 of the destination,
   keyed with `LEDGER_KEY` if that secret exists, else `GREEN_API_TOKEN` (`delivery_ledger.py`).
   Git history was rewritten on 2026-11-19 to remove old unkeyed hashes. GitHub may still show
   old commits by direct SHA until it garbage-collects them. Don't reintroduce plain hashes.

2. **Changing `GREEN_API_TOKEN` (or `LEDGER_KEY`) changes every ledger key.** On that day the
   ledger no longer recognises today's sends, so a second trigger or manual live run WILL send
   a duplicate to the group. Do not run the daily workflow live again that day. Either change the
   token right after the day's send and wait for the next day, or re-key with the migration in
   `delivery_ledger.py` (`rekey()`, run via a one-off workflow with the old key still available).

## Other facts

- Triggers: cron-job.org dispatch at ~22:00 IST is the main trigger. On 2026-11-25 it never
  fired (no run at all). GitHub `schedule` in the daily workflow is a backup: it only sends if
  it starts 22:00-23:59 IST and today's sends are missing (`already_sent`), else exits.
- GitHub runs schedules hours late (seen 5-8 h). The watchdog therefore checks `report_day`
  (yesterday if before 22:45 IST), runs 3 times, and alerts once per day (ledger slot
  `watchdog-alert`).

- `RECIPIENT_1` holds a group ID. Owner decision (2026-11-26): it receives the daily message and
  Sunday chart from **2026-12-01** (`RECIPIENT_1_START` in `gold_alert.py`). A bad value is
  skipped with an owner alert, never blocking the other destinations. It was dropped on
  2026-11-13, possibly due to GREEN-API free-plan chat limits; if sends to it fail, check that.
- Owner alerts go to `RECIPIENT_2`, which is the owner's personal number (or `OWNER_RECIPIENT`
  if set). Alerts must never go to a group.
- GREEN-API media host (`*.media.greenapi.com`) does not resolve for this instance. Uploads fall
  back to the API host (`weekly_chart.upload_with_fallback`).
- This session cannot create Actions secrets via API; ask the owner to add them in Settings.
- Test without touching the group: `Manual send` workflow with target=owner, or the daily
  workflow with `dry_run=true`. target=group sends to the group immediately; use it only when the owner asks.
- Before pushing: `ruff check .` and `python -m unittest discover -s tests`.
