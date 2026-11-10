# Free cron-job.org external trigger for Datia WhatsApp rates

This guide configures cron-job.org to dispatch the existing private GitHub Actions workflow. **Important November 2026 update:** Gold and Silver must BOTH have today's dated Aaj Tak Datia city quotation before an alert is sent; earlier 9 AM cron jobs should be moved to the new hours. An old external trigger before 11 AM now exits without sending. It does not move GREEN-API credentials or recipient phone numbers to cron-job.org.

**Schedule:** one cron-job.org job, at **11:17, 12:17, 13:17** every day in **Asia/Kolkata**, as the **only automatic scheduling source**; GitHub's internal `on.schedule` entries have been removed. The same daily ledger is used regardless of which trigger fires. A dispatch may return HTTP 200 before the workflow has actually completed; check the linked Actions run for delivery attempt and queue status.

## 1. Fine-grained GitHub personal access token

1. Open https://github.com/settings/personal-access-tokens/new and create a **fine-grained** token.
2. Resource owner: `ankitlitoriya17`.
3. Repository access: **Only select repositories** → `gold-rate-whatsapp`.
4. Repository permissions: **Actions: Read and write** (Metadata: Read is automatic). Do not add Contents, Secrets, Administration or other permissions.
5. Choose the shortest expiration you can manage; renew before expiry. Copy it once, and **do not commit it or paste it in chat**.

This PAT is only for the cron-job.org → GitHub workflow-dispatch HTTP call. Do not use the GREEN-API token here. cron-job.org necessarily stores the token in its request-header configuration; treat the cron-job.org account as sensitive and enable MFA.

## 2. Create one HTTP job in https://console.cron-job.org/

| Field | Value |
| --- | --- |
| Title | Datia Gold & Silver WhatsApp |
| URL | `https://api.github.com/repos/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml/dispatches` |
| Method | `POST` |
| Timezone | `Asia/Kolkata` |
| Hours | `11`, `12`, `13` |
| Minutes | `17` |
| Days | Every day (including weekends) |
| Timeout | 30 seconds, if configurable |
| Status notification | Enable HTTP failure notifications |

Use custom HTTP headers (separate name/value entries):

| Header name | Value |
| --- | --- |
| `Authorization` | `Bearer YOUR_FINE_GRAINED_GITHUB_TOKEN` |
| `Accept` | `application/vnd.github+json` |
| `Content-Type` | `application/json` |
| `X-GitHub-Api-Version` | `2022-11-28` |

Set the request **body** to:

```json
{
  "ref": "main",
  "inputs": {
    "dry_run": "false",
    "enforce_window": "true"
  },
  "return_run_details": true
}
```

GitHub returns **200** with a run URL when `return_run_details=true`, or **204** without the URL otherwise. Either confirms *dispatch accepted*, **not** WhatsApp delivered.

If the console offers to record request headers and responses, **disable recording request headers** to reduce token exposure. Never include the token in the URL/query/body. cron-job.org's terms advise against storing sensitive data there; use narrow token permissions, MFA, and rotate on suspicion of compromise.

## 3. Test without WhatsApp delivery

For a safe test, **temporarily** set `inputs.dry_run` in the job body to `"true"` and keep `enforce_window` `"true"`. At times outside the 11:00–13:45 IST window, the guarded job exits before building the preview. You can also test the request itself and look for GitHub's 200 response and resulting `workflow_dispatch` run; it won't send a WhatsApp message when `dry_run=true`.

After verification, restore `dry_run=false`, save the job and confirm the console shows the next three scheduled times. This sets future live sends; the repository variable `SEND_ENABLED=true` must also be set. Schedule-triggered runs use the same server-side recipient-day ledger, suppressing duplicates.

## 4. Verify and debug

1. cron-job.org job history should show **HTTP 200** or **HTTP 204**. HTTP 401 means an invalid/expired token, HTTP 403 permissions, HTTP 404 repo/workflow inaccessible, HTTP 422 invalid body or ref.
2. GitHub Actions `Daily Datia Gold WhatsApp` should show a `workflow_dispatch` run. A success at this layer is not proof of message delivery.
3. The run's job log may report `already attempted today; skipping duplicate`, or `accepted by API and receipt recorded`.
4. The private `.delivery-state.json` stores hashed per-recipient-day attempt state. If a send is recorded as `review`, do not reset without checking whether it reached WhatsApp.

GitHub workflow (manual or external dispatch only): https://github.com/ankitlitoriya17/gold-rate-whatsapp/actions/workflows/daily-gold-whatsapp.yml

## Notes

- No external scheduler can guarantee on-time delivery. cron-job.org can be delayed and GitHub Actions may be unavailable.
- The 11:00–13:45 local time window is enforced for automatic external dispatches. Late jobs do not send outdated alerts outside the window.
- For live testing outside the delivery window, use GitHub's manual workflow instead of temporarily removing the guard.
- Tokens with expiration need routine rotation or subsequent scheduled calls will fail.
- GREEN-API is an unofficial WhatsApp integration with account restrictions and delivery uncertainty.
