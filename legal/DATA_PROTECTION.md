# Data Protection & Security Addendum

**TrustLedger AI — GDPR / CCPA-aligned safeguards for financial transaction logs**

Version 1.0 · Effective date: 2026-10-30

---

## 1. Scope

This addendum documents the technical and organizational measures ("TOMs")
protecting personal data in the escrow lifecycle: milestone metadata,
transaction logs, dispute evidence, delivery proofs, AI verdicts, and the
audit ledger.

## 2. Data classification

| Class | Data | Handling |
|---|---|---|
| **Restricted** | `PAYPAL_CLIENT_SECRET`, `GEMINI_API_KEY`, `SECRET_KEY` | Environment only; never in code, logs, API responses, or the database |
| **Confidential** | Dispute evidence, delivery proofs, party references | Stored sanitized; access restricted to the operator |
| **Internal** | Transaction metadata, AI reasoning, audit hashes | Integrity-protected; operational access |
| **Public** | Aggregate dashboard metrics | Non-identifying counters only |

## 3. Technical measures implemented

1. **Secret isolation.** Credentials load exclusively from the environment via
   `python-dotenv`. There are no hardcoded fallbacks; `.env` is git-ignored and
   `.env.example` carries placeholders only. With `DEBUG=0` the application
   refuses to start without a real `SECRET_KEY`.
2. **Tamper-evident financial records.** Each Milestone seals a SHA-256 hash
   over its frozen commercial terms. Every settlement appends
   `sha256(previous_audit_hash | settlement_entry)` to a hash chain, so an
   altered historical record no longer reproduces the stored head. Payout is
   refused on hash mismatch and the refusal is itself logged.
3. **Input sanitization (anti-XSS / anti-injection).** All user text passes
   through a strict sanitizer: every HTML tag is stripped (allowlist: none),
   `<script>`/`<style>` bodies are dropped, C0 controls and Unicode
   bidi/zero-width characters are removed, and length is capped. Stored text
   is plain data; templates auto-escape on output.
4. **CSRF protection.** `CsrfViewMiddleware` is globally enabled. Milestone
   creation, funding, delivery proof, human release, and dispute submission
   are POST-only. PayPal's return URL is GET but requires a token that matches
   the stored order, so a forged link cannot force a capture.
5. **Least-privilege money movement.** No route mutates escrow state on GET.
   Settlement is idempotent: a settled vault cannot pay twice. Automated
   payouts require both `decision = release` and confidence at or above the
   configured threshold.
6. **Fail-closed AI.** Missing or malformed model output raises rather than
   defaulting to a settlement; model responses are validated against a strict
   key/type/enum whitelist, and confidence is clamped to `[0,1]`.
7. **Transport security (production profile).** With `DEBUG=0`: HTTPS
   redirect, HSTS (1 year, subdomains, preload), secure session/CSRF cookies,
   `X-Content-Type-Options: nosniff`, referrer policy `same-origin`, and
   clickjacking protection.
8. **Minimization.** No authentication secrets, government identifiers, or
   payment card numbers are collected — PayPal handles card data; the Service
   stores only order/capture/payout references.

## 4. Organizational measures

- Access to production data limited to named operators; no shared accounts.
- Secrets rotated on personnel change and at least every 90 days.
- Change control: code review before deployment; migrations reviewed.
- Incident response: triage within 24h; supervisory-authority notification
  within 72h where GDPR Art. 33 applies; affected-party notification where
  the risk is high.
- Processor due diligence for PayPal and Google, including sub-processor lists.

## 5. Data subject request handling

1. Verify identity without collecting excess data.
2. Locate records by party reference (`client_ref` / `vendor_ref`).
3. Export, rectify, or restrict. **Erasure constraint:** financial records
   within the statutory retention period are restricted rather than deleted;
   audit-chain entries are retained in pseudonymized form so the chain stays
   verifiable.
4. Respond within 30 days (extendable once by two months for complex cases,
   with notice).

## 6. Breach scenarios and responses

| Scenario | Response |
|---|---|
| Credential leak | Revoke and rotate at PayPal/Google; audit API logs for abuse; notify if personal data was exposed |
| Database exfiltration | Contain, preserve forensic copy, assess scope, notify per Art. 33/34 and CCPA §1798.82 |
| Hash-chain mismatch | Freeze affected vaults, block payouts, investigate tampering, log the incident |
| Model provider incident | Follow the processor's breach notice; assess whether evidence text was affected |

## 7. CCPA/CPRA specifics

- **No sale or sharing** of personal information for cross-context behavioral
  advertising.
- Categories collected, purposes, and retention are disclosed in
  `PRIVACY_POLICY.md`.
- Rights: know, delete, correct, opt out of sale/sharing, limit use of
  sensitive PI, and non-discrimination. Requests via privacy@trustledger.example.

## 8. Review

This addendum is reviewed at least annually, and after any material change to
the escrow flow, processors, or model configuration.

**Owner:** Security & Compliance · security@trustledger.example
