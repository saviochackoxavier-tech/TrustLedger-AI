"""
TrustLedger AI — Core Data Models
=================================
Autonomous Vendor Escrow & Dispute Mediator.

Design notes:
- SQLite is the default backend (zero configuration), so no
  PostgreSQL/JSONField-specific features are relied upon.
- Every money field is stored as DecimalField(max_digits=10, decimal_places=2)
  to avoid binary float rounding errors in escrow accounting.
- Status fields are constrained via TextChoices so invalid transitions
  fail loudly at the application layer.
- `escrow_hash` is a SHA-256 fingerprint of the milestone agreement terms,
  recalculated and compared before payout.
- `audit_hash` is a hash-chained ledger: each settlement appends
  sha256(previous_hash | entry), so any rewritten history is detectable.
"""

import hashlib
import hmac
import uuid

from django.db import models


class Milestone(models.Model):
    """A single escrowed payment milestone agreed between client and vendor."""

    class Status(models.TextChoices):
        AWAITING_FUNDING = "awaiting_funding", "Awaiting Funding"
        FUNDED = "funded", "Funded (Escrow Held)"
        WORK_SUBMITTED = "work_submitted", "Work Submitted"
        RELEASED = "released", "Funds Released"
        REFUNDED = "refunded", "Funds Refunded"
        PARTIALLY_RELEASED = "split", "Split Settlement"
        DISPUTED = "disputed", "Under Dispute"

    class Recommendation(models.TextChoices):
        AUTO_RELEASE = "auto_release", "Auto-release approved"
        HUMAN_REVIEW = "human_review", "Human review required"
        MEDIATION = "mediation", "Escalate to mediation"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project_title = models.CharField(max_length=200, help_text="Short title of the deliverable/milestone.")
    description = models.TextField(blank=True, help_text="Scope of work agreed for this milestone.")
    client_ref = models.CharField(max_length=120, help_text="Client identifier (PayPal payer ID or email).")
    vendor_ref = models.CharField(max_length=120, help_text="Vendor identifier (PayPal payee ID or email).")
    agreed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Escrow amount in the milestone currency (e.g. USD).",
    )
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.AWAITING_FUNDING,
        db_index=True,
    )
    escrow_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        help_text="SHA-256 fingerprint of the agreement terms (tamper evidence).",
    )
    # --- TrustScore AI: dynamic milestone auto-release -----------------------
    trust_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Latest AI confidence in [0.0, 1.0] for the submitted delivery proof.",
    )
    recommendation = models.CharField(
        max_length=16,
        choices=Recommendation.choices,
        blank=True,
        help_text="Routing decision derived from trust_score thresholds.",
    )
    work_submitted_at = models.DateTimeField(null=True, blank=True)
    audit_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False,
        help_text="Hash-chained audit head: sha256(previous | settlement entry).",
    )
    ledger_verified = models.BooleanField(
        default=False,
        help_text="Set once the vault is settled: the ledger entry is final and locked.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["recommendation"]),
        ]

    def compute_escrow_hash(self) -> str:
        """Deterministic SHA-256 over the frozen agreement terms.

        Any later mutation of title/amount/parties invalidates the hash,
        which the payout routine must verify before releasing funds.
        """
        payload = "|".join(
            [
                str(self.id),
                self.project_title,
                str(self.agreed_amount),
                self.currency,
                self.client_ref,
                self.vendor_ref,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def seal_terms(self) -> None:
        """Freeze the agreement hash. Re-sealing is intentionally refused:
        re-sealing after funding would defeat the tamper evidence."""
        if not self.escrow_hash:
            self.escrow_hash = self.compute_escrow_hash()

    def verify_escrow_hash(self) -> bool:
        """True only if the stored hash still matches the live terms."""
        if not self.escrow_hash:
            return False
        return hmac.compare_digest(self.escrow_hash, self.compute_escrow_hash())

    @property
    def is_sealed(self) -> bool:
        return bool(self.escrow_hash)

    def record_audit(self, entry: str) -> str:
        """Append an immutable, hash-chained audit entry and persist the head."""
        previous = self.audit_hash or self.escrow_hash or ""
        self.audit_hash = hashlib.sha256(f"{previous}|{entry}".encode("utf-8")).hexdigest()
        self.save(update_fields=["audit_hash", "updated_at"])
        return self.audit_hash

    def save(self, *args, **kwargs):
        self.seal_terms()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_title} [{self.status}] — {self.agreed_amount} {self.currency}"


class Transaction(models.Model):
    """A PayPal REST API money movement tied to a milestone (fund / capture / payout)."""

    class Kind(models.TextChoices):
        ORDER_CREATE = "order_create", "Order Created"
        ORDER_CAPTURE = "order_capture", "Order Captured (Escrow Funded)"
        PAYOUT = "payout", "Payout Released"

    class CaptureStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        DECLINED = "DECLINED", "Declined"
        FAILED = "FAILED", "Failed"
        REFUNDED = "REFUNDED", "Refunded"
        SIMULATED = "SIMULATED", "Simulated (no live credentials)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    paypal_order_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="PayPal v2 checkout order ID returned by the Orders API.",
    )
    capture_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="PayPal capture ID once funds are actually captured.",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    capture_status = models.CharField(
        max_length=16,
        choices=CaptureStatus.choices,
        default=CaptureStatus.PENDING,
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    raw_response = models.JSONField(
        blank=True,
        null=True,
        help_text="Verbatim PayPal API response, kept for audit/replay.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "transactions"

    def __str__(self) -> str:
        return f"{self.kind} {self.amount} {self.currency} — {self.capture_status}"


class DeliveryProof(models.Model):
    """Vendor delivery evidence for a milestone + the TrustScore AI verdict.

    This is the input to dynamic escrow release: Gemini compares the proof
    against the buyer's agreed terms and returns a confidence score that
    routes the vault to auto-release, human review, or mediation.
    """

    class ProofType(models.TextChoices):
        LINK = "link", "Artifact URL"
        COMMIT = "commit", "Repository commit"
        TEXT = "text", "Delivery notes"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        related_name="delivery_proofs",
    )
    submitted_by = models.CharField(max_length=120, default="vendor")
    proof_type = models.CharField(max_length=10, choices=ProofType.choices, default=ProofType.TEXT)
    artifact = models.TextField(help_text="Sanitized delivery proof / artifact reference.")
    ai_confidence = models.FloatField(null=True, blank=True)
    ai_reasoning = models.TextField(blank=True)
    missing_items = models.TextField(blank=True, help_text="Comma-separated gaps the AI identified.")
    auto_released = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "delivery proofs"

    def __str__(self) -> str:
        return f"Proof for {self.milestone.project_title} @ {self.ai_confidence or 0:.2f}"


class DisputeEvidence(models.Model):
    """Evidence package + AI arbitration verdict for a disputed milestone."""

    class Verdict(models.TextChoices):
        RELEASE = "release", "Release to Vendor"
        REFUND = "refund", "Refund to Client"
        SPLIT = "split", "Split Settlement"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    milestone = models.ForeignKey(
        Milestone,
        on_delete=models.CASCADE,
        related_name="disputes",
    )
    submitted_by = models.CharField(max_length=120, help_text="Party who filed the evidence.")
    text_logs = models.TextField(help_text="Chat logs / delivery notes / contract excerpts.")
    ai_verdict = models.CharField(
        max_length=16,
        choices=Verdict.choices,
        blank=True,
        help_text="Decision produced by ai_agent.mediate_dispute().",
    )
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="AI self-reported confidence in [0.0, 1.0].",
    )
    reasoning = models.TextField(blank=True, help_text="AI explanation accompanying the verdict.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "dispute evidence"

    def __str__(self) -> str:
        return f"Dispute on {self.milestone.project_title} → {self.ai_verdict or 'pending'}"
