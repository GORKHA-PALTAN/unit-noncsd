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

    def test_17_banner_photo_upload(self):
        import base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        r = self.owner.post("/api/admin/banners", {"title": "Photo test", "subtitle": "", "cta": "Go", "link": "#/", "theme": "navy", "department": "", "sort": 99, "active": True}, expect=200).json()
        items = self.owner.get("/api/admin/banners").json()["items"]
        bid = [b for b in items if b["title"] == "Photo test"][0]["id"]
        up = self.owner.call("POST", f"/api/admin/banners/{bid}/image", files={"file": ("a.png", png, "image/png")}, expect=200).json()
        self.assertTrue(up["image"].startswith("/uploads/banners/"))
        self.assertEqual(self.owner.get(up["image"]).status_code, 200)
        self.owner.call("POST", f"/api/admin/banners/{bid}/image", files={"file": ("a.txt", b"hello", "text/plain")}, expect=400)
        home = self.owner.get("/api/home").json()
        self.assertIn(up["image"], [b["image_url"] for b in home["banners"]])
        self.owner.call("DELETE", f"/api/admin/banners/{bid}/image", expect=200)
        items = self.owner.get("/api/admin/banners").json()["items"]
        self.assertFalse([b for b in items if b["id"] == bid][0]["image_url"])
        self.owner.call("DELETE", f"/api/admin/banners/{bid}", expect=200)

    def test_18_banner_video_upload(self):
        self.owner.post("/api/admin/banners", {"title": "Video test", "subtitle": "", "cta": "Go", "link": "#/", "theme": "navy", "department": "", "sort": 98, "active": True}, expect=200)
        bid = [b for b in self.owner.get("/api/admin/banners").json()["items"] if b["title"] == "Video test"][0]["id"]
        mp4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 5000
        up = self.owner.call("POST", f"/api/admin/banners/{bid}/video", files={"file": ("v.mp4", mp4, "video/mp4")}, expect=200).json()
        self.assertTrue(up["video"].endswith(".mp4"))
        r = self.owner.s.get(BASE + up["video"], headers={"Range": "bytes=0-99"})
        self.assertIn(r.status_code, (200, 206))
        self.assertEqual(r.headers["content-type"], "video/mp4")
        self.owner.call("POST", f"/api/admin/banners/{bid}/video", files={"file": ("v.exe", b"MZ" + b"\x00" * 100, "video/mp4")}, expect=400)
        home = self.owner.get("/api/home").json()
        self.assertIn(up["video"], [b["video_url"] for b in home["banners"]])
        self.owner.call("DELETE", f"/api/admin/banners/{bid}/video", expect=200)
        self.owner.call("DELETE", f"/api/admin/banners/{bid}", expect=200)

    def test_19_banner_audio_upload(self):
        self.owner.post("/api/admin/banners", {"title": "Audio test", "subtitle": "", "cta": "Go", "link": "#/", "theme": "navy", "department": "", "sort": 97, "active": True}, expect=200)
        bid = [b for b in self.owner.get("/api/admin/banners").json()["items"] if b["title"] == "Audio test"][0]["id"]
        mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\xff\xfb\x90\x00" + b"\x00" * 2000
        up = self.owner.call("POST", f"/api/admin/banners/{bid}/audio", files={"file": ("a.mp3", mp3, "audio/mpeg")}, expect=200).json()
        r = self.owner.s.get(BASE + up["audio"], headers={"Range": "bytes=0-99"})
        self.assertIn(r.status_code, (200, 206))
        self.owner.call("POST", f"/api/admin/banners/{bid}/audio", files={"file": ("a.exe", b"MZ" + b"\x00" * 100, "audio/mpeg")}, expect=400)
        home = self.owner.get("/api/home").json()
        self.assertIn(up["audio"], [b["audio_url"] for b in home["banners"]])
        self.owner.call("DELETE", f"/api/admin/banners/{bid}/audio", expect=200)
        self.owner.call("DELETE", f"/api/admin/banners/{bid}", expect=200)

    def test_20_vendor_flow(self):
        import base64, secrets as _s
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        em = f"v{_s.token_hex(3)}@example.com"
        cat = self.owner.get("/api/meta").json()["categories"][0]["id"]
        mine = self.new_product(stock=5)
        self.owner.post("/api/admin/vendors", {"business_name": "Test Traders", "contact_name": "Ravi", "email": em, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        vid = [v for v in self.owner.get("/api/admin/vendors").json()["items"] if v["email"] == em][0]["id"]
        v = Client(); v.login(em, "Vendor@12345")
        # vendor cannot reach owner or customer areas
        v.get("/api/admin/products", expect=403); v.get("/api/admin/vendors", expect=403)
        pid = v.post("/api/vendor/products", {"name": "Vendor Widget", "category_id": cat, "selling_price": 250, "mrp": 300, "stock": 7, "status": "active", "featured": True, "cost_price": 5}, expect=200).json()["id"]
        # hidden from the store until approved, even though vendor asked for 'active'
        self.assertEqual(Client().get("/api/products?q=Vendor+Widget").json().get("total", 0), 0)
        self.assertEqual(self.owner.get(f"/api/admin/products/{pid}").json()["status"], "draft")
        v.call("POST", f"/api/vendor/products/{pid}/images", files=[("files", ("a.png", png, "image/png"))], expect=200)
        # vendor sees only own products; owner's product is not visible/editable to vendor
        self.assertEqual([x["id"] for x in v.get("/api/vendor/products").json()["items"]], [pid])
        v.get(f"/api/vendor/products/{mine['id']}", expect=404)
        v.put(f"/api/vendor/products/{mine['id']}", {"name": "Hacked", "category_id": cat, "selling_price": 1}, expect=404)
        v.call("PATCH", f"/api/vendor/products/{mine['id']}/stock", json={"stock": 999}, expect=404)
        # owner approves -> visible in store with 'sold_by'
        self.owner.post(f"/api/admin/vendor-products/{pid}/review", {"decision": "approve"}, expect=200)
        self.assertEqual(self.owner.get(f"/api/admin/products/{pid}").json()["status"], "active")
        slug = self.owner.get(f"/api/admin/products/{pid}").json()["slug"]
        self.assertEqual(Client().get(f"/api/products/{slug}").json()["sold_by"], "Test Traders")
        # stock change by vendor
        v.call("PATCH", f"/api/vendor/products/{pid}/stock", json={"stock": 12}, expect=200)
        self.assertEqual(self.owner.get(f"/api/admin/products/{pid}").json()["physical_stock"], 12)
        # editing live content sends it back for approval
        v.put(f"/api/vendor/products/{pid}", {"name": "Vendor Widget Pro", "category_id": cat, "selling_price": 250}, expect=200)
        self.assertEqual(self.owner.get(f"/api/admin/products/{pid}").json()["status"], "draft")
        # owner's own product shows 'Sold by' shop name
        self.assertTrue(Client().get(f"/api/products/{mine['slug']}").json()["sold_by"])
        # suspended vendor is locked out
        self.owner.put(f"/api/admin/vendors/{vid}", {"business_name": "Test Traders", "contact_name": "Ravi", "commission_pct": 10, "status": "suspended"}, expect=200)
        v.get("/api/vendor/products", expect=401)
        c = Client(); c.register(); c.get("/api/vendor/products", expect=403); c.get("/api/admin/vendors", expect=403)

    def test_21_vendor_business_dashboard(self):
        import secrets as _s, sqlite3
        em1, em2 = f"a{_s.token_hex(3)}@example.com", f"b{_s.token_hex(3)}@example.com"
        for em, nm in ((em1, "Alpha Traders"), (em2, "Beta Traders")):
            self.owner.post("/api/admin/vendors", {"business_name": nm, "contact_name": "Owner Person", "email": em, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        vids = {v["email"]: v["id"] for v in self.owner.get("/api/admin/vendors").json()["items"]}
        A, B = Client(), Client(); A.login(em1, "Vendor@12345"); B.login(em2, "Vendor@12345")
        cat = self.cat["id"]
        def vendor_product(cl, name):
            pid = cl.post("/api/vendor/products", {"name": name, "category_id": cat, "selling_price": 1000, "stock": 20}, expect=200).json()["id"]
            self.owner.post(f"/api/admin/vendor-products/{pid}/review", {"decision": "approve"}, expect=200)
            return pid
        pa, pb = vendor_product(A, "Alpha Item " + _s.token_hex(2)), vendor_product(B, "Beta Item " + _s.token_hex(2))
        mine = self.new_product(stock=5)
        c = Client(); c.register()
        c.post("/api/cart", {"product_id": pa, "qty": 2}, expect=200); c.post("/api/cart", {"product_id": pb, "qty": 1}, expect=200); c.post("/api/cart", {"product_id": mine["id"], "qty": 1}, expect=200)
        addr = c.add_address()
        q = c.post("/api/checkout/quote", {"payment_method": "cod"}, expect=200).json()
        o = c.post("/api/orders", {"address_id": addr["id"], "payment_method": "cod", "expected_total": q["grand_total"]}, expect=200).json()
        oid = self.owner.get(f"/api/admin/orders?q={o['order_no']}").json()["items"][0]["id"]
        # each vendor sees ONLY their own items, never the other vendor's or the owner's
        la = A.get("/api/vendor/orders?filter=to_ship").json()["items"]
        lb = B.get("/api/vendor/orders?filter=to_ship").json()["items"]
        self.assertEqual([i["name"] for x in la if x["id"] == oid for i in x["items"]][0].startswith("Alpha"), True)
        self.assertEqual(len([x for x in la if x["id"] == oid][0]["items"]), 1)
        self.assertEqual(len([x for x in lb if x["id"] == oid][0]["items"]), 1)
        self.assertNotIn("email", str([x for x in la if x["id"] == oid][0]))
        self.assertEqual([x for x in la if x["id"] == oid][0]["total"], 2000.0)
        # vendor B cannot act on a different vendor's part, and cannot touch an order with none of their items
        other = c.order(mine["id"]).json()["order_no"]; ooid = self.owner.get(f"/api/admin/orders?q={other}").json()["items"][0]["id"]
        A.post(f"/api/vendor/orders/{ooid}/fulfil", {"action": "pack"}, expect=404)
        A.post(f"/api/vendor/orders/{oid}/fulfil", {"action": "ship"}, expect=400)  # tracking number required
        A.post(f"/api/vendor/orders/{oid}/fulfil", {"action": "pack"}, expect=200)
        A.post(f"/api/vendor/orders/{oid}/fulfil", {"action": "ship", "courier": "BlueDart", "tracking_no": "BD123"}, expect=200)
        od = c.get(f"/api/orders/{o['order_no']}").json()
        self.assertEqual([(x["vendor"], x["status"], x["tracking_no"]) for x in od["shipments"]], [("Alpha Traders", "shipped", "BD123")])
        self.assertTrue(any("shipped" in (e.get("note") or "") for e in od["timeline"]))
        self.assertTrue(any("items shipped" in n["title"] for n in c.get("/api/notifications").json()["items"]))
        detail = self.owner.get(f"/api/admin/orders/{oid}").json()
        self.assertEqual([p["status"] for p in detail["vendor_parts"]], ["shipped"])
        self.assertTrue(any(i["vendor"] == "Alpha Traders" for i in detail["items"]))
        # owner moves the order to delivered -> earnings appear (10% commission), still clearing for the return window
        for st in ("confirmed", "packed", "dispatched", "delivered"):
            self.owner.post(f"/api/admin/orders/{oid}/status", {"status": st}, expect=200)
        ea = A.get("/api/vendor/earnings").json()
        self.assertEqual(ea["summary"]["clearing"], 1800.0)
        self.assertEqual(ea["summary"]["commission"], 200.0)
        self.assertEqual(ea["summary"]["due_now"], 0)
        self.assertEqual(B.get("/api/vendor/earnings").json()["summary"]["clearing"], 900.0)
        self.owner.post(f"/api/admin/vendors/{vids[em1]}/payouts", {"method": "upi", "amount": 0}, expect=400)
        # after the return window the money becomes payable (SQLite test database only)
        if not os.environ.get("TEST_DATABASE_URL"):
            con = sqlite3.connect(DB); con.execute("UPDATE orders SET delivered_at='2020-01-01T00:00:00' WHERE id=?", (oid,)); con.commit(); con.close()
            led = self.owner.get(f"/api/admin/vendors/{vids[em1]}/ledger").json()
            self.assertEqual(led["summary"]["due_now"], 1800.0)
            self.owner.post(f"/api/admin/vendors/{vids[em1]}/payouts", {"method": "upi", "amount": 1, "reference": "UTR1"}, expect=409)
            self.owner.post(f"/api/admin/vendors/{vids[em1]}/payouts", {"method": "upi", "amount": 1800, "reference": "UTR1"}, expect=200)
            self.owner.post(f"/api/admin/vendors/{vids[em1]}/payouts", {"method": "upi", "amount": 1800}, expect=409)  # no double payment
            es = A.get("/api/vendor/earnings").json()
            self.assertEqual(es["summary"]["paid"], 1800.0); self.assertEqual(es["summary"]["due_now"], 0)
            self.assertEqual(len(es["payouts"]), 1)
        # overview + reports work and are scoped
        ov = A.get("/api/vendor/overview").json()
        self.assertEqual(ov["month"]["amount"], 2000.0)
        self.assertEqual(B.get("/api/vendor/overview").json()["month"]["amount"], 1000.0)
        rep = A.get("/api/vendor/report?kind=sales")
        self.assertEqual(rep.status_code, 200); self.assertIn("Alpha Item", rep.text); self.assertNotIn("Beta Item", rep.text)
        # a customer or an outsider cannot reach vendor data
        c.get("/api/vendor/overview", expect=403); Client().get("/api/vendor/orders", expect=401)
        A.get("/api/admin/vendors/1/ledger", expect=403)

    def test_24_item_returns(self):
        import secrets as _s, sqlite3
        em = f"r{_s.token_hex(3)}@example.com"
        self.owner.post("/api/admin/vendors", {"business_name": "Return Traders", "contact_name": "Owner Person", "email": em, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        vid = [v["id"] for v in self.owner.get("/api/admin/vendors").json()["items"] if v["email"] == em][0]
        V = Client(); V.login(em, "Vendor@12345")
        pid = V.post("/api/vendor/products", {"name": "Ret Item " + _s.token_hex(2), "category_id": self.cat["id"], "selling_price": 1000, "stock": 20}, expect=200).json()["id"]
        self.owner.post(f"/api/admin/vendor-products/{pid}/review", {"decision": "approve"}, expect=200)
        mine = self.new_product(stock=5)
        c = Client(); c.register()
        c.post("/api/cart", {"product_id": pid, "qty": 3}, expect=200); c.post("/api/cart", {"product_id": mine["id"], "qty": 1}, expect=200)
        addr = c.add_address()
        q = c.post("/api/checkout/quote", {"payment_method": "cod"}, expect=200).json()
        o = c.post("/api/orders", {"address_id": addr["id"], "payment_method": "cod", "expected_total": q["grand_total"]}, expect=200).json()
        no = o["order_no"]; oid = self.owner.get(f"/api/admin/orders?q={no}").json()["items"][0]["id"]
        det = c.get(f"/api/orders/{no}").json()
        item = [i for i in det["items"] if i["product_id"] == pid][0]
        c.post(f"/api/orders/{no}/item-returns", {"items": [{"item_id": item["id"], "qty": 1}], "reason": "Broken"}, expect=400)  # not delivered yet
        for st in ("confirmed", "packed", "dispatched", "delivered"):
            self.owner.post(f"/api/admin/orders/{oid}/status", {"status": st}, expect=200)
        self.owner.post(f"/api/admin/orders/{oid}/collect-cash", expect=200)
        det = c.get(f"/api/orders/{no}").json()
        self.assertTrue(det["actions"]["can_return_items"]); self.assertEqual([i["returnable"] for i in det["items"] if i["product_id"] == pid], [3])
        c.post(f"/api/orders/{no}/item-returns", {"items": [{"item_id": item["id"], "qty": 4}], "reason": "Broken"}, expect=400)
        c.post(f"/api/orders/{no}/item-returns", {"items": [{"item_id": item["id"], "qty": 1}], "reason": "Broken"}, expect=200)
        c.post(f"/api/orders/{no}/return", {"reason": "whole"}, expect=400)  # whole-order return blocked
        self.assertEqual([i["returnable"] for i in c.get(f"/api/orders/{no}").json()["items"] if i["product_id"] == pid], [2])
        rid = [r["id"] for r in self.owner.get("/api/admin/item-returns").json()["items"] if r["order_no"] == no][0]
        self.owner.post(f"/api/admin/item-returns/{rid}/receive", {}, expect=400)  # must approve first
        # the vendor decides on their own product's return; another vendor / a customer cannot
        em2 = f"x{_s.token_hex(3)}@example.com"
        self.owner.post("/api/admin/vendors", {"business_name": "Other Traders", "contact_name": "Owner Person", "email": em2, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        X = Client(); X.login(em2, "Vendor@12345")
        X.post(f"/api/vendor/item-returns/{rid}/decide", {"action": "approve"}, expect=404)
        c.post(f"/api/vendor/item-returns/{rid}/decide", {"action": "approve"}, expect=403)
        V.post(f"/api/vendor/item-returns/{rid}/decide", {"action": "approve"}, expect=200)
        V.post(f"/api/vendor/item-returns/{rid}/decide", {"action": "reject"}, expect=400)  # already decided
        before = self.owner.get(f"/api/admin/products/{pid}").json()["physical_stock"]
        self.owner.post(f"/api/admin/item-returns/{rid}/refund", {}, expect=400)  # must receive first
        V.post(f"/api/vendor/item-returns/{rid}/receive", {"restock": True}, expect=200)
        self.assertEqual(self.owner.get(f"/api/admin/products/{pid}").json()["physical_stock"], before + 1)
        V.post(f"/api/vendor/item-returns/{rid}/refund", {}, expect=404)  # refunds stay with the owner
        self.owner.post(f"/api/admin/item-returns/{rid}/refund", {"reference": "UTRX"}, expect=200)
        self.owner.post(f"/api/admin/item-returns/{rid}/refund", {}, expect=400)  # no double refund
        row = [r for r in c.get(f"/api/orders/{no}").json()["item_returns"] if r["id"] == rid][0]
        self.assertEqual(row["status"], "refunded"); self.assertEqual(row["amount"], 1000.0)
        # vendor earnings: 3 x 1000 - 10% = 2700, minus the returned unit (900) = 1800, still clearing
        ea = V.get("/api/vendor/earnings").json()
        self.assertEqual(ea["summary"]["clearing"], 1800.0); self.assertEqual(ea["summary"]["commission"], 200.0)
        self.assertEqual(len(ea["adjustments"]), 1)
        self.assertEqual(len(V.get("/api/vendor/item-returns").json()["items"]), 1)
        Client().get("/api/admin/item-returns", expect=401)
        ms = self.owner.get("/api/admin/marketplace-summary", expect=200).json()
        self.assertGreater(ms["totals"]["commission"], 0); self.assertTrue(any(x["name"] == "Return Traders" for x in ms["vendors"]))
        V.get("/api/admin/marketplace-summary", expect=403)
        V.put("/api/vendor/payout-details", {"upi": "bad"}, expect=400)
        V.put("/api/vendor/payout-details", {"bank_holder": "R Traders", "bank_account": "123456789012", "bank_ifsc": "SBIN0001234"}, expect=200)
        V.put("/api/vendor/payout-details", {"upi": "rtraders@okbank"}, expect=200)
        self.assertEqual(V.get("/api/vendor/payout-details").json()["upi"], "rtraders@okbank")
        self.assertEqual(self.owner.get(f"/api/admin/vendors/{vid}/ledger").json()["vendor"]["upi"], "rtraders@okbank")
        # a rejected request frees the quantity again
        c.post(f"/api/orders/{no}/item-returns", {"items": [{"item_id": item["id"], "qty": 2}], "reason": "Changed mind"}, expect=200)
        r2 = [r["id"] for r in self.owner.get("/api/admin/item-returns").json()["items"] if r["order_no"] == no and r["status"] == "requested"][0]
        self.owner.post(f"/api/admin/item-returns/{r2}/decide", {"action": "reject", "note": "Used"}, expect=200)
        self.assertEqual([i["returnable"] for i in c.get(f"/api/orders/{no}").json()["items"] if i["product_id"] == pid], [2])
        # after the window the rest becomes payable; pay it; then a later return is clawed back from the next payout
        if not os.environ.get("TEST_DATABASE_URL"):
            con = sqlite3.connect(DB); con.execute("UPDATE orders SET delivered_at='2020-01-01T00:00:00' WHERE id=?", (oid,)); con.commit(); con.close()
            self.assertEqual(self.owner.get(f"/api/admin/vendors/{vid}/ledger").json()["summary"]["due_now"], 1800.0)
            self.owner.post(f"/api/admin/vendors/{vid}/payouts", {"method": "upi", "amount": 1800, "reference": "U9"}, expect=200)

    def test_25_new_vendor_empty_dashboard(self):
        import secrets as _s
        em = f"n{_s.token_hex(3)}@example.com"
        self.owner.post("/api/admin/vendors", {"business_name": "Fresh Traders", "contact_name": "Owner Person", "email": em, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        V = Client(); V.login(em, "Vendor@12345")
        # no products, no orders yet
        for path in ("/api/vendor/overview", "/api/vendor/earnings", "/api/vendor/orders?filter=to_ship", "/api/vendor/orders?filter=returns", "/api/vendor/products",
                     "/api/vendor/item-returns", "/api/vendor/shop", "/api/vendor/payout-details", "/api/vendor/report?kind=sales", "/api/vendor/report?kind=earnings", "/api/vendor/report?kind=products"):
            V.get(path, expect=200)
        pid = V.post("/api/vendor/products", {"name": "Fresh Item", "category_id": self.cat["id"], "selling_price": 100, "stock": 5}, expect=200).json()["id"]
        V.post(f"/api/vendor/products/{pid}/images", files={"files": ("a.png", PNG, "image/png")}, expect=200)
        for path in ("/api/vendor/overview", "/api/vendor/earnings", "/api/vendor/products", "/api/vendor/report?kind=sales", "/api/vendor/report?kind=earnings", "/api/vendor/report?kind=products"):
            V.get(path, expect=200)
        self.owner.get("/api/admin/vendors", expect=200); self.owner.get("/api/admin/marketplace-summary", expect=200)
        self.owner.get("/api/admin/vendor-products?approval=pending", expect=200)

    def test_26_photos_are_shrunk_and_storage_report(self):
        import io
        from PIL import Image
        import random
        random.seed(1)
        im = Image.frombytes("RGB", (3000, 2000), bytes(random.getrandbits(8) for _ in range(3000 * 2000 * 3)))
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=95); big = buf.getvalue()
        self.assertGreater(len(big), 3 * 1024 * 1024)
        p = self.new_product(stock=3)
        r = self.owner.call("POST", f"/api/admin/products/{p['id']}/images", files={"files": ("big.jpg", big, "image/jpeg")}, expect=200).json()
        url = (r.get("images") or r.get("items") or [{}])[-1].get("url") if isinstance(r, dict) else None
        st = self.owner.get("/api/admin/storage").json()
        self.assertGreater(st["used"], 0); self.assertTrue(any(f["folder"] == "products" for f in st["folders"]))
        self.owner.post("/api/admin/storage/shrink", {}, expect=200)
        prod = self.owner.get(f"/api/admin/products/{p['id']}").json()
        img = prod["images"][-1]["url"] if prod.get("images") else None
        self.assertTrue(img)
        got = requests.get(BASE + img); self.assertEqual(got.status_code, 200)
        w, h = Image.open(io.BytesIO(got.content)).size
        self.assertLessEqual(max(w, h), 1200); self.assertLess(len(got.content), 1.5 * 1024 * 1024)
        Client().get("/api/admin/storage", expect=401)
        c = self.owner.post("/api/admin/storage/compact", {}, expect=200).json()
        self.assertLessEqual(c["after"], c["before"])
        Client().post("/api/admin/storage/compact", {}, expect=401)

    def test_27_free_narrative(self):
        r = self.owner.post("/api/admin/analytics/narrative", expect=200).json()
        self.assertTrue(r["text"]); self.assertIn("Sales in the last 30 days", r["text"]); self.assertTrue(r.get("builtin"))
        Client().post("/api/admin/analytics/narrative", expect=401)

    def test_28_installable_app_files(self):
        for path, kind in (("/manifest.webmanifest", "manifest"), ("/vendor.webmanifest", "manifest"), ("/sw.js", "javascript"), ("/static/common/pwa-512.png", "png"), ("/static/common/offline.html", "html")):
            r = requests.get(BASE + path); self.assertEqual(r.status_code, 200, path); self.assertIn(kind, r.headers["content-type"] + path)
        m = requests.get(BASE + "/manifest.webmanifest").json()
        self.assertEqual(m["display"], "standalone"); self.assertTrue(any(i["purpose"] == "maskable" for i in m["icons"]))
        self.assertIn('rel="manifest"', requests.get(BASE + "/").text)

    def test_22_vendor_shop_page(self):
        import secrets as _s, base64
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        em = f"s{_s.token_hex(3)}@example.com"
        self.owner.post("/api/admin/vendors", {"business_name": "Shop Page Co", "contact_name": "Ravi", "email": em, "password": "Vendor@12345", "commission_pct": 10}, expect=200)
        vid = [v for v in self.owner.get("/api/admin/vendors").json()["items"] if v["email"] == em][0]["id"]
        v = Client(); v.login(em, "Vendor@12345")
        pid = v.post("/api/vendor/products", {"name": "Shop Item " + _s.token_hex(2), "category_id": self.cat["id"], "selling_price": 100, "stock": 3}, expect=200).json()["id"]
        shop = Client().get(f"/api/shops/{vid}").json()
        self.assertEqual(shop["items"], [])  # unapproved products are not shown
        self.owner.post(f"/api/admin/vendor-products/{pid}/review", {"decision": "approve"}, expect=200)
        v.put("/api/vendor/shop", {"about": "We sell good things"}, expect=200)
        v.call("POST", "/api/vendor/shop/logo", files={"file": ("l.png", png, "image/png")}, expect=200)
        shop = Client().get(f"/api/shops/{vid}").json()
        self.assertEqual((shop["name"], shop["about"], len(shop["items"])), ("Shop Page Co", "We sell good things", 1))
        self.assertTrue(shop["logo"].startswith("/uploads/vendors/"))
        slug = self.owner.get(f"/api/admin/products/{pid}").json()["slug"]
        self.assertEqual(Client().get(f"/api/products/{slug}").json()["sold_by_id"], vid)
        det = Client().get(f"/api/products/{slug}").json()
        self.assertEqual((det["vendor"]["name"], det["vendor"]["about"], det["vendor"]["products"]), ("Shop Page Co", "We sell good things", 1))
        self.assertIn("Shop Page Co", [x["name"] for x in Client().get("/api/home").json()["vendors"]])
        self.assertEqual([c["vendor"] for c in Client().get("/api/products?q=Shop+Item").json()["items"] if c["id"] == pid], ["Shop Page Co"])
        c = Client(); c.register(); c.post("/api/cart", {"product_id": pid, "qty": 1}, expect=200)
        self.assertEqual(c.get("/api/cart").json()["items"][0]["vendor"], "Shop Page Co")
        mine = self.new_product(stock=3); self.assertIsNone(Client().get(f"/api/products/{mine['slug']}").json()["vendor"])
        self.owner.put(f"/api/admin/vendors/{vid}", {"business_name": "Shop Page Co", "contact_name": "Ravi", "commission_pct": 10, "status": "suspended"}, expect=200)
        Client().get(f"/api/shops/{vid}", expect=404)
        Client().get("/api/shops/999999", expect=404)

    def test_23_vendor_application(self):
        import secrets as _s
        em = f"app{_s.token_hex(3)}@example.com"
        form = {"business_name": "Himalaya Gear", "contact_name": "Dil Bahadur", "phone": "9876500000", "email": em, "password": "Gurkha@2026", "about": "Trekking and camping gear", "address": "Dehradun"}
        anon = Client()
        anon.post("/api/vendor-apply", {**form, "password": "short"}, expect=400)
        anon.post("/api/vendor-apply", {**form, "about": ""}, expect=400)
        anon.post("/api/vendor-apply", form, expect=200)
        anon.post("/api/vendor-apply", form, expect=409)  # already applied
        # cannot sign in until approved, and applicants are not users yet
        Client().post("/api/auth/login", {"email": em, "password": "Gurkha@2026"}, expect=401)
        apps = self.owner.get("/api/admin/vendor-applications").json()["items"]
        aid = [a for a in apps if a["email"] == em][0]["id"]
        self.assertNotIn("password", str(apps))
        Client().get("/api/admin/vendor-applications", expect=401)
        c = Client(); c.register(); c.get("/api/admin/vendor-applications", expect=403)
        self.owner.post(f"/api/admin/vendor-applications/{aid}/approve", {"commission_pct": 12}, expect=200)
        self.owner.post(f"/api/admin/vendor-applications/{aid}/approve", {"commission_pct": 12}, expect=404)  # only once
        v = Client(); v.login(em, "Gurkha@2026")
        self.assertEqual(v.get("/api/vendor/me").json()["vendor"]["commission_pct"], 12)
        self.assertEqual(v.get("/api/vendor/shop").json()["about"], "Trekking and camping gear")
        anon.post("/api/vendor-apply", form, expect=409)  # email now has an account
        em2 = f"rej{_s.token_hex(3)}@example.com"
        anon.post("/api/vendor-apply", {**form, "email": em2}, expect=200)
        aid2 = [a for a in self.owner.get("/api/admin/vendor-applications").json()["items"] if a["email"] == em2][0]["id"]
        self.owner.post(f"/api/admin/vendor-applications/{aid2}/reject", {"note": "Not now"}, expect=200)
        Client().post("/api/auth/login", {"email": em2, "password": "Gurkha@2026"}, expect=401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
