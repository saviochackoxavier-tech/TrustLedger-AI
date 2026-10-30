"""
TrustLedger AI — TrustScore AI Engine
=====================================
Dynamic milestone auto-release driven by AI confidence thresholds.

    confidence >= TRUSTSCORE_AUTO_RELEASE (0.95)  -> auto-release via PayPal Payouts
    0.70 <= confidence < 0.95                     -> hold for human review
    confidence <  TRUSTSCORE_REVIEW (0.70)        -> flag for mediation

Guarantees:
- Funds only ever move through `_settle_release()`, which re-verifies the
  escrow hash (tamper evidence) before calling PayPal.
- The settlement is hash-chained onto `Milestone.audit_hash`, so the audit
  trail cannot be rewritten without breaking the chain.
- The PayPal round-trip can run in a daemon thread so the vendor's HTTP
  request is never blocked by the payment rail ("secure background API call").
- Missing credentials never fabricate a real payout: the demo records an
  explicit SIMULATED transaction instead.
"""

import hashlib
import logging
import os
import threading
from typing import Any, Dict, Optional

from django.utils import timezone

from . import paypal
from .models import Milestone, Transaction

logger = logging.getLogger(__name__)

DEFAULT_AUTO_RELEASE = 0.95
DEFAULT_REVIEW = 0.70


# ---------------------------------------------------------------------------
# Thresholds (env-tunable, validated)
# ---------------------------------------------------------------------------

def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, value))


def thresholds() -> Dict[str, float]:
    """Auto-release / review cut-offs, guaranteed ordered and in [0, 1]."""
    auto = _env_float("TRUSTSCORE_AUTO_RELEASE", DEFAULT_AUTO_RELEASE)
    review = _env_float("TRUSTSCORE_REVIEW", DEFAULT_REVIEW)
    if review >= auto:  # never let a bad env collapse the review band
        review = max(0.0, auto - 0.01)
    return {"auto_release": auto, "review": review}


def classify(confidence: float, decision: str = "release") -> str:
    """Map a confidence score to a Milestone.Recommendation value.

    Only a `release` verdict can auto-pay the vendor; any other verdict is
    always seen by a human (money never leaves on an unreviewed refund/split).
    """
    cuts = thresholds()
    score = min(1.0, max(0.0, float(confidence or 0.0)))
    if decision != "release":
        return (
            Milestone.Recommendation.HUMAN_REVIEW
            if score >= cuts["review"]
            else Milestone.Recommendation.MEDIATION
        )
    if score >= cuts["auto_release"]:
        return Milestone.Recommendation.AUTO_RELEASE
    if score >= cuts["review"]:
        return Milestone.Recommendation.HUMAN_REVIEW
    return Milestone.Recommendation.MEDIATION


# ---------------------------------------------------------------------------
# Release orchestration
# ---------------------------------------------------------------------------

def _async_enabled() -> bool:
    return os.getenv("TRUSTLEDGER_RELEASE_ASYNC", "1") == "1"


def schedule_release(milestone_id: str, *, reason: str = "trustscore-auto") -> str:
    """Dispatch the payout call; returns 'queued' or the settlement state."""
    if _async_enabled():
        threading.Thread(
            target=_release_worker,
            args=(str(milestone_id), reason),
            name=f"trustledger-release-{milestone_id}",
            daemon=True,
        ).start()
        return "queued"
    return _release_worker(str(milestone_id), reason)["state"]


def _release_worker(milestone_id: str, reason: str) -> Dict[str, Any]:
    milestone = Milestone.objects.filter(pk=milestone_id).first()
    if milestone is None:
        logger.error("Auto-release aborted: milestone %s not found", milestone_id)
        return {"state": "missing"}
    return settle_release(milestone, reason=reason)


