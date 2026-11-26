[![Daily Datia Gold WhatsApp](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml/badge.svg)](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml)
[![Verify](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/validate-gold.yml/badge.svg)](https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/validate-gold.yml)

# Datia Gold Update → WhatsApp

A short Hinglish **10:00 PM IST daily gold update** for a WhatsApp group, plus a **Sunday chart recap**. Every number comes from a dated source; the optional AI lines may only repeat numbers they were given.

## What the group receives

**Daily** (`daily_message.py`)

| Section | Content |
|---|---|
| Headline | One line: today's move and what stands out (lowest/highest in N days, N-day streak, or a ≥1.5% "bada move") |
| Rates | 24K / 22K / 18K per 10g with change, per-gram price, silver per kg and per 10g |
| Investment nazar | ₹1 lakh = X g 24K (vs 7 days ago), Gold:Silver ratio, 7-day Gold vs Nifty (once stored) |
| Trend · 24K | 7-day and 30-day change, range over the stored window, up/down streak |
| Jewellery estimate | 10g 22K bill range assuming 8–15% making + 3% GST |
| Markets | Nifty/Sensex; USD/INR + Brent; international gold ($/oz) + Gold BeES ETF |
| AI ki nazar se | 2 lines (insight + what to watch tomorrow) from Groq, checked for invented numbers and advice words |
| Kaam ki baat | A buyer tip on Mon/Wed/Fri (`tips.py`) |

**Sunday** (`weekly_chart.py`): a 30-day 24K gold and silver chart (PNG) with a week summary caption.

**Owner alerts** (`owner_alert.py`) go privately to the owner's number (`RECIPIENT_2`, or `OWNER_RECIPIENT` if set). Group IDs are rejected for alerts, so they can never land in a group.

## Data flow

```
cron-job.org 22:00 IST ─▶ workflow_dispatch ─▶ gold_alert.py
  1. IBJA benchmark (3 tries) ──fail──▶ wait HOLD_MINUTES (10) ─▶ retry ──fail──▶ Goodreturns Bhopal (backup)
  2. Goodreturns Bhopal 24K cross-check (>4% gap or opposite direction ⇒ owner alert)
  3. data/rate_history.json  ◀── merge today + IBJA's dated series (gaps heal themselves)
  4. Yahoo Finance markets, Groq AI (optional), tip of the day
  5. Send to RECIPIENT_2 + GROUP_CHAT_ID (ledger: once per day per destination)
  6. Sunday: chart + caption (separate "weekly" ledger slot)
  7. Any problem (fallback used, gold missing, history save failed…) ⇒ one alert to the owner
GitHub schedule 22:50/23:20 IST ─▶ backup trigger, sends only if today is still missing
watchdog.yml 23:37 / 08:07 / 11:37 IST ─▶ checks the last due day, alerts the owner once
workflow step failed ⇒ alert to the owner
```

Backup rows (other city) are stored but excluded from trend maths.

## Configuration

**Settings → Secrets and variables → Actions**

| Name | Kind | Purpose |
|---|---|---|
| `GREEN_API_INSTANCE_ID`, `GREEN_API_TOKEN` | secret | GREEN-API instance |
| `GREEN_API_BASE_URL` | secret | apiUrl from the GREEN-API dashboard, e.g. `https://7107.api.greenapi.com` |
| `GREEN_API_MEDIA_URL` | secret, optional | mediaUrl for the Sunday image. Default: apiUrl with `api` → `media` |
| `RECIPIENT_2` | secret | Daily destination (phone with country code, or group ID `…@g.us`) |
| `GROUP_CHAT_ID` | secret, optional | Group ID from GREEN-API `getChats` (not the invite link) |
| `RECIPIENT_1` | secret | Third destination (a group), active from 2026-12-01 (`RECIPIENT_1_START`) |
| `LEDGER_KEY` | secret, optional | Key for hashing destinations in the public ledger. Default: `GREEN_API_TOKEN` |
| `OWNER_RECIPIENT` | secret, optional | Personal number for alerts if it should differ from `RECIPIENT_2` |
| `GROQ_API_KEY` | secret, optional | AI lines (`openai/gpt-oss-120b`, falls back to `gpt-oss-20b`) |
| `SEND_ENABLED` | variable | Must be `true` for any WhatsApp send |

The cron-job.org setup is in [CRON_JOB_ORG_SETUP.md](CRON_JOB_ORG_SETUP.md).

## Runbook — "aaj message nahi aaya / galat aaya"

1. **Check your WhatsApp (owner number).** The bot alerts you with the reason and a link to the run.
2. **Actions → latest "Datia Gold WhatsApp" run → "Build gold report" step.** Look for these log lines:
   - `DATIA FETCH attempt N failed …: HTTP 403 / TimeoutError / bot block`: the source blocked or timed out. One bad day is normal. If it repeats daily, Aaj Tak is blocking GitHub; consider a different source.
   - `CROSS-CHECK: … fark`: Datia and Bhopal differ by more than 4%. Open both sites and compare.
   - `AI INSIGHTS: … rejected`: the AI wrote an unverified number, so the message went without AI lines. This is safe.
   - `GREEN-API is not authorized`: re-scan the QR code in the GREEN-API dashboard.
3. **No run at all today?** (watchdog alert "not attempted"):
   - Check cron-job.org job history. A 401 means the GitHub token expired, so make a new fine-grained token (Actions: read/write on this repo only) and paste it into the cron-job.org header.
   - Set a calendar reminder 1 week before the token's expiry date.
4. **Resend after a failure:** delete today's entry for that destination in `.delivery-state.json` (only if it is `attempting`/`review` and the message really did not arrive), then run the workflow with `dry_run=false`.
5. **Preview anything safely:** run the workflow with `dry_run=true`. It never sends and uploads the Sunday chart as the `weekly-chart-preview` artifact.

## Duplicate protection

Before each GREEN-API call, the script commits an `attempting` claim to `.delivery-state.json`, keyed by an HMAC of the destination (so numbers cannot be brute-forced from this public repo) and the slot (`daily` or `weekly`). After `idMessage`, the claim becomes `queued`. Later triggers on the same day skip claimed destinations. An uncertain send stays in `review` and is never auto-resent. Queue acceptance is not proof of delivery.

## Development

```bash
pip install -r requirements.txt ruff
ruff check .
python -m unittest discover -s tests -v
DRY_RUN=true python gold_alert.py          # prints the message, saves weekly_preview.png
```

Dependabot updates GitHub Actions and pip dependencies monthly. `validate-gold.yml` runs lint, tests and a no-send preview on every push.

## Sources and limits

- Gold/silver: IBJA benchmark (ibjarates.com), national rate without GST/making; Datia shop rates are usually a little higher. Aaj Tak Datia was dropped on 2026-11-26 (it lagged one day). Backup: Goodreturns Bhopal.
- Markets: Yahoo Finance chart endpoint (unofficial, may be delayed, not licensed for redistribution). Treat it as a personal preview.
- WhatsApp: GREEN-API is unofficial. The sending number can be restricted by WhatsApp, so use a dedicated number with consenting recipients.
- No message is investment advice.
