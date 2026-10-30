"""
TrustLedger AI — Views (Frontend ↔ Backend Integration)
=======================================================
Function-based views covering the full escrow lifecycle:

    Dashboard -> Create Milestone -> Fund (PayPal POST) -> Capture
              -> Submit delivery proof -> TrustScore AI -> Auto-release / Review
              -> Dispute -> AI Mediation

Security contract:
- No secrets in code; paypal.py / ai_agent.py read from os.getenv().
- Every state mutation is POST-only behind Django's CsrfViewMiddleware.
- All user text passes through security.sanitize_text() before storage.
- Amounts are parsed as Decimal (never float) and bounded.
- Escrow hash is re-verified before any payout.
"""

import logging
import re
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from . import paypal, trustscore
from .ai_agent import evaluate_delivery, mediate_dispute
from .models import DeliveryProof, DisputeEvidence, Milestone, Transaction
from .security import sanitize_ref, sanitize_text

logger = logging.getLogger(__name__)

MAX_AMOUNT = Decimal("1000000.00")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Statuses counted as "money currently sitting in escrow"
IN_ESCROW_STATUSES = [
    Milestone.Status.FUNDED,
    Milestone.Status.WORK_SUBMITTED,
    Milestone.Status.DISPUTED,
]


def _wants_json(request) -> bool:
    return bool(
        request.headers.get("HX-Request")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _error(message: str, status: int = 400, **extra) -> JsonResponse:
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


# ---------------------------------------------------------------------------
# 1. Dashboard Home — bento-grid metrics + vault list + latest verdict
# ---------------------------------------------------------------------------

@require_GET
def dashboard(request):
    """Render the main bento dashboard with KPIs, vaults and AI verdict feed."""
    milestones = Milestone.objects.prefetch_related(
        "transactions", "disputes", "delivery_proofs"
    )

    escrowed_total = Milestone.objects.filter(
        status__in=IN_ESCROW_STATUSES
    ).aggregate(total=Sum("agreed_amount"))["total"] or Decimal("0.00")

    resolved = Milestone.objects.filter(
        status__in=[
            Milestone.Status.RELEASED,
            Milestone.Status.REFUNDED,
            Milestone.Status.PARTIALLY_RELEASED,
        ]
    ).count()

    context = {
        "milestones": milestones,
        "metrics": {
            "escrowed_total": escrowed_total,
            "active_vaults": Milestone.objects.filter(status__in=IN_ESCROW_STATUSES).count(),
            "resolved_disputes": resolved,
            "auto_released": DeliveryProof.objects.filter(auto_released=True).count(),
            "pending_review": Milestone.objects.filter(
                recommendation=Milestone.Recommendation.HUMAN_REVIEW
            ).count(),
        },
        "latest_dispute": DisputeEvidence.objects.select_related("milestone").first(),
        "thresholds": trustscore.thresholds(),
    }
    return render(request, "trustledger/dashboard.html", context)


# ---------------------------------------------------------------------------
# 2. Milestone Creation — seals the SHA-256 escrow hash on save
# ---------------------------------------------------------------------------

@require_POST
def milestone_create(request):
    """Create a milestone agreement; the model seals the escrow hash on save."""
    title = sanitize_text(request.POST.get("project_title") or "", 200)
    client_ref = sanitize_ref(request.POST.get("client_ref") or "")
    vendor_ref = sanitize_ref(request.POST.get("vendor_ref") or "")
    description = sanitize_text(request.POST.get("description") or "", 4000)
    currency = sanitize_text(request.POST.get("currency") or "USD", 3).upper()

    errors = {}
    if not title:
        errors["project_title"] = "Enter a project title (letters, numbers, punctuation)."
    if not client_ref:
        errors["client_ref"] = "Enter a valid client email or PayPal payer ID."
    if not vendor_ref:
        errors["vendor_ref"] = "Enter a valid vendor email or PayPal payee ID."
    if not CURRENCY_RE.match(currency):
        errors["currency"] = "Use a 3-letter ISO currency code."

    try:
        amount = Decimal(request.POST.get("agreed_amount") or "").quantize(Decimal("0.01"))
        if amount <= 0 or amount > MAX_AMOUNT:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        errors["agreed_amount"] = "Enter a positive amount up to 1,000,000.00."

    if errors:
        return _error("Please correct the highlighted fields.", 400, errors=errors)

    milestone = Milestone.objects.create(
        project_title=title,
        description=description,
        client_ref=client_ref,
        vendor_ref=vendor_ref,
        agreed_amount=amount,
        currency=currency,
    )
    logger.info("Milestone %s sealed with escrow hash %s", milestone.id, milestone.escrow_hash[:12])

    if _wants_json(request):
        return JsonResponse({"ok": True, "id": str(milestone.id)}, status=201)
    messages.success(request, "Milestone created and escrow hash sealed.")
    return redirect("trustledger:dashboard")


# ---------------------------------------------------------------------------
# 3. PayPal Funding & Capture flow
# ---------------------------------------------------------------------------

@require_POST
def fund_escrow(request, pk):
    """Step 1 — POST-only: create a PayPal order and redirect to approval."""
    milestone = get_object_or_404(Milestone, pk=pk)

    if milestone.status != Milestone.Status.AWAITING_FUNDING:
        return _error(f"Vault is '{milestone.status}', funding not allowed.", 409)
    if not milestone.verify_escrow_hash():
        return _error("Escrow hash mismatch — funding blocked for audit review.", 409)

    try:
        order = paypal.create_escrow_order(
            milestone_id=str(milestone.id),
            amount=milestone.agreed_amount,
            currency=milestone.currency,
        )
    except paypal.PayPalError as exc:
        logger.warning("Escrow order failed for %s: %s", milestone.id, exc)
        return _error("PayPal is unavailable. Check sandbox credentials.", 502)

    Transaction.objects.create(
        milestone=milestone,
        paypal_order_id=order["id"],
        kind=Transaction.Kind.ORDER_CREATE,
        amount=milestone.agreed_amount,
        currency=milestone.currency,
        raw_response=order,
    )

    approve_link = next(
        (lnk.get("href") for lnk in order.get("links", []) if lnk.get("rel") == "approve"),
        None,
    )
    if not approve_link or not str(approve_link).startswith("https://"):
        return _error("PayPal returned no valid approval link.", 502)

    if _wants_json(request):
        return JsonResponse({"ok": True, "approve_url": approve_link})
    return redirect(approve_link)


@require_GET
def capture_escrow(request, pk):
    """Step 2 — PayPal redirects here with ?token=<order id>; capture it.

    The token is verified against the stored order before any money moves,
    so a forged link cannot force a capture on this vault.
    """
    milestone = get_object_or_404(Milestone, pk=pk)
    order_tx = milestone.transactions.filter(
        kind=Transaction.Kind.ORDER_CREATE
    ).order_by("-created_at").first()

    if not order_tx:
        return _error("No PayPal order found for this vault.", 404)

    token = (request.GET.get("token") or "").strip()
    if token != order_tx.paypal_order_id:
        return render(
            request,
            "trustledger/capture.html",
            {"milestone": milestone, "order_id": order_tx.paypal_order_id, "verified": False},
            status=400,
        )

    try:
        capture = paypal.capture_order(order_tx.paypal_order_id)
    except paypal.PayPalError as exc:
        logger.warning("Capture failed for %s: %s", milestone.id, exc)
        return _error("PayPal capture failed or was not approved.", 502)

    capture_unit = (capture.get("purchase_units") or [{}])[0]
    payments = (capture_unit.get("payments") or {}).get("captures") or []
    Transaction.objects.create(
        milestone=milestone,
        paypal_order_id=order_tx.paypal_order_id,
        capture_id=(payments[0].get("id") if payments else "") or "",
        kind=Transaction.Kind.ORDER_CAPTURE,
        capture_status=Transaction.CaptureStatus.COMPLETED,
        amount=milestone.agreed_amount,
        currency=milestone.currency,
        raw_response=capture,
    )

    milestone.status = Milestone.Status.FUNDED
    milestone.save(update_fields=["status", "updated_at"])
    milestone.record_audit(f"funded:capture={order_tx.paypal_order_id}")
    messages.success(request, "Escrow funded — PayPal capture completed.")
    return redirect("trustledger:dashboard")


# ---------------------------------------------------------------------------
# 4. TrustScore AI — delivery proof in, automatic release / review out
# ---------------------------------------------------------------------------

@require_POST
def submit_delivery(request, pk):
    """Vendor submits proof; Gemini scores it against the buyer's terms.

    >= 0.95  -> instant PayPal Payouts release (background thread)
    0.70-0.94-> vault held with a highlighted human-review recommendation
    < 0.70   -> vault flagged for mediation
    """
    milestone = get_object_or_404(Milestone, pk=pk)

    if milestone.status == Milestone.Status.AWAITING_FUNDING:
        return _error("Fund the vault before submitting delivery proof.", 409)
    if milestone.status in {
        Milestone.Status.RELEASED,
        Milestone.Status.REFUNDED,
        Milestone.Status.PARTIALLY_RELEASED,
    }:
        return _error("This vault is already settled.", 409)

    artifact = sanitize_text(request.POST.get("artifact") or "", 4000)
    if len(artifact) < 20:
        return _error("Delivery proof must be at least 20 characters.", 400)

    proof_type = sanitize_text(request.POST.get("proof_type") or "text", 10).lower()
    if proof_type not in DeliveryProof.ProofType.values:
        proof_type = DeliveryProof.ProofType.TEXT
    submitted_by = sanitize_ref(request.POST.get("submitted_by") or "") or milestone.vendor_ref

    try:
        result = evaluate_delivery(
            project_title=milestone.project_title,
            agreed_amount=f"{milestone.agreed_amount} {milestone.currency}",
            terms=milestone.description,
            evidence=artifact,
            evidence_type=proof_type,
        )
    except RuntimeError as exc:
        logger.error("Delivery audit failed for %s: %s", milestone.id, exc)
        return _error("AI delivery audit unavailable. Check GEMINI_API_KEY.", 502)

    recommendation = trustscore.classify(result["confidence"], result["decision"])
    proof = DeliveryProof.objects.create(
        milestone=milestone,
        submitted_by=submitted_by,
        proof_type=proof_type,
        artifact=artifact,
        ai_confidence=result["confidence"],
        ai_reasoning=result["reasoning"],
        missing_items=result.get("missing_items", ""),
    )

    milestone.trust_score = result["confidence"]
    milestone.recommendation = recommendation
    milestone.work_submitted_at = timezone.now()
    if recommendation == Milestone.Recommendation.MEDIATION:
        milestone.status = Milestone.Status.DISPUTED
    else:
        milestone.status = Milestone.Status.WORK_SUBMITTED
    milestone.save(
        update_fields=["trust_score", "recommendation", "work_submitted_at", "status", "updated_at"]
    )
    milestone.record_audit(
        f"delivery:{recommendation}:score={result['confidence']:.4f}:decision={result['decision']}"
    )

    release_state = None
    if recommendation == Milestone.Recommendation.AUTO_RELEASE:
        proof.auto_released = True
        proof.save(update_fields=["auto_released"])
        release_state = trustscore.schedule_release(str(milestone.id))
        milestone.refresh_from_db()

    return JsonResponse(
        {
            "ok": True,
            "proof_id": str(proof.id),
            "decision": result["decision"],
            "confidence": result["confidence"],
            "reasoning": result["reasoning"],
            "missing_items": result.get("missing_items", ""),
            "recommendation": recommendation,
            "milestone_status": milestone.status,
            "release_state": release_state,
            "audit_hash": milestone.audit_hash,
        },
        status=201,
    )


@require_POST
def approve_release(request, pk):
    """Human approval for the review band — releases escrow through PayPal."""
    milestone = get_object_or_404(Milestone, pk=pk)

    if milestone.status == Milestone.Status.AWAITING_FUNDING:
        return _error("Vault is not funded — nothing to release.", 409)
    if milestone.status in {
        Milestone.Status.RELEASED,
        Milestone.Status.REFUNDED,
        Milestone.Status.PARTIALLY_RELEASED,
    }:
        return _error("This vault is already settled.", 409)
    if not milestone.verify_escrow_hash():
        milestone.record_audit("release_blocked:hash_mismatch:human")
        return _error("Escrow hash mismatch — release blocked for audit review.", 409)

    actor = sanitize_ref(request.POST.get("actor") or "") or "operations"
    outcome = trustscore.human_release(milestone, actor=actor)
    milestone.refresh_from_db()

    if _wants_json(request):
        payload = {"ok": outcome["state"] in {"released", "simulated"}, **outcome}
        payload["milestone_status"] = milestone.status
        return JsonResponse(payload, status=200 if payload["ok"] else 502)
    if outcome["state"] in {"released", "simulated"}:
        messages.success(request, "Escrow released after human review.")
    else:
        messages.error(request, "Release failed — check server logs and PayPal sandbox.")
    return redirect("trustledger:dashboard")


# ---------------------------------------------------------------------------
# 5. AI Dispute Mediation endpoint — evidence in, structured verdict out
# ---------------------------------------------------------------------------

@require_POST
def dispute_mediate(request, pk):
    """Accept evidence logs, run Gemini arbitration, persist the verdict."""
    milestone = get_object_or_404(Milestone, pk=pk)
    dispute_text = sanitize_text(request.POST.get("evidence") or "", 8000)
    submitted_by = sanitize_ref(request.POST.get("submitted_by") or "") or "anonymous"

    if len(dispute_text) < 40:
        return _error("Evidence logs must be at least 40 characters of plain text.", 400)
    if milestone.status == Milestone.Status.AWAITING_FUNDING:
        return _error("Fund the vault before opening a dispute.", 409)
    if milestone.status in {
        Milestone.Status.RELEASED,
        Milestone.Status.REFUNDED,
        Milestone.Status.PARTIALLY_RELEASED,
    }:
        return _error("This vault is already settled.", 409)

    try:
        verdict = mediate_dispute(
            project_title=milestone.project_title,
            agreed_amount=f"{milestone.agreed_amount} {milestone.currency}",
            dispute_text=dispute_text,
        )
    except RuntimeError as exc:
        logger.error("Mediation failed for milestone %s: %s", milestone.id, exc)
        return _error("AI mediator unavailable. Check GEMINI_API_KEY.", 502)

    evidence = DisputeEvidence.objects.create(
        milestone=milestone,
        submitted_by=submitted_by,
        text_logs=dispute_text,
        ai_verdict=verdict["decision"],
        confidence=verdict["confidence"],
        reasoning=verdict["reasoning"],
    )

    # Autonomous settlement: verdict drives the vault status atomically.
    status_map = {
        "release": Milestone.Status.RELEASED,
        "refund": Milestone.Status.REFUNDED,
        "split": Milestone.Status.PARTIALLY_RELEASED,
    }
    milestone.status = status_map.get(verdict["decision"], Milestone.Status.DISPUTED)
    milestone.trust_score = verdict["confidence"]
    milestone.ledger_verified = verdict["decision"] in status_map
    milestone.save(update_fields=["status", "trust_score", "ledger_verified", "updated_at"])
    milestone.record_audit(
        f"arbitration:{verdict['decision']}:score={verdict['confidence']:.4f}"
    )
    logger.info("Milestone %s settled as '%s' (confidence %.2f)",
                milestone.id, verdict["decision"], verdict["confidence"])

    return JsonResponse({
        "ok": True,
        "id": str(evidence.id),
        "decision": evidence.ai_verdict,
        "confidence": evidence.confidence,
        "reasoning": evidence.reasoning,
        "milestone_status": milestone.status,
        "audit_hash": milestone.audit_hash,
    }, status=201)
