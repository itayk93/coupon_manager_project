# 2026-04-23 CouponMasterIL Remediation Plan

**Goal:** Fix code-quality issues first, then harden security, then verify with regression + security tests.

---

## Priority Order (as requested)

1. **Code fixes first** (stability/markup/assets/dependency hygiene)
2. **Security hardening second** (headers/cookies/rate-limit)
3. **Verification pass** (functional + security re-test)

---

## Phase 1 - Code Fixes (Day 0-1)

## P1.1 Fix malformed login `<head>` meta tags
**Owner:** Frontend template owner  
**Action:** Close broken `og:description` tag properly and validate generated HTML.

**Acceptance criteria:**
- HTML validator reports no broken tag in `<head>`.
- OpenGraph tags render correctly in link preview tools.

## P1.2 Fix broken links/assets
**Action list:**
- Create/restore `/privacy-policy` route/page.
- Add missing icon files under `/static/icons/`:
  - `apple-touch-icon.png`
  - `favicon-32x32.png`
  - `favicon-16x16.png`
  - `safari-pinned-tab.svg`
- Ensure manifest icon paths resolve to `200`.

**Acceptance criteria:**
- All above URLs return `200`.
- Browser tab icon and mobile add-to-home icon work.

## P1.3 Restore SEO baseline files
**Action list:**
- Add `/robots.txt`.
- Add `/sitemap.xml` (or dynamic sitemap route).

**Acceptance criteria:**
- Both endpoints return `200` and valid content.

## P1.4 Build-time dependency hygiene
**Action list:**
- Remove Tailwind CDN runtime injection from production templates.
- Move Tailwind to build pipeline (`tailwindcss` + compiled CSS artifact).
- Keep one Font Awesome version only.
- Review necessity of third-party widget (`website-widgets.pages.dev`); pin, self-host, or remove.

**Acceptance criteria:**
- No production dependence on `cdn.tailwindcss.com`.
- One icon lib version only.
- Third-party JS inventory approved and documented.

## P1.5 Canonical/OpenGraph sanitization
**Action:** Canonical and og:url must not include untrusted query parameters (`next`, arbitrary query strings).  
**Implementation hint:** build canonical from route path only.

**Acceptance criteria:**
- `/auth/login?next=https://evil.com` canonical still points to clean login URL.

---

## Phase 2 - Security Hardening (Day 1-2)

## P2.1 Add mandatory security headers at edge/app
**Target headers:**
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
- `Content-Security-Policy` (start strict, report-only if needed first)
- `X-Frame-Options: DENY` (or CSP `frame-ancestors 'none'`)
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` (disable unused capabilities)

**Acceptance criteria:**
- Header set present on all HTML/auth endpoints.

## P2.2 Harden cookies
**Action list:**
- Session cookie: add `Secure; HttpOnly; SameSite=Lax` (or `Strict` if flow permits).
- Consent cookie: add `Secure; SameSite=Lax`; if JS access not needed, add `HttpOnly`.
- Define explicit cookie max-age policy and domain/path scope.

**Acceptance criteria:**
- All auth/session cookies include `Secure` and `SameSite`.

## P2.3 Add auth abuse protection
**Action list:**
- Rate-limit login endpoint by IP + account identifier.
- Temporary lockout/backoff after failed attempts.
- Optional: CAPTCHA/challenge after threshold.
- Audit-log failed login bursts.

**Acceptance criteria:**
- Repeated failed login attempts trigger `429` or lockout/challenge.

## P2.4 Validate `next` redirect target allowlist
**Action:** Prevent open redirect by allowing only internal relative paths.  
**Rule:** reject absolute URLs, protocol-relative URLs, and malformed targets.

**Acceptance criteria:**
- `next=https://evil.com` cannot be used for post-login external redirect.

## P2.5 CSP rollout strategy
**Action list:**
- Inventory inline scripts.
- Move inline scripts to static files where possible.
- Introduce nonce/hash-based CSP for remaining inline scripts.
- Remove/limit third-party script origins.

**Acceptance criteria:**
- CSP enforced (not only report-only) without breaking login flow.

---

## Phase 3 - Verification & Regression (Day 2)

## P3.1 Functional smoke tests
- Login success/failure flow
- Register/forgot password flow
- Consent flow (`/auth/save_consent`)
- Auth-required route redirects

## P3.2 Security re-tests
- Header checklist on key routes
- Cookie flags re-check
- CSRF (missing token/referrer should fail)
- Brute-force (expect throttling)
- XSS reflection smoke tests
- SQLi error leakage smoke tests
- TLS + HTTPS redirect + HSTS verification

## P3.3 SEO/asset checks
- `robots.txt` and `sitemap.xml` live
- Canonical/OG do not reflect attacker query params
- No 404 on footer legal links and icon assets

---

## Suggested Implementation Sequence (Concrete)

1. Fix template markup + broken routes/assets.
2. Move Tailwind/CDN dependencies into deterministic build output.
3. Add security headers at reverse proxy/platform config.
4. Harden cookie flags in app config.
5. Implement login rate limit + lockout policy.
6. Lock down redirect `next` logic.
7. Roll out CSP in `Report-Only`, then enforce.
8. Execute full regression/security checklist and publish final report.

---

## Quick Win Checklist (Can be done today)

- [ ] Fix malformed `og:description` tag.
- [ ] Restore `/privacy-policy` page.
- [ ] Upload missing favicon/apple-touch/safari icons.
- [ ] Add `robots.txt` and `sitemap.xml`.
- [ ] Set `Secure` + `SameSite` on session cookie.
- [ ] Add baseline headers (`HSTS`, `XFO`, `nosniff`, `Referrer-Policy`).

---

## Definition of Done

1. No critical/high findings remain from this audit.
2. Security header/cookie baseline passes on all public/auth pages.
3. Login abuse controls are observable and logged.
4. Canonical/meta and legal/static assets return valid responses.
5. Regression checks pass without auth-flow breakage.

