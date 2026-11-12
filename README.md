[![Daily Datia Gold WhatsApp](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml/badge.svg)](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml)

# Datia Daily Investor Brief → WhatsApp

One compact **9:30 PM IST investor brief**, built from dated Datia-local indicative Gold (24K/22K) and Silver quotations, plus four best-effort market indicators: **Nifty 50, Sensex, USD/INR, and Brent crude futures**. The system records a maximum of one accepted send per IST report date and destination. Gold and Silver always show their real source publication dates; other assets show their quote timestamps. No forecast, buy signal or fabricated figure is included. Sends via the third-party **unofficial** GREEN-API WhatsApp integration to two opted-in individual recipients and optionally one opted-in WhatsApp group.

**Safety:** WhatsApp sends do not happen unless the GitHub Actions variable `SEND_ENABLED` is explicitly set to `true` and a run is not a dry run. GREEN-API is not an approved Meta Cloud API and WhatsApp accounts may be restricted or disconnected. GitHub scheduled jobs can be delayed.

## Secure configuration

Go to **Settings → Secrets and variables → Actions → Repository secrets**, then create:
- `GREEN_API_INSTANCE_ID` — GREEN-API idInstance
- `GREEN_API_TOKEN` — GREEN-API apiTokenInstance (keep private)
- `GREEN_API_BASE_URL` — exact HTTPS apiUrl displayed in GREEN-API instance dashboard (e.g. `https://7107.api.greenapi.com`)
- `RECIPIENT_1` — first destination: opted-in international phone number (e.g. 919876543210), or a GREEN-API group ID ending `@g.us`
- `RECIPIENT_2` — second distinct destination: international phone number or a GREEN-API group ID ending `@g.us`
- `GROUP_CHAT_ID` (optional) — third distinct destination, a group ID ending `@g.us` returned by GREEN-API `getChats` (not the group invite link). The sending WhatsApp account must be a member and group members should consent.

The free Developer tariff counts a group as one chat; a setup of one individual plus two groups also uses all three permitted chats. You may need to clear/disconnect other active chats based on provider behavior. Never commit recipient numbers or an API token. GREEN-API free Developer tier is limited by number of chats and can change pricing or limits. Use a dedicated sender and ensure recipients consent to automated daily messages.

## Validate first

1. Confirm GREEN-API dashboard says **Authorized**.
2. Add the five Actions secrets.
3. Open **Actions → Datia Gold WhatsApp (External Trigger) → Run workflow**, choose `dry_run=true`.
4. Inspect logs: an unavailable Datia price or market indicator is marked `unavailable`. A daily report is still prepared and dispatched, even if some or all feeds fail, with no invented prices.
5. After a successful preview and confirming both recipients opted in, add the **Actions variable** `SEND_ENABLED=true` under **Settings → Secrets and variables → Actions → Variables**.
6. Run again with `dry_run=false` to attempt sending a test to *both* recipients; check actual delivery in WhatsApp.
7. **Only cron-job.org automatically dispatches the workflow**. Set the primary to **21:30 IST (9:30 PM)** and optional backup to **22:30 IST**, removing earlier 8:30 PM jobs. GitHub internal `on.schedule` is disabled.

**Datia Gold/Silver sources:** https://www.aajtak.in/commodity/gold-rate-in-datia-today and https://www.aajtak.in/commodity/silver-rate-in-datia-today . **Market snapshot source:** Yahoo Finance chart data (unofficial/no SLA), https://finance.yahoo.com/ . These are **indicative city quotations**, not verified individual-jeweller transaction prices nor IBJA benchmark quotes. GST and making charges are excluded. The old TrackLivePrice/IBJA parsing code remains for backward-compatible tests only and is **not used by live WhatsApp sends**. Messages use the **latest retrievable published rate for each metal**, clearly dated; stale sources do not block a report. An inaccessible, malformed or future-dated *Datia rate* source is shown as `unavailable` and does **not** block the daily summary; prices are never invented. If Yahoo Finance is blocked, affected market metrics read `unavailable` too. Index metrics are last published quotes, while USD/INR and Brent can be active at 9:30 PM and must not be described as market closes.

## Market-data rights and reliability

