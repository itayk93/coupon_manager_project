# 2026-04-23 Authorization Audit - Phase 2

## Scope
Extended authorization and data-isolation validation across additional sensitive routes after Phase 1 hardening.

## New Findings Fixed

1. `coupon_request_detail` (requests routes)
- Issue: user could open another user's coupon request details by ID.
- Fix: owner/admin check added.

2. `delete_coupon_request` overlap path in coupons routes
- Issue: route collision path (`/delete_coupon_request/<id>`) existed in multiple modules; coupons version had weaker behavior and broken redirect endpoint.
- Fix:
  - owner/admin authorization check
  - fixed redirect target to `marketplace.marketplace`

3. Sharing viewers endpoints (`sharing_routes`)
- Issue: `track_coupon_viewer` and `get_active_viewers` accepted any logged-in user for arbitrary coupon IDs.
- Risk: potential information disclosure (who is viewing which coupon).
- Fix: added unified access check (owner OR accepted shared access only).

4. Admin email report endpoint
- Issue: `/admin/email/view-full-report` lacked auth decorators.
- Fix: added `@login_required` + `@admin_required`.

## New Tests Added

File: `tests/test_authorization_matrix.py`

Covered scenarios:
- Non-owner denied on coupon request detail.
- Non-owner denied on coupon request deletion.
- Non-owner denied on coupon viewer tracking/listing.
- Shared-access user allowed on coupon viewer tracking.
- Admin email full report endpoint protected (unauthenticated denied, non-admin denied, admin allowed).

## Validation Run

```bash
pytest -q tests/test_security_hardening.py tests/test_authorization_matrix.py
```

Result:
- **10 passed**

## Data Isolation Status

Status after Phase 2: **PASS**
- User A cannot read/act on User B protected resources in tested flows.
- Viewer and request-based cross-user leakage vectors are blocked.
