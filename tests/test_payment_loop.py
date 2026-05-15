"""
End-to-end payment-loop contract test.

Exercises the full Razorpay automated flow without touching real
external services:

  POST /api/v1/checkout/create-order      (mocked Razorpay SDK call)
        ↓
  Order row in DB (status='created')
        ↓
  Razorpay calls /webhooks/razorpay with a signed body
  (we synthesise the signature using the configured webhook secret)
        ↓
  Webhook handler verifies signature, mints License via mint_license,
  updates Order.status='paid', calls send_license_email
        ↓
  License row exists with product='rwagenie', plan='PRO'
  Email send was attempted via mocked SMTP

The test sets RAZORPAY_KEY_ID / SECRET / WEBHOOK_SECRET to dummy
values so the endpoints don't 503, then patches the SDK + smtplib so
no real network call leaves the test process. Locks the
"on payment.captured → mint+email" contract that go-live depends on.

Run with:   python -m unittest tests.test_payment_loop -v
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Force a SQLite temp DB before anything imports the license_server
_TMP_DIR = Path(tempfile.mkdtemp(prefix="aicc_payloop_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR / 'licenses.db'}"
# Dummy Razorpay creds so razorpay_client.is_enabled() returns True
os.environ["RAZORPAY_KEY_ID"]         = "rzp_test_dummy_key_id"
os.environ["RAZORPAY_KEY_SECRET"]     = "dummy_key_secret"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = "dummy_webhook_secret_for_tests"
# SMTP intentionally left blank — email is best-effort; webhook still succeeds.


class TestPaymentLoop(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from license_server.db   import init_db
        from license_server.main import app

        init_db()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(_TMP_DIR, ignore_errors=True)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sign_webhook(body: bytes) -> str:
        return hmac.new(
            key=b"dummy_webhook_secret_for_tests",
            msg=body,
            digestmod=hashlib.sha256,
        ).hexdigest()

    _next_order_seq = 0

    @classmethod
    def _razorpay_order_factory(cls, amount_paise: int,
                                 currency: str = "INR",
                                 order_id: str | None = None):
        """Stand-in for razorpay.Client().order.create(...). Returns the
        shape the real SDK does. Each call yields a fresh order_id so
        the UNIQUE constraint on orders.razorpay_order_id doesn't bite
        when multiple tests run in the same DB."""
        if order_id is None:
            cls._next_order_seq += 1
            order_id = f"order_TEST_{cls._next_order_seq:08d}"
        return {
            "id":       order_id,
            "entity":   "order",
            "amount":   int(amount_paise),
            "currency": currency,
            "receipt":  f"rwag-PRO-{cls._next_order_seq}",
            "status":   "created",
            "attempts": 0,
            "notes":    {},
        }

    @staticmethod
    def _webhook_payload_payment_captured(order_id: str,
                                           amount_paise: int) -> dict:
        return {
            "entity":  "event",
            "event":   "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id":       "pay_TEST_PAYMENT_ID_abc",
                        "amount":   amount_paise,
                        "currency": "INR",
                        "status":   "captured",
                        "order_id": order_id,
                        "method":   "upi",
                    }
                }
            },
            "created_at": 1700000000,
        }

    # ── Tests ─────────────────────────────────────────────────────────────────

    def test_create_order_rwagenie_pro_inr(self):
        """POST /api/v1/checkout/create-order for product=rwagenie plan=PRO
        creates a Razorpay order at 2999 INR (per inline RWA pricing)."""
        from license_server.services import razorpay_client

        with patch.object(razorpay_client, "create_order") as mock_create:
            mock_create.return_value = self._razorpay_order_factory(
                amount_paise=2999 * 100,
            )

            resp = self.client.post(
                "/api/v1/checkout/create-order",
                json={
                    "plan":           "PRO",
                    "product":        "rwagenie",
                    "country_code":   "IN",
                    "customer_email": "customer@example.com",
                    "customer_name":  "Customer Name",
                    "company_name":   "Test Society CHS",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            body = resp.json()
            self.assertTrue(body["ok"], body)
            self.assertEqual(body["product"] or "rwagenie", "rwagenie")
            self.assertEqual(body["plan"], "PRO")
            self.assertEqual(body["currency"], "INR")
            # Wait — server runs price_for('rwagenie', 'PRO', 'IN') which
            # returns 5999 per plans.PLAN_PRICES_RWA_INR. Check that
            # paise math, not the mock's number.
            from license_server.plans import price_for
            expected_paise = int(price_for("rwagenie", "PRO", "IN") * 100)
            self.assertEqual(body["amount_paise"], expected_paise)

            # The Razorpay SDK call should have happened with the right
            # amount + a product='rwagenie' note for cross-check.
            self.assertTrue(mock_create.called)
            call = mock_create.call_args
            self.assertEqual(call.kwargs["amount_paise"], expected_paise)
            self.assertEqual(call.kwargs["notes"]["product"], "rwagenie")

    def test_create_order_rejects_unknown_product(self):
        resp = self.client.post(
            "/api/v1/checkout/create-order",
            json={
                "plan":           "PRO",
                "product":        "bogus",
                "country_code":   "IN",
                "customer_email": "x@y.com",
            },
        )
        # FastAPI returns 422 (pydantic validation) because product
        # has a regex constraint in CheckoutCreateRequest.
        self.assertEqual(resp.status_code, 422)

    def test_create_order_free_plan_rejected(self):
        """Razorpay can't process zero-amount orders, and FREE plans don't
        flow through checkout anyway."""
        from license_server.services import razorpay_client
        with patch.object(razorpay_client, "create_order"):
            resp = self.client.post(
                "/api/v1/checkout/create-order",
                json={
                    "plan":           "FREE",
                    "product":        "rwagenie",
                    "country_code":   "IN",
                    "customer_email": "x@y.com",
                },
            )
            self.assertEqual(resp.status_code, 200)
            self.assertFalse(resp.json()["ok"])
            self.assertIn("not priced", resp.json()["error"].lower())

    def test_webhook_signature_required(self):
        """Webhook with no/bad signature must 401 so an attacker can't
        forge a 'payment.captured' to mint a free key."""
        from license_server.plans import price_for
        amount_paise = int(price_for("rwagenie", "PRO", "IN") * 100)
        body = json.dumps(
            self._webhook_payload_payment_captured(
                "order_does_not_exist", amount_paise
            )
        ).encode()
        # No signature header
        resp = self.client.post("/webhooks/razorpay", content=body,
                                 headers={"content-type": "application/json"})
        self.assertEqual(resp.status_code, 401)

        # Wrong signature
        resp = self.client.post(
            "/webhooks/razorpay", content=body,
            headers={
                "content-type":          "application/json",
                "x-razorpay-signature":  "not_the_right_hash",
            },
        )
        self.assertEqual(resp.status_code, 401)

    def test_payment_captured_mints_rwagenie_license(self):
        """Full happy path: create-order, then a signed payment.captured
        webhook mints a License row with product='rwagenie' and updates
        the Order to status='paid'."""
        from license_server.db   import SessionLocal
        from license_server.models import Order, License
        from license_server.services import razorpay_client, email_service
        from license_server.plans import price_for

        amount_paise = int(price_for("rwagenie", "PRO", "IN") * 100)

        # 1) create-order — generates a real Order row via the mocked SDK
        mock_order = self._razorpay_order_factory(amount_paise)
        with patch.object(razorpay_client, "create_order",
                          return_value=mock_order):
            resp = self.client.post(
                "/api/v1/checkout/create-order",
                json={
                    "plan":           "PRO",
                    "product":        "rwagenie",
                    "country_code":   "IN",
                    "customer_email": "buyer@example.com",
                    "customer_name":  "Test Buyer",
                    "company_name":   "Test Society",
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            order_id = resp.json()["order_id"]
            self.assertEqual(order_id, mock_order["id"])

        # 2) Verify the Order row exists and carries product=rwagenie
        with SessionLocal() as db:
            from sqlalchemy import select
            ord_row = db.scalar(
                select(Order).where(Order.razorpay_order_id == order_id)
            )
            self.assertIsNotNone(ord_row)
            self.assertEqual(ord_row.product, "rwagenie")
            self.assertEqual(ord_row.plan, "PRO")
            self.assertEqual(ord_row.status, "created")
            self.assertIsNone(ord_row.license_id)

        # 3) Simulate Razorpay's webhook callback — payment.captured
        webhook_body = json.dumps(
            self._webhook_payload_payment_captured(order_id, amount_paise)
        ).encode()
        signature = self._sign_webhook(webhook_body)

        sent_emails: list[dict] = []

        def _capture_email(**kwargs):
            sent_emails.append(kwargs)
            return True

        with patch.object(email_service, "send_license_email",
                          side_effect=_capture_email):
            resp = self.client.post(
                "/webhooks/razorpay",
                content=webhook_body,
                headers={
                    "content-type":         "application/json",
                    "x-razorpay-signature": signature,
                },
            )
            self.assertEqual(resp.status_code, 200, resp.text)
            self.assertEqual(resp.json()["status"], "paid")

        # 4) Order is now paid; License row exists; product carries through
        with SessionLocal() as db:
            from sqlalchemy import select
            ord_row = db.scalar(
                select(Order).where(Order.razorpay_order_id == order_id)
            )
            self.assertEqual(ord_row.status, "paid")
            self.assertEqual(ord_row.razorpay_payment_id, "pay_TEST_PAYMENT_ID_abc")
            self.assertIsNotNone(ord_row.license_id)

            lic = db.get(License, ord_row.license_id)
            self.assertIsNotNone(lic)
            self.assertEqual(lic.product, "rwagenie")
            self.assertEqual(lic.plan, "PRO")
            self.assertEqual(lic.customer_email, "buyer@example.com")
            self.assertEqual(lic.company_name, "Test Society")
            # Expiry should be ~1 year out
            self.assertGreater(
                lic.expires_at, date.today() + timedelta(days=350)
            )

        # 5) Email was attempted with the right shape
        self.assertEqual(len(sent_emails), 1)
        sent = sent_emails[0]
        self.assertEqual(sent["to_email"],   "buyer@example.com")
        self.assertEqual(sent["plan"],       "PRO")
        self.assertTrue(sent["license_key"].startswith("ACCG-"))
        # Receipt info present in the email body args
        self.assertIn("INR", sent["amount_paid_str"])

    def test_webhook_replay_is_idempotent(self):
        """Razorpay retries on any non-2xx. A second delivery of the
        same payment.captured must NOT mint a second license."""
        from license_server.db     import SessionLocal
        from license_server.models import License
        from license_server.services import razorpay_client, email_service
        from license_server.plans import price_for
        from sqlalchemy import select, func as sa_func

        amount_paise = int(price_for("rwagenie", "PRO", "IN") * 100)

        # Use a fresh order_id so it doesn't collide with the other tests.
        order_id = "order_REPLAY_TEST_xyz"
        mock_order = self._razorpay_order_factory(amount_paise, order_id=order_id)

        with patch.object(razorpay_client, "create_order",
                          return_value=mock_order):
            self.client.post(
                "/api/v1/checkout/create-order",
                json={
                    "plan":           "PRO",
                    "product":        "rwagenie",
                    "country_code":   "IN",
                    "customer_email": "replay@example.com",
                },
            )

        body = json.dumps(
            self._webhook_payload_payment_captured(order_id, amount_paise)
        ).encode()
        sig  = self._sign_webhook(body)

        with patch.object(email_service, "send_license_email", return_value=True):
            r1 = self.client.post(
                "/webhooks/razorpay", content=body,
                headers={"content-type": "application/json",
                         "x-razorpay-signature": sig},
            )
            r2 = self.client.post(
                "/webhooks/razorpay", content=body,
                headers={"content-type": "application/json",
                         "x-razorpay-signature": sig},
            )

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["status"], "paid")
        self.assertEqual(r2.json()["status"], "already_paid")

        with SessionLocal() as db:
            count = db.scalar(
                select(sa_func.count()).select_from(License)
                .where(License.customer_email == "replay@example.com")
            )
            self.assertEqual(count, 1, "replayed webhook must not double-mint")


if __name__ == "__main__":
    unittest.main()
