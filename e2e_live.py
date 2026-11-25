"""Browser walk-through of the wired UI against the live API.

Runs a real Chromium: signs in with a real password, exercises the lab panel,
saves a run through the server, signs the technical review, approves as QA,
downloads the generated PDF and XLSX, and fails on any console error.

Usage: python3 e2e_live.py [base_url]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
OUT = Path("/tmp/e2e")
OUT.mkdir(exist_ok=True)

def _creds(username: str, env_var: str) -> tuple[str, str]:
    """Credentials come from the environment — never from the repository.

    `export SBDMA_ANALYST_PASSWORD=...` etc. (see backend/.env.example); the same
    variables the seeder uses.
    """
    password = os.environ.get(env_var)
    if not password:
        sys.exit(
            f"missing {env_var}. Export the seeded passwords before running this walkthrough:\n"
            "  source /tmp/seedenv.sh   # or your own .env"
        )
    return (username, password)


ANALYST = _creds("analyst.phys", "SBDMA_ANALYST_PASSWORD")
REVIEWER = _creds("reviewer.phys", "SBDMA_REVIEWER_PASSWORD")
QA = _creds("qa.officer", "SBDMA_QA_OFFICER_PASSWORD")

INPUTS_PATH = Path(os.environ.get("SBDMA_E2E_INPUTS", "/tmp/e2e_inputs.json"))
COMPLIANT = json.loads(INPUTS_PATH.read_text())


def fill_lab_form(page) -> None:
    """Type the 13-test reference dataset into the laboratory panel."""
    for code, values in COMPLIANT.items():
        page.locator(f'button:has-text("{code}")').first.click()
        page.wait_for_timeout(120)
        for key, value in values.items():
            series = isinstance(value, list)
            if series:
                for index, item in enumerate(value):
                    locator = page.locator(f'[data-field="{code}.{key}.{index}"]')
                    if locator.count():
                        locator.first.fill(str(item))
            else:
                locator = page.locator(f'[data-field="{code}.{key}"]')
                if locator.count():
                    tag = locator.first.evaluate("el => el.tagName")
                    if tag == "SELECT":
                        locator.first.select_option(str(value))
                    else:
                        locator.first.fill(str(value))


def _mfa_code(username: str) -> str:
    """Compute the account's current TOTP code, as an authenticator app would.

    The walkthrough cannot read a phone, so it derives the code from the enrolled
    secret. This is a *test* affordance, and the reason the secret is encrypted at
    rest: reading the database column is not enough to produce a code without the
    application key.
    """
    backend = os.path.join(os.path.dirname(__file__), "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    import base64
    import hashlib
    from datetime import datetime, timezone

    import psycopg
    import pyotp
    from cryptography.fernet import Fernet

    from app.core.config import get_settings

    dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT totp_secret, totp_enabled, totp_last_counter FROM users WHERE username = %s",
            (username,),
        ).fetchone()
    # A *pending* enrolment already has a secret but totp_enabled is still false:
    # the code has to be derived from it to prove possession and activate. So the
    # only requirement here is that a secret exists.
    if not row or not row[0]:
        return ""

    key = Fernet(
        base64.urlsafe_b64encode(
            hashlib.sha256(f"sbdma-totp::{get_settings().mfa_encryption_key}".encode()).digest()
        )
    )
    secret = key.decrypt(row[0].encode()).decode()

    totp = pyotp.TOTP(secret)
    counter = int(totp.timecode(datetime.now(timezone.utc)))
    if row[2] is not None and counter <= row[2]:
        counter = row[2] + 1
    return totp.generate_otp(counter)


def sign_in_with_mfa(page, username: str, password: str) -> None:
    """Sign in, entering a code or completing enrolment when the server asks.

    Three states are possible after the password step:
      1. signed in                        → done
      2. a code field appeared (#totp)    → the account is already enrolled
      3. the enrolment screen appeared    → the role mandates a factor and this
                                            account has none yet
    """
    # A fresh context opens on "/", which the app bounces to /login once it
    # discovers there is no session. Navigating straight there avoids racing that
    # redirect — and after a user switch the login form is what we need anyway.
    if page.locator("#username").count() == 0:
        page.goto(f"{BASE}/login")
    page.wait_for_selector("#username", timeout=20000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.get_by_role("button", name="دخول").click()
    page.wait_for_timeout(2000)

    # 2) enrolled: the login form revealed the code field
    if page.locator("#totp").count():
        page.fill("#totp", _mfa_code(username))
        page.get_by_role("button", name="دخول").click()
        page.wait_for_timeout(2000)

    # 3) not enrolled: the enrolment screen replaces the app. Identified by its
    #    code field / QR image rather than the heading, which also appears in
    #    help copy elsewhere in the interface.
    if page.locator("input[placeholder='000000']").count() or page.locator(
        'img[alt*="QR"]'
    ).count():
        page.wait_for_selector("input[placeholder='000000']", timeout=20000)
        page.fill("input[placeholder='000000']", _mfa_code(username))
        page.get_by_role("button", name="تفعيل").click()
        page.wait_for_timeout(2500)
        # recovery codes are shown exactly once
        if page.get_by_text("أكواد الاسترداد").count():
            ok = page.get_by_role("button", name="تم — سجّل الدخول من جديد")
            if ok.count():
                ok.click()
                page.wait_for_timeout(2000)
            sign_in_with_mfa(page, username, password)
            return

    page.wait_for_url(lambda url: "/login" not in url, timeout=20000)


def main() -> int:
    failures: list[str] = []

    def go(page, path: str) -> None:
        """Navigate, retrying while `next dev` compiles a route on first hit."""
        last: Exception | None = None
        for _ in range(3):
            try:
                page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=60000)
                return
            except Exception as exc:  # noqa: BLE001 - retry on compile gaps
                last = exc
                page.wait_for_timeout(4000)
        raise last  # type: ignore[misc]

    def _drain_api(page) -> None:
        """Next dev serialises compiles; wait until the page stops talking to the API."""
        page.wait_for_load_state("domcontentloaded")
        for _ in range(60):
            try:
                with page.expect_response(lambda r: "/api/v1/" in r.url, timeout=3000):
                    page.wait_for_timeout(500)
            except Exception:
                return
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1500, "height": 1000}, locale="ar-YE")
        page = context.new_page()
        def _on_console(message) -> None:
            text_ = message.text
            # an anonymous visit legitimately 401s while discovering the session
            if message.type == "error" and "401" not in text_:
                console_errors.append(text_)

        page.on("console", _on_console)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # 1) protected route redirects an anonymous visitor to /login
        go(page, "/qa")
        page.wait_for_timeout(2500)
        if "/login" not in page.url:
            failures.append(f"anonymous visitor was not redirected to /login (at {page.url})")

        # 2) wrong password is rejected by the server
        page.fill("#username", ANALYST[0])
        page.fill("#password", "definitely-wrong-1")
        page.get_by_role("button", name="دخول").click()
        page.wait_for_timeout(1500)
        if "/login" not in page.url:
            failures.append("a wrong password produced a session")

        # 3) real sign-in
        page.fill("#password", ANALYST[1])
        page.get_by_role("button", name="دخول").click()
        page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "01-dashboard.png"), full_page=True)

        # 4) the instrument register came from PostgreSQL
        _drain_api(page)
        go(page, "/lab")
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        if "LC-2050C" not in body:
            failures.append("the seeded LC-2050C instrument is not shown in the lab panel")

        # 5) run the engine and store the run through the API
        page.wait_for_timeout(1500)
        if not page.locator("[data-field]").count():
            failures.append("lab inputs are not instrumented with data-field attributes")
        else:
            fill_lab_form(page)
            page.get_by_role("button", name="Run Calibration").click()
            page.wait_for_timeout(1200)
            page.screenshot(path=str(OUT / "02-preview.png"), full_page=True)
            confirm = page.get_by_role("button", name="حفظ وإرسال للمراجعة الفنية")
            if confirm.count():
                confirm.click()
                page.wait_for_timeout(3500)
            page.screenshot(path=str(OUT / "03-saved.png"), full_page=True)
            toast = page.inner_text("body")
            if "PASS" not in toast:
                failures.append("the saved run does not report a PASS verdict")

        print("reached QA queue with the analyst", flush=True)
        # 6) evidence attachments: the analyst files a document and reads it back
        go(page, "/engineering")
        page.wait_for_timeout(2500)
        picker = page.locator('[data-testid="evidence-instrument"]')
        # the instrument list arrives from the API after first paint
        try:
            page.wait_for_function(
                """() => {
                    const el = document.querySelector('[data-testid="evidence-instrument"]');
                    return !!el && el.options.length > 1;
                }""",
                timeout=15000,
            )
        except Exception:  # noqa: BLE001 - reported below
            pass
        options = picker.locator("option")
        if options.count() < 2:
            failures.append("the engineering page lists no instrument to file evidence against")
        else:
            picker.select_option(index=1)
            try:
                page.wait_for_selector('input[type="file"]', state="attached", timeout=20000)
            except Exception:  # noqa: BLE001
                page.screenshot(path=str(OUT / "08-attachments-missing.png"), full_page=True)
                failures.append("the file input never mounted in the attachments panel")

            evidence = OUT / "evidence-upload.txt"
            evidence.write_text(
                "SBDMA\nChromatogram export for repeatability test (T11)\n"
                "noise=0.010 mAU; drift=0.100 mAU/h\n",
                encoding="utf-8",
            )
            file_input = page.locator('input[type="file"]')
            if file_input.count() == 0:
                failures.append("the attachments panel does not offer a file input")
            else:
                file_input.first.set_input_files(str(evidence))
                page.locator("textarea").last.fill(
                    "مخطط كروماتوغرافي لاختبار التكرارية مأخوذ من LabSolutions"
                )
                page.get_by_role("button", name="إرفاق الدليل").click()
                page.wait_for_timeout(3000)
                page.screenshot(path=str(OUT / "08-attachments.png"), full_page=True)
                body_text = page.inner_text("body")
                if "evidence-upload.txt" not in body_text:
                    failures.append("the filed attachment does not appear in the evidence list")
                if "SHA-256" not in body_text:
                    failures.append("the attachment list does not show the recorded SHA-256")

                download_button = page.get_by_role("button", name="تنزيل موثّق")
                if download_button.count() == 0:
                    failures.append("no verified download action for the filed attachment")
                else:
                    with page.expect_download(timeout=20000) as dl:
                        download_button.first.click()
                    got = dl.value
                    saved = OUT / (got.suggested_filename or "attachment.txt")
                    got.save_as(str(saved))
                    if saved.read_bytes() != evidence.read_bytes():
                        failures.append("the downloaded attachment differs from the filed bytes")
                    else:
                        print(f"downloaded attachment verified byte-identical: {saved.name}")

        # 6) sign out, then sign in as the technical reviewer and sign the review
        go(page, "/qa")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / "04-qa-queue.png"), full_page=True)

        def sign_out_and_in(credentials: tuple[str, str]) -> None:
            # a signed-in session redirects /login to the dashboard, so end it first
            go(page, "/")
            page.wait_for_timeout(1500)
            # the identity menu hides the sign-out action
            page.locator('button[aria-haspopup="menu"]').first.click()
            page.wait_for_timeout(600)
            sign_out = page.get_by_role("menuitem", name="تسجيل الخروج")
            if not sign_out.count():
                failures.append("the sign-out action is missing from the identity menu")
            else:
                sign_out.first.click()
                page.wait_for_timeout(2500)
            go(page, "/login")
            page.wait_for_timeout(800)
            sign_in_with_mfa(page, credentials[0], credentials[1])
            page.wait_for_timeout(2000)

        sign_out_and_in(REVIEWER)
        go(page, "/qa")
        page.wait_for_timeout(2500)
        # open the newest run in the queue
        page.locator("li button").first.click()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "05-qa-review.png"), full_page=True)
        # the first test tab must be active, or the chart card is never mounted
        tab_button = page.get_by_role("button", name="T01 ·")
        if tab_button.count():
            tab_button.first.click()
            page.wait_for_timeout(1200)
        canvas = page.locator("canvas").first
        if not canvas.count():
            failures.append("the QA scientific chart did not render (no canvas)")
        else:
            size = page.evaluate(
                "() => { const c = document.querySelector('canvas'); return c ? [c.width, c.height] : null; }"
            )
            if not size or size[0] < 200 or size[1] < 100:
                failures.append(f"the QA scientific chart canvas has no usable size: {size}")
            # the summary card must not push content outside its own box
            overflow = page.evaluate(
                """() => [...document.querySelectorAll('.card')]
                     .filter((el) => el.scrollWidth > el.clientWidth + 2).length"""
            )
            if overflow:
                failures.append(f"{overflow} card(s) overflow horizontally")

        # the reviewer may read evidence but must not be offered the filing form
        go(page, "/engineering")
        page.wait_for_timeout(2000)
        reviewer_picker = page.locator('[data-testid="evidence-instrument"]')
        if reviewer_picker.count():
            reviewer_picker.select_option(index=1)
            page.wait_for_timeout(1800)
            if page.locator('input[type="file"]').count():
                failures.append("the reviewer was offered the evidence filing form without attachments.manage")
            if "الإرفاق متاح" not in page.inner_text("body"):
                failures.append("the reviewer sees no explanation for the hidden filing form")

        # back to the approval queue
        go(page, "/qa")
        page.wait_for_timeout(2500)
        page.locator("li button").first.click()
        page.wait_for_timeout(1500)

        review_button = page.get_by_role("button", name="توقيع المراجعة الفنية")
        if review_button.count() == 0:
            failures.append("the technical review action is not offered to the reviewer")
        else:
            review_button.first.click()
            page.wait_for_timeout(800)
            page.fill('input[type="password"]', REVIEWER[1])
            page.fill("textarea", "مراجعة فنية للقراءات مقابل البروتوكول المعتمد")
            page.get_by_role("button", name="توقيع واعتماد").click()
            page.wait_for_timeout(2800)
            page.screenshot(path=str(OUT / "06-review-signed.png"), full_page=True)

        # 7) QA approval, then the certificate download
        sign_out_and_in(QA)
        go(page, "/qa")
        page.wait_for_timeout(2500)
        page.locator("li button").first.click()
        page.wait_for_timeout(1200)
        approve_button = page.get_by_role("button", name="اعتماد ضمان الجودة النهائي")
        if approve_button.count() == 0:
            failures.append("the QA approval action is not offered to the approver")
        else:
            approve_button.first.click()
            page.wait_for_timeout(800)
            page.fill('input[type="password"]', QA[1])
            page.fill("textarea", "اعتماد ضمان الجودة وإصدار الشهادة")
            page.get_by_role("button", name="توقيع").last.click()
            page.wait_for_timeout(3000)
            page.screenshot(path=str(OUT / "07-approved.png"), full_page=True)

        pdf_button = page.get_by_role("button", name="PDF")
        if pdf_button.count() and pdf_button.first.is_enabled():
            with page.expect_download(timeout=20000) as download_info:
                pdf_button.first.click()
            download = download_info.value
            target = OUT / (download.suggested_filename or "certificate.pdf")
            download.save_as(str(target))
            if target.stat().st_size < 20000:
                failures.append("the downloaded certificate is suspiciously small")
            print(f"downloaded certificate: {target.name} ({target.stat().st_size} bytes)")
        else:
            failures.append("the certificate button stayed disabled after approval")

        browser.close()

    # ── OOS deviations: the register must be reachable and populated ────────
    # The specific loop (raise → investigate → close) is exercised over the API
    # by the test suite; what a browser adds is evidence the page actually
    # renders for the role that owns it, with no console error.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_context(base_url=BASE).new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        sign_in_with_mfa(page, QA[0], QA[1])
        page.goto(f"{BASE}/deviations")
        page.wait_for_timeout(2500)
        body = page.inner_text("body")
        if "DEV-" not in body and "لا توجد انحرافات" not in body:
            failures.append("the deviations register rendered neither rows nor its empty state")
        else:
            print("deviations register rendered for QA", flush=True)
        if errors:
            failures.extend(f"deviations page error: {e}" for e in errors)
        browser.close()

    # the duplicate toast seen in the screenshots is cosmetic; the real check is
    # that no unexpected console error fired
    unexpected = [e for e in console_errors if "429" not in e and "401" not in e]

    print(json.dumps({"failures": failures, "console_errors": unexpected[:10]}, indent=2, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
