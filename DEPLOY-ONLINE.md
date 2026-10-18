# Put the Unit Non-CSD App online (free: Render + Neon)

When you're done, the store has a permanent address like `https://unit-noncsd.onrender.com`. Its two QR codes (Customer and Owner) then work on any Android phone or iPhone, on mobile data or any Wi-Fi, even when your own computer is switched off.

You need: an email address, about 30 minutes, and the folder **unit-noncsd-upload** (in your Documents).

---

## Part 1: Create the database (Neon)
1. Go to **neon.com** and click **Sign up**. Choosing "Continue with Google" is easiest.
2. Create a project:
   - Project name: `unit-noncsd`
   - Region: **Asia Pacific (Singapore)**, or the closest Asia option
   - Click **Create project**.
3. Click **Connect** (or "Connection string").
4. Copy the line that starts with `postgresql://…`. It ends with something like `?sslmode=require`.
5. Paste it into Notepad for now. **Treat it like a password and don't share it.**

## Part 2: Put the code on GitHub
1. Go to **github.com** and sign up.
2. Click **+** (top right), then **New repository**.
   - Name: `unit-noncsd`
   - Select **Private**
   - Click **Create repository**.
3. On the next page, click the link **"uploading an existing file"**.
4. Open **Documents → unit-noncsd-upload**. Select **everything inside it** (Ctrl + A) and drag it into the GitHub page.
5. Wait for the upload to finish, then click **Commit changes**.

## Part 3: Start the website (Render)
1. Go to **render.com**, click **Get Started**, and choose **GitHub** to sign in.
2. Click **New +**, then **Web Service**. Allow Render to see your `unit-noncsd` repository and select it.
3. Fill in:
   - **Name:** `unit-noncsd` (this becomes the web address)
   - **Region:** Singapore
   - **Branch:** main
   - **Runtime / Language:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python run.py`
   - **Instance type:** **Free**
4. Under **Environment Variables**, click **Add** for each of these:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Neon line from Part 1 |
   | `OWNER_EMAIL` | the email you'll use to log in as owner |
   | `OWNER_PASSWORD` | a strong password (8+ characters, letters and numbers) |
   | `PYTHON_VERSION` | `3.12.7` |
   | `COOKIE_SECURE` | `true` |
   | `FORWARDED_ALLOW_IPS` | `*` |
   | `SEED_DEMO_ACCOUNTS` | `false` |

5. Click **Create Web Service**. Wait 3–6 minutes until it shows **Live** in green.
6. Your address is shown at the top, for example `https://unit-noncsd.onrender.com`.

## Part 4: Get your two QR codes
1. On your phone or computer, open `https://YOUR-ADDRESS.onrender.com/admin`.
2. Log in with the `OWNER_EMAIL` and `OWNER_PASSWORD` you entered in Part 3.
3. Open **Share & QR codes**. You'll see the **Customer store** and **Owner dashboard** codes with your permanent address.
4. Click **Download PNG** or **Print**. These codes never change.
5. The sample products take about 5 minutes to appear after the first start.

## Part 5: Before real customers use it
1. **Settings → Delete all sample data**
2. **Settings → turn off "Sandbox test payments"**. Cash on Delivery stays on.
3. Optional: for UPI/card payments, add `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` under Render → Environment.

---

### Good to know
- **Free plan sleep:** if nobody opens the store for 15 minutes, it goes to sleep. The next person to scan waits about 1 minute while it wakes, then it's fast again.
  - Optional fix: create a free account at **cron-job.org** and add a job that opens `https://YOUR-ADDRESS.onrender.com/health` every 10 minutes. This keeps the store awake.
- **Your data is safe** in the Neon database. Restarts don't erase orders, products or uploaded photos.
- **Free limits** are plenty for a unit store:
  - Neon: 1 GB of storage. Photos count toward this, so keep product photos under about 1 MB each.
  - Render: about 5 GB of traffic a month.
- **Updating later:** upload the changed files to the same GitHub repository. Render updates the site automatically within a few minutes.
- **If something goes wrong:** in Render, open your service, then **Logs**. Send a screenshot of the red lines and it can be fixed.
