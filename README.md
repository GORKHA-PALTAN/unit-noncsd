# Unit Non-CSD App

An online store with an owner dashboard: customers browse, order, pay and track deliveries; the owner controls products, prices, stock, orders, customers, unit buyer codes, reports and AI-assisted demand forecasts.

## Quick start (Windows)

1. Install **Python 3.10 or newer** from python.org. During setup, tick **"Add Python to PATH"**.
2. Unzip this folder and double-click **`start-windows.bat`**. The first start takes about a minute: it installs 3 small packages and creates the sample data.
3. Open **http://127.0.0.1:8000** for the store and **http://127.0.0.1:8000/admin** for the owner dashboard.

The **owner login** is printed in the black console window and saved to `data/FIRST_RUN_OWNER_LOGIN.txt`. After you sign in, change the password (sidebar → Change password) and delete that file. To choose your own email and password instead, copy `.env.example` to `.env` and set `OWNER_EMAIL` and `OWNER_PASSWORD` before the first start.

On macOS or Linux, run `./start-mac-linux.sh`. To run it by hand: `pip install -r requirements.txt` then `python run.py`.

### Demo accounts (sample data)

| Who | Login | Password |
|---|---|---|
| Owner | printed on first start | printed on first start |
| Demo customer (buyer code A-O-1) | customer@demo.local | Demo@1234 |
| Sample staff (Orders, Inventory, Products only) | clerk@unit.local | Clerk@1234 |

## What's inside

**Customer store (mobile-first; the layout follows your reference screenshots).** Menu drawer with department tabs, quick-link cards, "Shop All" and "Categories" sections. Bottom bar with Home, Wishlist, Categories, Orders and Profile. Hero banners, category tiles, featured items, best sellers, offers, new arrivals, recommendations and popular categories. Search, filters (brand, price, rating, availability, offers) and sorting. Product pages with a gallery, specifications and verified reviews. The cart checks stock and prices again before checkout. Checkout covers address, delivery method, coupon, payment and GST. Order tracking shows a progress bar and timeline. Customers can cancel, request returns, keep a wishlist, get notifications and save addresses.

**Owner dashboard.**

- **Overview:** KPIs for the selected period (today, yesterday, 7 days, 30 days, this month, last month, or custom), a sales trend, status and category breakdowns, low and out-of-stock items, and recent orders.
- **Orders:** status workflow, courier and tracking number, cash-on-delivery collection, and packing slips.
- **Returns and refunds.**
- **Customers:** history, money spent, most-bought products, and suspend or reactivate.
- **Unit buyer codes:** codes like `A-O-1`, CSV import with a preview step, and company or rank reports.
- **Catalogue:** products (images, specs, pricing, status) and categories with subcategories.
- **Inventory:** stock adjustments with a full movement log.
- **AI insights and forecast.**
- **Reports and CSV exports.**
- **Finance:** profit and expenses.
- **Banners and coupons.**
- **Staff and permissions.**
- **Settings:** delivery methods, payments, tax, policies, and removing the sample data.
- **Activity log.**

### How stock works
`Available = Physical − Reserved − Unavailable`

- **Order placed:** the units are reserved. One atomic database update means two customers can never buy the same last unit.
- **Dispatched:** the units are taken off physical stock and counted as sold.
- **Cancelled:** the reservation is released.
- **Returned:** the units go back to stock. If they are marked damaged, they are held as unavailable instead.
- **Every change** is written to the movement log.
- **Unpaid online orders** are cancelled automatically after 30 minutes (you can change this), and their stock is released.

### How payments are verified
- **Cash on Delivery:** stays unpaid until staff press **Record cash collected**.
- **Razorpay:** works once you add your keys to `.env`. The server checks Razorpay's HMAC signature with your secret key, then asks Razorpay to confirm the payment status and amount. Signed webhooks are also supported (`/api/payments/razorpay/webhook`). No one can mark an online order as paid by hand.
- **Sandbox:** a clearly labelled test gateway that uses a server-signed, single-use token. **Turn it off in Settings before going live.**

### How the AI analytics work
Everything is calculated from data stored in the app: orders, stock, product views, add-to-cart events, searches and returns. Nothing is made up.

- **Product lists:** best sellers, rising and falling demand, low sales, high interest but low conversion, frequently out of stock, overstock risk, and restock soon.
- **Recommendations:** each one shows the evidence behind it, for example "may run out within 2 days … consider ordering 61 units", with a reorder quantity worked out from recent demand and your supplier lead time.
- **Forecasts (7, 15, 30 or 90 days):** use damped exponential smoothing with weekday seasonality. They are drawn as a dashed line with a shaded likely range, kept apart from the solid line of recorded sales. Each forecast also shows a back-tested error figure and a confidence label.
- **Written briefing (optional):** set `ANTHROPIC_API_KEY` to have an AI model summarise the computed figures.

