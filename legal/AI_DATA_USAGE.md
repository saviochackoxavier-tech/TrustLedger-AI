# AI Data Usage Statement

**TrustLedger AI — how Google Gemini processes arbitration evidence**

Version 1.0 · Effective date: 2026-10-30

---

## 1. What the AI does

TrustLedger AI uses **Google Gemini** (default `gemini-2.0-flash`, configurable
via `GEMINI_MODEL`) for exactly two operations:

1. **Dispute mediation** — given the milestone terms and the evidence logs
   submitted by the parties, return a strict JSON verdict:
   `{"decision": "release" | "refund" | "split", "confidence": 0..1,
   "reasoning": "..."}`.
2. **Delivery audit (TrustScore)** — given the buyer's agreed terms and the
   vendor's delivery proof, return the same verdict shape plus
   `missing_items`.

No other user data is sent to Gemini. Model output never directly renders as
HTML — it is validated, sanitized, and escaped.

## 2. What is transmitted

| Sent | Not sent |
|---|---|
| Milestone title and agreed amount/currency | PayPal client ID/secret, API keys, tokens |
| Agreed scope text (buyer's description) | Card data, bank details, passwords |
| Evidence logs / delivery proof text (sanitized, capped at 8,000 chars) | Full database rows or unrelated milestones |
| Static system instructions and a JSON response schema | Server logs, IP addresses, browser fingerprints |

Prompts are assembled per request; the Service does **not** use a persistent
Gemini conversation, file upload, or corpus.

## 3. Prompt-injection containment

- Submitted evidence is wrapped in a delimited
  `<<<UNTRUSTED_DATA:…>>>` block and declared data-only in the system prompt.
- Triple-backtick fences are neutralized so evidence cannot close the block.
- Output is constrained by `responseSchema` **and** re-validated against a
  strict key/type/enum whitelist; unexpected fields, unknown decisions, or
  non-numeric confidence cause a hard failure (HTTP 502), never a settlement.

## 4. Retention and model training

- **Training:** the Service uses the Gemini API as a processor. Per Google's
  current Generative AI API terms, customer prompts and responses are **not
  used to train or improve Google's foundation models** when using the paid
  Gemini API; where a free tier applies, Google's applicable terms govern.
  The operator must confirm the active tier's terms before production use.
- **Abuse monitoring:** Google may log requests transiently for abuse
  detection under its terms; the operator enables the strictest available
  retention setting for the project.
- **Our storage:** evidence text, verdicts, confidence, and reasoning are
  stored in the Service's database for audit and the retention periods in
  `PRIVACY_POLICY.md`. Deleting a dispute record removes its evidence text;
  the hash-chained audit entry remains to keep settlement history verifiable.

## 5. Human oversight

- Automated settlement requires an AI `release` decision **and** confidence
  ≥ 0.95.
- The 0.70–0.94 band is **always** reviewed by a human before money moves.
- Below 0.70 the milestone escalates to mediation with full evidence.
- Either party may request human review of any AI verdict within 14 days
  (see `TERMS_OF_SERVICE.md` §5).

## 6. Accuracy and limitations

Gemini can be wrong in both directions. The Service mitigates this with low
temperature (0.2), a schema-constrained response, evidence-only prompting, and
the confidence bands above. AI reasoning is **not legal advice** and does not
create rights beyond the Terms of Service.

## 7. Data subject requests involving AI outputs

Where a party requests access or erasure, the stored verdict, confidence, and
reasoning are included in the export and are deletable subject to the
financial-record retention constraint. The Service cannot delete data already
processed by Google beyond the retention described in §4; the operator
escalates such requests to Google where applicable.

## 8. Configuration reference

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Credential; absent → AI routes return 502 and never guess |
| `GEMINI_MODEL` | Model identifier (default `gemini-2.0-flash`) |
| `TRUSTSCORE_AUTO_RELEASE` | Auto-payout confidence threshold (default 0.95) |
| `TRUSTSCORE_REVIEW` | Human-review threshold (default 0.70) |
| `TRUSTLEDGER_RELEASE_ASYNC` | `1` dispatches the payout on a daemon thread |

**Contact:** ai-compliance@trustledger.example
