# 2026-07-08 Multipass Hourly Automation Fix

## Summary

Implemented and deployed the Multipass hourly automation repair so Supabase is the scheduling source, Flask remains the update orchestrator, GitHub Actions scraping is resilient to per-card failures, and admin failure alerts are configured.

## Code Changes

- Main repo `coupon_manager_project`
  - Added Supabase Edge Function orchestrator at `supabase/functions/trigger-multipass-update/index.ts`.
  - Added hourly Supabase `pg_cron` migration at `supabase/migrations/20260708051804_schedule_hourly_multipass_update.sql`.
  - Added RLS migration for scheduler tables at `supabase/migrations/20260707161802_enable_rls_on_scheduler_tables.sql`.
  - Added Multipass failure alert email helper and connected it to dispatch, GitHub, artifact, DB processing, summary email, and background thread failure paths.
  - Updated Flask cron background thread handling to send alerts on unexpected crashes.
  - Documented required env/secrets in `README.md`.
  - Ignored `supabase/.temp/`.

- `scrape_multipass` repo
  - Updated `scrape.js` so each card is processed independently.
  - Added `failures.json` output for failed cards.
  - Kept `transactions.json` backward compatible.
  - Changed the workflow to upload artifacts with `if: always()`.
  - Removed the GitHub scheduled trigger so Supabase is the hourly schedule source.

## Git Commits Pushed

- `coupon_manager_project`
  - `7f0018e` - `Fix hourly Multipass automation`
  - `fe11ee8` - `Use anon key for Supabase Multipass cron`

- `scrape_multipass`
  - `fe77729` - `Harden Multipass scraper workflow`

All commits were pushed to `origin/main`.

## Production Configuration Updated

- Render service: `coupon_manager_project`
  - Service ID: `srv-d2m1ncripnbc738p65u0`
  - Workspace fixed to `Itay's workspace`
  - Deployed commit: `fe11ee824db26f291aeb65f3e8e119344dede860`
  - Added/verified:
    - `DATABASE_URL`
    - `SECRET_KEY`
    - `FLASK_ENV=production`
    - `SESSION_COOKIE_SECURE=true`
    - `CRON_API_TOKEN`
    - `GITHUB_TOKEN`
    - `MULTIPASS_ALERT_EMAILS`

- Supabase project: `MaCoupon`
  - Project ref: `dugjsiyenazpsoiyduuz`
  - Deployed function: `trigger-multipass-update`
  - Applied migrations:
    - `20260707161802_enable_rls_on_scheduler_tables.sql`
    - `20260708051804_schedule_hourly_multipass_update.sql`
  - Verified extensions:
    - `pg_cron`
    - `pg_net`
    - `supabase_vault`
  - Verified cron job:
    - `hourly-multipass-update`
    - schedule: `0 * * * *`
    - active: `true`
  - Added/verified secrets:
    - `APP_BASE_URL`
    - `CRON_API_TOKEN`
    - `GITHUB_TOKEN`
    - `SUPABASE_ANON_KEY`
  - Added Vault secrets:
    - `multipass_update_function_url`
    - `supabase_anon_key`

No secret values were written to the repo.

## Verification Run

1. Deployed Render successfully.
2. Invoked Supabase Edge Function manually.
3. Verified it called:
   - `https://www.couponmasteril.com/api/cron/update_multipass?mode=full`
4. First valid run returned:
   - `All coupons correspond to recent data (filtered by smart logic)`
5. For an end-to-end test, coupon ID `706` was marked as recently viewed so it would pass `should_update_coupon`.
6. Re-ran the Supabase function.
7. Flask started a full update for coupon code `1231622963438`.
8. GitHub Actions run created:
   - Run ID: `28920427536`
   - Status: `completed`
   - Conclusion: `success`
9. Verified artifact:
   - name: `transactions-json`
   - created: `2026-07-08T05:44:24Z`
10. Verified Flask logs:
    - found run `28920427536`
    - detected completion
    - read `transactions.json`
    - processed card `1231622963438`
11. Verified DB update:
    - coupon ID `706`
    - `last_scraped = 2026-07-08 05:44:43 UTC`

No user summary email was sent during the test because the coupon had no positive usage delta; that matches the existing summary-email logic. Failure alert recipients are configured through `MULTIPASS_ALERT_EMAILS`.

## Notes

- Existing cron-job.org calls are still visible in Render logs. They were not disabled because this environment does not have access to the cron-job.org account.
- Supabase hourly cron is active and should now be the canonical scheduler.
- `scrape_multipass/.env` remains untracked and was intentionally not committed.
