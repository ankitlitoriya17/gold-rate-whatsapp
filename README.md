# Datia Gold Rates → WhatsApp

Daily 9:00 AM Asia/Kolkata scheduled alerts containing 24K (999) and 22K (916) published IBJA closing benchmark prices, daily change and seven-day comparison. Sends via the third-party **unofficial** GREEN-API WhatsApp integration to two opted-in recipients.

**Status on initial setup: preview mode.** WhatsApp sends do not happen unless the GitHub Actions variable `SEND_ENABLED` is explicitly set to `true` and a run is not a dry run. GREEN-API is not an approved Meta Cloud API and WhatsApp accounts may be restricted or disconnected. GitHub scheduled jobs can be delayed.

## Secure configuration

Go to **Settings → Secrets and variables → Actions → Repository secrets**, then create:
- `GREEN_API_INSTANCE_ID` — GREEN-API idInstance
- `GREEN_API_TOKEN` — GREEN-API apiTokenInstance (keep private)
- `GREEN_API_BASE_URL` — exact HTTPS apiUrl displayed in GREEN-API instance dashboard (e.g. `https://7107.api.greenapi.com`)
- `RECIPIENT_1` — first opted-in recipient's full international phone number (e.g. 919876543210)
- `RECIPIENT_2` — second distinct opted-in recipient's full international phone number

Never commit recipient numbers or an API token. GREEN-API free Developer tier is limited by number of chats and can change pricing or limits. Use a dedicated sender and ensure recipients consent to automated daily messages.

## Validate first

1. Confirm GREEN-API dashboard says **Authorized**.
2. Add the five Actions secrets.
3. Open **Actions → Daily Datia Gold WhatsApp → Run workflow**, choose `dry_run=true`.
4. Inspect logs: data source may fail or change schema. Any error blocks sending instead of inventing prices.
5. After a successful preview and confirming both recipients opted in, add the **Actions variable** `SEND_ENABLED=true` under **Settings → Secrets and variables → Actions → Variables**.
6. Run again with `dry_run=false` to attempt sending a test to *both* recipients; check actual delivery in WhatsApp.
7. Scheduled workflow uses cron `30 3 * * *` UTC, equivalent to 09:00 IST; GitHub may delay runs.

Data: https://trackliveprice.com/api/gold/999.json and https://trackliveprice.com/api/gold/916.json . Attribution required by TrackLivePrice. The national IBJA benchmark is **not** a confirmed Datia local jewellery retail price, and GST/making charges are excluded. At 9 AM latest confirmed prior PM price is usually the previous working day's; weekends and holidays reuse prior sessions. Old or unverified data is rejected.

## Local tests

```bash
python -m unittest discover -s tests -v
DRY_RUN=true python gold_alert.py
```

The previously configured ChatGPT reminder is separate and does not cause WhatsApp sends.

**Security:** The sender's instance ID alone is not a token; never share API token. For any leaked token rotate it immediately in GREEN-API and replace the GitHub secret.
