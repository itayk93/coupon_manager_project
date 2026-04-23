# 2026-04-23 CouponMasterIL Code + Security Audit

**Date:** 2026-04-23  
**Target:** https://couponmasteril.com/ (redirects to https://www.couponmasteril.com/)  
**Audit mode:** External black-box (HTTP/HTML/JS/CSS behavior + header/cookie security checks)

---

## Scope and Method

1. Code-quality checks (first): HTML validity, broken assets/links, client-side dependency hygiene, endpoint behavior, form handling.
2. Security checks (second): transport/TLS, security headers, cookie flags, CSRF behavior, basic injection probes, auth abuse signals, CORS/method exposure.
3. Evidence was captured under:
   - `/Users/itaykarkason/Python Projects/coupon_manager_project/audit_couponmasteril_2026-04-23`

---

## Executive Summary

### Overall status
- **Code quality:** ⚠️ Needs multiple fixes before hardening pass.
- **Security posture:** ⚠️ Core auth/CSRF behavior exists, but **critical browser-security headers and cookie hardening are missing**.

### High-impact findings
1. Missing critical security headers (`CSP`, `HSTS`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`).
2. Session cookie is missing `Secure` and `SameSite` attributes.
3. Multiple broken important assets/links in login page (`/privacy-policy`, favicon/apple-touch icons).
4. Production page relies on third-party JS/CSS CDNs without SRI (`tailwindcdn`, font-awesome, widget script).
5. No observable login throttling/lockout after repeated failed login attempts (12 attempts test).

---

## Findings - Code First

## C1. Broken HTML meta markup (login page)
**Severity:** Medium  
**Evidence:** `og:description` meta tag is missing closing `>` before next tag in fetched login HTML snapshot.  
**Impact:** Invalid head parsing, SEO/OpenGraph parsing inconsistencies.

## C2. Broken internal links/assets from login page
**Severity:** High  
**Evidence:**
- `GET /privacy-policy` => `404`
- `GET /static/icons/apple-touch-icon.png` => `404`
- `GET /static/icons/favicon-32x32.png` => `404`
- `GET /static/icons/favicon-16x16.png` => `404`
- `GET /static/icons/safari-pinned-tab.svg` => `404`

**Impact:** Broken legal link, poor trust/UX, incomplete PWA/browser icon experience.

## C3. `robots.txt` and `sitemap.xml` missing
**Severity:** Medium  
**Evidence:** both endpoints return `404`.  
**Impact:** Crawl/index quality and SEO operations degraded.

## C4. Client-side dependency hygiene issues
**Severity:** Medium  
**Evidence:**
- Tailwind loaded via `https://cdn.tailwindcss.com` in production.
- Font Awesome loaded twice with different major versions (`6.4.0` and `5.15.4`).
- External widget script from `website-widgets.pages.dev` loaded.

**Impact:** Larger attack surface, possible style/script conflicts, less deterministic builds.

## C5. Query string reflected into canonical/og:url
**Severity:** Low-Medium  
**Evidence:** `/auth/login?next=https://evil.com` appears in canonical and OpenGraph URL meta values.
**Impact:** SEO poisoning and metadata pollution risk. (No direct XSS observed; values are HTML-escaped.)

---

## Findings - Security

## S1. Missing browser security headers
**Severity:** Critical  
**Observed missing on `/auth/login`:**
- `Strict-Transport-Security`
- `Content-Security-Policy`
- `X-Frame-Options`
- `X-Content-Type-Options`
- `Referrer-Policy`
- `Permissions-Policy`

**Impact:** Increased exposure to clickjacking, content-type confusion, policy bypasses, and weaker transport hardening.

## S2. Weak cookie hardening
**Severity:** High  
**Evidence:**
- `session` cookie set with `HttpOnly; Path=/` but no `Secure`, no `SameSite`.
- `consent_id` cookie set without `HttpOnly`, `Secure`, or `SameSite`.

**Impact:** Higher risk for CSRF/session handling issues and cookie leakage on non-HTTPS misconfiguration paths.

## S3. Login brute-force protection not observed
**Severity:** Medium-High  
**Evidence:** 12 consecutive wrong login attempts did not return `429`/lockout/challenge indicators.

**Impact:** Increased credential-stuffing risk.

## S4. CSRF controls are present (good)
**Severity:** Positive finding  
**Evidence:**
- POST to `/auth/save_consent` without CSRF token => `400` (`The CSRF token is missing.`)
- With token but missing `Referer` => `400` (`The referrer header is missing.`)
- With valid token + referer => `200`

## S5. Basic injection probes
**Severity:** Informational  
**Results:**
- Reflected payload in email input is HTML-escaped (`<svg ...>` becomes `&lt;svg...&gt;`).
- SQLi-like login payloads did not expose DB errors.
- One classic `' OR 1=1--` payload triggered Cloudflare protection page (`403`/cookie challenge).

## S6. TLS baseline
**Severity:** Positive finding  
**Evidence:**
- TLS 1.2 and TLS 1.3 supported.
- TLS 1.0/1.1 handshakes unavailable.
- Valid certificate chain for `www.couponmasteril.com`.

---

## Test Matrix (Condensed)

| Test | Result | Notes |
|---|---|---|
| Root redirects | PASS | `couponmasteril.com -> www -> /auth/login` |
| HTML/asset integrity | FAIL | Broken legal/icons links, malformed meta |
| robots/sitemap | FAIL | Both 404 |
| Session/consent cookies flags | FAIL | Missing Secure/SameSite (+consent HttpOnly) |
| Security headers | FAIL | Major set missing |
| CSRF checks | PASS | Token + referer validation works |
| Login abuse throttling | FAIL/WARN | No observable lockout/rate-limit in 12 attempts |
| Basic XSS reflection check | PASS | Escaped in tested flow |
| Basic SQLi error leakage check | PASS | No DB error leakage observed |
| TLS protocols/cert | PASS | Modern baseline OK |

---

## Limitations

1. This is a black-box audit without source access.
2. Authenticated/business-logic tests (authorization boundaries, data isolation, admin role abuse) were not fully testable without a valid account/session and app internals.
3. No destructive testing was performed.