The Yahoo Finance chart endpoint is unofficial. The publisher states that its financial data **must not be redistributed** and may be delayed; before operating or scaling a WhatsApp investor broadcast, obtain an appropriately licensed feed or permission. The current integration is a technical preview, not a guarantee of redistribution rights, data quality, or long-term API access. Market provider failure is nonfatal, and every figure is explicitly dated/timestamped.

## Local tests

```bash
python -m unittest discover -s tests -v
DRY_RUN=true python gold_alert.py
```

The previously configured ChatGPT reminder is separate and does not cause WhatsApp sends.

**Security:** The sender's instance ID alone is not a token; never share API token. For any leaked token rotate it immediately in GREEN-API and replace the GitHub secret.

## Replacing one phone number with another WhatsApp group

The workflow supports **up to three distinct destinations**. If you currently have two people plus one group and want **one person plus two groups**, change only the intended numbered destination secret:

1. Add the GREEN-API sender WhatsApp account to the new group.
2. Open the GREEN-API instance **API / GetChats** method and run it using the existing authorized instance (official docs: https://green-api.com/en/docs/api/service/GetChats/). Find the entry with `"type": "group"` and the matching group name, and copy its `id` ending `@g.us`. Do not use an invite link.
3. Open GitHub repository **Settings → Secrets and variables → Actions → Repository secrets**. Replace the value of `RECIPIENT_1` or `RECIPIENT_2`—whichever phone you intend to stop messaging—with the new group ID. Leave `GROUP_CHAT_ID` unchanged for the existing group.
4. Ensure the two groups have different IDs. Run a `dry_run=true` preview (never sends). The next external cron trigger sends once per destination per IST day, subject to prior ledger claims. Do not manually trigger live sends until the destination configuration is verified.

Do not commit group IDs, personal numbers, GREEN-API credentials or tokens to Git. GitHub Actions secrets cannot be viewed after saving, but can be replaced. The API response with the group list may include private chat names: do not post the complete response publicly.

## Optional WhatsApp group

1. Add the sending WhatsApp account to the target group and get the group's consent for daily gold updates.
2. In GREEN-API documentation, use the `getChats` method (from the authorized instance) to find the **group chat ID** ending in `@g.us`; do not use the group's invite link or name.
3. Use the private GitHub Actions secret `GROUP_CHAT_ID` to add or replace the third group destination; or put a group ID into `RECIPIENT_1` / `RECIPIENT_2` to replace a phone recipient. No further code changes required.
4. Run a `dry_run=true` preview, then (only if sending is already authorized and enabled) run a live test and confirm it appears in the group.
5. To stop sending to the group, delete the `GROUP_CHAT_ID` secret; the other two configured destinations continue working.

## Automatic retries and duplicate protection

The cron-job.org HTTP job should dispatch at **20:17 / 21:17 / 22:17 IST** with `inputs.enforce_window=true` and `dry_run=false`. The GitHub workflow deliberately has **no internal schedule**. Automatic external dispatches run at any time, without a hardcoded time cutoff; edit the cron-job.org job to send in the evening for better same-day coverage. Runs share one concurrency group to prevent overlap. Manual GitHub `Run workflow` remains available.

When live sending is enabled, GitHub Actions uses its built-in `GITHUB_TOKEN` with `contents: write` to record daily destination attempts in `.delivery-state.json` in this private repository. Each entry uses a SHA-256-derived identifier, not a raw phone number or group ID.

- Before contacting GREEN-API, the script commits an **attempting** claim for the particular recipient or group.
- After GREEN-API returns `idMessage`, it commits a **queued** receipt.
- Later retries skip any claimed destination that day, even if a prior run was interrupted.
- If either Datia page is missing, fails to parse, or is future-dated, or GREEN-API is unauthorized, no claims are created and later runs may retry. A dated old quote is allowed and labelled. No outdated IBJA data is substituted.
- If an outbound send has an uncertain result, the claim remains under **review** and is **not automatically resent**. Check WhatsApp/provider journal before resetting it manually.
- API queue acceptance is **not guaranteed WhatsApp delivery**.

Because GitHub and WhatsApp cannot commit a single atomic transaction, exactly-once delivery cannot be guaranteed. The workflow prioritizes avoiding duplicate messages over retrying uncertain sends. GitHub itself can still drop all scheduled attempts.

Preview runs do not create or change delivery state. The ledger is created at the first live send. Do not remove a daily state entry unless a resend is intended.
