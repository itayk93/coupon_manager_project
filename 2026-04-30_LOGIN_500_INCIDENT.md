# Login 500 Incident Notes

Date: 2026-04-30

## Symptom

The production site returned `500 Internal Server Error` immediately after submitting the login form.

Observed flow:

- `GET /auth/login` loaded normally
- `POST /auth/login` returned `500`
- The error was visible both on desktop and mobile

## What We Verified

- The login user existed in the database.
- The stored password was a normal `pbkdf2:sha256` hash, not encrypted with `ENCRYPTION_KEY`.
- Local login against the same Supabase database succeeded and redirected to `/index`.
- Local verification with the same credentials returned `302 /index`.

## What Changed During Investigation

- Added null-safe handling for coupon and dashboard rendering.
- Hardened the login route so unexpected failures return a controlled flash + redirect instead of a hard 500.
- Added a small login-route log line to make future debugging easier.

## Likely Root Cause

The most likely explanation was an environment or deployment mismatch on production rather than bad credentials:

- local app + same DB worked
- production still served `500` until redeploy / runtime refresh

In other words, this did not look like a password encoding problem.

## Relevant Code Paths

- Login route: [`app/routes/auth_routes.py`](/Users/itaykarkason/Python%20Projects/coupon_manager_project/app/routes/auth_routes.py)
- User password hashing: [`app/models.py`](/Users/itaykarkason/Python%20Projects/coupon_manager_project/app/models.py)

## If This Happens Again

1. Check whether production is actually running the latest `main` commit.
2. Reproduce locally against the same database and same credentials.
3. Inspect the login POST logs before assuming a password or schema issue.
4. Confirm the user has a local password hash if they are not Google-only.

## Outcome

The login flow now succeeds locally for the reported account and redirects to the dashboard.