## Security
- **Sign-in and sessions:** login runs on the server. Sessions use an HttpOnly cookie, and every change you make is checked with a CSRF token. Passwords are stored as PBKDF2 hashes. An account locks after 5 failed logins, and the number of requests per user is limited.
- **Admin access:** the dashboard is protected by roles and permissions checked on the server, not by a hidden link. Staff only see the sections you grant them.
- **Customer privacy:** customers can only see their own orders and addresses.
- **Data checks:** everything sent to the server is validated there. Uploaded images must really be JPG, PNG, WEBP or GIF. Security headers (CSP, X-Frame-Options and others) are set, and CSV exports are protected against formula injection.
- **Secrets:** keys and passwords stay in `.env` on the server and never reach the browser.

## Before going live (checklist)
1. Settings → **Delete all sample data**.
2. Settings → turn **Sandbox test payments** off. Add live Razorpay keys to `.env` and restart.
3. Serve the site over HTTPS, for example behind Nginx or Caddy, and set `COOKIE_SECURE=true`.
4. Set a long random `SECRET_KEY` in `.env`.
5. Back up `data/store.db` and the `uploads/` folder regularly, or switch to PostgreSQL.

## Configuration
Everything lives in `.env`; see `.env.example`. Restart the app after you change it.

- **Database:** SQLite (`data/store.db`) is the default and needs no setup. **PostgreSQL:** set `DATABASE_URL=postgresql://…` and run `pip install "psycopg[binary]"`. The SQL is portable and the adapter is included, but every automated test so far has run on SQLite. Run the test suite against PostgreSQL before relying on it.
- **Delivery services:** add or edit them in Settings with no code changes. Courier tracking numbers are entered on each order. Automatic courier-API syncing is not connected yet, and the Settings page shows it as "Not configured".
- **Email:** add SMTP settings to send emails. In-app notifications always work.

## Tests
```
pip install -r requirements-dev.txt
python -m unittest tests.test_acceptance -v        # 15 tests covering criteria 1–15 (starts its own server on a temp database)
playwright install chromium
python tests/ui_smoke.py http://127.0.0.1:8000 owner@unit.local <password>   # criteria 16–17: phone and desktop click-through
```

| Brief test | Covered by |
|---|---|
| 1 Owner login + protected admin | `test_01` |
| 2 Add product with image | `test_02` |
| 3 Visible when activated | `test_03` |
| 4 Change price and quantity | `test_04` |
| 5–6 Customer orders, admin sees details | `test_05_06` |
| 7 No overselling (6 buyers race for 3 units at once) | `test_07` |
| 8 Status updates and tracking timeline | `test_08` |
| 9 Live dashboard data | `test_09` |
| 10 Top and slow sellers | `test_10` |
| 11 History vs estimate | `test_11` |
| 12 Customer data isolation, staff permissions, CSRF | `test_12` |
| 13 Payment verification (failed, tampered and replayed payments rejected) | `test_13` |
| 14 Exports | `test_14` |
| 15 Persistence after logout and restart | `test_15` |
| 16–17 Mobile and desktop, every section and filter | `ui_smoke.py` |

## Project layout
```
run.py                     start the server
app/main.py                routes, security headers, background job
app/config.py              settings from .env
app/db.py, schema.py       database layer and tables (SQLite / PostgreSQL)
app/security.py            passwords, sessions, permissions, rate limits
app/web.py                 request handling, auth/CSRF checks, validation
app/routes/                auth.py, store.py (customer API), admin.py (owner API)
app/services/              inventory, orders, payments, analytics, reports
app/seed.py                first-run owner, settings and SAMPLE data
static/store/              customer website
static/admin/              owner dashboard
tests/                     acceptance and UI tests
```

## Putting the store online permanently (recommended for QR codes)
See **DEPLOY-ONLINE.md** for step-by-step instructions. It uses free Render hosting with a free Neon database. You get a permanent https address, and the QR codes work on any phone, anywhere.

## Opening the store from anywhere (not just the same Wi-Fi)
**Quick and free (your computer stays the server):**
1. Start the app.
2. Double-click **start-online-windows.bat** (Mac: `bash start-online-mac.sh`) and keep that window open. The first time, it downloads Cloudflare's free connector.
3. In the dashboard, open **Share & QR codes** and press **Refresh**. The "Codes that work anywhere" appear. They work on mobile data and any Wi-Fi.

Things to know:
- The address changes every time the helper restarts, so re-print the codes after a restart.
- The store is only online while your computer is on and both windows are open.
- For a permanent address, host the app on a cloud server or set up a named Cloudflare Tunnel with your own domain, then enter that address under **Use my own fixed web address**.

**Before sharing publicly:** delete the sample data in Settings (this removes the demo logins) and turn off test payments.

## QR codes for phones (customers and owner)
Open the dashboard → **Share & QR codes**. It shows two codes: **Customer store** and **Owner dashboard**. They use this computer's Wi-Fi address automatically.
- Scan with any phone camera. The phone must be on the **same Wi-Fi**, and the app must be running.
- **Download PNG** or **Print** them to put up at the counter.
- If the page says phones can't connect, set `HOST=0.0.0.0` in `.env` and restart. Allow the app through the firewall when Windows asks.
- **Expo Go:** the same page also has two Expo Go codes. They need the helper in `expo-app/` (see `expo-app/README.txt`, which requires Node.js).
