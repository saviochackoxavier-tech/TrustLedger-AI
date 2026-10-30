# Legal & Compliance Package

Production-grade policy set for TrustLedger AI, structured so a deploying
operator can publish it with minimal edits (replace the example contact
addresses and the governing-law clause).

| Document | Covers |
|---|---|
| [`TERMS_OF_SERVICE.md`](TERMS_OF_SERVICE.md) | Escrow smart-contract terms, TrustScore auto-release consent, AI mediation binding effect, human-review rights, liability limits |
| [`PRIVACY_POLICY.md`](PRIVACY_POLICY.md) | Data categories collected, purposes and legal bases, processors (PayPal, Google), retention, GDPR/CCPA rights |
| [`DATA_PROTECTION.md`](DATA_PROTECTION.md) | GDPR/CCPA-aligned technical and organizational measures for financial transaction logs, DSR handling, breach playbooks |
| [`AI_DATA_USAGE.md`](AI_DATA_USAGE.md) | What is sent to Google Gemini, prompt-injection containment, model-training/retention position, human oversight |

## Honest scope statement

This is a **hackathon reference implementation** running against PayPal
Sandbox. It is not a licensed escrow agent, money transmitter, or law firm,
and these documents are templates prepared for evaluation — not executed
legal advice. Before any production deployment the operator must:

1. Have counsel review every document against the target jurisdiction.
2. Replace `legal@`, `privacy@`, `security@`, `ai-compliance@trustledger.example`.
3. Complete the governing-law clause and, if applicable, appoint an EU/UK representative.
4. Confirm the active Gemini API tier's data-use terms and configure the
   strictest available retention.
5. Register as required with the relevant financial regulator.

The engineering claims in these documents are testable against the codebase:
`trustledger/security.py` (sanitization), `trustledger/trustscore.py`
(thresholds, tamper check, audit chain), `trustledger/ai_agent.py` (strict
JSON whitelist), `config/settings.py` (env-only secrets, production hardening).
