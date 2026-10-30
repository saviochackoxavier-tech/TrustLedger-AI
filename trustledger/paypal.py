"""
TrustLedger AI — PayPal Sandbox Helper
======================================
Lightweight wrapper around the PayPal REST v2 Orders API and the v1
Payouts API using `requests` (no heavyweight SDK dependency).

Security contract:
- Credentials are read EXCLUSIVELY from environment variables at call time:
      PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_API_BASE
- No secret is ever logged, serialized, or embedded in responses.
- Captures refuse ambiguous states; payouts verify the escrow hash first.
"""

import logging
import os
import threading
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api-m.sandbox.paypal.com"
REQUEST_TIMEOUT = 15  # seconds — fail fast, never hang a request handler


class PayPalError(RuntimeError):
    """Base error for PayPal integration failures."""


class PayPalCredentialsMissing(PayPalError):
    """Raised when the sandbox credentials are not configured."""


# ---------------------------------------------------------------------------
# Configuration (env-only, read at call time so `.env`/tests can update it)
# ---------------------------------------------------------------------------

def _api_base() -> str:
    base = (os.getenv("PAYPAL_API_BASE") or DEFAULT_API_BASE).strip().rstrip("/")
    if not base.startswith("https://"):
        raise PayPalCredentialsMissing("PAYPAL_API_BASE must be an https:// endpoint.")
    return base


def _credentials() -> Tuple[str, str]:
    client_id = (os.getenv("PAYPAL_CLIENT_ID") or "").strip()
    secret = (os.getenv("PAYPAL_CLIENT_SECRET") or "").strip()
    if not client_id or not secret:
        raise PayPalCredentialsMissing(
            "PayPal credentials missing. Set PAYPAL_CLIENT_ID and "
            "PAYPAL_CLIENT_SECRET in your .env file — never hardcode them."
        )
    return client_id, secret


# ---------------------------------------------------------------------------
# OAuth2
# ---------------------------------------------------------------------------

_token_lock = threading.Lock()
_token_cache: Dict[str, Any] = {"token": None, "expires_in": 0}


def get_access_token(force_refresh: bool = False) -> str:
    """Fetch (and memoize, thread-safely) an OAuth2 client-credentials token."""
    client_id, secret = _credentials()
    with _token_lock:
        if _token_cache["token"] and not force_refresh:
            return _token_cache["token"]

        try:
            resp = requests.post(
                f"{_api_base()}/v1/oauth2/token",
                auth=(client_id, secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise PayPalError("PayPal OAuth token request failed.") from exc
        except ValueError as exc:
            raise PayPalError("PayPal OAuth returned a non-JSON body.") from exc

        token = data.get("access_token")
        if not token:
            raise PayPalError("PayPal OAuth response contained no access_token.")
        _token_cache["token"] = token
        _token_cache["expires_in"] = int(data.get("expires_in") or 0)
        logger.info("PayPal access token acquired (sandbox=%s)", "sandbox" in _api_base())
        return token


def _auth_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json",
    }


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST with one automatic token refresh on 401."""
    for attempt in (1, 2):
        try:
            resp = requests.post(
                f"{_api_base()}{path}",
                headers=_auth_headers(),
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise PayPalError("PayPal API request failed.") from exc
        if resp.status_code == 401 and attempt == 1:
            get_access_token(force_refresh=True)
            continue
        if resp.status_code >= 400:
            logger.error("PayPal %s -> %s", path, resp.status_code)
            raise PayPalError(f"PayPal API error (HTTP {resp.status_code}).")
        try:
            return resp.json()
        except ValueError as exc:
            raise PayPalError("PayPal returned a non-JSON body.") from exc
    raise PayPalError("PayPal API request failed after token refresh.")


# ---------------------------------------------------------------------------
# Orders API — v2/checkout/orders
# ---------------------------------------------------------------------------

def _money(amount: Any) -> str:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PayPalError("Invalid escrow amount.") from exc
    if value <= 0:
        raise PayPalError("Escrow amount must be positive.")
    return f"{value:.2f}"


def create_escrow_order(milestone_id: str, amount: Decimal, currency: str = "USD") -> Dict[str, Any]:
    """Create a PayPal order that will hold the milestone's escrow funds."""
    _credentials()
    site_base = (os.getenv("SITE_BASE_URL") or "http://127.0.0.1:8000").rstrip("/")
    payload = {
        "intent": "CAPTURE",
        "application_context": {
            "brand_name": "TrustLedger AI",
            "landing_page": "NO_PREFERENCE",
            "user_action": "PAY_NOW",
            "return_url": f"{site_base}/pay/{milestone_id}/capture/",
            "cancel_url": f"{site_base}/",
        },
        "purchase_units": [
            {
                "reference_id": str(milestone_id)[:64],
                "description": f"TrustLedger escrow for milestone {milestone_id}"[:127],
                "amount": {"currency_code": currency, "value": _money(amount)},
            }
        ],
    }
    order = _post("/v2/checkout/orders", payload)
    if not order.get("id"):
        raise PayPalError("PayPal returned no order id.")
    logger.info("Escrow order created: %s (milestone=%s)", order["id"], milestone_id)
    return order


def capture_order(order_id: str) -> Dict[str, Any]:
    """Capture a buyer-approved order — the moment escrow funds are secured.

    Raises if PayPal does not report a COMPLETED capture, so the milestone
    status is never advanced on an ambiguous state.
    """
    capture = _post(f"/v2/checkout/orders/{order_id}/capture", {})
    status = capture.get("status")
    if status != "COMPLETED":
        logger.warning("Capture not completed for order %s: %s", order_id, status)
        raise PayPalError(f"PayPal capture status is '{status}', expected 'COMPLETED'.")
    logger.info("Escrow captured for order %s", order_id)
    return capture


def verify_escrow_hash(expected_hash: str, milestone) -> None:
    """Tamper check executed before any payout leaves the platform."""
    if not milestone.verify_escrow_hash():
        raise PayPalError(
            "Escrow hash mismatch — agreement terms were modified after "
            "funding. Payout blocked for audit review."
        )
    if milestone.escrow_hash != expected_hash:
        raise PayPalError("Escrow hash mismatch — payout blocked.")


# ---------------------------------------------------------------------------
# Payouts API — v1/payments/payouts (release escrow to vendor)
# ---------------------------------------------------------------------------

def release_payout_to_vendor(
    milestone, receiver_email: str, amount: Optional[Decimal] = None
) -> Dict[str, Any]:
    """Pay out captured escrow to the vendor after AI or human approval."""
    _credentials()
    verify_escrow_hash(milestone.escrow_hash, milestone)
    receiver = (receiver_email or "").strip()
    if "@" not in receiver:
        raise PayPalError("Vendor payout requires a PayPal email address.")

    payout = _post(
        "/v1/payments/payouts",
        {
            "sender_batch_header": {
                "sender_batch_id": f"tl-{milestone.id}"[:64],
                "email_subject": "You have an escrow payout from TrustLedger AI",
                "email_message": f"Milestone released: {milestone.project_title}"[:1000],
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {
                        "value": _money(amount if amount is not None else milestone.agreed_amount),
                        "currency": milestone.currency,
                    },
                    "receiver": receiver[:127],
                    "note": f"Escrow release for milestone: {milestone.project_title}"[:255],
                }
            ],
        },
    )
    logger.info(
        "Payout batch %s dispatched for milestone %s",
        (payout.get("batch_header") or {}).get("payout_batch_id"),
        milestone.id,
    )
    return payout
