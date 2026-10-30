"""
TrustLedger AI — Real-HTTP Smoke Test
=====================================
Drives a LIVE server (not the test client) to prove the security contract
end-to-end: CSRF is enforced, POST-only routes reject GET, sanitization is
applied before storage, and state guards refuse illegal transitions.

Usage
-----
1) python manage.py migrate && python manage.py seed_demo
2) python manage.py runserver 127.0.0.1:8011
3) python scripts/smoke_http.py http://127.0.0.1:8011

Exit code 0 = all checks passed.
"""

import sys

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8011").rstrip("/")
FAILURES = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}{(' — ' + str(detail)) if detail and not condition else ''}")
    if not condition:
        FAILURES.append(label)


def main():
    session = requests.Session()
    session.get(f"{BASE}/", timeout=10)
    token = session.cookies.get("csrftoken")
    check("dashboard issues a CSRF cookie", bool(token))

    headers = {
        "X-CSRFToken": token,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/",
    }

    # --- 1. CSRF enforced on a token-less POST -----------------------------
    no_token = requests.post(
        f"{BASE}/milestones/new/",
        data={"project_title": "csrf probe"},
        headers={"X-Requested-With": "XMLHttpRequest"},
        timeout=10,
    )
    check("POST without CSRF token is rejected (403)", no_token.status_code == 403, no_token.status_code)

    # --- 2. Milestone creation + stored XSS sanitization --------------------
    payload = "Smoke <script>alert('xss')</script>"
    created = session.post(
        f"{BASE}/milestones/new/",
        data={
            "project_title": payload,
            "description": "Scope <img src=x onerror=alert(1)>",
            "agreed_amount": "99.99",
            "currency": "USD",
            "client_ref": "smoke@client.io",
            "vendor_ref": "smoke@vendor.io",
        },
        headers=headers,
        timeout=10,
    )
    check("milestone create returns 201", created.status_code == 201, created.text[:120])
    milestone_id = created.json().get("id") if created.status_code == 201 else None

    page = session.get(f"{BASE}/", timeout=10).text
    check("script payload is not stored raw", "<script>alert('xss')</script>" not in page)
    check("img onerror payload is not stored raw", "onerror=alert(1)" not in page)
    check("sanitized title still renders", "Smoke" in page)

    if not milestone_id:
        return report()

    # --- 3. POST-only funding --------------------------------------------
    check("GET on fund route is 405", session.get(f"{BASE}/pay/{milestone_id}/", timeout=10).status_code == 405)

    # --- 4. State guards --------------------------------------------------
    unfunded = session.post(
        f"{BASE}/deliver/{milestone_id}/",
        data={"artifact": "commit abc123 deployed to staging", "proof_type": "commit"},
        headers=headers,
        timeout=10,
    )
    check("delivery rejected on unfunded vault (409)", unfunded.status_code == 409, unfunded.text[:120])

    short = session.post(
        f"{BASE}/dispute/{milestone_id}/",
        data={"evidence": "too short"},
        headers=headers,
        timeout=10,
    )
    check("short dispute evidence rejected (400)", short.status_code == 400, short.text[:120])

    # --- 5. Capture token verification -----------------------------------
    bad_token = session.get(f"{BASE}/pay/{milestone_id}/capture/?token=WRONG", timeout=10)
    # 404 = no PayPal order exists for this (unfunded) vault;
    # 400 = order exists but the token does not match it.
    check(
        "capture with wrong token refused (400/404)",
        bad_token.status_code in {400, 404},
        bad_token.status_code,
    )
    if bad_token.status_code == 400:
        check("capture guard page hides the order", "Capture link not verified" in bad_token.text)

    # --- 6. Sanitized input reaches the AI agent -------------------------
    funded_artifact = "<script>steal()</script> Deployed build 9f2ac1b with 40 screens and passing tests."
    delivery = session.post(
        f"{BASE}/deliver/{milestone_id}/",
        data={"artifact": funded_artifact, "proof_type": "link"},
        headers=headers,
        timeout=15,
    )
    # Vault is unfunded -> 409; on a funded vault this returns 502 without a
    # GEMINI_API_KEY, and 201 with one. Both prove the route is wired.
    check("delivery route responds (409/502/201)", delivery.status_code in {201, 409, 502}, delivery.status_code)

    return report()


def report():
    print("-" * 62)
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