def settle_release(milestone: Milestone, *, reason: str = "trustscore-auto") -> Dict[str, Any]:
    """Release escrow to the vendor. Idempotent and tamper-checked."""
    if milestone.status in {
        Milestone.Status.RELEASED,
        Milestone.Status.REFUNDED,
        Milestone.Status.PARTIALLY_RELEASED,
    }:
        logger.info("Auto-release skipped: %s already settled (%s)", milestone.id, milestone.status)
        return {"state": "already_settled", "status": milestone.status}

    if not milestone.verify_escrow_hash():
        # Terms were edited after sealing — never pay against them.
        milestone.recommendation = Milestone.Recommendation.MEDIATION
        milestone.save(update_fields=["recommendation", "updated_at"])
        milestone.record_audit(f"release_blocked:hash_mismatch:{reason}")
        logger.error("Auto-release blocked by escrow hash mismatch: %s", milestone.id)
        return {"state": "hash_mismatch"}

    try:
        payout = paypal.release_payout_to_vendor(milestone, receiver_email=milestone.vendor_ref)
        batch_id = str((payout.get("batch_header") or {}).get("payout_batch_id", ""))[:64]
        Transaction.objects.create(
            milestone=milestone,
            paypal_order_id=batch_id or f"payout-{milestone.id}",
            kind=Transaction.Kind.PAYOUT,
            capture_status=Transaction.CaptureStatus.COMPLETED,
            amount=milestone.agreed_amount,
            currency=milestone.currency,
            raw_response=payout,
        )
        state, detail = "released", batch_id
    except paypal.PayPalCredentialsMissing:
        # Demo mode: no live keys -> record an explicit, non-monetary simulation.
        Transaction.objects.create(
            milestone=milestone,
            paypal_order_id=f"SIMULATED-{milestone.id}",
            kind=Transaction.Kind.PAYOUT,
            capture_status=Transaction.CaptureStatus.SIMULATED,
            amount=milestone.agreed_amount,
            currency=milestone.currency,
            raw_response={"simulated": True, "reason": "PayPal credentials not configured"},
        )
        state, detail = "simulated", "no-credentials"
        logger.warning("Payout simulated for %s — PayPal credentials absent", milestone.id)
    except Exception as exc:  # noqa: BLE001 - payout failure must never 500 the caller
        Transaction.objects.create(
            milestone=milestone,
            paypal_order_id=f"FAILED-{milestone.id}",
            kind=Transaction.Kind.PAYOUT,
            capture_status=Transaction.CaptureStatus.FAILED,
            amount=milestone.agreed_amount,
            currency=milestone.currency,
            raw_response={"error": str(exc)[:300]},
        )
        logger.error("Payout failed for %s: %s", milestone.id, exc)
        return {"state": "failed"}

    milestone.status = Milestone.Status.RELEASED
    milestone.ledger_verified = True  # lock the ledger entry as final
    milestone.save(update_fields=["status", "ledger_verified", "updated_at"])
    entry = hashlib.sha256(
        f"{milestone.id}|{milestone.agreed_amount}|{milestone.currency}|{reason}|{detail}".encode()
    ).hexdigest()[:32]
    audit_head = milestone.record_audit(
        f"release:{reason}:{state}:amount={milestone.agreed_amount}:ref={entry}"
    )
    logger.info("Escrow %s for %s (audit %s)", state, milestone.id, audit_head[:12])
    return {"state": state, "audit_hash": audit_head, "ref": detail}


def mark_for_review(milestone: Milestone, confidence: float, decision: str) -> str:
    """Persist the TrustScore routing without moving money."""
    recommendation = classify(confidence, decision)
    milestone.trust_score = round(float(confidence), 4)
    milestone.recommendation = recommendation
    milestone.save(update_fields=["trust_score", "recommendation", "updated_at"])
    milestone.record_audit(
        f"trustscore:{recommendation}:score={milestone.trust_score:.4f}:decision={decision}"
    )
    return recommendation


def human_release(milestone: Milestone, actor: str = "human") -> Dict[str, Any]:
    """Manual approval path for the 0.70–0.94 review band."""
    milestone.work_submitted_at = milestone.work_submitted_at or timezone.now()
    milestone.save(update_fields=["work_submitted_at", "updated_at"])
    return settle_release(milestone, reason=f"human:{actor[:60]}")
