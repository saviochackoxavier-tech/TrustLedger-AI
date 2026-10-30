# Terms of Service

**TrustLedger AI — Autonomous Vendor Escrow & Dispute Mediation**

Version 1.0 · Effective date: 2026-10-30

> **Deployment scope.** This document governs the TrustLedger AI reference
> implementation submitted for the PayPal AI Hackathon 2026. The service
> operates against **PayPal Sandbox** infrastructure and is provided for
> demonstration and evaluation. Nothing here constitutes licensed escrow,
> payment-services, or legal-advice activity.

---

## 1. Acceptance

By accessing or using TrustLedger AI ("the Service"), you ("Client", "Vendor",
or jointly "Party") agree to these Terms of Service ("ToS"). If you do not
agree, do not use the Service.

## 2. Definitions

- **Milestone** — an escrowed work agreement between a Client and a Vendor,
  recorded with a tamper-evident SHA-256 hash ("Escrow Hash").
- **Escrow Funds** — money captured from the Client and held pending
  settlement of a Milestone.
- **Delivery Proof** — evidence submitted by a Vendor that a Milestone was
  completed (artifact URL, commit reference, or delivery notes).
- **AI Mediation** — arbitration of a dispute or delivery audit performed by
  the Google Gemini model under the Service's strict JSON verdict contract.
- **TrustScore** — the AI-generated confidence value in [0.0, 1.0] attached to
  a Delivery Proof, used to route Milestones to automatic release, human
  review, or mediation.

## 3. The escrow flow and its bindings

1. **Agreement.** The Client defines a Milestone. On creation the Service
   seals the Escrow Hash over the frozen terms (title, amount, currency,
   parties). Any later modification invalidates the hash and **blocks payout**.
2. **Funding.** The Client funds the Milestone via the PayPal Orders API v2.
   Funds are captured and held; no Party may withdraw them unilaterally.
3. **Delivery.** The Vendor submits Delivery Proof. The Service scores the
   proof against the agreed terms (see §4).
4. **Settlement.** Escrow Funds are released to the Vendor, refunded to the
   Client, or split, as described in §4–§5. Each settlement is appended to a
   hash-chained audit ledger and the ledger entry is locked.

## 4. TrustScore auto-release and human review

- **Confidence ≥ 0.95** (and an AI decision of *release*): the Service
  dispatches a payout to the Vendor through the PayPal Payouts API. This is an
  **automated contractual act**: by submitting the Milestone, both Parties
  consent that a delivery audit at or above this threshold executes settlement
  without further human intervention.
- **Confidence 0.70–0.94:** funds are held and the Milestone is marked for
  human review. A human operator may approve release or escalate.
- **Confidence < 0.70:** the Milestone is flagged for full AI mediation
  (§5).
- **Non-release verdicts (refund / split) never move money automatically.**
  They always require human confirmation.

The thresholds are configuration values (`TRUSTSCORE_AUTO_RELEASE`,
`TRUSTSCORE_REVIEW`) and may be tuned by the operator; changes are not applied
retroactively to already-settled Milestones.

## 5. AI Mediation of disputes

Either Party may submit evidence logs. The AI mediator returns a strict JSON
verdict — `release`, `refund`, or `split` — with a confidence score and
reasoning. By submitting a dispute, the Parties agree that:

- the verdict settles the escrow disposition of the Milestone, **except** that
  either Party may request human review within **14 calendar days** of the
  verdict by contacting the operator;
- the AI's reasoning is generated from the submitted evidence only and does
  not constitute legal advice;
- the Service rejects malformed or non-conforming model output (fail-closed)
  rather than guessing a verdict.

## 6. Party obligations

- Provide accurate identity and payment references (PayPal payer/payee IDs).
- Submit only evidence you have the right to submit; do not submit third-party
  personal data, secrets, or unlawful content.
- Do not attempt to manipulate the AI mediator (prompt injection, fabricated
  evidence, or collusion). Attempts are logged in the audit ledger.
- Use the Service only for lawful transactions.

## 7. Fees

The hackathon build charges no fees. A production deployment may introduce a
platform fee, which will be disclosed before funding.

## 8. Liability

- The Service is provided **"as is"**, without warranties of any kind.
- To the maximum extent permitted by law, the operator's aggregate liability
  is limited to the amount of the Milestone in dispute.
- The operator is not liable for: PayPal outages or reversals, AI error where
  the verdict was subject to human review rights under §5, indirect or
  consequential damages, or losses caused by a Party's misrepresentation.

## 9. Suspension and termination

The operator may suspend a Party's access for suspected fraud, abuse, or
legal compliance reasons, and will wind down any open Milestone in accordance
with its then-current status.

## 10. Governing law

[To be completed by the deploying operator — e.g., the laws of the operator's
principal place of business.] Consumer rights under mandatory local law are
unaffected.

## 11. Changes

Material changes to these ToS will be published with a new version number and
effective date. Continued use after the effective date constitutes acceptance.

**Contact:** legal@trustledger.example (replace with the operator's address)
