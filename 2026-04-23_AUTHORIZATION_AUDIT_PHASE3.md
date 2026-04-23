# 2026-04-23 Authorization Audit - Phase 3

## Summary
Performed another authorization-focused test expansion and fixed one additional critical impersonation risk.

## New Critical Fix

### API coupon detail impersonation prevention
- Endpoint: `/api/coupon_detail/<coupon_id>`
- Previous behavior: accepted `X-User-ID` request header and used it as identity source.
- Risk: authenticated/non-authenticated caller could potentially spoof another user identity in API context.
- Fix:
  - added `@login_required`
  - removed identity resolution from header
  - now relies on authenticated `current_user` only

File:
- `app/routes/coupons_routes.py`

## Extended Test Coverage Added

New file:
- `tests/test_authorization_extended.py`

Added checks:
1. Web coupon detail denies non-owner/non-shared user (`404`).
2. API coupon detail requires authenticated session.
3. API coupon detail cannot be bypassed using forged `X-User-ID`.
4. API coupon detail allows owner access.
5. API coupon usage update denies non-owner (`403`).

## Combined Validation Run

```bash
pytest -q tests/test_security_hardening.py tests/test_authorization_matrix.py tests/test_authorization_extended.py
```

Result:
- **15 passed**

## Current Isolation Confidence

- Cross-user data isolation now validated across:
  - core coupon/statistics API
  - coupon request access/delete
  - sharing viewer tracking/listing
  - coupon detail API and web detail
  - admin-only report endpoint

Status: **PASS**
