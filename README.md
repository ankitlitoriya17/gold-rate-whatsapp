# Datia Gold Rates → WhatsApp

Daily 9:00 AM Asia/Kolkata scheduled short Hinglish alerts containing IBJA benchmark closing prices for 24K gold (per 10g), 22K gold (per 10g), and silver 999 (per kg), with changes from the previous closing session. Sends via the third-party **unofficial** GREEN-API WhatsApp integration to two opted-in individual recipients and optionally one opted-in WhatsApp group.

**Status on initial setup: preview mode.** WhatsApp sends do not happen unless the GitHub Actions variable `SEND_ENABLED` is explicitly set to `true` and a run is not a dry run. GREEN-API is not an approved Meta Cloud API and WhatsApp accounts may be restricted or disconnected. GitHub scheduled jobs can be delayed.

## Secure configuration

Go to **Settings → Secrets and variables → Actions → Repository secrets**, then create:
- `GREEN_API_INSTANCE_ID` — GREEN-API idInstance
- `GREEN_API_TOKEN` — GREEN-API apiTokenInstance (keep private)
- `GREEN_API_BASE_URL` — exact HTTPS apiUrl displayed in GREEN-API instance dashboard (e.g. `https://7107.api.greenapi.com`)
- `RECIPIENT_1` — first opted-in recipient's full international phone number (e.g. 919876543210)
- `RECIPIENT_2` — second distinct opted-in recipient's full international phone number
- `GROUP_CHAT_ID` (optional) — WhatsApp group ID ending in `@g.us` returned by GREEN-API `getChats` (not the group invite link). Group must include the sender and members should consent to the daily messages.

The free Developer tariff counts a group as one chat; two individuals plus one group use all three permitted chats. You may need to clear/disconnect other active chats based on provider behavior. Never commit recipient numbers or an API token. GREEN-API free Developer tier is limited by number of chats and can change pricing or limits. Use a dedicated sender and ensure recipients consent to automated daily messages.

## Validate first

1. Confirm GREEN-API dashboard says **Authorized**.
2. Add the five Actions secrets.
3. Open **Actions → Daily Datia Gold WhatsApp → Run workflow**, choose `dry_run=true`.
4. Inspect logs: data source may fail or change schema. Any error blocks sending instead of inventing prices.
5. After a successful preview and confirming both recipients opted in, add the **Actions variable** `SEND_ENABLED=true` under **Settings → Secrets and variables → Actions → Variables**.
6. Run again with `dry_run=false` to attempt sending a test to *both* recipients; check actual delivery in WhatsApp.
7. Scheduled attempts run at **09:00, 09:17, 09:34, 09:51, 10:08 and 11:00 IST**. GitHub can still delay or drop them.

Data: https://trackliveprice.com/api/gold/999.json, https://trackliveprice.com/api/gold/916.json and https://trackliveprice.com/api/silver.json . Attribution required by TrackLivePrice. The national IBJA benchmark is **not** a confirmed Datia local jewellery retail price, and GST/making charges are excluded. At 9 AM latest confirmed prior PM price is usually the previous working day's; weekends and holidays reuse prior sessions. Old or unverified data is rejected.

## Local tests

```bash
python -m unittest discover -s tests -v
DRY_RUN=true python gold_alert.py
```

The previously configured ChatGPT reminder is separate and does not cause WhatsApp sends.

**Security:** The sender's instance ID alone is not a token; never share API token. For any leaked token rotate it immediately in GREEN-API and replace the GitHub secret.

## Optional WhatsApp group

1. Add the sending WhatsApp account to the target group and get the group's consent for daily gold updates.
2. In GREEN-API documentation, use the `getChats` method (from the authorized instance) to find the **group chat ID** ending in `@g.us`; do not use the group's invite link or name.
3. Add the ID to the private GitHub Actions secret `GROUP_CHAT_ID`. No code changes or other secret changes required.
4. Run a `dry_run=true` preview, then (only if sending is already authorized and enabled) run a live test and confirm it appears in the group.
5. To stop sending to the group, delete the `GROUP_CHAT_ID` secret; the two individual recipients continue working.

## Automatic retries and duplicate protection

The daily workflow has six chances: **09:00 / 09:17 / 09:34 / 09:51 / 10:08 / 11:00 IST**. A scheduled event arriving after 11:20 IST is skipped. Runs share one concurrency group to prevent overlap.

When live sending is enabled, GitHub Actions uses its built-in `GITHUB_TOKEN` with `contents: write` to record daily destination attempts in `.delivery-state.json` in this private repository. Each entry uses a SHA-256-derived identifier, not a raw phone number or group ID.

- Before contacting GREEN-API, the script commits an **attempting** claim for the particular recipient or group.
- After GREEN-API returns `idMessage`, it commits a **queued** receipt.
- Later retries skip any claimed destination that day, even if a prior run was interrupted.
- If price retrieval fails or GREEN-API is unauthorized, no claims are created, so later runs may retry.
- If an outbound send has an uncertain result, the claim remains under **review** and is **not automatically resent**. Check WhatsApp/provider journal before resetting it manually.
- API queue acceptance is **not guaranteed WhatsApp delivery**.

Because GitHub and WhatsApp cannot commit a single atomic transaction, exactly-once delivery cannot be guaranteed. The workflow prioritizes avoiding duplicate messages over retrying uncertain sends. GitHub itself can still drop all scheduled attempts.

Preview runs do not create or change delivery state. The ledger is created at the first live send. Do not remove a daily state entry unless a resend is intended.
