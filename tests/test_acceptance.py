"""Acceptance tests mapped to the 17 success criteria in the project brief.

Run:  python -m unittest tests.test_acceptance -v
(needs:  pip install requests)

The tests start the real server on a throw-away database, exercise it over HTTP exactly as a browser
would (cookies + CSRF header), restart it to prove persistence, and then delete the test database.
"""
import base64
import concurrent.futures
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("TEST_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
OWNER_EMAIL = "owner-test@unit.local"
OWNER_PW = "OwnerTest123"
TMP = Path(tempfile.mkdtemp(prefix="ncsd_test_"))
DB = TMP / "test.db"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
_server = None


def start_server():
    global _server
    env = dict(os.environ, DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite:///{DB}"), PORT=str(PORT), OWNER_EMAIL=OWNER_EMAIL, OWNER_PASSWORD=OWNER_PW,
               SEED_SAMPLE_DATA="true", RATE_LIMIT_SCALE="50", SECRET_KEY="test-secret", RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="")
    _server = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=open(TMP / "server.log", "ab"), stderr=subprocess.STDOUT)
    for _ in range(90):
        try:
            if requests.get(BASE + "/health", timeout=1).ok:
                return
        except requests.RequestException:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def stop_server():
    global _server
    if _server:
        _server.terminate()
        try:
            _server.wait(10)
        except subprocess.TimeoutExpired:
            _server.kill()
        _server = None


class Client:
    def __init__(self):
        self.s = requests.Session()
        self.csrf = None

    def call(self, method, path, json=None, files=None, expect=None):
        h = {"X-Requested-With": "fetch"}
        if self.csrf:
            h["X-CSRF-Token"] = self.csrf
        r = self.s.request(method, BASE + path, json=json, files=files, headers=h, timeout=30)
        if expect is not None and r.status_code != expect:
            raise AssertionError(f"{method} {path} -> {r.status_code} (expected {expect}): {r.text[:300]}")
        return r

    def get(self, path, **kw): return self.call("GET", path, **kw)
    def post(self, path, json=None, **kw): return self.call("POST", path, json=json if json is not None else {}, **kw)
    def put(self, path, json=None, **kw): return self.call("PUT", path, json=json, **kw)
    def patch(self, path, json=None, **kw): return self.call("PATCH", path, json=json, **kw)

    def login(self, email, pw):
        r = self.post("/api/auth/login", {"email": email, "password": pw}, expect=200)
        self.csrf = r.json()["user"]["csrf"]
        return r.json()["user"]

    def register(self, name=None):
        email = f"cust_{secrets.token_hex(4)}@test.local"
        r = self.post("/api/auth/register", {"name": name or "Test Customer", "email": email, "password": "Passw0rd!"}, expect=200)
        self.csrf = r.json()["user"]["csrf"]
        self.email = email
        return r.json()["user"]

    def add_address(self):
        return self.post("/api/account/addresses", {"name": "Test Buyer", "phone": "9876543210", "line1": "Qtr 12, Block A",
                                                    "city": "Pune", "state": "Maharashtra", "pincode": "411001"}, expect=200).json()

    def order(self, product_id, qty=1, method="cod"):
        self.post("/api/cart", {"product_id": product_id, "qty": qty}, expect=200)
        addr = self.get("/api/account/addresses").json()["items"]
        aid = addr[0]["id"] if addr else self.add_address()["id"]
        q = self.post("/api/checkout/quote", {"payment_method": method}, expect=200).json()
        return self.post("/api/orders", {"address_id": aid, "payment_method": method, "expected_total": q["grand_total"]})


class Acceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        start_server()
        cls.owner = Client()
        cls.owner.login(OWNER_EMAIL, OWNER_PW)
        for _ in range(240):  # on PostgreSQL the sample data is built in the background
            cats = cls.owner.get("/api/admin/categories", expect=200).json()["items"]
            if cats and cls.owner.get("/api/admin/orders?per=1").json()["total"] > 100:
                break
            time.sleep(1)
        cls.cat = next(c for c in cats if not c["parent_id"])

    @classmethod
    def tearDownClass(cls):
        stop_server()
        for f in TMP.glob("*"):
            f.unlink()
        TMP.rmdir()

    def new_product(self, stock=10, status="active", price=999.0, name=None):
        r = self.owner.post("/api/admin/products", {"name": name or f"Test Product {secrets.token_hex(3)}", "category_id": self.cat["id"],
                                                    "selling_price": price, "mrp": price + 200, "cost_price": price / 2, "stock": stock,
                                                    "status": status, "brand": "TestBrand"}, expect=200)
        return r.json()

    # TEST 1
    def test_01_owner_login_and_protected_admin(self):
        self.owner.get("/api/admin/overview", expect=200)
        anon = Client()
        anon.get("/api/admin/overview", expect=401)
        cust = Client(); cust.register()
        cust.get("/api/admin/overview", expect=403)
        cust.get("/api/admin/products", expect=403)
        bad = Client()
        bad.post("/api/auth/login", {"email": OWNER_EMAIL, "password": "wrong-password"}, expect=401)

    # TEST 2
    def test_02_add_product_with_image(self):
        p = self.new_product(stock=25, status="draft", name="Acceptance Kettle")
        self.assertEqual(p["physical_stock"], 25)
        self.assertEqual(p["category_id"], self.cat["id"])
        r = self.owner.call("POST", f"/api/admin/products/{p['id']}/images", files={"files": ("k.png", PNG, "image/png")}, expect=200)
        self.assertEqual(len(r.json()["images"]), 1)
        # non-images are rejected
        self.owner.call("POST", f"/api/admin/products/{p['id']}/images", files={"files": ("x.png", b"<svg onload=alert(1)>", "image/png")}, expect=400)
        self.__class__.kettle = p

    # TEST 3
    def test_03_product_visible_only_when_active(self):
        p = getattr(self, "kettle", None) or self.new_product(status="draft", name="Acceptance Kettle")
        anon = Client()
        anon.get(f"/api/products/{p['slug']}", expect=404)
        names = [i["name"] for i in anon.get("/api/products?q=Acceptance Kettle").json()["items"]]
        self.assertNotIn(p["name"], names)
        self.owner.patch(f"/api/admin/products/{p['id']}", {"status": "active"}, expect=200)
        names = [i["name"] for i in anon.get("/api/products?q=Acceptance Kettle").json()["items"]]
        self.assertIn(p["name"], names)
        d = anon.get(f"/api/products/{p['slug']}", expect=200).json()
        self.assertTrue(d["images"][0].startswith("/uploads/products/"))

    # TEST 4
    def test_04_change_price_and_quantity_without_code(self):
        p = self.new_product(stock=5)
        self.owner.patch(f"/api/admin/products/{p['id']}", {"selling_price": 777}, expect=200)
        self.owner.post(f"/api/admin/inventory/{p['id']}/adjust", {"type": "received", "qty": 15, "note": "delivery"}, expect=200)
        d = Client().get(f"/api/products/{p['slug']}", expect=200).json()
        self.assertEqual(d["price"], 777)
        self.assertEqual(d["available"], 20)
        # movement is logged
        mv = self.owner.get(f"/api/admin/inventory/movements?product_id={p['id']}").json()["items"]
        self.assertTrue(any(m["type"] == "received" and m["qty"] == 15 for m in mv))
        # invalid price rejected server-side
        self.owner.patch(f"/api/admin/products/{p['id']}", {"selling_price": -5}, expect=400)

    # TEST 5 + 6
    def test_05_06_customer_order_appears_in_admin(self):
        p = self.new_product(stock=10, price=500)
        c = Client(); u = c.register("Order Tester")
        self.assertTrue(len(c.get("/api/products").json()["items"]) > 0)
        r = c.order(p["id"], qty=2)
        self.assertEqual(r.status_code, 200, r.text)
        no = r.json()["order_no"]
        orders = self.owner.get(f"/api/admin/orders?q={no}", expect=200).json()["items"]
        self.assertEqual(len(orders), 1)
        o = self.owner.get(f"/api/admin/orders/{orders[0]['id']}", expect=200).json()
        self.assertEqual(o["customer"]["email"], c.email)
        self.assertEqual(o["customer"]["name"], "Order Tester")
        self.assertEqual(o["items"][0]["product_id"], p["id"])
        self.assertEqual(o["items"][0]["qty"], 2)
        self.assertEqual(o["items"][0]["unit_price"], 500)
        self.assertEqual(o["subtotal"], 1000)
        self.assertEqual(o["ship_address"]["pincode"], "411001")

    # TEST 7
    def test_07_stock_reserved_and_never_oversold(self):
        p = self.new_product(stock=3)
        buyers = []
        for _ in range(6):
            c = Client(); c.register(); c.add_address(); buyers.append(c)
        for c in buyers:  # each puts 1 in cart while stock is available
            c.post("/api/cart", {"product_id": p["id"], "qty": 1}, expect=200)

        def checkout(c):
            aid = c.get("/api/account/addresses").json()["items"][0]["id"]
            return c.post("/api/orders", {"address_id": aid, "payment_method": "cod"}).status_code

        with concurrent.futures.ThreadPoolExecutor(6) as ex:
            codes = list(ex.map(checkout, buyers))
        self.assertEqual(codes.count(200), 3, codes)
        self.assertEqual(codes.count(409), 3, codes)
        prod = self.owner.get(f"/api/admin/products/{p['id']}").json()
        self.assertEqual(prod["reserved_qty"], 3)
        self.assertEqual(prod["available"], 0)
        # cannot add more than available
        c = Client(); c.register()
        c.post("/api/cart", {"product_id": p["id"], "qty": 1}, expect=409)
        # cancelling releases the reservation
        oid = self.owner.get(f"/api/admin/orders?status=placed&per=200").json()["items"]
        mine = [o for o in oid if self.owner.get(f"/api/admin/orders/{o['id']}").json()["items"][0]["product_id"] == p["id"]][0]
        self.owner.post(f"/api/admin/orders/{mine['id']}/status", {"status": "cancelled", "note": "test"}, expect=200)
        prod = self.owner.get(f"/api/admin/products/{p['id']}").json()
        self.assertEqual(prod["reserved_qty"], 2)
        self.assertEqual(prod["available"], 1)

    # TEST 8
    def test_08_status_updates_visible_on_customer_timeline(self):
        p = self.new_product(stock=5)
        c = Client(); c.register()
        no = c.order(p["id"]).json()["order_no"]
        oid = self.owner.get(f"/api/admin/orders?q={no}").json()["items"][0]["id"]
        for st in ("confirmed", "processing", "packed", "dispatched"):
            self.owner.post(f"/api/admin/orders/{oid}/status", {"status": st, "note": f"now {st}"}, expect=200)
        self.owner.put(f"/api/admin/orders/{oid}/shipping", {"courier": "Unit Dispatch", "tracking_no": "UD999"}, expect=200)
        # an illegal jump is refused
        self.owner.post(f"/api/admin/orders/{oid}/status", {"status": "refunded"}, expect=400)
        o = c.get(f"/api/orders/{no}", expect=200).json()
        self.assertEqual(o["status"], "dispatched")
        labels = [e["label"] for e in o["timeline"]]
        for l in ("Order Placed", "Order Confirmed", "Processing", "Packed", "Dispatched"):
            self.assertIn(l, labels)
        self.assertEqual(o["tracking_no"], "UD999")
        # dispatch deducted physical stock
        prod = self.owner.get(f"/api/admin/products/{p['id']}").json()
        self.assertEqual(prod["physical_stock"], 4)
        self.assertEqual(prod["reserved_qty"], 0)
        notes = c.get("/api/notifications").json()["items"]
        self.assertTrue(any("Dispatched" in n["title"] for n in notes))

    # TEST 9
    def test_09_dashboard_shows_real_data(self):
        before = self.owner.get("/api/admin/overview?range=today").json()
        p = self.new_product(stock=5, price=1234)
        c = Client(); c.register()
        total = c.order(p["id"]).json()["grand_total"]
        self.assertEqual(total, 1234)  # free delivery above the threshold
        after = self.owner.get("/api/admin/overview?range=today").json()
        self.assertEqual(after["orders"]["today"], before["orders"]["today"] + 1)
        self.assertAlmostEqual(after["sales"]["today"], before["sales"]["today"] + total, places=2)
        self.assertGreater(after["products"]["total"], 0)
        self.assertEqual(after["products"]["total"], before["products"]["total"] + 1)

    # TEST 10
    def test_10_ai_identifies_top_and_slow_sellers(self):
        d = self.owner.get("/api/admin/analytics/insights", expect=200).json()
        best = d["groups"]["best_sellers"]
        self.assertTrue(best)
        self.assertEqual(best, sorted(best, key=lambda r: -r["revenue_30"]))
        self.assertTrue(d["groups"]["low_sales"])
        for r in d["groups"]["low_sales"]:
            self.assertLessEqual(r["units_30"], 2)
        self.assertTrue(d["recommendations"])
        self.assertTrue(all(r["evidence"] for r in d["recommendations"]))

    # TEST 11
    def test_11_forecast_separates_history_from_estimate(self):
        for h in (7, 15, 30, 90):
            f = self.owner.get(f"/api/admin/analytics/forecast?horizon={h}", expect=200).json()
            self.assertTrue(f["enough_data"])
            self.assertEqual(len(f["forecast"]), h)
            last_hist = f["history"][-1]["day"]
            self.assertTrue(all(p["day"] > last_hist for p in f["forecast"]))
            self.assertTrue(all(p["lo"] <= p["value"] <= p["hi"] for p in f["forecast"]))
            self.assertIn("estimate", f["method"].lower())

    # TEST 12
    def test_12_customer_data_protected(self):
        p = self.new_product(stock=5)
        a = Client(); a.register(); no = a.order(p["id"]).json()["order_no"]
        b = Client(); b.register()
        b.get(f"/api/orders/{no}", expect=404)
        b.post(f"/api/orders/{no}/cancel", {"reason": "x"}, expect=404)
        self.assertEqual(b.get("/api/orders").json()["items"], [])
        # staff without the customers permission
        self.owner.post("/api/admin/staff", {"name": "Clerk", "email": "clerk2@test.local", "password": "Clerk12345", "permissions": ["inventory"]}, expect=200)
        s = Client(); s.login("clerk2@test.local", "Clerk12345")
        s.get("/api/admin/customers", expect=403)
        s.get("/api/admin/orders", expect=403)
        s.get("/api/admin/inventory", expect=200)
        s.get("/api/admin/staff", expect=403)
        s.get("/api/admin/settings", expect=403)
        # CSRF: a signed-in request without the token is refused
        tok = a.csrf; a.csrf = None
        a.post("/api/account/addresses", {"name": "x"}, expect=403)
        a.csrf = tok

    # TEST 13
    def test_13_payments_verified_securely(self):
        p = self.new_product(stock=5, price=300)
        c = Client(); c.register()
        r = c.order(p["id"], method="sandbox")
        self.assertEqual(r.status_code, 200, r.text)
        no, pay = r.json()["order_no"], r.json()["payment"]
        # tampered token is rejected
        c.post("/api/payments/sandbox/complete", {"payment_id": pay["payment_id"], "token": "0" * 64, "outcome": "success"}, expect=400)
        # a failed payment is not marked paid
        res = c.post("/api/payments/sandbox/complete", {"payment_id": pay["payment_id"], "token": pay["token"], "outcome": "fail"}, expect=200).json()
        self.assertFalse(res["ok"])
        o = c.get(f"/api/orders/{no}").json()
        self.assertEqual(o["status"], "payment_pending")
        self.assertNotEqual(o["payment_status"], "paid")
        # the same token cannot be replayed
        c.post("/api/payments/sandbox/complete", {"payment_id": pay["payment_id"], "token": pay["token"], "outcome": "success"}, expect=400)
        # admin cannot hand-mark an online order as paid
        oid = self.owner.get(f"/api/admin/orders?q={no}").json()["items"][0]["id"]
        self.owner.post(f"/api/admin/orders/{oid}/status", {"status": "payment_confirmed"}, expect=400)
        self.owner.post(f"/api/admin/orders/{oid}/collect-cash", expect=400)
        # a fresh, valid attempt succeeds
        pay2 = c.post(f"/api/orders/{no}/pay", {"method": "sandbox"}, expect=200).json()
        res = c.post("/api/payments/sandbox/complete", {"payment_id": pay2["payment_id"], "token": pay2["token"], "outcome": "success"}, expect=200).json()
        self.assertTrue(res["ok"])
        o = c.get(f"/api/orders/{no}").json()
        self.assertEqual(o["payment_status"], "paid")
        self.assertEqual(o["status"], "payment_confirmed")
        # Razorpay endpoint refuses when not configured; signature check works
        c.post("/api/payments/razorpay/verify", {"razorpay_order_id": "x", "razorpay_payment_id": "y", "razorpay_signature": "z"}, expect=404)
        sys.path.insert(0, str(ROOT))
        from app.services.payments import verify_razorpay_signature
        good = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
        self.assertTrue(verify_razorpay_signature("order_1", "pay_1", good, secret="secret"))
        self.assertFalse(verify_razorpay_signature("order_1", "pay_1", "bad", secret="secret"))
        self.assertFalse(verify_razorpay_signature("order_1", "pay_2", good, secret="secret"))

    # TEST 14
    def test_14_exports(self):
        for kind in ("products", "inventory", "orders", "order_items", "sales", "customers", "buyers", "company"):
            r = self.owner.get(f"/api/admin/export/{kind}?range=30d", expect=200)
            self.assertIn("text/csv", r.headers["content-type"])
            self.assertIn("attachment", r.headers["content-disposition"])
            lines = r.content.decode("utf-8-sig").strip().splitlines()
            self.assertGreaterEqual(len(lines), 2, kind)

    # TEST 15
    def test_15_persistence_across_logout_and_restart(self):
        p = self.new_product(stock=7, name=f"Persistent {secrets.token_hex(2)}")
        c = Client(); c.register(); no = c.order(p["id"]).json()["order_no"]
        email = c.email
        c.post("/api/auth/logout", expect=200)
        stop_server(); start_server()
        c2 = Client(); c2.login(email, "Passw0rd!")
        self.assertEqual(c2.get(f"/api/orders/{no}", expect=200).json()["order_no"], no)
        self.owner.login(OWNER_EMAIL, OWNER_PW)
        prod = self.owner.get(f"/api/admin/products/{p['id']}", expect=200).json()
        self.assertEqual(prod["reserved_qty"], 1)

    # Extra: returns restock, rate limiting, security headers
    def test_16_returns_restock_and_headers(self):
        p = self.new_product(stock=4)
        c = Client(); c.register(); no = c.order(p["id"]).json()["order_no"]
        oid = self.owner.get(f"/api/admin/orders?q={no}").json()["items"][0]["id"]
        for st in ("confirmed", "packed", "dispatched", "delivered"):
            self.owner.post(f"/api/admin/orders/{oid}/status", {"status": st}, expect=200)
        self.owner.post(f"/api/admin/orders/{oid}/collect-cash", expect=200)
        c.post(f"/api/orders/{no}/return", {"reason": "Wrong size"}, expect=200)
        req = [r for r in self.owner.get("/api/admin/returns").json()["requests"] if r["order_no"] == no][0]
        self.owner.post(f"/api/admin/returns/{req['id']}/resolve", {"action": "approve"}, expect=200)
        self.owner.post(f"/api/admin/orders/{oid}/status", {"status": "returned", "restock": True}, expect=200)
        prod = self.owner.get(f"/api/admin/products/{p['id']}").json()
        self.assertEqual(prod["physical_stock"], 4)
        self.assertEqual(prod["units_sold"], 0)
        self.owner.post(f"/api/admin/orders/{oid}/status", {"status": "refund_processing"}, expect=200)
        self.owner.post(f"/api/admin/orders/{oid}/status", {"status": "refunded", "reference": "UTR123"}, expect=200)
        o = c.get(f"/api/orders/{no}").json()
        self.assertEqual(o["payment_status"], "refunded")
        self.assertEqual(o["refunds"][0]["reference"], "UTR123")
        h = requests.get(BASE + "/").headers
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        sys.path.insert(0, str(ROOT))
        from app import security
        security.reset_rate_limits()
        hits = [security.rate_limited("login", "1.2.3.4") for _ in range(int(10 * security.config.RATE_LIMIT_SCALE) + 1)]
        self.assertTrue(hits[-1] > 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
