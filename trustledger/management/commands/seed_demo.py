"""
TrustLedger AI — Demo Data Seeder
=================================
Usage:  python manage.py seed_demo [--reset]

Creates 5 showcase vaults for the hackathon video recording:
  1. `funded`          — clean escrow-held vault with PayPal transaction.
  2. `released`        — resolved dispute with a pre-solved Gemini verdict (0.94).
  3. `awaiting_funding`— untouched vault, ready for the live payment demo.
  4. `released`        — TrustScore AI auto-release at 0.97 (payout + audit chain).
  5. `work_submitted`  — TrustScore 0.82, held for human review.

Idempotent: skips seeding if milestones already exist; `--reset` wipes first.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from trustledger.models import DeliveryProof, DisputeEvidence, Milestone, Transaction


class Command(BaseCommand):
    help = "Seed 5 showcase milestones for the TrustLedger AI demo recording."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing milestones/transactions/disputes before seeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            Transaction.objects.all().delete()
            DisputeEvidence.objects.all().delete()
            DeliveryProof.objects.all().delete()
            Milestone.objects.all().delete()
            self.stdout.write(self.style.WARNING("Existing demo data cleared (--reset)."))
        elif Milestone.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Milestones already exist — seed_demo skipped (idempotent). "
                "Use --reset to rebuild demo data."
            ))
            return

        now = timezone.now()

        # ---- Milestone 1: funded (Escrow Held, clean transaction) ----------
        m1 = Milestone.objects.create(
            project_title="Brand Explainer Video (60s)",
            description="Full production: script, storyboard, animation, final cut.",
            client_ref="client@northwind.io",
            vendor_ref="studio@pixelforge.dev",
            agreed_amount=Decimal("2400.00"),
            currency="USD",
            status=Milestone.Status.FUNDED,
        )
        Transaction.objects.create(
            milestone=m1,
            paypal_order_id="SEED-ORDER-1XA2B3C4D5E6",
            capture_id="SEED-CAPT-9Z8Y7X6W5V",
            kind=Transaction.Kind.ORDER_CAPTURE,
            capture_status=Transaction.CaptureStatus.COMPLETED,
            amount=m1.agreed_amount,
            currency=m1.currency,
            raw_response={"seed": True, "note": "Sandbox capture replayed for demo."},
        )
        self.stdout.write(self.style.SUCCESS(f"[1/5] FUNDED   -> {m1} (escrow {m1.escrow_hash[:12]}…)"))

        # ---- Milestone 2: resolved dispute with pre-solved AI verdict ------
        m2 = Milestone.objects.create(
            project_title="React Landing Page Build",
            description="Pixel-perfect implementation of Figma design, Lighthouse > 90.",
            client_ref="client@lumenlabs.co",
            vendor_ref="dev@hexbit.io",
            agreed_amount=Decimal("1250.00"),
            currency="USD",
            status=Milestone.Status.RELEASED,
            trust_score=0.94,
            ledger_verified=True,
        )
        DisputeEvidence.objects.create(
            milestone=m2,
            submitted_by="client@lumenlabs.co",
            text_logs=(
                "CLIENT: The hero section is broken on Safari and the contact form "
                "does not send emails. VENDOR: I fixed the Safari layout on Oct 12 "
                "and re-deployed; form issue was on your SMTP config, documented in "
                "handover notes. CLIENT: Confirmed, Safari looks correct now and our "
                "IT fixed SMTP after vendor's diagnosis. Deliverables match the "
                "agreed Figma scope."
            ),
            ai_verdict=DisputeEvidence.Verdict.RELEASE,
            confidence=0.94,
            reasoning=(
                "Vendor demonstrated timely remediation of the Safari rendering "
                "defect with a dated redeploy, and the remaining SMTP fault was "
                "traced to the client's infrastructure, not the delivered code. "
                "Both parties subsequently confirmed the issues were resolved and "
                "the delivered scope matches the agreed Figma specification. "
                "Preponderance of evidence supports full release to the vendor."
            ),
        )
        m2.record_audit("arbitration:release:score=0.9400:seeded")
        self.stdout.write(self.style.SUCCESS(f"[2/5] DISPUTED -> {m2} (AI verdict: release @ 0.94)"))

        # ---- Milestone 3: awaiting_funding (live payment demo target) ------
        m3 = Milestone.objects.create(
            project_title="Mobile App UI Kit — 40 Screens",
            description="Design system + 40 screens, Figma source, dark & light themes.",
            client_ref="client@zenpath.app",
            vendor_ref="design@neonui.studio",
            agreed_amount=Decimal("3800.00"),
            currency="USD",
            status=Milestone.Status.AWAITING_FUNDING,
        )
        self.stdout.write(self.style.SUCCESS(f"[3/5] READY    -> {m3} (awaiting live PayPal funding)"))

        # ---- Milestone 4: TrustScore auto-release at 0.97 ------------------
        m4 = Milestone.objects.create(
            project_title="API Integration — Stripe → CRM Sync",
            description=(
                "Two-way sync for customers, invoices and refunds; webhook retries; "
                "staging demo; 95% test coverage on the sync module."
            ),
            client_ref="ops@finchpay.co",
            vendor_ref="team@quantshift.io",
            agreed_amount=Decimal("4650.00"),
            currency="USD",
            status=Milestone.Status.RELEASED,
            trust_score=0.97,
            recommendation=Milestone.Recommendation.AUTO_RELEASE,
            work_submitted_at=now - timedelta(hours=3),
            ledger_verified=True,
        )
        DeliveryProof.objects.create(
            milestone=m4,
            submitted_by="team@quantshift.io",
            proof_type=DeliveryProof.ProofType.COMMIT,
            artifact=(
                "https://github.com/quantshift/finchpay-sync/tree/9f2ac1b — two-way sync "
                "for customers/invoices/refunds, webhook retry queue, 96.4% coverage, "
                "staging walkthrough recorded (12 min)."
            ),
            ai_confidence=0.97,
            ai_reasoning=(
                "All four stated requirements are evidenced: bidirectional sync, "
                "webhook retry handling, a recorded staging demo, and coverage above "
                "the 95% bar at 96.4%. No unmet terms were identified."
            ),
            missing_items="",
            auto_released=True,
        )
        Transaction.objects.create(
            milestone=m4,
            paypal_order_id=f"SIMULATED-{m4.id}",
            kind=Transaction.Kind.PAYOUT,
            capture_status=Transaction.CaptureStatus.SIMULATED,
            amount=m4.agreed_amount,
            currency=m4.currency,
            raw_response={"seed": True, "note": "TrustScore auto-release replayed for demo."},
        )
        m4.record_audit(f"release:trustscore-auto:simulated:amount={m4.agreed_amount}")
        self.stdout.write(self.style.SUCCESS(f"[4/5] AUTO     -> {m4} (TrustScore 0.97 → payout, audit {m4.audit_hash[:10]}…)"))

        # ---- Milestone 5: TrustScore 0.82 → human review -------------------
        m5 = Milestone.objects.create(
            project_title="SEO Content Sprint — 8 Articles",
            description="8 long-form articles (1,200+ words), keyword-mapped, internal links, meta descriptions.",
            client_ref="growth@verdantgoods.com",
            vendor_ref="editor@inkwell.co",
            agreed_amount=Decimal("1480.00"),
            currency="USD",
            status=Milestone.Status.WORK_SUBMITTED,
            trust_score=0.82,
            recommendation=Milestone.Recommendation.HUMAN_REVIEW,
            work_submitted_at=now - timedelta(hours=1),
        )
        DeliveryProof.objects.create(
            milestone=m5,
            submitted_by="editor@inkwell.co",
            proof_type=DeliveryProof.ProofType.LINK,
            artifact=(
                "https://docs.inkwell.co/verdant/seo-sprint — 8 drafts delivered, "
                "7 keyword-mapped and meta-complete; article 8 awaiting client SME interview."
            ),
            ai_confidence=0.82,
            ai_reasoning=(
                "Seven of eight articles meet the word count, keyword mapping and meta "
                "requirements. The eighth is drafted but blocked on a client interview, "
                "so full delivery cannot be verified."
            ),
            missing_items="Article 8 missing meta description and final keyword pass",
            auto_released=False,
        )
        m5.record_audit("trustscore:human_review:score=0.8200:decision=release")
        self.stdout.write(self.style.SUCCESS(f"[5/5] REVIEW   -> {m5} (TrustScore 0.82 → human review badge)"))

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete at {timezone.now():%Y-%m-%d %H:%M} — "
            "5 milestones, 2 payouts, 1 arbitration, 1 auto-release, 1 review hold. "
            "Dashboard ready to record."
        ))
