"""R2 photo storage + page cache tests (uses a tiny fake S3 server, no internet needed).
Run:  python -m unittest tests.test_r2
"""
import base64
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PORT, S3PORT = 8766, 8767
BASE = f"http://127.0.0.1:{PORT}"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
STORE, LOG, FAIL = {}, [], [False]


class FakeS3(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _key(self):
        return self.path.split("/", 2)[2]

    def _go(self, method):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        LOG.append((method, self._key()))
        assert "AWS4-HMAC-SHA256" in self.headers.get("Authorization", "")
        if FAIL[0]:
            self.send_response(500); self.end_headers(); return
        k = self._key()
        if method == "PUT":
            STORE[k] = (self.headers.get("Content-Type"), body); self.send_response(200); self.end_headers()
        elif method == "DELETE":
            STORE.pop(k, None); self.send_response(204); self.end_headers()
        elif k in STORE:
            self.send_response(200); self.send_header("Content-Type", STORE[k][0]); self.send_header("Content-Length", str(len(STORE[k][1]))); self.end_headers()
            if method == "GET":
                self.wfile.write(STORE[k][1])
        else:
            self.send_response(404); self.end_headers()

    do_PUT = lambda s: s._go("PUT")
    do_GET = lambda s: s._go("GET")
    do_HEAD = lambda s: s._go("HEAD")
    do_DELETE = lambda s: s._go("DELETE")


class R2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="r2test_"))
        cls.db = cls.tmp / "t.db"
        cls.s3 = ThreadingHTTPServer(("127.0.0.1", S3PORT), FakeS3)
        threading.Thread(target=cls.s3.serve_forever, daemon=True).start()
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{cls.db}", PORT=str(PORT), OWNER_EMAIL="o@unit.local", OWNER_PASSWORD="OwnerTest123",
                   SEED_SAMPLE_DATA="true", RATE_LIMIT_SCALE="50", SECRET_KEY="t", R2_ACCOUNT_ID="acct", R2_ACCESS_KEY_ID="AK",
                   R2_SECRET_ACCESS_KEY="SK", R2_BUCKET="shop", R2_ENDPOINT=f"http://127.0.0.1:{S3PORT}")
        cls.proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=open(cls.tmp / "log", "ab"), stderr=subprocess.STDOUT)
        for _ in range(90):
            try:
                if requests.get(BASE + "/health", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        cls.s = requests.Session()
        r = cls.s.post(BASE + "/api/auth/login", json={"email": "o@unit.local", "password": "OwnerTest123"}, headers={"x-requested-with": "fetch"})
        assert r.ok, r.text
        cls.csrf = r.json()["user"]["csrf"]
        time.sleep(3)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate(); cls.proc.wait(10); cls.s3.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, **kw):
        h = {"x-csrf-token": self.csrf, "x-requested-with": "fetch"}
        return self.s.request(method, BASE + path, headers=h, **kw)

    def test_1_check_and_new_upload_goes_to_r2(self):
        self.assertTrue(self.call("POST", "/api/admin/storage/r2-check").json()["ok"])
        cat = self.call("GET", "/api/admin/categories").json()["items"][0]
        p = self.call("POST", "/api/admin/products", json={"name": "R2 Kettle", "category_id": cat["id"], "selling_price": 100, "mrp": 120, "cost_price": 50, "stock": 5, "status": "active"}).json()
        r = self.call("POST", f"/api/admin/products/{p['id']}/images", files={"files": ("k.png", PNG, "image/png")})
        self.assertEqual(r.status_code, 200, r.text)
        url = r.json()["images"][-1]["url"] if isinstance(r.json()["images"][-1], dict) else r.json()["images"][-1]
        key = url.replace("/uploads/", "", 1)
        self.assertIn(key, STORE)
        # photo must still be served if the local copy is gone: it now comes from R2
        for f in (ROOT / "uploads").rglob(key.split("/")[-1]):
            f.unlink()
        LOG.clear()
        got = requests.get(BASE + url)
        self.assertEqual(got.status_code, 200); self.assertEqual(got.content, STORE[key][1])
        self.assertIn(("GET", key), LOG)
        self.assertIn("max-age=2592000", got.headers["cache-control"])
        self.__class__.url, self.__class__.key = url, key

    def test_2_database_copy_is_a_fallback(self):
        FAIL[0] = True
        try:
            for f in (ROOT / "uploads").rglob(self.key.split("/")[-1]):
                f.unlink()
            got = requests.get(BASE + self.url)
            self.assertEqual(got.status_code, 200); self.assertEqual(got.content, PNG)
        finally:
            FAIL[0] = False

    def test_3_migrate_existing_photos(self):
        con = sqlite3.connect(self.db); con.execute("DELETE FROM r2_files"); con.commit()
        total = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]; con.close()
        STORE.clear()
        st = self.call("GET", "/api/admin/storage").json()["r2"]
        self.assertEqual((st["enabled"], st["copied"]), (True, 0))
        for _ in range(500):
            r = self.call("POST", "/api/admin/storage/r2-migrate").json()
            if not r["left"]:
                break
        self.assertEqual(r["left"], 0)
        self.assertEqual(len(STORE), total)
        con = sqlite3.connect(self.db); self.assertEqual(con.execute("SELECT COUNT(*) FROM files").fetchone()[0], total); con.close()  # DB copies untouched
        self.assertEqual(self.call("GET", "/api/admin/storage").json()["r2"]["copied"], total)
        requests.post(BASE + "/api/admin/storage/r2-migrate", headers={"x-requested-with": "fetch"}).status_code == 401 or self.fail("must need login")

    def test_4_page_cache(self):
        a = requests.get(BASE + "/api/products?q=kettle"); b = requests.get(BASE + "/api/products?q=kettle")
        self.assertEqual(a.json(), b.json()); self.assertEqual(b.headers.get("x-cache"), "hit")
        cat = self.call("GET", "/api/admin/categories").json()["items"][0]
        self.call("POST", "/api/admin/products", json={"name": "Kettle Two", "category_id": cat["id"], "selling_price": 100, "mrp": 120, "cost_price": 50, "stock": 5, "status": "active"})
        c = requests.get(BASE + "/api/products?q=kettle")
        self.assertNotEqual(c.headers.get("x-cache"), "hit")  # an edit clears the cache at once
        self.assertGreater(len(c.json()["items"]), len(a.json()["items"]))
        # signed-in visitors are never served from the shared cache
        self.assertNotEqual(self.call("GET", "/api/products?q=kettle").headers.get("x-cache"), "hit")


if __name__ == "__main__":
    unittest.main()
