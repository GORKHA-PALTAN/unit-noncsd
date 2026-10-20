/* PVC Paltan Store — owner / staff dashboard. Every action is authorised again on the server. */
(function () {
  const { api, esc, fmt, toast, modal, confirmDialog, promptDialog, formData, debounce } = NC;
  const C = NCCharts;
  const A = { me: null, perms: new Set(), range: "30d", from: "", to: "", cats: null };
  const app = document.getElementById("app");

  const I = (d) => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
  const NAV = [
    ["Business", [
      ["overview", "Overview", null, I('<path d="M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 3v6h8V3z"/>')],
      ["orders", "Orders", "orders", I('<path d="M3 7h13v10H3z"/><path d="M16 10h3l2 3v4h-5"/><circle cx="7" cy="18" r="1.6"/><circle cx="18" cy="18" r="1.6"/>')],
      ["returns", "Returns & refunds", "returns", I('<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>')],
      ["customers", "Customers", "customers", I('<circle cx="9" cy="8" r="4"/><path d="M2 21c.8-4 3.6-6 7-6s6.2 2 7 6"/><path d="M17 11a3 3 0 1 0 0-6M22 21c-.5-2.6-2-4.3-4-5"/>')],
      ["buyers", "Unit buyer codes", "buyers", I('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h4M7 13h10M7 17h6"/>')],
    ]],
    ["Catalogue", [
      ["products", "Products", "products", I('<path d="M21 8 12 3 3 8l9 5 9-5z"/><path d="M3 8v8l9 5 9-5V8"/><path d="M12 13v8"/>')],
      ["categories", "Categories", "products", I('<path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/>')],
      ["inventory", "Inventory", "inventory", I('<path d="M3 21V8l9-5 9 5v13"/><path d="M7 21v-8h10v8"/><path d="M7 17h10"/>')],
    ]],
    ["Intelligence", [
      ["insights", "AI insights & forecast", "analytics", I('<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>')],
      ["reports", "Reports & exports", "reports", I('<path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6M9 13h8M9 17h8"/>')],
      ["finance", "Finance & profit", "finance", I('<path d="M12 2v20M17 6H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>')],
    ]],
    ["Store", [
      ["share", "Share & QR codes", null, I('<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3h-3zM20 14v1M14 20h1M17 17h4v4"/>')],
      ["marketing", "Banners & coupons", "marketing", I('<path d="M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M16 8a5 5 0 0 1 0 8"/>')],
      ["staff", "Staff & permissions", "staff", I('<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/><path d="m17 3 2 2 3-3"/>')],
      ["settings", "Settings", "settings", I('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>')],
      ["audit", "Activity log", "settings", I('<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>')],
    ]],
  ];
  const TITLES = Object.fromEntries(NAV.flatMap((g) => g[1].map((n) => [n[0], n[1]])));
  const can = (p) => !p || A.perms.has(p);
  const PM = { cod: "Cash on Delivery", razorpay: "Razorpay", sandbox: "Sandbox (test)", upi: "UPI (direct)" };
  const RANGES = [["today", "Today"], ["yesterday", "Yesterday"], ["7d", "7 days"], ["30d", "30 days"], ["month", "This month"], ["prev_month", "Last month"], ["custom", "Custom"]];

  // ------------------------------------------------------------------ boot & auth
  async function boot() {
    let me;
    try { me = await api("GET", "/api/auth/me"); } catch (e) { app.innerHTML = `<div class="empty"><h3>Server unavailable</h3><p>${esc(e.message)}</p></div>`; return; }
    if (!me.user) return loginScreen();
    NC.state.csrf = me.user.csrf;
    if (!["owner", "staff"].includes(me.user.role)) {
      app.innerHTML = `<div class="login"><div class="login-box"><img src="/static/common/gurkha-logo.svg" alt="" style="display:block;margin:0 auto 12px;width:auto;height:150px"><h1>Admin access required</h1>
        <p>You are signed in as a customer (${esc(me.user.email)}). Sign out and sign in with an owner or staff account.</p>
        <button class="btn btn-primary btn-block" id="lo">Sign out</button><p style="margin-top:12px"><a href="/" style="color:var(--teal)">← Back to store</a></p></div></div>`;
      document.getElementById("lo").onclick = async () => { await api("POST", "/api/auth/logout"); location.reload(); };
      return;
    }
    A.me = me.user; A.perms = new Set(me.user.permissions || []);
    shell();
    window.addEventListener("hashchange", route);
    route();
  }

  function loginScreen() {
    app.innerHTML = `<div class="login"><form class="login-box" id="lf"><img src="/static/common/gurkha-logo.svg" alt="" style="display:block;margin:0 auto 12px;width:auto;height:150px"><h1>Owner & staff sign-in</h1>
      <p>PVC Paltan Store dashboard</p>
      <label class="fld"><span>Email</span><input name="email" type="email" required autocomplete="username"></label>
      <label class="fld"><span>Password</span><input name="password" type="password" required autocomplete="current-password"></label>
      <div class="issue" id="le" role="alert" style="color:#c62828;font-weight:600;margin-bottom:10px" hidden></div>
      <button class="btn btn-primary btn-block" style="min-height:48px">Sign in</button>
      <p style="margin-top:14px;font-size:13px">First run? The owner email and password are printed in the server console and saved to <code>data/FIRST_RUN_OWNER_LOGIN.txt</code>.</p>
      <p><a href="/" style="color:var(--teal)">← Back to store</a></p></form></div>`;
    document.getElementById("lf").onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("le"); err.hidden = true;
      const b = e.target.querySelector("button"); b.disabled = true;
      try {
        const r = await api("POST", "/api/auth/login", formData(e.target));
        if (!["owner", "staff"].includes(r.user.role)) { await api("POST", "/api/auth/logout").catch(() => {}); NC.state.csrf = null; throw new Error("This account does not have admin access."); }
        location.reload();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; b.disabled = false; }
    };
  }

  function shell() {
    app.innerHTML = `<div class="shell"><aside class="side" id="side">
      <div class="side-brand"><img src="/static/common/logo.svg" alt=""><div><b style="font-size:14px;white-space:nowrap">PVC Paltan Store</b><small>${A.me.role === "owner" ? "Owner dashboard" : "Staff dashboard"}</small></div></div>
      <nav aria-label="Dashboard">${NAV.map(([g, items]) => {
        const vis = items.filter((n) => can(n[2]));
        return vis.length ? `<div class="grp">${g}</div>${vis.map((n) => `<a href="#/${n[0]}" data-nav="${n[0]}">${n[3]}<span>${n[1]}</span>${["orders", "returns", "inventory"].includes(n[0]) ? `<span class="n" data-badge="${n[0]}" hidden></span>` : ""}</a>`).join("")}` : "";
      }).join("")}</nav>
      <div class="side-foot"><a href="/" target="_blank" rel="noopener">↗ View store</a><a href="#" id="chpw">Change password</a><a href="#" id="logout">Sign out</a><div class="side-credit">Created &amp; managed by <b>Surjeet Choudhary</b></div></div></aside>
      <div class="mainc"><header class="topbar"><button class="icon-btn menu-toggle" id="mt" aria-label="Menu">☰</button><h1 id="ttl">Dashboard</h1>
        <div class="who"><span>${esc(A.me.name)} · ${esc(A.me.role)}</span><div class="av">${esc(A.me.name[0])}</div></div></header>
        <div class="content" id="content"></div></div></div>`;
    document.getElementById("mt").onclick = () => document.getElementById("side").classList.toggle("open");
    document.getElementById("logout").onclick = async (e) => { e.preventDefault(); await api("POST", "/api/auth/logout").catch(() => {}); location.hash = ""; location.reload(); };
    document.getElementById("chpw").onclick = (e) => {
      e.preventDefault();
      modal({ title: "Change password", body: `<label class="fld"><span>Current password</span><input type="password" id="pc"></label><label class="fld"><span>New password</span><input type="password" id="pn"><small>At least 8 characters with letters and numbers.</small></label>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Update", cls: "btn-primary", handler: async (el) => { await api("POST", "/api/auth/password", { current: el.querySelector("#pc").value, new: el.querySelector("#pn").value }); toast("Password updated"); } }] });
    };
  }

  async function badges() {
    try {
      if (can("orders")) {
        const o = await api("GET", "/api/admin/orders?status=to_process&per=1");
        setBadge("orders", o.total);
      }
      if (can("returns")) { const r = await api("GET", "/api/admin/returns?status=pending"); setBadge("returns", r.requests.length); }
      if (can("inventory")) { const i = await api("GET", "/api/admin/inventory?filter=out"); setBadge("inventory", i.items.length); }
    } catch (e) { /* non-critical */ }
  }
  function setBadge(k, n) { const el = document.querySelector(`[data-badge="${k}"]`); if (el) { el.textContent = n; el.hidden = !n; } }

  // ------------------------------------------------------------------ router
  function parse() { const h = location.hash.replace(/^#\/?/, ""); const [p, qs] = h.split("?"); return { parts: p.split("/").filter(Boolean), q: new URLSearchParams(qs || "") }; }

  async function route() {
    const { parts, q } = parse();
    const page = parts[0] || "overview";
    document.getElementById("side").classList.remove("open");
    document.querySelectorAll(".side a[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === page));
    document.getElementById("ttl").textContent = TITLES[page] || "Dashboard";
    document.title = (TITLES[page] || "Dashboard") + " · PVC Paltan Store";
    const el = document.getElementById("content");
    el.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
    const navItem = NAV.flatMap((g) => g[1]).find((n) => n[0] === page);
    if (navItem && !can(navItem[2])) { el.innerHTML = `<div class="empty"><div class="ico">🔒</div><h3>No access</h3><p>Your account doesn't have permission for this section. Ask the owner to grant it.</p></div>`; return; }
    try {
      const pages = { share, overview, orders, returns, customers, buyers, products, categories, inventory, insights, reports, finance, marketing, staff, settings, audit };
      if (!pages[page]) throw Object.assign(new Error("Page not found"), { status: 404 });
      await pages[page](el, parts.slice(1), q);
    } catch (e) {
      if (e.status === 401) { location.reload(); return; }
      el.innerHTML = `<div class="empty"><div class="ico">!</div><h3>Couldn't load this section</h3><p>${esc(e.message)}</p><button class="btn btn-primary" id="rt">Try again</button></div>`;
      document.getElementById("rt").onclick = route;
    }
    badges();
  }

  // ------------------------------------------------------------------ shared UI
  function rangeBar(onChange) {
    const wrap = document.createElement("div");
    wrap.className = "toolbar";
    wrap.innerHTML = `<div class="seg" role="group" aria-label="Date range">${RANGES.map(([k, l]) => `<button data-r="${k}" class="${A.range === k ? "on" : ""}">${l}</button>`).join("")}</div>
      <span id="cust" ${A.range === "custom" ? "" : "hidden"}><input type="date" class="inp" id="rf" value="${A.from}" aria-label="From date"> – <input type="date" class="inp" id="rt2" value="${A.to}" aria-label="To date"> <button class="btn btn-sm btn-primary" id="rgo">Apply</button></span>`;
    wrap.querySelectorAll("[data-r]").forEach((b) => (b.onclick = () => {
      A.range = b.dataset.r;
      wrap.querySelectorAll("[data-r]").forEach((x) => x.classList.toggle("on", x === b));
      wrap.querySelector("#cust").hidden = A.range !== "custom";
      if (A.range !== "custom") onChange();
    }));
    wrap.querySelector("#rgo").onclick = () => {
      A.from = wrap.querySelector("#rf").value; A.to = wrap.querySelector("#rt2").value;
      if (!A.from || !A.to) return toast("Choose both dates", "err");
      onChange();
    };
    return wrap;
  }
  const rq = () => `range=${A.range}${A.range === "custom" ? `&from=${A.from}&to=${A.to}` : ""}`;

  const STATUS_CLS = { delivered: "ok", refunded: "ok", cancelled: "bad", delivery_failed: "bad", payment_pending: "warn", cancel_requested: "warn",
    return_requested: "warn", return_in_progress: "warn", refund_processing: "warn", returned: "info", placed: "info", payment_confirmed: "info" };
  const stPill = (s, l) => `<span class="pill ${STATUS_CLS[s] || "teal"}">${esc(l)}</span>`;
  const payPill = (o) => {
    if (o.payment_status === "paid") return `<span class="pill ok">Paid</span>`;
    if (o.payment_status === "refunded") return `<span class="pill">Refunded</span>`;
    if (o.payment_status === "failed") return `<span class="pill bad">Failed</span>`;
    if (o.payment_status === "cancelled") return `<span class="pill">Not charged</span>`;
    return o.payment_method === "cod" ? `<span class="pill warn">COD due</span>` : `<span class="pill warn">Unpaid</span>`;
  };
  const kpi = (label, value, sub = "", cls = "", href = "") => `<${href ? `a href="${href}"` : "div"} class="kpi ${cls}"><div class="k-l">${esc(label)}</div><div class="k-v">${value}</div>${sub ? `<div class="k-s">${sub}</div>` : ""}</${href ? "a" : "div"}>`;
  function pager(el, data, onPage) {
    const pages = Math.max(1, Math.ceil(data.total / data.per));
    const div = document.createElement("div");
    div.className = "pager";
    div.innerHTML = `<span>${fmt.num(data.total)} result${data.total === 1 ? "" : "s"}</span><span>${data.page > 1 ? `<button class="btn btn-sm" data-p="${data.page - 1}">‹ Prev</button>` : ""} Page ${data.page} of ${pages} ${data.page < pages ? `<button class="btn btn-sm" data-p="${data.page + 1}">Next ›</button>` : ""}</span>`;
    div.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => onPage(+b.dataset.p)));
    el.appendChild(div);
  }
  function download(url) {
    const a = document.createElement("a"); a.href = url; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
    toast("Export started");
  }
  async function loadCats() { A.cats = (await api("GET", "/api/admin/categories")).items; return A.cats; }


  // ------------------------------------------------------------------ SHARE / QR CODES
  async function share(el) {
    const d = await api("GET", "/api/admin/share-info");
    let ip = d.addresses[0] || "";
    const card = (c) => `<div class="card qr-card c6"><div class="qr-head qr-${c.tone || "slate"}"><b>${esc(c.title)}</b>${c.who ? `<span>${esc(c.who)}</span>` : ""}</div>
      <div class="qr-img">${NCQR.svg(c.url, 7)}</div><div class="qr-url">${esc(c.url)}</div>
      <div class="qr-acts no-print"><a class="btn btn-sm" download="${esc(d.store_name)} - ${esc(c.title)}.png" href="${NCQR.png(c.url, 12)}">⬇ Download PNG</a><button class="btn btn-sm" data-copy="${esc(c.url)}">Copy link</button></div></div>`;
    const pair = (base, note) => [
      { title: "Customer store", who: "For buyers: browse, order, pay and track" + note, url: base + "/", tone: "teal" },
      { title: "Owner dashboard", who: "For you and staff: sign-in is still required" + note, url: base + "/admin", tone: "navy" },
    ];
    const paint = () => {
      const lan = ip ? `http://${ip}:${d.port}` : "";
      const w = d.warnings;
      const risks = [];
      if (w.sample_staff.length) risks.push(`the sample staff login <b>${esc(w.sample_staff.join(", "))}</b> (its password is in the README)`);
      if (w.demo_customer) risks.push(`the demo customer login <b>customer@demo.local</b>`);
      if (w.sandbox_on) risks.push(`<b>test payments</b> (anyone could “pay” without real money)`);
      el.innerHTML = `
        <div class="card" style="margin-bottom:14px"><div class="card-h"><div><h2>Codes that work anywhere</h2>
          <div class="sub" style="margin:0">For phones on mobile data or any Wi-Fi. This needs an online address for your store.</div></div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${d.public_url ? `<span class="pill ok">Online: ${esc(d.public_url)}</span><button class="btn btn-sm btn-primary no-print" id="qprint2">🖨 Print</button>` : `<span class="pill warn">Not online yet</span>`}</div></div>
          ${d.public_url ? `
            ${d.public_source === "server" ? `<div class="est-note" style="margin:0 0 12px">Permanent address of your online store. These codes work on any Android or iPhone, on mobile data or any Wi-Fi. Print them once — they don't change.</div>` : ""}
            ${d.public_source === "tunnel" ? `<div class="est-note" style="margin:0 0 12px">Detected from the online-access helper. This address changes each time the helper restarts, so re-print the codes after a restart, or use a fixed address (see README).</div>` : ""}
            ${risks.length ? `<div class="card" style="border-color:#c62828;background:var(--red-soft);margin-bottom:12px"><b>Before sharing these widely, turn off:</b> ${risks.join("; ")}. Go to Settings → “Delete all sample data” and switch off test payments.</div>` : ""}
            <div class="cards qr-grid">${pair(d.public_url, "").map(card).join("")}</div>` : `
            <ol style="margin:6px 0 12px;padding-left:20px;font-size:15px;line-height:1.6">
              <li>Keep the app running, then double-click <b>start-online-windows.bat</b> in the app folder (Mac: <code>bash start-online-mac.sh</code>).</li>
              <li>Wait until it says it is connected, then press <b>Refresh</b> below. The codes appear automatically.</li></ol>
            <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn btn-primary btn-sm" id="q-refresh">Refresh</button></div>`}
          ${A.me.role === "owner" && d.public_source !== "server" ? `<details style="margin-top:12px" ${d.saved_public_url ? "open" : ""}><summary style="cursor:pointer;font-weight:600;font-size:14px">Use my own fixed web address</summary>
            <div style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap"><input class="inp" id="pub" style="flex:1;min-width:220px" placeholder="https://shop.yourdomain.in" value="${esc(d.saved_public_url)}"><button class="btn btn-sm" id="pub-save">Save</button></div>
            <div class="sub" style="margin-top:6px">Only if your store is hosted online or you have a permanent tunnel. Leave empty otherwise.</div></details>` : ""}
        </div>
        ${d.public_source === "server" ? "" : `<div class="card"><div class="card-h"><div><h2>Codes for the same Wi-Fi</h2><div class="sub" style="margin:0">Free and instant, but only for phones on the same Wi-Fi as this computer.</div></div>
          <div class="toolbar no-print" style="margin:0">${d.addresses.length > 1 ? `<select id="ipsel" aria-label="Network address">${d.addresses.map((a) => `<option ${a === ip ? "selected" : ""}>${esc(a)}</option>`).join("")}</select>` : ""}<button class="btn btn-sm btn-primary" id="qprint">🖨 Print</button></div></div>
          ${!d.phones_can_connect ? `<div class="card" style="border-color:var(--amber);background:var(--amber-soft);margin-bottom:12px">Phones can't connect yet: in the <b>.env</b> file change <code>HOST=127.0.0.1</code> to <code>HOST=0.0.0.0</code>, save, and restart the app.</div>` : ""}
          ${ip ? `<div class="cards qr-grid">${pair(lan, "").map(card).join("")}</div>` : `<div class="empty-sm">No Wi-Fi network found on this computer.</div>`}
          ${ip ? `<details class="no-print" style="margin-top:12px"><summary style="cursor:pointer;font-weight:600;font-size:14px">Expo Go codes (same Wi-Fi only)</summary>
            <div class="sub" style="margin-top:6px">Only work while <b>expo-app/start-expo-windows.bat</b> is running. See expo-app/README.txt.</div>
            <div class="cards qr-grid">${[{ title: "Customer store · Expo Go", url: `exp://${ip}:${d.expo_port}/--/store` }, { title: "Owner dashboard · Expo Go", url: `exp://${ip}:${d.expo_port}/--/admin` }].map(card).join("")}</div></details>` : ""}
        </div>`}`;
      el.querySelectorAll("[data-copy]").forEach((bt) => (bt.onclick = async () => { try { await navigator.clipboard.writeText(bt.dataset.copy); toast("Link copied"); } catch (e) { toast(bt.dataset.copy); } }));
      const sel = el.querySelector("#ipsel"); if (sel) sel.onchange = () => { ip = sel.value; paint(); };
      el.querySelectorAll("#qprint, #qprint2").forEach((b) => (b.onclick = () => window.print()));
      const rf = el.querySelector("#q-refresh"); if (rf) rf.onclick = () => share(el);
      const sv = el.querySelector("#pub-save");
      if (sv) sv.onclick = async () => { try { await api("PUT", "/api/admin/public-url", { public_url: el.querySelector("#pub").value }); toast("Saved"); share(el); } catch (e) { toast(e.message, "err"); } };
    };
    paint();
  }

  // ------------------------------------------------------------------ OVERVIEW
  async function overview(el) {
    el.innerHTML = "";
    el.appendChild(rangeBar(() => overview(el)));
    const body = document.createElement("div");
    body.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
    el.appendChild(body);
    const d = await api("GET", "/api/admin/overview?" + rq());
    const s = d.sales, o = d.orders, p = d.products;
    const fin = "gross_profit" in s;
    body.innerHTML = `
      <div class="kgroup-title">Sales · ${fmt.date(d.range.from)} – ${fmt.date(d.range.to)}</div>
      <div class="kpis">
        ${kpi("Sales in period", fmt.inr(s.in_range, 0), `${fmt.num(s.orders_in_range)} orders · AOV ${fmt.inr(s.avg_order_value, 0)}`, "hl")}
        ${kpi("Today's sales", fmt.inr(s.today, 0), `${o.today} orders today`)}
        ${kpi("This month", fmt.inr(s.month, 0))}
        ${kpi("Total sales (all time)", fmt.compact(s.total_all_time), `${fmt.num(o.total_all_time)} orders`)}
        ${fin ? kpi("Est. gross profit", fmt.inr(s.gross_profit, 0), s.gross_margin_pct != null ? `${s.gross_margin_pct}% margin on net revenue (ex-GST)` : "", s.gross_profit >= 0 ? "good" : "bad") : ""}
        ${fin ? kpi("Est. net profit", s.net_profit == null ? "—" : fmt.inr(s.net_profit, 0), s.net_profit == null ? "Add expenses in Finance to calculate" : `after ${fmt.inr(s.expenses, 0)} expenses`, s.net_profit == null ? "" : s.net_profit >= 0 ? "good" : "bad", "#/finance") : ""}
      </div>
      <div class="kgroup-title">Orders</div>
      <div class="kpis">
        ${kpi("Awaiting processing", o.awaiting_processing, "placed → packed", o.awaiting_processing ? "warn" : "", "#/orders?status=to_process")}
        ${kpi("Awaiting payment", o.awaiting_payment, "online, unpaid", "", "#/orders?status=payment_pending")}
        ${kpi("Dispatched", o.dispatched, "in this period", "", "#/orders?status=shipping")}
        ${kpi("Delivered", o.delivered, "in this period", "good")}
        ${kpi("Cancelled", o.cancelled, "in this period", o.cancelled ? "bad" : "")}
        ${kpi("Returns / requests open", o.returns_open, "", o.returns_open ? "warn" : "", "#/returns")}
        ${kpi("COD cash to collect", o.cod_to_collect, fmt.inr(o.cod_to_collect_amount, 0) + " delivered, unpaid", o.cod_to_collect ? "warn" : "", "#/orders?status=delivered&payment=pending&method=cod")}
      </div>
      <div class="kgroup-title">Catalogue, stock & customers</div>
      <div class="kpis">
        ${kpi("Products", p.total, `${p.active} active · ${p.inactive} inactive · ${p.draft} draft`, "", "#/products")}
        ${kpi("Stock on hand", fmt.num(p.total_stock), `${fmt.num(p.available_stock)} available · ${fmt.num(p.reserved_stock)} reserved`, "", "#/inventory")}
        ${kpi("Inventory value", fmt.compact(p.valuation_cost ?? p.valuation_retail), p.valuation_cost != null ? `at cost · ${fmt.compact(p.valuation_retail)} at selling price` : "at selling price")}
        ${kpi("Low stock", p.low_stock, "at or below threshold", p.low_stock ? "warn" : "", "#/inventory?filter=low")}
        ${kpi("Out of stock", p.out_of_stock, "", p.out_of_stock ? "bad" : "", "#/inventory?filter=out")}
        ${kpi("Customers", fmt.num(d.customers.total), `${d.customers.new} new in period`, "", "#/customers")}
      </div>
      <div class="cards">
        <div class="card c8"><div class="card-h"><div><h2>Sales trend</h2><div class="sub">Daily revenue from valid orders (excludes cancelled, unpaid online and refunded)</div></div></div><div id="ch-sales"></div></div>
        <div class="card c4"><h2>Orders by status</h2><div class="sub">Orders created in this period</div><div id="ch-status"></div></div>
        <div class="card c6"><h2>Revenue by category</h2><div class="sub">This period</div><div id="ch-cat"></div></div>
        <div class="card c6"><h2>Top products</h2><div class="sub">By revenue, this period</div><div id="ch-top"></div></div>
        <div class="card c4"><div class="card-h"><h2>Low stock</h2><a href="#/inventory?filter=low" class="btn-link">View all</a></div>
          ${d.low_stock_items.length ? `<table class="tbl"><tbody>${d.low_stock_items.map((x) => `<tr><td>${esc(x.name)}<div class="muted">${esc(x.sku)}</div></td><td class="num"><span class="pill warn">${x.available} left</span></td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">No low-stock products.</div>`}
          ${d.out_of_stock_items.length ? `<h2 style="margin-top:14px">Out of stock</h2><table class="tbl"><tbody>${d.out_of_stock_items.map((x) => `<tr><td>${esc(x.name)}</td><td class="num"><span class="pill bad">0</span></td></tr>`).join("")}</tbody></table>` : ""}</div>
        <div class="card c8"><div class="card-h"><h2>Recent orders</h2><a href="#/orders" class="btn-link">All orders</a></div>
          <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Order</th><th>Customer</th><th>Status</th><th>Payment</th><th class="num">Total</th></tr></thead><tbody>
          ${d.recent_orders.map((r) => `<tr class="click" data-href="#/orders/${r.id}"><td><b>${esc(r.order_no)}</b><div class="muted">${fmt.datetime(r.created_at)}</div></td><td>${esc(r.customer)}<div class="muted">${esc(r.buyer_code || "")}</div></td><td>${stPill(r.status, r.status_label)}</td><td>${payPill(r)}</td><td class="num">${fmt.inr(r.grand_total)}</td></tr>`).join("")}
          </tbody></table></div></div>
      </div>`;
    C.line(body.querySelector("#ch-sales"), { labels: d.series.map((x) => x.day), series: [{ name: "Revenue", color: C.S.s1, points: d.series.map((x) => ({ y: x.revenue })) }],
      yFmt: (v) => fmt.compact(v), xFmt: (l, long) => (long ? fmt.date(l) : fmt.short(l)), area: true });
    C.hbars(body.querySelector("#ch-status"), o.by_status.map((x) => ({ label: x.label, value: x.n })), { fmt: (v) => fmt.num(v), color: C.S.s7 });
    C.hbars(body.querySelector("#ch-cat"), d.by_category.map((x) => ({ label: x.name, value: x.revenue, sub: `${x.units} units` })), { fmt: (v) => fmt.compact(v) });
    C.hbars(body.querySelector("#ch-top"), d.top_products.map((x) => ({ label: x.name, value: x.revenue, sub: `${x.units} units` })), { fmt: (v) => fmt.compact(v), color: C.S.s3 });
    bindRows(body);
  }

  function bindRows(root) { root.querySelectorAll("tr[data-href]").forEach((tr) => (tr.onclick = (e) => { if (!e.target.closest("button,input,select,a")) location.hash = tr.dataset.href; })); }

  // ------------------------------------------------------------------ ORDERS
  async function orders(el, parts, q) {
    if (parts[0]) return orderDetail(el, +parts[0]);
    const st = { status: q.get("status") || "", payment: q.get("payment") || "", method: q.get("method") || "", q: q.get("q") || "", page: 1, company: "" };
    el.innerHTML = `<div class="toolbar"><input type="search" class="inp" id="oq" placeholder="Search order no., customer, buyer code, phone" value="${esc(st.q)}">
      <select id="ost" aria-label="Status"><option value="">All statuses</option><optgroup label="Groups"><option value="open">Open orders</option><option value="to_process">To process</option><option value="shipping">In delivery</option><option value="returns">Returns & refunds</option></optgroup><optgroup label="Status" id="ost-list"></optgroup></select>
      <select id="opay" aria-label="Payment"><option value="">Any payment</option><option value="paid">Paid</option><option value="pending">Pending / COD due</option><option value="failed">Failed</option><option value="refunded">Refunded</option></select>
      <select id="ometh" aria-label="Method"><option value="">Any method</option><option value="cod">Cash on Delivery</option><option value="razorpay">Razorpay</option><option value="upi">UPI (direct)</option><option value="sandbox">Sandbox</option></select>
      <span class="grow"></span>${can("reports") ? `<button class="btn btn-sm" id="oexp">⬇ Export CSV</button>` : ""}</div><div id="olist"></div>`;
    const load = async () => {
      const box = el.querySelector("#olist");
      box.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
      const params = new URLSearchParams({ page: st.page, per: 25 });
      ["status", "payment", "method", "q"].forEach((k) => st[k] && params.set(k, st[k]));
      const d = await api("GET", "/api/admin/orders?" + params);
      const sl = el.querySelector("#ost-list");
      if (!sl.children.length) { sl.innerHTML = d.statuses.map((s) => `<option value="${s.code}">${esc(s.label)} (${d.status_counts[s.code] || 0})</option>`).join(""); el.querySelector("#ost").value = st.status; }
      if (!d.items.length) { box.innerHTML = `<div class="empty"><div class="ico">📦</div><h3>No orders match</h3><p>Try clearing the filters.</p></div>`; return; }
      box.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Order</th><th>Date</th><th>Customer</th><th>Buyer code</th><th class="num">Units</th><th>Status</th><th>Payment</th><th class="num">Total</th></tr></thead><tbody>
        ${d.items.map((r) => `<tr class="click" data-href="#/orders/${r.id}"><td><b>${esc(r.order_no)}</b> ${r.is_sample ? '<span class="pill sample">SAMPLE</span>' : ""}</td><td>${fmt.datetime(r.created_at)}</td><td>${esc(r.customer)}</td><td>${esc(r.buyer_code || "—")}</td>
          <td class="num">${r.units || 0}</td><td>${stPill(r.status, r.status_label)}</td><td>${payPill(r)}<div class="muted">${PM[r.payment_method] || esc(r.payment_method)}</div></td><td class="num">${fmt.inr(r.grand_total)}</td></tr>`).join("")}</tbody></table></div>`;
      pager(box, d, (p) => { st.page = p; load(); });
      bindRows(box);
    };
    el.querySelector("#oq").oninput = debounce((e) => { st.q = e.target.value.trim(); st.page = 1; load(); });
    el.querySelector("#ost").onchange = (e) => { st.status = e.target.value; st.page = 1; load(); };
    el.querySelector("#opay").value = st.payment; el.querySelector("#opay").onchange = (e) => { st.payment = e.target.value; st.page = 1; load(); };
    el.querySelector("#ometh").value = st.method; el.querySelector("#ometh").onchange = (e) => { st.method = e.target.value; st.page = 1; load(); };
    const ex = el.querySelector("#oexp"); if (ex) ex.onclick = () => download("/api/admin/export/orders?" + rq());
    await load();
  }

  async function orderDetail(el, id) {
    const o = await api("GET", "/api/admin/orders/" + id);
    document.getElementById("ttl").textContent = "Order " + o.order_no;
    const a = o.ship_address;
    el.innerHTML = `<div class="toolbar"><a class="btn btn-sm" href="#/orders">‹ All orders</a><span class="grow"></span>${o.is_sample ? '<span class="pill sample">SAMPLE ORDER</span>' : ""}
      <button class="btn btn-sm" id="print">🖨 Print packing slip</button></div>
      <div class="split"><div>
        <div class="card" style="margin-bottom:14px"><div class="card-h"><div><h2 style="font-size:20px">${esc(o.order_no)}</h2><div class="sub">Placed ${fmt.datetime(o.created_at)} · ${esc(PM[o.payment_method] || o.payment_method)}</div></div>
          <div style="display:flex;gap:6px">${stPill(o.status, o.status_label)} ${payPill(o)}</div></div>
          <div class="tbl-wrap" style="margin:0"><table class="tbl"><thead><tr><th></th><th>Item</th><th>SKU</th><th class="num">Qty</th><th class="num">Unit price</th>${"cost_total" in o ? '<th class="num">Unit cost</th>' : ""}<th class="num">Line total</th></tr></thead><tbody>
            ${o.items.map((i) => `<tr><td><img class="thumb" src="${esc(i.image)}" alt=""></td><td class="pname">${esc(i.name)}</td><td class="muted">${esc(i.sku || "")}</td><td class="num">${i.qty}</td><td class="num">${fmt.inr(i.unit_price)}</td>${"cost_total" in o ? `<td class="num">${fmt.inr(i.cost_price)}</td>` : ""}<td class="num">${fmt.inr(i.line_total)}</td></tr>`).join("")}
          </tbody></table></div>
          <div style="max-width:340px;margin-left:auto;margin-top:12px;font-size:14px">
            <div style="display:flex;justify-content:space-between"><span>Items</span><span>${fmt.inr(o.subtotal)}</span></div>
            ${o.coupon_discount ? `<div style="display:flex;justify-content:space-between"><span>Coupon ${esc(o.coupon_code)}</span><span>− ${fmt.inr(o.coupon_discount)}</span></div>` : ""}
            <div style="display:flex;justify-content:space-between"><span>Delivery (${esc(o.delivery_method || "")})</span><span>${fmt.inr(o.delivery_charge)}</span></div>
            <div style="display:flex;justify-content:space-between;color:var(--ink-3)"><span>GST included</span><span>${fmt.inr(o.tax_total)}</span></div>
            <div style="display:flex;justify-content:space-between;font-weight:700;font-size:17px;border-top:1px solid var(--line);margin-top:6px;padding-top:6px"><span>Total</span><span>${fmt.inr(o.grand_total)}</span></div>
            ${"cost_total" in o ? `<div style="display:flex;justify-content:space-between;color:var(--ink-3)"><span>Cost of goods</span><span>${fmt.inr(o.cost_total)}</span></div>` : ""}</div></div>
        <div class="card" style="margin-bottom:14px"><h2>Timeline</h2><div class="sub">Visible to the customer on their tracking page</div>
          <ul class="timeline-a">${o.timeline.slice().reverse().map((e) => `<li><b>${esc(e.label)}</b>${e.note ? ` — ${esc(e.note)}` : ""}<div class="t">${fmt.datetime(e.at)} · ${esc(e.actor)}</div></li>`).join("")}</ul></div>
        <div class="card"><h2>Payments</h2>${o.payments.length ? `<table class="tbl"><thead><tr><th>Method</th><th>Reference</th><th>Status</th><th class="num">Amount</th><th>Time</th></tr></thead><tbody>
          ${o.payments.map((p) => `<tr><td>${esc(PM[p.method] || p.method)}</td><td class="muted">${esc(p.provider_payment_id || p.provider_order_id || "—")}</td><td>${p.status === "verified" ? '<span class="pill ok">Verified</span>' : p.status === "failed" ? `<span class="pill bad">Failed</span><div class="muted">${esc(p.error || "")}</div>` : `<span class="pill">${esc(p.status)}</span>`}</td><td class="num">${fmt.inr(p.amount)}</td><td>${fmt.datetime(p.verified_at || p.created_at)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">No payment attempts recorded.</div>`}
          ${o.refunds.length ? `<h2 style="margin-top:12px">Refunds</h2>${o.refunds.map((r) => `<div style="font-size:14px">${fmt.inr(r.amount)} · ${esc(r.status)} ${r.reference ? "· Ref " + esc(r.reference) : ""} · ${fmt.datetime(r.created_at)}</div>`).join("")}` : ""}</div>
      </div>
      <div>
        <div class="card" style="margin-bottom:14px"><h2>Update status</h2>
          ${o.next_statuses.length ? `<label class="fld"><span>Move to</span><select id="ns">${o.next_statuses.map((s) => `<option value="${s.code}">${esc(s.label)}</option>`).join("")}</select></label>
            <label class="fld"><span>Note for the customer (optional)</span><input id="nn" placeholder="e.g. Packed and ready for dispatch"></label>
            <div id="ref-box" hidden><label class="fld"><span>Refund reference (UTR / transaction ID)</span><input id="nref"></label></div>
            <div id="restock-box" hidden><label class="chk"><input type="checkbox" id="nrestock" checked> Returned items are resaleable (add back to stock)</label></div>
            <button class="btn btn-primary btn-block" id="go-st">Update status</button>` : `<div class="empty-sm">No further status changes for this order.</div>`}
          ${o.status === "payment_pending" && o.payment_method !== "upi" ? `<div class="est-note">Online payment not yet verified. Payment Confirmed is set automatically only after the gateway verifies it — it cannot be set by hand.</div>` : ""}
          ${o.upi && o.upi.status === "submitted" && o.payment_status !== "paid" ? `<div class="upi-box"><h3>UPI payment to confirm</h3>
            <dl class="kv"><dt>Amount</dt><dd><b>${fmt.inr(o.grand_total)}</b></dd><dt>Txn ID / UTR</dt><dd><b>${esc(o.upi.utr)}</b></dd><dt>Submitted</dt><dd>${fmt.datetime(o.upi.created_at)}</dd></dl>
            <div class="est-note">Open your bank or UPI app and check that ${fmt.inr(o.grand_total)} arrived with this transaction ID before confirming.</div>
            <div style="display:flex;gap:8px;margin-top:8px"><button class="btn btn-primary" id="upi-ok" style="flex:1">✓ Confirm payment</button><button class="btn btn-danger" id="upi-no" style="flex:1">Reject</button></div></div>` : ""}
          ${o.payment_method === "upi" && o.status === "payment_pending" && !(o.upi && o.upi.status === "submitted") ? `<div class="est-note">Waiting for the customer to pay by UPI and submit the transaction ID.</div>` : ""}
          ${o.payment_method === "cod" && o.payment_status === "pending" && ["out_for_delivery", "delivered"].includes(o.status) ? `<button class="btn btn-dark btn-block" id="cash" style="margin-top:10px">Record cash collected · ${fmt.inr(o.grand_total)}</button>` : ""}
        </div>
        <div class="card" style="margin-bottom:14px"><h2>Shipment</h2>
          <label class="fld"><span>Courier / delivery service</span><input id="sc" value="${esc(o.courier || "")}" placeholder="e.g. Unit Dispatch, India Post"></label>
          <label class="fld"><span>Tracking number</span><input id="stn" value="${esc(o.tracking_no || "")}"></label>
          <div class="row2"><label class="fld"><span>ETA from</span><input type="date" id="sf" value="${esc(o.est_delivery_from || "")}"></label><label class="fld"><span>ETA to</span><input type="date" id="stt" value="${esc(o.est_delivery_to || "")}"></label></div>
          <button class="btn btn-block" id="save-ship">Save shipment details</button></div>
        <div class="card" style="margin-bottom:14px"><h2>Customer</h2><dl class="kv"><dt>Name</dt><dd>${o.customer ? `${can("customers") ? `<a href="#/customers/${o.customer.id}" style="color:var(--teal);font-weight:600">${esc(o.customer.name)}</a>` : esc(o.customer.name)}` : "—"}</dd>
          <dt>Email</dt><dd>${esc(o.customer?.email || "—")}</dd><dt>Phone</dt><dd>${esc(o.customer?.phone || "—")}</dd><dt>Buyer code</dt><dd>${esc(o.buyer_code || "—")}</dd></dl></div>
        <div class="card"><h2>Deliver to</h2><div style="font-size:14px"><b>${esc(o.ship_name)}</b><br>${esc(a.line1)}${a.line2 ? ", " + esc(a.line2) : ""}<br>${esc(a.city)}, ${esc(a.state)} ${esc(a.pincode)}<br>📞 ${esc(o.ship_phone)}</div>
          ${o.requests.length ? `<h2 style="margin-top:12px">Requests</h2>${o.requests.map((r) => `<div style="font-size:14px">${r.kind === "cancel" ? "Cancellation" : "Return"} · <b>${esc(r.status)}</b> — ${esc(r.reason || "")}</div>`).join("")}` : ""}</div>
      </div></div>`;
    const ns = el.querySelector("#ns");
    if (ns) {
      const sync = () => { el.querySelector("#ref-box").hidden = ns.value !== "refunded"; el.querySelector("#restock-box").hidden = ns.value !== "returned"; };
      ns.onchange = sync; sync();
      el.querySelector("#go-st").onclick = async () => {
        const label = ns.options[ns.selectedIndex].text;
        const danger = ns.value === "cancelled";
        if (!(await confirmDialog("Update order status", `Move order ${o.order_no} to “${label}”? The customer will be notified${danger ? " and reserved stock will be released" : ""}.`, { confirmLabel: "Update", danger }))) return;
        try {
          await api("POST", `/api/admin/orders/${id}/status`, { status: ns.value, note: el.querySelector("#nn").value, reference: el.querySelector("#nref").value, restock: el.querySelector("#nrestock").checked });
          toast("Status updated to " + label); orderDetail(el, id);
        } catch (e) { toast(e.message, "err"); }
      };
    }
    const upiOk = el.querySelector("#upi-ok");
    if (upiOk) upiOk.onclick = async () => {
      if (!(await confirmDialog("Confirm UPI payment", `Have you checked that ${fmt.inr(o.grand_total)} with Txn ID ${o.upi.utr} arrived in your account? The order will move to Payment Confirmed.`, { confirmLabel: "Yes, payment received" }))) return;
      try { await api("POST", `/api/admin/orders/${id}/upi-review`, { action: "confirm" }); toast("UPI payment confirmed"); orderDetail(el, id); } catch (e) { toast(e.message, "err"); }
    };
    const upiNo = el.querySelector("#upi-no");
    if (upiNo) upiNo.onclick = async () => {
      const note = await promptDialog("Reject UPI payment", "Reason shown to the customer", { confirmLabel: "Reject payment", placeholder: "e.g. No payment found with this transaction ID" });
      if (note === null || note === undefined || note === false) return;
      try { await api("POST", `/api/admin/orders/${id}/upi-review`, { action: "reject", note }); toast("Payment rejected — customer notified"); orderDetail(el, id); } catch (e) { toast(e.message, "err"); }
    };
    const cash = el.querySelector("#cash");
    if (cash) cash.onclick = async () => {
      if (!(await confirmDialog("Record cash collection", `Confirm that ${fmt.inr(o.grand_total)} cash was collected for ${o.order_no}?`, { confirmLabel: "Cash collected" }))) return;
      try { await api("POST", `/api/admin/orders/${id}/collect-cash`); toast("Cash payment recorded"); orderDetail(el, id); } catch (e) { toast(e.message, "err"); }
    };
    el.querySelector("#save-ship").onclick = async () => {
      try { await api("PUT", `/api/admin/orders/${id}/shipping`, { courier: el.querySelector("#sc").value, tracking_no: el.querySelector("#stn").value, est_delivery_from: el.querySelector("#sf").value, est_delivery_to: el.querySelector("#stt").value }); toast("Shipment details saved"); orderDetail(el, id); }
      catch (e) { toast(e.message, "err"); }
    };
    el.querySelector("#print").onclick = () => {
      const w = window.open("", "_blank", "width=720,height=900");
      if (!w) return toast("Allow pop-ups to print", "err");
      w.document.write(`<html><head><title>Packing slip ${esc(o.order_no)}</title><style>body{font-family:Arial,sans-serif;padding:24px}table{width:100%;border-collapse:collapse}td,th{border-bottom:1px solid #ddd;padding:6px;text-align:left}</style></head><body>
        <h2>Packing slip — ${esc(o.order_no)}</h2><p>${fmt.datetime(o.created_at)} · ${esc(PM[o.payment_method] || "")} · ${o.payment_status === "paid" ? "PAID" : o.payment_method === "cod" ? "COLLECT " + fmt.inr(o.grand_total) : "UNPAID"}</p>
        <p><b>${esc(o.ship_name)}</b><br>${esc(a.line1)} ${esc(a.line2 || "")}<br>${esc(a.city)}, ${esc(a.state)} ${esc(a.pincode)}<br>${esc(o.ship_phone)}${o.buyer_code ? "<br>Buyer code: " + esc(o.buyer_code) : ""}</p>
        <table><tr><th>Item</th><th>SKU</th><th>Qty</th></tr>${o.items.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.sku || "")}</td><td>${i.qty}</td></tr>`).join("")}</table>
        <p><b>Total: ${fmt.inr(o.grand_total)}</b></p><p style="margin-top:32px;font-size:12px;color:#666;border-top:1px solid #ddd;padding-top:8px">Created &amp; managed by <b>Surjeet Choudhary</b></p></body></html>`);
      w.document.close(); w.focus(); w.print();
    };
  }

  // ------------------------------------------------------------------ RETURNS
  async function returns(el) {
    let status = "pending";
    const load = async () => {
      const d = await api("GET", "/api/admin/returns?status=" + status);
      el.innerHTML = `<div class="toolbar"><div class="seg">${["pending", "approved", "rejected", "all"].map((s) => `<button data-s="${s}" class="${s === status ? "on" : ""}">${s[0].toUpperCase() + s.slice(1)}</button>`).join("")}</div></div>
        <div class="card" style="margin-bottom:14px"><h2>Cancellation & return requests</h2><div class="sub">Approving a return moves the order to “Return in progress”; mark it Returned from the order page when the item arrives.</div>
        ${d.requests.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Order</th><th>Customer</th><th>Type</th><th>Reason</th><th>Requested</th><th>Order status</th><th class="num">Value</th><th></th></tr></thead><tbody>
          ${d.requests.map((r) => `<tr><td><a href="#/orders/${r.order_id}" style="color:var(--teal);font-weight:600">${esc(r.order_no)}</a></td><td>${esc(r.customer)}</td><td>${r.kind === "cancel" ? '<span class="pill warn">Cancellation</span>' : '<span class="pill info">Return</span>'}</td>
            <td>${esc(r.reason || "")}</td><td>${fmt.datetime(r.created_at)}</td><td>${stPill(r.order_status, r.order_status_label)}</td><td class="num">${fmt.inr(r.grand_total)}</td>
            <td>${r.status === "pending" ? `<div style="display:flex;gap:6px"><button class="btn btn-sm btn-primary" data-ap="${r.id}" data-k="${r.kind}">Approve</button><button class="btn btn-sm" data-rj="${r.id}">Reject</button></div>` : `<span class="pill">${esc(r.status)}</span>`}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-sm">No ${status === "all" ? "" : status} requests.</div>`}</div>
        <div class="card"><h2>Refunds</h2><div class="sub">Refunds in “processing” are completed from the order page (status → Refunded) once money is returned. Razorpay refunds are sent to the gateway automatically when keys are configured.</div>
        ${d.refunds.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Order</th><th>Customer</th><th>Method</th><th>Status</th><th>Reference</th><th>Created</th><th class="num">Amount</th></tr></thead><tbody>
          ${d.refunds.slice(0, 100).map((f) => `<tr class="click" data-href="#/orders/${f.order_id}"><td><b>${esc(f.order_no)}</b></td><td>${esc(f.customer)}</td><td>${esc(PM[f.method] || f.method || "")}</td><td>${f.status === "completed" ? '<span class="pill ok">Completed</span>' : '<span class="pill warn">Processing</span>'}</td><td class="muted">${esc(f.reference || "—")}</td><td>${fmt.datetime(f.created_at)}</td><td class="num">${fmt.inr(f.amount)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-sm">No refunds yet.</div>`}</div>`;
      el.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => { status = b.dataset.s; load(); }));
      el.querySelectorAll("[data-ap]").forEach((b) => (b.onclick = async () => {
        const isRet = b.dataset.k === "return";
        const ok = await modal({ title: isRet ? "Approve return" : "Approve cancellation",
          body: `<p>${isRet ? "The order will move to “Return in progress”." : "The order will be cancelled and its reserved stock released. Paid orders move to refund processing."}</p><label class="fld"><span>Note to customer (optional)</span><input id="rn"></label>`,
          actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Approve", cls: "btn-primary", handler: (m) => api("POST", `/api/admin/returns/${b.dataset.ap}/resolve`, { action: "approve", note: m.querySelector("#rn").value }) }] });
        if (ok) { toast("Request approved"); load(); badges(); }
      }));
      el.querySelectorAll("[data-rj]").forEach((b) => (b.onclick = async () => {
        const note = await promptDialog("Reject request", "Reason (shown to the customer)", { confirmLabel: "Reject" });
        if (note === null) return;
        try { await api("POST", `/api/admin/returns/${b.dataset.rj}/resolve`, { action: "reject", note }); toast("Request rejected"); load(); badges(); } catch (e) { toast(e.message, "err"); }
      }));
      bindRows(el);
    };
    await load();
  }

  // ------------------------------------------------------------------ CUSTOMERS
  async function customers(el, parts) {
    if (parts[0]) return customerDetail(el, +parts[0]);
    const st = { q: "", status: "", sort: "", page: 1 };
    el.innerHTML = `<div class="toolbar"><input type="search" class="inp" id="cq" placeholder="Search name, email, phone, buyer code">
      <select id="cs"><option value="">All accounts</option><option value="active">Active</option><option value="suspended">Suspended</option></select>
      <select id="csort"><option value="">Newest</option><option value="spent">Top spenders</option><option value="orders">Most orders</option><option value="recent">Recent buyers</option><option value="name">Name</option></select>
      <span class="grow"></span>${can("reports") ? `<button class="btn btn-sm" id="cexp">⬇ Export CSV</button>` : ""}</div><div id="clist"></div>`;
    const load = async () => {
      const box = el.querySelector("#clist");
      const p = new URLSearchParams({ page: st.page, per: 25 }); ["q", "status", "sort"].forEach((k) => st[k] && p.set(k, st[k]));
      const d = await api("GET", "/api/admin/customers?" + p);
      box.innerHTML = d.items.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Phone</th><th>Buyer code</th><th>Registered</th><th class="num">Orders</th><th class="num">Spent</th><th>Last order</th><th>Status</th></tr></thead><tbody>
        ${d.items.map((c) => `<tr class="click" data-href="#/customers/${c.id}"><td class="muted">#${c.id}</td><td class="pname">${esc(c.name)} ${c.is_sample ? '<span class="pill sample">SAMPLE</span>' : ""}</td><td>${esc(c.email || "—")}</td><td>${esc(c.phone || "—")}</td><td>${esc(c.buyer_code || "—")}</td><td>${fmt.date(c.created_at)}</td><td class="num">${c.orders}</td><td class="num">${fmt.inr(c.spent, 0)}</td><td>${fmt.date(c.last_order)}</td><td>${c.status === "active" ? '<span class="pill ok">Active</span>' : '<span class="pill bad">Suspended</span>'}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty"><div class="ico">👤</div><h3>No customers found</h3></div>`;
      if (d.items.length) pager(box, d, (n) => { st.page = n; load(); });
      bindRows(box);
    };
    el.querySelector("#cq").oninput = debounce((e) => { st.q = e.target.value.trim(); st.page = 1; load(); });
    el.querySelector("#cs").onchange = (e) => { st.status = e.target.value; st.page = 1; load(); };
    el.querySelector("#csort").onchange = (e) => { st.sort = e.target.value; st.page = 1; load(); };
    const ex = el.querySelector("#cexp"); if (ex) ex.onclick = () => download("/api/admin/export/customers?" + rq());
    await load();
  }

  async function customerDetail(el, id) {
    const c = await api("GET", "/api/admin/customers/" + id);
    document.getElementById("ttl").textContent = c.name;
    const olist = (rows) => rows.length ? `<table class="tbl"><tbody>${rows.map((o) => `<tr class="click" data-href="#/orders/${o.id}"><td><b>${esc(o.order_no)}</b><div class="muted">${fmt.datetime(o.created_at)}</div></td><td>${stPill(o.status, o.status_label)}</td><td class="num">${fmt.inr(o.grand_total)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">None.</div>`;
    el.innerHTML = `<div class="toolbar"><a class="btn btn-sm" href="#/customers">‹ All customers</a></div>
      <div class="kpis">${kpi("Total orders", c.total_orders)}${kpi("Total spent", fmt.inr(c.total_spent, 0), "valid orders")}${kpi("Last order", fmt.date(c.last_order))}${kpi("Current orders", c.current_orders.length)}${kpi("Cancelled", c.cancelled_orders.length)}${kpi("Returns", c.returns.length)}</div>
      <div class="split"><div>
        <div class="card" style="margin-bottom:14px"><h2>Order history</h2><div class="tbl-wrap">${olist(c.orders)}</div></div>
        <div class="card" style="margin-bottom:14px"><h2>Most purchased</h2>${c.top_products.length ? `<table class="tbl"><tbody>${c.top_products.map((t) => `<tr><td>${esc(t.name)}</td><td class="num">${t.units} units · ${t.times} orders</td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">No purchases yet.</div>`}</div>
        <div class="card"><h2>Returns & refunds</h2>${c.returns.map((r) => `<div style="font-size:14px">${esc(r.order_no)} · ${r.kind} · <b>${esc(r.status)}</b> — ${esc(r.reason || "")}</div>`).join("") || `<div class="empty-sm">No return requests.</div>`}
          ${c.refunds.map((r) => `<div style="font-size:14px">Refund ${fmt.inr(r.amount)} · ${esc(r.order_no)} · ${esc(r.status)}${r.reference ? " · " + esc(r.reference) : ""}</div>`).join("")}</div>
      </div><div>
        <div class="card" style="margin-bottom:14px"><h2>Profile</h2><dl class="kv"><dt>Customer ID</dt><dd>#${c.id}</dd><dt>Email</dt><dd>${esc(c.email || "—")}</dd><dt>Phone</dt><dd>${esc(c.phone || "—")}</dd>
          <dt>Registered</dt><dd>${fmt.date(c.created_at)}</dd><dt>Last sign-in</dt><dd>${fmt.datetime(c.last_login_at)}</dd><dt>Status</dt><dd>${c.status === "active" ? '<span class="pill ok">Active</span>' : '<span class="pill bad">Suspended</span>'}</dd></dl>
          <button class="btn btn-sm ${c.status === "active" ? "btn-danger" : "btn-primary"}" id="cst" style="margin-top:12px">${c.status === "active" ? "Suspend account" : "Reactivate account"}</button></div>
        ${can("buyers") ? `<div class="card" style="margin-bottom:14px"><h2>Unit buyer code</h2><div class="sub">Orders placed by this customer are recorded against this code.</div>
          <div style="display:flex;gap:8px"><input class="inp" id="bc" value="${esc(c.buyer_code || "")}" placeholder="e.g. A-O-1" style="text-transform:uppercase"><button class="btn btn-primary btn-sm" id="bcs">Save</button></div></div>` : ""}
        <div class="card"><h2>Delivery addresses</h2>${c.addresses.map((a) => `<div style="font-size:14px;border-bottom:1px solid var(--line-2);padding:8px 0"><b>${esc(a.name)}</b> ${a.is_default ? '<span class="pill teal">Default</span>' : ""}<br>${esc(a.line1)}${a.line2 ? ", " + esc(a.line2) : ""}, ${esc(a.city)}, ${esc(a.state)} ${esc(a.pincode)} · ${esc(a.phone)}</div>`).join("") || `<div class="empty-sm">No saved addresses.</div>`}</div>
      </div></div>`;
    bindRows(el);
    el.querySelector("#cst").onclick = async () => {
      const suspend = c.status === "active";
      if (!(await confirmDialog(suspend ? "Suspend customer" : "Reactivate customer", suspend ? `${c.name} will be signed out and unable to sign in or order.` : `${c.name} will be able to sign in again.`, { confirmLabel: suspend ? "Suspend" : "Reactivate", danger: suspend }))) return;
      try { await api("PUT", "/api/admin/customers/" + id, { status: suspend ? "suspended" : "active" }); toast("Account updated"); customerDetail(el, id); } catch (e) { toast(e.message, "err"); }
    };
    const bcs = el.querySelector("#bcs");
    if (bcs) bcs.onclick = async () => { try { await api("PUT", "/api/admin/customers/" + id, { buyer_code: el.querySelector("#bc").value }); toast("Buyer code saved"); customerDetail(el, id); } catch (e) { toast(e.message, "err"); } };
  }

  // ------------------------------------------------------------------ BUYERS
  async function buyers(el) {
    const st = { company: "", category: "", q: "" };
    const load = async () => {
      const p = new URLSearchParams(); Object.entries(st).forEach(([k, v]) => v && p.set(k, v));
      const d = await api("GET", "/api/admin/buyers?" + p);
      el.innerHTML = `<div class="card" style="margin-bottom:14px"><h2>How buyer codes work</h2><div class="sub" style="margin:0">Code format <b>COMPANY-CATEGORY-SENIORITY</b>, e.g. <b>A-O-1</b> = Alpha Company, Officer, seniority 1. Real names stay private to authorised staff; reports show codes. Link a code to a customer account from the customer's page.</div></div>
        <div class="toolbar"><input type="search" class="inp" id="bq" placeholder="Search code or name" value="${esc(st.q)}">
        <select id="bco"><option value="">All companies</option>${d.companies.map((c) => `<option value="${c.code}" ${st.company === c.code ? "selected" : ""}>${c.code} — ${esc(c.name)}</option>`).join("")}</select>
        <select id="bca"><option value="">All categories</option>${d.categories.map((c) => `<option value="${c.code}" ${st.category === c.code ? "selected" : ""}>${c.code} — ${esc(c.name)}</option>`).join("")}</select>
        <span class="grow"></span><button class="btn btn-sm" id="b-comp">+ Company</button><button class="btn btn-sm" id="b-cat">+ Category</button><button class="btn btn-sm" id="b-imp">⬆ Import CSV</button>
        ${can("reports") ? `<button class="btn btn-sm" id="b-exp">⬇ Export</button>` : ""}<button class="btn btn-sm btn-primary" id="b-add">+ Add buyer</button></div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Code</th><th>Company</th><th>Category</th><th class="num">Seniority</th><th>Name (private)</th><th>Linked account</th><th class="num">Orders</th><th class="num">Spent</th><th>Status</th><th></th></tr></thead><tbody>
        ${d.items.map((b) => `<tr><td><b>${esc(b.code)}</b> ${b.is_sample ? '<span class="pill sample">SAMPLE</span>' : ""}</td><td>${esc(b.company_code)}</td><td>${esc(b.category_code)}</td><td class="num">${b.seniority}</td><td>${esc(b.real_name || "—")}</td>
          <td>${b.account_name ? esc(b.account_name) + `<div class="muted">${esc(b.account_email || "")}</div>` : '<span class="muted">Not linked</span>'}</td><td class="num">${b.orders}</td><td class="num">${fmt.inr(b.spent, 0)}</td>
          <td>${b.active ? '<span class="pill ok">Active</span>' : '<span class="pill">Inactive</span>'}</td><td><div style="display:flex;gap:6px"><button class="btn btn-sm" data-be="${b.id}">Edit</button><button class="btn btn-sm" data-bd="${b.id}" style="color:#c62828">Delete</button></div></td></tr>`).join("") || `<tr><td colspan="10" class="empty-sm">No buyers.</td></tr>`}</tbody></table></div>`;
      el.querySelector("#bq").oninput = debounce((e) => { st.q = e.target.value.trim(); load(); });
      el.querySelector("#bco").onchange = (e) => { st.company = e.target.value; load(); };
      el.querySelector("#bca").onchange = (e) => { st.category = e.target.value; load(); };
      const be = el.querySelector("#b-exp"); if (be) be.onclick = () => download("/api/admin/export/buyers?" + rq());
      el.querySelector("#b-add").onclick = async () => {
        const ok = await modal({ title: "Add buyer code", body: `<div class="row3"><label class="fld"><span>Company</span><select id="nc">${d.companies.map((c) => `<option value="${c.code}">${c.code} — ${esc(c.name)}</option>`).join("")}</select></label>
          <label class="fld"><span>Category</span><select id="nk">${d.categories.map((c) => `<option value="${c.code}">${c.code} — ${esc(c.name)}</option>`).join("")}</select></label><label class="fld"><span>Seniority</span><input id="ns" type="number" min="1" value="1"></label></div>
          <label class="fld"><span>Name (private, optional)</span><input id="nn"></label>`,
          actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Add", cls: "btn-primary", handler: (m) => api("POST", "/api/admin/buyers", { company_code: m.querySelector("#nc").value, category_code: m.querySelector("#nk").value, seniority: m.querySelector("#ns").value, real_name: m.querySelector("#nn").value }) }] });
        if (ok) { toast("Buyer added"); load(); }
      };
      el.querySelectorAll("[data-be]").forEach((btn) => (btn.onclick = async () => {
        const b = d.items.find((x) => x.id == btn.dataset.be);
        const ok = await modal({ title: "Edit " + b.code, body: `<label class="fld"><span>Name (private)</span><input id="en" value="${esc(b.real_name || "")}"></label><label class="chk"><input type="checkbox" id="ea" ${b.active ? "checked" : ""}> Active</label>`,
          actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (m) => api("PUT", "/api/admin/buyers/" + b.id, { real_name: m.querySelector("#en").value, active: m.querySelector("#ea").checked }) }] });
        if (ok) { toast("Saved"); load(); }
      }));
      el.querySelectorAll("[data-bd]").forEach((btn) => (btn.onclick = async () => {
        const b = d.items.find((x) => x.id == btn.dataset.bd);
        if (!(await confirmDialog("Delete buyer code", `Delete ${b.code}? Codes with order history are deactivated instead.`, { confirmLabel: "Delete", danger: true }))) return;
        try { const r = await api("DELETE", "/api/admin/buyers/" + b.id); toast(r.message); load(); } catch (e) { toast(e.message, "err"); }
      }));
      const simple = (title, url) => async () => {
        const ok = await modal({ title, body: `<div class="row2"><label class="fld"><span>Code (1–3 letters)</span><input id="xc" maxlength="3" style="text-transform:uppercase"></label><label class="fld"><span>Name</span><input id="xn"></label></div>`,
          actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Add", cls: "btn-primary", handler: (m) => api("POST", url, { code: m.querySelector("#xc").value, name: m.querySelector("#xn").value }) }] });
        if (ok) { toast("Added"); load(); }
      };
      el.querySelector("#b-comp").onclick = simple("Add company", "/api/admin/companies");
      el.querySelector("#b-cat").onclick = simple("Add rank category", "/api/admin/rank-categories");
      el.querySelector("#b-imp").onclick = importBuyers.bind(null, load);
    };
    await load();
  }

  function importBuyers(reload) {
    let csvText = "";
    modal({ title: "Import buyer master (CSV)", wide: true,
      body: `<p style="font-size:14px">Columns: <code>company,category,seniority,name</code> (name optional). Existing codes get their name updated. Example:</p>
        <pre style="background:var(--bg-2);padding:10px;border-radius:8px;font-size:13px">company,category,seniority,name\nA,O,6,Maj. Example\nB,J,3,Sub. Example</pre>
        <label class="fld"><span>CSV file</span><input type="file" id="ifile" accept=".csv,text/csv"></label><label class="fld"><span>…or paste CSV</span><textarea id="itext" rows="5"></textarea></label><div id="iprev"></div>`,
      onOpen: (m) => { m.querySelector("#ifile").onchange = async (e) => { const f = e.target.files[0]; if (f) m.querySelector("#itext").value = await f.text(); }; },
      actions: [{ label: "Close", cls: "btn-ghost" },
        { label: "Preview", cls: "", handler: async (m) => {
          csvText = m.querySelector("#itext").value;
          const r = await api("POST", "/api/admin/buyers/import/preview", { csv: csvText });
          m.querySelector("#iprev").innerHTML = `<div class="kpis">${kpi("New codes", r.new)}${kpi("Updates", r.updates)}${kpi("Errors", r.errors.length, "", r.errors.length ? "bad" : "good")}</div>
            ${r.errors.length ? `<div class="tbl-wrap" style="max-height:180px;margin-bottom:10px"><table class="tbl"><thead><tr><th>Line</th><th>Problem</th></tr></thead><tbody>${r.errors.map((x) => `<tr><td>${x.line}</td><td style="color:#c62828">${esc(x.error)}</td></tr>`).join("")}</tbody></table></div>` : ""}
            <div class="tbl-wrap" style="max-height:220px"><table class="tbl"><thead><tr><th>Line</th><th>Code</th><th>Name</th><th>Action</th></tr></thead><tbody>${r.rows.slice(0, 200).map((x) => `<tr><td>${x.line}</td><td><b>${esc(x.code)}</b></td><td>${esc(x.real_name || "")}</td><td>${x.action === "new" ? '<span class="pill ok">New</span>' : '<span class="pill info">Update</span>'}</td></tr>`).join("")}</tbody></table></div>`;
          return false;
        } },
        { label: "Import", cls: "btn-primary", handler: async (m) => {
          csvText = m.querySelector("#itext").value;
          try { const r = await api("POST", "/api/admin/buyers/import/commit", { csv: csvText }); toast(`Imported ${r.imported} rows`); reload(); return true; }
          catch (e) { toast(e.message, "err"); return false; }
        } }] });
  }

  function importProducts(reload) {
    const sample = "name,category,price,stock,description,brand,mrp,sku,low_stock,gst\nSample Biscuit 100g,Groceries,20,50,Tasty biscuit,Parle,25,BISC-100,10,5\nSample Soap,Toiletries,35,100,Bathing soap,Lifebuoy,40,SOAP-01,10,18\n";
    modal({ title: "Import products (CSV)", wide: true,
      body: `<p style="font-size:14px">Columns: <code>name, category, price</code> are required. Optional: <code>stock, description, brand, mrp, sku, low_stock, gst, cost_price, subcategory, status</code>. The category name must already exist (Categories page). Products are added as <b>active</b> unless <code>status</code> says otherwise. Photos are added afterwards, product by product.</p>
        <p><a href="#" id="isample">⬇ Download a sample CSV</a></p>
        <label class="fld"><span>CSV file</span><input type="file" id="ifile" accept=".csv,text/csv"></label>
        <label class="fld"><span>…or paste CSV</span><textarea id="itext" rows="5"></textarea></label><div id="iprev"></div>`,
      onOpen: (m) => {
        m.querySelector("#ifile").onchange = async (e) => { const f = e.target.files[0]; if (f) m.querySelector("#itext").value = await f.text(); };
        m.querySelector("#isample").onclick = (e) => { e.preventDefault(); const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([sample], { type: "text/csv" })); a.download = "products-sample.csv"; a.click(); };
      },
      actions: [{ label: "Close", cls: "btn-ghost" },
        { label: "Preview", cls: "", handler: async (m) => {
          try {
            const r = await api("POST", "/api/admin/products/import/preview", { csv: m.querySelector("#itext").value });
            m.querySelector("#iprev").innerHTML = `<div class="kpis">${kpi("Ready to add", r.ok, "", "good")}${kpi("Errors", r.error_count, "", r.error_count ? "bad" : "good")}</div>
              ${r.errors.length ? `<div class="tbl-wrap" style="max-height:180px;margin-bottom:10px"><table class="tbl"><thead><tr><th>Line</th><th>Item</th><th>Problem</th></tr></thead><tbody>${r.errors.map((x) => `<tr><td>${x.line}</td><td>${esc(x.name || "")}</td><td style="color:#c62828">${esc(x.error)}</td></tr>`).join("")}</tbody></table></div>` : ""}
              <div class="tbl-wrap" style="max-height:220px"><table class="tbl"><thead><tr><th>Line</th><th>Name</th><th>SKU</th><th>Price</th><th>Stock</th></tr></thead><tbody>${r.rows.map((x) => `<tr><td>${x.line}</td><td>${esc(x.name)}</td><td>${esc(x.sku)}</td><td>${x.price}</td><td>${x.stock}</td></tr>`).join("")}</tbody></table></div>`;
          } catch (e) { toast(e.message, "err"); }
          return false;
        } },
        { label: "Import", cls: "btn-primary", handler: async (m) => {
          try { const r = await api("POST", "/api/admin/products/import/commit", { csv: m.querySelector("#itext").value }); toast(`Added ${r.imported} products`); reload(); return true; }
          catch (e) { toast(e.message, "err"); return false; }
        } }] });
  }

  // ------------------------------------------------------------------ PRODUCTS
  async function products(el, parts, q) {
    if (parts[0] === "new") return productForm(el, null);
    if (parts[0]) return productForm(el, +parts[0]);
    const cats = await loadCats();
    const st = { q: "", status: q.get("status") || "", category: "", stock: q.get("stock") || "", sort: "", page: 1 };
    el.innerHTML = `<div class="toolbar"><input type="search" class="inp" id="pq" placeholder="Search name, SKU or brand">
      <select id="pst"><option value="">All statuses</option><option value="active">Active</option><option value="inactive">Inactive</option><option value="draft">Draft</option><option value="out_of_stock">Out of stock (status)</option></select>
      <select id="pc"><option value="">All categories</option>${cats.filter((c) => !c.parent_id).map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      <select id="pstock"><option value="">Any stock</option><option value="low">Low stock</option><option value="out">Out of stock</option></select>
      <select id="psort"><option value="">Recently updated</option><option value="name">Name</option><option value="price">Price</option><option value="stock">Available stock</option><option value="sold">Units sold</option></select>
      <span class="grow"></span>${can("reports") ? `<button class="btn btn-sm" id="pexp">⬇ Export</button>` : ""}${can("products") ? `<button class="btn btn-sm" id="pimp">⬆ Import CSV</button><a class="btn btn-primary btn-sm" href="#/products/new">+ Add product</a>` : ""}</div><div id="plist"></div>`;
    el.querySelector("#pst").value = st.status; el.querySelector("#pstock").value = st.stock;
    const load = async () => {
      const box = el.querySelector("#plist");
      const p = new URLSearchParams({ page: st.page, per: 25 }); ["q", "status", "category", "stock", "sort"].forEach((k) => st[k] && p.set(k, st[k]));
      const d = await api("GET", "/api/admin/products?" + p);
      const edit = can("products");
      box.innerHTML = d.items.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th></th><th>Product</th><th>Category</th><th>Status</th>${"cost_price" in d.items[0] ? '<th class="num">Cost</th>' : ""}<th class="num">Selling price</th><th class="num">MRP</th><th class="num">Avail.</th><th class="num">Reserved</th><th class="num">Sold</th><th class="num">Rating</th><th></th></tr></thead><tbody>
        ${d.items.map((r) => `<tr><td><img class="thumb" src="${esc(r.image || "/static/common/placeholder.svg")}" alt=""></td>
          <td><a href="#/products/${r.id}" class="pname">${esc(r.name)}</a> ${r.is_sample ? '<span class="pill sample">SAMPLE</span>' : ""}<div class="muted">${esc(r.sku)} · ${esc(r.brand || "")}</div></td>
          <td>${esc(r.category || "—")}<div class="muted">${esc(r.subcategory || "")}</div></td>
          <td>${edit ? `<select class="inp" data-qs="${r.id}" style="min-height:32px;padding:2px 6px;width:auto">${["active", "inactive", "draft", "out_of_stock"].map((s) => `<option value="${s}" ${r.status === s ? "selected" : ""}>${s.replace(/_/g, " ")}</option>`).join("")}</select>` : esc(r.status)}</td>
          ${"cost_price" in r ? `<td class="num">${fmt.inr(r.cost_price)}</td>` : ""}
          <td class="num">${edit ? `<input class="inline" data-qp="${r.id}" type="number" step="0.01" min="0.01" value="${r.selling_price}" aria-label="Selling price">` : fmt.inr(r.selling_price)}${r.discount_pct ? `<div class="muted">${r.discount_pct}% off</div>` : ""}</td>
          <td class="num">${r.mrp ? fmt.inr(r.mrp) : "—"}</td>
          <td class="num">${r.available <= 0 ? '<span class="pill bad">0</span>' : r.available <= r.low_stock_threshold ? `<span class="pill warn">${r.available}</span>` : r.available}</td>
          <td class="num">${r.reserved_qty}</td><td class="num">${fmt.num(r.units_sold)}</td><td class="num">${r.rating_count ? `${Number(r.rating_avg).toFixed(1)}★ <span class="muted">(${r.rating_count})</span>` : "—"}</td>
          <td><a class="btn btn-sm" href="#/products/${r.id}">${edit ? "Edit" : "View"}</a></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty"><div class="ico">📦</div><h3>No products found</h3>${edit ? '<a class="btn btn-primary" href="#/products/new">Add your first product</a>' : ""}</div>`;
      if (d.items.length) pager(box, d, (n) => { st.page = n; load(); });
      box.querySelectorAll("[data-qs]").forEach((s) => (s.onchange = async () => {
        try { await api("PATCH", "/api/admin/products/" + s.dataset.qs, { status: s.value }); toast("Status updated"); } catch (e) { toast(e.message, "err"); load(); }
      }));
      box.querySelectorAll("[data-qp]").forEach((inp) => (inp.onchange = async () => {
        try { const r = await api("PATCH", "/api/admin/products/" + inp.dataset.qp, { selling_price: inp.value }); toast(`Price updated to ${fmt.inr(r.selling_price)}`); } catch (e) { toast(e.message, "err"); load(); }
      }));
    };
    el.querySelector("#pq").oninput = debounce((e) => { st.q = e.target.value.trim(); st.page = 1; load(); });
    [["#pst", "status"], ["#pc", "category"], ["#pstock", "stock"], ["#psort", "sort"]].forEach(([s, k]) => (el.querySelector(s).onchange = (e) => { st[k] = e.target.value; st.page = 1; load(); }));
    const ex = el.querySelector("#pexp"); if (ex) ex.onclick = () => download("/api/admin/export/products?" + rq());
    const im = el.querySelector("#pimp"); if (im) im.onclick = () => importProducts(() => load());
    await load();
  }

  async function productForm(el, id) {
    const cats = await loadCats();
    const p = id ? await api("GET", "/api/admin/products/" + id) : { status: "draft", specs: {}, tax_rate: 18, low_stock_threshold: 10, max_per_order: 10, images: [] };
    const edit = can("products");
    document.getElementById("ttl").textContent = id ? p.name : "Add product";
    const roots = cats.filter((c) => !c.parent_id);
    const subsOf = (cid) => cats.filter((c) => c.parent_id == cid);
    el.innerHTML = `<div class="toolbar"><a class="btn btn-sm" href="#/products">‹ All products</a><span class="grow"></span>${p.is_sample ? '<span class="pill sample">SAMPLE PRODUCT</span>' : ""}
      ${id && edit ? `<button class="btn btn-sm" id="pdel" style="color:#c62828">Delete product</button>` : ""}</div>
      <div class="split"><form class="card" id="pf" novalidate>
        <h2 style="margin-bottom:12px">${id ? "Edit product" : "New product"}</h2>
        <label class="fld"><span>Product name *</span><input name="name" required value="${esc(p.name || "")}"></label>
        <label class="fld"><span>Description</span><textarea name="description" rows="4">${esc(p.description || "")}</textarea></label>
        <div class="row3"><label class="fld"><span>Category *</span><select name="category_id" id="fcat"><option value="">Choose…</option>${roots.map((c) => `<option value="${c.id}" ${p.category_id == c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
          <label class="fld"><span>Subcategory</span><select name="subcategory_id" id="fsub"></select></label>
          <label class="fld"><span>Brand</span><input name="brand" value="${esc(p.brand || "")}"></label></div>
        <div class="row3"><label class="fld"><span>SKU</span><input name="sku" value="${esc(p.sku || "")}" placeholder="Auto-generated if empty"></label>
          <label class="fld"><span>Status</span><select name="status">${[["active", "Active (visible in store)"], ["inactive", "Inactive (hidden)"], ["draft", "Draft"], ["out_of_stock", "Out of stock (visible, not buyable)"]].map(([v, l]) => `<option value="${v}" ${p.status === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
          <label class="chk" style="margin-top:30px"><input type="checkbox" name="featured" ${p.featured ? "checked" : ""}> Featured on home page</label></div>
        <div class="form-sec"><h3>Pricing</h3><div class="row3">
          <label class="fld"><span>Cost price (₹)</span><input name="cost_price" type="number" step="0.01" min="0" value="${p.cost_price ?? ""}"><small>Private — used for profit estimates</small></label>
          <label class="fld"><span>MRP (₹)</span><input name="mrp" type="number" step="0.01" min="0" value="${p.mrp ?? ""}"></label>
          <label class="fld"><span>Selling price (₹) *</span><input name="selling_price" type="number" step="0.01" min="0.01" required value="${p.selling_price ?? ""}"></label></div>
          <div class="row3"><label class="fld"><span>Discount % off MRP</span><input name="discount_pct" type="number" min="0" max="95" step="0.1" value="${p.discount_pct ?? ""}"><small><label class="chk" style="margin:4px 0 0"><input type="checkbox" name="apply_discount"> Set selling price from MRP and discount</label></small></label>
          <label class="fld"><span>GST rate %</span><input name="tax_rate" type="number" min="0" max="40" step="0.5" value="${p.tax_rate ?? 18}"></label>
          <div class="fld"><span>Margin</span><div id="margin" style="padding-top:10px;font-weight:600">—</div></div></div></div>
        <div class="form-sec"><h3>Stock</h3><div class="row3">
          ${id ? `<div class="fld"><span>Physical / reserved / unavailable</span><div style="padding-top:10px"><b>${p.physical_stock}</b> / ${p.reserved_qty} / ${p.unavailable_qty} → <b>${p.available} available</b></div><small>Change stock from Inventory so every movement is logged.</small></div>` :
            `<label class="fld"><span>Opening stock (units)</span><input name="stock" type="number" min="0" step="1" value="0"></label>`}
          <label class="fld"><span>Low-stock alert at</span><input name="low_stock_threshold" type="number" min="0" step="1" value="${p.low_stock_threshold ?? 10}"></label>
          <label class="fld"><span>Max units per order</span><input name="max_per_order" type="number" min="1" step="1" value="${p.max_per_order ?? 10}"></label></div>
          ${id && can("inventory") ? `<button type="button" class="btn btn-sm" id="adj">Adjust stock…</button>` : ""}</div>
        <div class="form-sec"><h3>Shipping</h3><div class="row3">
          <label class="fld"><span>Weight (grams)</span><input name="weight_g" type="number" min="0" step="1" value="${p.weight_g ?? ""}"></label>
          <label class="fld"><span>Dimensions</span><input name="dimensions" value="${esc(p.dimensions || "")}" placeholder="L x W x H cm"></label>
          <label class="fld"><span>Shipping requirements</span><input name="shipping_req" value="${esc(p.shipping_req || "")}" placeholder="e.g. Fragile"></label></div></div>
        <div class="form-sec"><h3>Specifications</h3><div id="specs"></div><button type="button" class="btn btn-sm" id="addspec">+ Add specification</button></div>
        ${edit ? `<div style="display:flex;gap:10px;margin-top:18px"><button class="btn btn-primary" id="psave">${id ? "Save changes" : "Create product"}</button><a class="btn" href="#/products">Cancel</a></div>` : ""}
      </form>
      <div><div class="card" style="margin-bottom:14px"><h2>Images</h2><div class="sub">JPG, PNG, WEBP or GIF up to 5 MB each, max 8. The first image is the main photo.</div>
        ${id ? `<div class="img-grid" id="imgs"></div>` : `<div class="empty-sm">Save the product first, then add images.</div>`}</div>
        ${id ? `<div class="card"><h2>Recent stock movements</h2>${p.movements.length ? `<table class="tbl"><tbody>${p.movements.slice(0, 12).map((m) => `<tr><td>${esc(m.type.replace(/_/g, " "))}<div class="muted">${fmt.datetime(m.created_at)}${m.order_no ? " · " + esc(m.order_no) : ""}</div></td><td class="num">${m.qty > 0 && !["sold", "reserved", "damaged", "damage_cleared"].includes(m.type) ? "+" : m.type === "adjustment" ? "" : "−"}${Math.abs(m.qty)}</td><td class="num muted">→ ${m.physical_after}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">No movements.</div>`}</div>` : ""}
      </div></div>`;
    const f = el.querySelector("#pf");
    const fillSubs = () => { const v = el.querySelector("#fcat").value; el.querySelector("#fsub").innerHTML = `<option value="">None</option>` + subsOf(v).map((s) => `<option value="${s.id}" ${p.subcategory_id == s.id ? "selected" : ""}>${esc(s.name)}</option>`).join(""); };
    el.querySelector("#fcat").onchange = () => { fillSubs(); const c = cats.find((x) => x.id == el.querySelector("#fcat").value); if (c && !id) f.tax_rate.value = c.default_tax_rate; };
    fillSubs();
    const margin = () => {
      const sp = +f.selling_price.value, cp = +f.cost_price.value, mrp = +f.mrp.value;
      el.querySelector("#margin").textContent = sp ? `${fmt.inr(sp - cp)} (${(((sp - cp) / sp) * 100).toFixed(1)}%)` + (mrp > sp ? ` · ${Math.round(((mrp - sp) / mrp) * 100)}% off MRP` : "") : "—";
    };
    ["selling_price", "cost_price", "mrp"].forEach((n) => f[n].addEventListener("input", margin)); margin();
    const specs = el.querySelector("#specs");
    const addSpec = (k = "", v = "") => {
      const row = document.createElement("div"); row.className = "spec-row";
      row.innerHTML = `<input class="inp" placeholder="Name (e.g. Battery)" value="${esc(k)}"><input class="inp" placeholder="Value (e.g. 5000 mAh)" value="${esc(v)}"><button type="button" class="btn btn-sm" aria-label="Remove">✕</button>`;
      row.querySelector("button").onclick = () => row.remove();
      specs.appendChild(row);
    };
    Object.entries(p.specs || {}).forEach(([k, v]) => addSpec(k, v));
    if (!Object.keys(p.specs || {}).length) addSpec();
    el.querySelector("#addspec").onclick = () => addSpec();
    if (!edit) f.querySelectorAll("input,select,textarea,button").forEach((x) => (x.disabled = true));
    const save = el.querySelector("#psave");
    if (save) f.onsubmit = async (e) => {
      e.preventDefault();
      const d = formData(f);
      d.specs = {}; specs.querySelectorAll(".spec-row").forEach((r) => { const [k, v] = r.querySelectorAll("input"); if (k.value.trim()) d.specs[k.value.trim()] = v.value.trim(); });
      save.disabled = true;
      try {
        const r = await api(id ? "PUT" : "POST", id ? "/api/admin/products/" + id : "/api/admin/products", d);
        toast(id ? "Product saved" : "Product created — now add images");
        if (!id) location.hash = "#/products/" + r.id; else productForm(el, id);
      } catch (ex) { toast(ex.message, "err"); save.disabled = false; }
    };
    if (id) paintImages(el, id, p.images, edit);
    const del = el.querySelector("#pdel");
    if (del) del.onclick = async () => {
      if (!(await confirmDialog("Delete product", `Delete “${p.name}”? Products with past orders are archived (set Inactive) so sales history stays accurate.`, { confirmLabel: "Delete", danger: true }))) return;
      try { const r = await api("DELETE", "/api/admin/products/" + id); toast(r.message); location.hash = "#/products"; } catch (e) { toast(e.message, "err"); }
    };
    const adj = el.querySelector("#adj");
    if (adj) adj.onclick = async () => { if (await stockDialog({ id, name: p.name, physical_stock: p.physical_stock, reserved_qty: p.reserved_qty, unavailable_qty: p.unavailable_qty, available: p.available })) productForm(el, id); };
  }

  function paintImages(el, id, images, edit) {
    const box = el.querySelector("#imgs");
    box.innerHTML = images.map((im, i) => `<div class="im ${i === 0 ? "primary" : ""}"><img src="${esc(im.url)}" alt="">${edit ? `<div class="acts">${i ? `<button data-pr="${im.id}">Make main</button>` : "<span></span>"}<button data-rm="${im.id}">Delete</button></div>` : ""}</div>`).join("")
      + (edit && images.length < 8 ? `<label class="drop">+ Add images<input type="file" id="up" accept="image/jpeg,image/png,image/webp,image/gif" multiple hidden></label>` : "");
    const up = box.querySelector("#up");
    if (up) up.onchange = async () => {
      const fd = new FormData(); [...up.files].forEach((f) => fd.append("files", f));
      try { const r = await api("POST", `/api/admin/products/${id}/images`, fd); toast("Images uploaded"); paintImages(el, id, r.images, edit); } catch (e) { toast(e.message, "err"); }
    };
    box.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Delete image", "Remove this image?", { confirmLabel: "Delete", danger: true }))) return;
      await api("DELETE", "/api/admin/images/" + b.dataset.rm); const p = await api("GET", "/api/admin/products/" + id); paintImages(el, id, p.images, edit);
    }));
    box.querySelectorAll("[data-pr]").forEach((b) => (b.onclick = async () => { await api("POST", `/api/admin/images/${b.dataset.pr}/primary`); const p = await api("GET", "/api/admin/products/" + id); paintImages(el, id, p.images, edit); }));
  }

  // ------------------------------------------------------------------ CATEGORIES
  async function categories(el) {
    const cats = await loadCats();
    const roots = cats.filter((c) => !c.parent_id);
    const edit = can("products");
    el.innerHTML = `<div class="toolbar"><div class="sub" style="color:var(--ink-3)">${roots.length} categories · ${cats.length - roots.length} subcategories</div><span class="grow"></span>${edit ? `<button class="btn btn-primary btn-sm" id="cadd">+ Add category</button>` : ""}</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Photo</th><th>Name</th><th>Department</th><th class="num">Products</th><th class="num">Default GST</th><th>Visible</th><th></th></tr></thead><tbody>
      ${roots.map((r) => [r, ...cats.filter((c) => c.parent_id === r.id)].map((c) => `<tr><td>${c.image ? `<img src="${esc(c.image)}" alt="" style="width:44px;height:44px;object-fit:cover;border-radius:8px;display:block">` : '<span class="muted" style="font-size:12px">Auto</span>'}</td><td style="${c.parent_id ? "padding-left:34px" : "font-weight:700"}">${c.parent_id ? "↳ " : ""}${esc(c.name)}</td><td>${esc(c.department || "")}</td><td class="num">${c.products}</td><td class="num">${c.default_tax_rate}%</td>
        <td>${c.active ? '<span class="pill ok">Yes</span>' : '<span class="pill">Hidden</span>'}</td><td>${edit ? `<div style="display:flex;gap:6px">${!c.parent_id ? `<button class="btn btn-sm" data-sub="${c.id}">+ Sub</button>` : ""}<button class="btn btn-sm" data-ph="${c.id}">📷 Photo</button><button class="btn btn-sm" data-ed="${c.id}">Edit</button><button class="btn btn-sm" data-del="${c.id}" style="color:#c62828">Delete</button></div>` : ""}</td></tr>`).join("")).join("")}
      </tbody></table></div>`;
    const dlg = async (c = {}, parent = null) => {
      const ok = await modal({ title: c.id ? "Edit category" : parent ? "Add subcategory" : "Add category",
        body: `<label class="fld"><span>Name</span><input id="cn" value="${esc(c.name || "")}"></label>
          <div class="row2"><label class="fld"><span>Parent</span><select id="cp"><option value="">— Top level —</option>${roots.filter((r) => r.id !== c.id).map((r) => `<option value="${r.id}" ${(c.parent_id || parent) == r.id ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label>
          <label class="fld"><span>Department (store tab)</span><input id="cd" list="depts" value="${esc(c.department || (parent ? (roots.find((r) => r.id === parent) || {}).department : "") || "")}"><datalist id="depts">${[...new Set(roots.map((r) => r.department).filter(Boolean))].map((d) => `<option value="${esc(d)}">`).join("")}</datalist></label></div>
          <div class="row3"><label class="fld"><span>Default GST %</span><input id="ct" type="number" value="${c.default_tax_rate ?? 18}"></label><label class="fld"><span>Sort order</span><input id="cs" type="number" value="${c.sort ?? 0}"></label>
          <label class="chk" style="margin-top:30px"><input type="checkbox" id="ca" ${c.active !== 0 ? "checked" : ""}> Visible</label></div>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (m) => {
          const d = { name: m.querySelector("#cn").value, parent_id: m.querySelector("#cp").value || null, department: m.querySelector("#cd").value, default_tax_rate: m.querySelector("#ct").value, sort: m.querySelector("#cs").value, active: m.querySelector("#ca").checked, icon: c.icon, color: c.color };
          return c.id ? api("PUT", "/api/admin/categories/" + c.id, d) : api("POST", "/api/admin/categories", d);
        } }] });
      if (ok) { toast("Category saved"); categories(el); }
    };
    const photoDlg = (c) => modal({ title: "Category photo · " + c.name,
      body: `<div style="text-align:center;margin-bottom:12px">${c.image ? `<img src="${esc(c.image)}" alt="" style="max-width:100%;max-height:220px;border-radius:12px">` : `<p class="muted" style="margin:0">No photo chosen yet. The store shows the first product's picture.</p>`}</div>
        <label class="fld"><span>Choose a photo (JPG, PNG or WEBP, up to 5 MB)</span><input type="file" id="cpf" accept="image/*"></label>
        <p class="muted" style="font-size:13px;margin:6px 0 0">Tip: a square photo looks best on the store.</p>`,
      actions: [{ label: "Close", cls: "btn-ghost" },
        ...(c.image ? [{ label: "Remove photo", cls: "", handler: async () => {
          try { await api("DELETE", `/api/admin/categories/${c.id}/image`); toast("Photo removed"); categories(el); return true; } catch (e) { toast(e.message, "err"); return false; } } }] : []),
        { label: "Upload", cls: "btn-primary", handler: async (m) => {
          const f = m.querySelector("#cpf").files[0];
          if (!f) { toast("Choose a photo first", "err"); return false; }
          const fd = new FormData(); fd.append("file", f);
          try { await api("POST", `/api/admin/categories/${c.id}/image`, fd); toast("Photo saved"); categories(el); return true; } catch (e) { toast(e.message, "err"); return false; }
        } }] });
    el.querySelectorAll("[data-ph]").forEach((b) => (b.onclick = () => photoDlg(cats.find((c) => c.id == b.dataset.ph))));
    const add = el.querySelector("#cadd"); if (add) add.onclick = () => dlg();
    el.querySelectorAll("[data-sub]").forEach((b) => (b.onclick = () => dlg({}, +b.dataset.sub)));
    el.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = () => dlg(cats.find((c) => c.id == b.dataset.ed))));
    el.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      const c = cats.find((x) => x.id == b.dataset.del);
      if (!(await confirmDialog("Delete category", `Delete “${c.name}”? Categories that still contain products or subcategories can't be deleted.`, { confirmLabel: "Delete", danger: true }))) return;
      try { await api("DELETE", "/api/admin/categories/" + c.id); toast("Category deleted"); categories(el); } catch (e) { toast(e.message, "err"); }
    }));
  }

  // ------------------------------------------------------------------ INVENTORY
  function stockDialog(p, types) {
    return modal({ title: "Stock update · " + p.name,
      body: `<p style="font-size:14px">Physical <b>${p.physical_stock}</b> − Reserved <b>${p.reserved_qty}</b> − Unavailable <b>${p.unavailable_qty}</b> = <b>${p.available} available</b></p>
        <label class="fld"><span>Operation</span><select id="st"><option value="received">New stock received (+)</option><option value="damaged">Mark units damaged / unavailable</option>
          <option value="restored">Restore unavailable units to sale</option><option value="damage_cleared">Write off damaged units (remove)</option><option value="adjustment">Manual adjustment (+/−, e.g. stock count)</option></select></label>
        <label class="fld"><span>Quantity</span><input id="sq" type="number" step="1" value="1"><small id="sqh">Positive number.</small></label>
        <label class="fld"><span>Note / reason</span><input id="sn" placeholder="e.g. Supplier invoice #123, stock count correction"></label>`,
      onOpen: (m) => { m.querySelector("#st").onchange = (e) => { m.querySelector("#sqh").textContent = e.target.value === "adjustment" ? "Use a negative number to remove units (reason required)." : "Positive number."; }; },
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Apply", cls: "btn-primary", handler: async (m) => {
        await api("POST", `/api/admin/inventory/${p.id}/adjust`, { type: m.querySelector("#st").value, qty: m.querySelector("#sq").value, note: m.querySelector("#sn").value });
        toast("Stock updated");
      } }] });
  }

  async function inventory(el, parts, q) {
    let filter = q.get("filter") || "", search = "", tab = "stock";
    const load = async () => {
      if (tab === "moves") return moves();
      const d = await api("GET", `/api/admin/inventory?filter=${filter}&q=${encodeURIComponent(search)}`);
      const tot = d.items.reduce((a, r) => ({ phys: a.phys + r.physical_stock, res: a.res + r.reserved_qty, un: a.un + r.unavailable_qty, av: a.av + r.available, val: a.val + r.value_cost }), { phys: 0, res: 0, un: 0, av: 0, val: 0 });
      box.innerHTML = `<div class="kpis">${kpi("Physical stock", fmt.num(tot.phys))}${kpi("Reserved for orders", fmt.num(tot.res))}${kpi("Unavailable / damaged", fmt.num(tot.un))}${kpi("Available to sell", fmt.num(tot.av), "Physical − Reserved − Unavailable", "hl")}${"value_cost" in (d.items[0] || {}) ? kpi("Value at cost", fmt.compact(tot.val)) : ""}</div>
        <div class="toolbar"><input type="search" class="inp" id="iq" placeholder="Search product or SKU" value="${esc(search)}"><div class="seg">${[["", "All"], ["low", "Low stock"], ["out", "Out of stock"], ["reserved", "Has reservations"], ["damaged", "Has damaged"]].map(([k, l]) => `<button data-f="${k}" class="${filter === k ? "on" : ""}">${l}</button>`).join("")}</div>
          <span class="grow"></span>${can("reports") ? `<button class="btn btn-sm" id="iexp">⬇ Export stock</button>` : ""}</div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Product</th><th>Category</th><th class="num">Physical</th><th class="num">Reserved</th><th class="num">Unavailable</th><th class="num">Available</th><th class="num">Alert at</th><th class="num">Sold</th><th>Level</th><th></th></tr></thead><tbody>
          ${d.items.map((r) => `<tr><td class="pname">${esc(r.name)}<div class="muted">${esc(r.sku)}</div></td><td>${esc(r.category || "")}</td><td class="num">${r.physical_stock}</td><td class="num">${r.reserved_qty}</td><td class="num">${r.unavailable_qty}</td>
            <td class="num"><b>${r.available}</b></td><td class="num"><input class="inline" style="width:64px" type="number" min="0" data-th="${r.id}" value="${r.low_stock_threshold}" aria-label="Low stock threshold"></td><td class="num">${fmt.num(r.units_sold)}</td>
            <td>${r.level === "out" ? '<span class="pill bad">Out</span>' : r.level === "low" ? '<span class="pill warn">Low</span>' : '<span class="pill ok">OK</span>'}</td><td><button class="btn btn-sm btn-primary" data-adj="${r.id}">Update stock</button></td></tr>`).join("") || `<tr><td colspan="10" class="empty-sm">Nothing here.</td></tr>`}</tbody></table></div>`;
      box.querySelector("#iq").oninput = debounce((e) => { search = e.target.value.trim(); load(); });
      box.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { filter = b.dataset.f; load(); }));
      const ex = box.querySelector("#iexp"); if (ex) ex.onclick = () => download("/api/admin/export/products?" + rq());
      box.querySelectorAll("[data-adj]").forEach((b) => (b.onclick = async () => { const r = d.items.find((x) => x.id == b.dataset.adj); if (await stockDialog(r)) load(); }));
      box.querySelectorAll("[data-th]").forEach((i) => (i.onchange = async () => { try { await api("PUT", `/api/admin/inventory/${i.dataset.th}/threshold`, { low_stock_threshold: i.value }); toast("Alert level saved"); } catch (e) { toast(e.message, "err"); } }));
    };
    let mpage = 1, mtype = "";
    const moves = async () => {
      const d = await api("GET", `/api/admin/inventory/movements?page=${mpage}&type=${mtype}`);
      box.innerHTML = `<div class="toolbar"><select id="mt"><option value="">All movement types</option>${Object.entries(d.types).map(([k, v]) => `<option value="${k}" ${mtype === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select><span class="grow"></span>${can("reports") ? `<button class="btn btn-sm" id="mexp">⬇ Export movements (${RANGES.find((r) => r[0] === A.range)[1]})</button>` : ""}</div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>Product</th><th>Movement</th><th class="num">Qty</th><th class="num">Physical after</th><th class="num">Reserved after</th><th>Order</th><th>Note</th><th>By</th></tr></thead><tbody>
          ${d.items.map((m) => `<tr><td>${fmt.datetime(m.created_at)}</td><td>${esc(m.name)}<div class="muted">${esc(m.sku)}</div></td><td>${esc(d.types[m.type] || m.type)}</td><td class="num">${m.qty}</td><td class="num">${m.physical_after}</td><td class="num">${m.reserved_after}</td><td>${esc(m.order_no || "")}</td><td class="muted">${esc(m.note || "")}</td><td class="muted">${esc(m.by_user || (m.order_no ? "Order system" : ""))}</td></tr>`).join("")}</tbody></table></div>`;
      pager(box, d, (n) => { mpage = n; moves(); });
      box.querySelector("#mt").onchange = (e) => { mtype = e.target.value; mpage = 1; moves(); };
      const ex = box.querySelector("#mexp"); if (ex) ex.onclick = () => download("/api/admin/export/inventory?" + rq());
    };
    el.innerHTML = `<div class="toolbar"><div class="seg"><button data-t="stock" class="on">Stock levels</button><button data-t="moves">Movement log</button></div>
      <div class="sub" style="color:var(--ink-3);font-size:13px">Stock is reserved when an order is placed, deducted at dispatch, released on cancellation and restored on return.</div></div><div id="ibox"></div>`;
    const box = el.querySelector("#ibox");
    el.querySelectorAll("[data-t]").forEach((b) => (b.onclick = () => { tab = b.dataset.t; el.querySelectorAll("[data-t]").forEach((x) => x.classList.toggle("on", x === b)); load(); }));
    await load();
  }

  // ------------------------------------------------------------------ AI INSIGHTS
  async function insights(el) {
    el.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
    const d = await api("GET", "/api/admin/analytics/insights");
    const t = d.totals, f = d.funnel;
    const GROUPS = [["best_sellers", "Best sellers"], ["increasing", "Increasing demand"], ["declining", "Declining demand"], ["low_sales", "Low sales"],
      ["interest_low_conversion", "High interest, low conversion"], ["frequent_stockouts", "Frequently out of stock"], ["overstock_risk", "Overstock risk"], ["restock_soon", "Restock soon"]];
    let gsel = "best_sellers";
    const cats = await loadCats();
    el.innerHTML = `
      <div class="est-note" style="margin:0 0 14px">All figures below are calculated from orders, stock, product views and searches recorded in this app (window ${fmt.date(d.data_window.from)} – ${fmt.date(d.data_window.to)}). Forecasts are statistical <b>estimates</b> and are shown separately from recorded history. Sample data is included until you clear it in Settings.</div>
      <div class="kpis">${kpi("Revenue · last 30 days", fmt.inr(t.revenue_30, 0), `${fmt.pct(t.revenue_prev_30 ? ((t.revenue_30 - t.revenue_prev_30) / t.revenue_prev_30) * 100 : null)} vs previous 30 days`, "hl")}
        ${kpi("Units sold · 30 days", fmt.num(t.units_30), `${fmt.num(t.units_prev_30)} in previous 30`)}
        ${kpi("Product views · 30 days", fmt.num(f.views_30), `${f.view_to_cart_pct ?? "—"}% added to cart`)}
        ${kpi("View → order", (f.view_to_order_pct ?? "—") + "%", `${fmt.num(f.orders_30)} orders`)}
        ${kpi("Restock alerts", d.groups.restock_soon.length, `lead time ${d.lead_days} days`, d.groups.restock_soon.length ? "warn" : "", "")}</div>
      <div class="cards">
        <div class="card c7"><div class="card-h"><div><h2>Recommendations</h2><div class="sub">Generated from your stored data — each shows the evidence behind it</div></div></div>
          <div id="recos">${d.recommendations.length ? d.recommendations.map((r, ri) => `<div class="reco" ${ri >= 8 ? "data-more hidden" : ""}><div class="sev">${{ high: '<span class="pill bad">Act now</span>', medium: '<span class="pill warn">Review</span>', info: '<span class="pill info">Insight</span>', low: '<span class="pill">Watch</span>' }[r.severity]}</div>
            <div><div>${esc(r.message)}</div><div class="ev">Evidence: ${esc(r.evidence)}</div></div></div>`).join("") + (d.recommendations.length > 8 ? `<button class="btn btn-sm" id="more-recos" style="margin-top:8px">Show all ${d.recommendations.length} recommendations</button>` : "") : `<div class="empty-sm">Not enough data for recommendations yet.</div>`}</div>
          <div style="margin-top:12px;border-top:1px solid var(--line);padding-top:12px"><div class="card-h"><h2>AI narrative</h2><button class="btn btn-sm" id="narr">${d.ai_configured ? "Generate briefing" : "About AI narrative"}</button></div><div id="narr-out" class="sub">${d.ai_configured ? "Uses only the figures above." : "Optional: connect an AI model (ANTHROPIC_API_KEY) for a written briefing. The statistics work without it."}</div></div></div>
        <div class="card c5"><h2>Category demand</h2><div class="sub">Units, last 30 days vs previous 30</div><div id="ch-catd"></div></div>
        <div class="card c12"><div class="card-h"><div><h2>Sales forecast</h2><div class="sub">Solid = recorded sales · dashed = estimate with likely range (shaded)</div></div>
          <div class="toolbar" style="margin:0"><select id="fscope"><option value="all">Whole store</option><optgroup label="Category">${cats.filter((c) => !c.parent_id).map((c) => `<option value="category:${c.id}">${esc(c.name)}</option>`).join("")}</optgroup><optgroup label="Product">${d.products.slice().sort((a, b) => a.name.localeCompare(b.name)).map((p) => `<option value="product:${p.id}">${esc(p.name)}</option>`).join("")}</optgroup></select>
            <select id="fmetric"><option value="revenue">Revenue</option><option value="units">Units</option></select>
            <div class="seg" id="fh">${[7, 15, 30, 90].map((h) => `<button data-h="${h}" class="${h === 30 ? "on" : ""}">${h} days</button>`).join("")}</div></div></div>
          <div id="fc-sum" class="kpis" style="margin-bottom:8px"></div><div class="legend"><span><i style="background:${C.S.s1}"></i>Recorded sales (history)</span><span style="color:${C.S.s2}"><i class="dash"></i><span style="color:var(--ink-2)">Forecast estimate</span></span><span><i style="background:${C.S.s2};opacity:.3;height:10px"></i>Likely range (~80%)</span></div>
          <div id="ch-fc"></div><div id="fc-note" class="est-note"></div></div>
        <div class="card c12"><h2>Product demand analysis</h2><div class="sub">Pick a group — lists are computed from the last 30–90 days</div>
          <div class="group-tabs" id="gtabs">${GROUPS.map(([k, l]) => `<button data-g="${k}" class="${k === gsel ? "on" : ""}">${l}<span class="c">${d.groups[k].length}</span></button>`).join("")}</div><div id="gbox"></div></div>
        <div class="card c4"><h2>Average revenue by weekday</h2><div class="sub">Last 90 days</div><div id="ch-wd"></div></div>
        <div class="card c4"><h2>Monthly revenue</h2><div class="sub">Recorded, last 6 months</div><div id="ch-mo"></div></div>
        <div class="card c4"><h2>Top searches</h2><div class="sub">Last 30 days · zero-result searches show unmet demand</div>
          ${d.searches.length ? `<table class="tbl"><tbody>${d.searches.slice(0, 10).map((s) => `<tr><td>${esc(s.query)}</td><td class="num">${s.n}×</td><td>${s.results ? "" : '<span class="pill warn">No results</span>'}</td></tr>`).join("")}</tbody></table>` : `<div class="empty-sm">No searches recorded.</div>`}</div>
      </div>`;
    C.hbars(el.querySelector("#ch-catd"), d.categories.map((c) => ({ label: c.name, value: c.units_30, sub: `prev ${c.units_prev_30} · ${fmt.pct(c.growth_pct)}` })), { fmt: (v) => fmt.num(v) + " units" });
    C.columns(el.querySelector("#ch-wd"), d.by_weekday.map((x) => ({ label: x.day, value: x.avg_revenue })), { fmt: (v) => fmt.compact(v), color: C.S.s7 });
    C.columns(el.querySelector("#ch-mo"), d.by_month.map((x) => ({ label: new Date(x.month + "-01").toLocaleDateString("en-IN", { month: "short" }), value: x.revenue })), { fmt: (v) => fmt.compact(v), color: C.S.s3 });
    const paintGroup = () => {
      const rows = d.groups[gsel];
      el.querySelector("#gbox").innerHTML = rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Product</th><th class="num">Units 30d</th><th class="num">Prev 30d</th><th class="num">Change</th><th class="num">Revenue 30d</th><th class="num">Avg / day</th><th class="num">Available</th><th class="num">Days of cover</th><th class="num">Views 30d</th><th class="num">Conversion</th><th class="num">Stock-outs 90d</th><th class="num">Suggested reorder</th></tr></thead><tbody>
        ${rows.map((r) => `<tr><td class="pname">${esc(r.name)}<div class="muted">${esc(r.category || "")}</div></td><td class="num">${r.units_30}</td><td class="num">${r.units_prev_30}</td><td class="num" style="color:${(r.growth_pct || 0) >= 0 ? "var(--green)" : "#c62828"}">${fmt.pct(r.growth_pct)}</td>
          <td class="num">${fmt.inr(r.revenue_30, 0)}</td><td class="num">${r.avg_daily}</td><td class="num">${r.available}</td><td class="num">${r.days_of_cover ?? "—"}</td><td class="num">${fmt.num(r.views_30)}</td><td class="num">${r.conversion_pct ?? "—"}%</td><td class="num">${r.stockouts_90}</td><td class="num">${r.reorder_qty || "—"}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-sm">No products in this group right now.</div>`;
    };
    el.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => { gsel = b.dataset.g; el.querySelectorAll("[data-g]").forEach((x) => x.classList.toggle("on", x === b)); paintGroup(); }));
    paintGroup();
    const mr = el.querySelector("#more-recos");
    if (mr) mr.onclick = () => { el.querySelectorAll("[data-more]").forEach((x) => (x.hidden = false)); mr.remove(); };
    let fh = 30;
    const loadFc = async () => {
      const [scope, id] = el.querySelector("#fscope").value.split(":");
      const metric = el.querySelector("#fmetric").value;
      const r = await api("GET", `/api/admin/analytics/forecast?scope=${scope}&id=${id || ""}&horizon=${fh}&metric=${metric}`);
      const box = el.querySelector("#ch-fc");
      const yf = metric === "revenue" ? (v) => fmt.compact(v) : (v) => Number(v).toFixed(v < 10 ? 1 : 0) + " units";
      if (!r.enough_data) { box.innerHTML = `<div class="empty-sm">${esc(r.message)}</div>`; el.querySelector("#fc-sum").innerHTML = ""; el.querySelector("#fc-note").textContent = ""; return; }
      const labels = [...r.history.map((h) => h.day), ...r.forecast.map((p) => p.day)];
      const nH = r.history.length;
      const hist = labels.map((_, i) => ({ y: i < nH ? r.history[i].value : null }));
      const fcs = labels.map((_, i) => (i >= nH ? { y: r.forecast[i - nH].value, lo: r.forecast[i - nH].lo, hi: r.forecast[i - nH].hi } : i === nH - 1 ? { y: r.history[i].value, lo: r.history[i].value, hi: r.history[i].value } : { y: null }));
      C.line(box, { labels, series: [{ name: "Recorded", color: C.S.s1, points: hist }, { name: "Estimate", color: C.S.s2, points: fcs, dashed: true, band: true }],
        yFmt: yf, xFmt: (l, long) => (long ? fmt.date(l) : fmt.short(l)), splitIndex: nH - 1, splitLabel: "Forecast →", height: 280 });
      const s = r.summary;
      const money = metric === "revenue";
      el.querySelector("#fc-sum").innerHTML = kpi(`Estimated next ${fh} days`, money ? fmt.inr(s.forecast_total, 0) : fmt.num(Math.round(s.forecast_total)) + " units", `Likely ${money ? fmt.compact(s.range[0]) : Math.round(s.range[0])} – ${money ? fmt.compact(s.range[1]) : Math.round(s.range[1])} · ESTIMATE`, "hl")
        + kpi(`Recorded last ${fh} days`, s.previous_period_actual == null ? "—" : money ? fmt.inr(s.previous_period_actual, 0) : fmt.num(s.previous_period_actual) + " units", "actual history")
        + kpi("Forecast confidence", s.confidence[0].toUpperCase() + s.confidence.slice(1), s.backtest_error_pct != null ? `Back-test error ${s.backtest_error_pct}% on last 14 days` : "Not enough data to back-test", s.confidence === "high" ? "good" : s.confidence === "low" ? "warn" : "")
        + kpi("History used", s.history_days + " days", `${s.active_days_last_60} of last 60 days had sales`);
      el.querySelector("#fc-note").innerHTML = esc(r.method);
    };
    el.querySelector("#fscope").onchange = loadFc; el.querySelector("#fmetric").onchange = loadFc;
    el.querySelectorAll("[data-h]").forEach((b) => (b.onclick = () => { fh = +b.dataset.h; el.querySelectorAll("[data-h]").forEach((x) => x.classList.toggle("on", x === b)); loadFc(); }));
    await loadFc();
    el.querySelector("#narr").onclick = async (e) => {
      const out = el.querySelector("#narr-out");
      e.target.disabled = true; out.innerHTML = `<span class="spin"></span> Working…`;
      try { const r = await api("POST", "/api/admin/analytics/narrative"); out.innerHTML = r.text ? `<div style="white-space:pre-line;color:var(--ink)">${esc(r.text)}</div><div class="est-note">AI-written summary of the computed figures above. Verify before acting.</div>` : esc(r.message); }
      catch (ex) { out.textContent = ex.message; }
      e.target.disabled = false;
    };
  }

  // ------------------------------------------------------------------ REPORTS
  async function reports(el) {
    let group = "company";
    el.innerHTML = "";
    el.appendChild(rangeBar(() => paint()));
    const body = document.createElement("div"); el.appendChild(body);
    const EXPORTS = [["products", "Products & stock", "products"], ["inventory", "Inventory movements", "inventory"], ["orders", "Orders", "orders"], ["order_items", "Order line items", "orders"],
      ["sales", "Daily sales", null], ["customers", "Customers", "customers"], ["buyers", "Buyer codes", "buyers"], ["company", "Company-wise sales", null], ["rank", "Category (rank)-wise sales", null], ["buyer", "Buyer statements", null]];
    const paint = async () => {
      const d = await api("GET", `/api/admin/reports/grouped?group=${group}&${rq()}`);
      body.innerHTML = `<div class="cards"><div class="card c8"><div class="card-h"><div><h2>Sales report</h2><div class="sub">${fmt.date(d.range.from)} – ${fmt.date(d.range.to)} · valid orders only</div></div>
          <div class="seg">${[["company", "By company"], ["rank", "By rank category"], ["buyer", "By buyer code"], ["payment", "By payment method"], ["day", "By day"]].map(([k, l]) => `<button data-g="${k}" class="${k === group ? "on" : ""}">${l}</button>`).join("")}</div></div>
          <div class="kpis">${kpi("Orders", fmt.num(d.totals.orders))}${kpi("Sales", fmt.inr(d.totals.sales, 0), "", "hl")}${kpi("Paid", fmt.inr(d.totals.paid, 0), "", "good")}${kpi("COD outstanding", fmt.inr(d.totals.cod_pending, 0), "", d.totals.cod_pending ? "warn" : "")}</div>
          <div id="ch-rep"></div>
          <div class="tbl-wrap" style="margin-top:12px;max-height:420px"><table class="tbl"><thead><tr><th>${{ company: "Company", rank: "Rank category", buyer: "Buyer code", payment: "Payment method", day: "Date" }[group]}</th><th class="num">Orders</th><th class="num">Sales</th><th class="num">Paid</th><th class="num">COD outstanding</th></tr></thead><tbody>
            ${d.rows.map((r) => `<tr><td>${esc(group === "payment" ? PM[r.name] || r.name : group === "day" ? fmt.date(r.name) : r.name)}${group === "company" || group === "rank" ? ` <span class="muted">${esc(r.k)}</span>` : ""}</td><td class="num">${r.orders}</td><td class="num">${fmt.inr(r.sales, 0)}</td><td class="num">${fmt.inr(r.paid, 0)}</td><td class="num">${fmt.inr(r.cod_pending, 0)}</td></tr>`).join("") || `<tr><td colspan="5" class="empty-sm">No sales in this period.</td></tr>`}</tbody></table></div></div>
        <div class="card c4"><h2>Download data (CSV)</h2><div class="sub">Uses the date range above where relevant. Opens in Excel.</div>
          ${EXPORTS.filter((x) => !x[2] || can(x[2]) || x[2] === "products" || x[2] === "orders").map(([k, l]) => `<button class="btn btn-block" style="justify-content:space-between;margin-bottom:8px" data-x="${k}"><span>${l}</span><span>⬇</span></button>`).join("")}</div></div>`;
      body.querySelectorAll("[data-g]").forEach((b) => (b.onclick = () => { group = b.dataset.g; paint(); }));
      body.querySelectorAll("[data-x]").forEach((b) => (b.onclick = () => download(`/api/admin/export/${b.dataset.x}?${rq()}`)));
      if (group === "day") C.line(body.querySelector("#ch-rep"), { labels: d.rows.map((r) => r.name), series: [{ name: "Sales", color: C.S.s1, points: d.rows.map((r) => ({ y: r.sales })) }], yFmt: (v) => fmt.compact(v), xFmt: (l, long) => (long ? fmt.date(l) : fmt.short(l)), area: true });
      else C.hbars(body.querySelector("#ch-rep"), d.rows.slice(0, 12).map((r) => ({ label: group === "payment" ? PM[r.name] || r.name : r.name, value: r.sales, sub: `${r.orders} orders` })), { fmt: (v) => fmt.compact(v) });
    };
    await paint();
  }

  // ------------------------------------------------------------------ FINANCE
  async function finance(el) {
    if (!["month", "prev_month", "30d", "7d", "custom", "today", "yesterday"].includes(A.range)) A.range = "month";
    el.innerHTML = "";
    el.appendChild(rangeBar(() => finance(el)));
    const body = document.createElement("div"); el.appendChild(body);
    const d = await api("GET", "/api/admin/finance?" + rq());
    const s = d.sales;
    body.innerHTML = `<div class="kpis">${kpi("Gross sales", fmt.inr(s.in_range, 0), `${s.orders_in_range} orders incl. GST & delivery`, "hl")}${kpi("Net revenue (ex-GST)", fmt.inr(s.net_revenue_ex_tax, 0))}${kpi("Cost of goods", fmt.inr(s.cogs, 0))}
      ${kpi("Est. gross profit", fmt.inr(s.gross_profit, 0), s.gross_margin_pct != null ? s.gross_margin_pct + "% margin" : "", s.gross_profit >= 0 ? "good" : "bad")}${kpi("Expenses", fmt.inr(s.expenses, 0), `${s.expense_entries} entries`)}
      ${kpi("Est. net profit", s.net_profit == null ? "—" : fmt.inr(s.net_profit, 0), s.net_profit == null ? "Record expenses for this period to calculate" : "gross profit − expenses", s.net_profit == null ? "" : s.net_profit >= 0 ? "good" : "bad")}${kpi("Refunds created", fmt.inr(d.refunds.amount, 0), `${d.refunds.count} refunds`)}</div>
      <div class="est-note" style="margin-bottom:14px">Estimates: GST is treated as included in selling prices; cost of goods uses the cost price recorded on each order line at the time of sale. Cancelled, unpaid-online, returned and refunded orders are excluded.</div>
      <div class="cards"><div class="card c7"><h2>Daily sales</h2><div id="ch-fin"></div></div>
        <div class="card c5"><div class="card-h"><h2>Expenses</h2><button class="btn btn-sm btn-primary" id="eadd">+ Add expense</button></div>
          ${Object.keys(d.expenses_by_category).length ? `<div id="ch-exp" style="margin-bottom:12px"></div>` : ""}
          <div class="tbl-wrap" style="max-height:340px"><table class="tbl"><thead><tr><th>Date</th><th>Category</th><th>Note</th><th class="num">Amount</th><th></th></tr></thead><tbody>
          ${d.expenses.map((e) => `<tr><td>${fmt.date(e.date)}</td><td>${esc(e.category)}</td><td class="muted">${esc(e.note || "")}</td><td class="num">${fmt.inr(e.amount)}</td><td><button class="btn btn-sm" data-ed="${e.id}" aria-label="Delete">✕</button></td></tr>`).join("") || `<tr><td colspan="5" class="empty-sm">No expenses in this period.</td></tr>`}</tbody></table></div></div></div>`;
    C.line(body.querySelector("#ch-fin"), { labels: d.series.map((x) => x.day), series: [{ name: "Sales", color: C.S.s1, points: d.series.map((x) => ({ y: x.revenue })) }], yFmt: (v) => fmt.compact(v), xFmt: (l, long) => (long ? fmt.date(l) : fmt.short(l)), area: true });
    const ce = body.querySelector("#ch-exp"); if (ce) C.hbars(ce, Object.entries(d.expenses_by_category).map(([k, v]) => ({ label: k, value: v })), { fmt: (v) => fmt.inr(v, 0), color: C.S.s8 });
    body.querySelector("#eadd").onclick = async () => {
      const ok = await modal({ title: "Add expense", body: `<div class="row2"><label class="fld"><span>Date</span><input type="date" id="xd" value="${new Date().toISOString().slice(0, 10)}"></label><label class="fld"><span>Amount (₹)</span><input type="number" id="xa" min="0" step="0.01"></label></div>
        <label class="fld"><span>Category</span><input id="xc" list="xcats" placeholder="e.g. Staff salaries"><datalist id="xcats"><option value="Staff salaries"><option value="Store rent & utilities"><option value="Packaging"><option value="Transport"><option value="Marketing"><option value="Other"></datalist></label><label class="fld"><span>Note</span><input id="xn"></label>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Add", cls: "btn-primary", handler: (m) => api("POST", "/api/admin/expenses", { date: m.querySelector("#xd").value, amount: m.querySelector("#xa").value, category: m.querySelector("#xc").value, note: m.querySelector("#xn").value }) }] });
      if (ok) { toast("Expense added"); finance(el); }
    };
    body.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Delete expense", "Delete this expense entry?", { confirmLabel: "Delete", danger: true }))) return;
      await api("DELETE", "/api/admin/expenses/" + b.dataset.ed); toast("Expense deleted"); finance(el);
    }));
  }

  // ------------------------------------------------------------------ MARKETING
  async function marketing(el) {
    const [b, c, meta] = await Promise.all([api("GET", "/api/admin/banners"), api("GET", "/api/admin/coupons"), api("GET", "/api/meta")]);
    el.innerHTML = `<div class="cards">
      <div class="card c12"><h2>Announcement strip</h2><div class="sub">The teal bar under the store header</div><div style="display:flex;gap:8px"><input class="inp" id="ann" value="${esc(b.announcement || "")}" maxlength="160"><button class="btn btn-primary" id="anns">Save</button></div></div>
      <div class="card c12"><div class="card-h"><div><h2>Home page banners</h2><div class="sub">Shown as the hero carousel. Leave department empty to show on every tab.</div></div><button class="btn btn-primary btn-sm" id="badd">+ Add banner</button></div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Photo</th><th>Order</th><th>Title</th><th>Theme</th><th>Department</th><th>Link</th><th>Status</th><th></th></tr></thead><tbody>
        ${b.items.map((x) => `<tr><td>${x.image_url ? `<img src="${esc(x.image_url)}" alt="" style="width:56px;height:56px;object-fit:cover;border-radius:8px;display:block">` : `<span class="muted">Auto</span>`}</td><td>${x.sort}</td><td class="pname">${esc(x.title)}<div class="muted">${esc(x.subtitle || "")}</div></td><td><span class="pill">${esc(x.theme)}</span></td><td>${esc(x.department || "All")}</td><td class="muted">${esc(x.link || "")}</td><td>${x.active ? '<span class="pill ok">Live</span>' : '<span class="pill">Off</span>'}</td>
          <td><div style="display:flex;gap:6px"><button class="btn btn-sm" data-bp="${x.id}">📷 Photo</button><button class="btn btn-sm" data-bv="${x.id}">🎬 Video${x.video_url ? " ✓" : ""}</button><button class="btn btn-sm" data-be="${x.id}">Edit</button><button class="btn btn-sm" data-bd="${x.id}" style="color:#c62828">Delete</button></div></td></tr>`).join("") || `<tr><td colspan="8" class="empty-sm">No banners.</td></tr>`}</tbody></table></div></div>
      <div class="card c12"><div class="card-h"><div><h2>Coupons & promotional offers</h2><div class="sub">Product-level discounts are set with MRP vs selling price on each product.</div></div><button class="btn btn-primary btn-sm" id="cadd">+ Add coupon</button></div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Code</th><th>Offer</th><th class="num">Min order</th><th>Valid</th><th class="num">Used</th><th>Status</th><th></th></tr></thead><tbody>
        ${c.items.map((x) => `<tr><td><b>${esc(x.code)}</b><div class="muted">${esc(x.description || "")}</div></td><td>${x.kind === "pct" ? `${x.value}% off${x.max_discount ? ` (max ${fmt.inr(x.max_discount)})` : ""}` : fmt.inr(x.value) + " off"}</td><td class="num">${fmt.inr(x.min_order)}</td>
          <td>${x.starts_at ? fmt.date(x.starts_at) : "Now"} – ${x.ends_at ? fmt.date(x.ends_at) : "No end"}</td><td class="num">${x.used_count}${x.usage_limit ? " / " + x.usage_limit : ""}</td><td>${x.active ? '<span class="pill ok">Active</span>' : '<span class="pill">Off</span>'}</td>
          <td><div style="display:flex;gap:6px"><button class="btn btn-sm" data-ce="${x.id}">Edit</button><button class="btn btn-sm" data-cd="${x.id}" style="color:#c62828">Delete</button></div></td></tr>`).join("") || `<tr><td colspan="7" class="empty-sm">No coupons.</td></tr>`}</tbody></table></div></div></div>`;
    el.querySelector("#anns").onclick = async () => { try { await api("PUT", "/api/admin/announcement", { announcement: el.querySelector("#ann").value }); toast("Announcement saved"); } catch (e) { toast(e.message, "err"); } };
    const links = [["#/search?offers=1&sort=discount", "Offers page"], ["#/search?sort=newest", "New arrivals"], ["#/search?sort=popular", "Best sellers"], ...meta.categories.map((x) => [`#/c/${x.slug}`, "Category: " + x.name])];
    const bdlg = async (x = { theme: "navy", active: 1, sort: b.items.length }) => {
      const ok = await modal({ title: x.id ? "Edit banner" : "Add banner", body: `<label class="fld"><span>Title</span><input id="bt" value="${esc(x.title || "")}" maxlength="80"></label><label class="fld"><span>Subtitle</span><input id="bs" value="${esc(x.subtitle || "")}" maxlength="160"></label>
        <div class="row2"><label class="fld"><span>Button text</span><input id="bc" value="${esc(x.cta || "")}"></label><label class="fld"><span>Links to</span><select id="bl">${links.map(([v, l]) => `<option value="${esc(v)}" ${x.link === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label></div>
        <div class="row3"><label class="fld"><span>Theme</span><select id="bth">${["navy", "teal", "coral", "gold", "plum", "slate"].map((t) => `<option ${x.theme === t ? "selected" : ""}>${t}</option>`).join("")}</select></label>
        <label class="fld"><span>Department</span><select id="bd"><option value="">All tabs</option>${meta.departments.map((d) => `<option ${x.department === d ? "selected" : ""}>${esc(d)}</option>`).join("")}</select></label><label class="fld"><span>Order</span><input id="bo" type="number" value="${x.sort}"></label></div>
        <label class="chk"><input type="checkbox" id="ba" ${x.active ? "checked" : ""}> Live</label>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (m) => {
          const d = { title: m.querySelector("#bt").value, subtitle: m.querySelector("#bs").value, cta: m.querySelector("#bc").value, link: m.querySelector("#bl").value, theme: m.querySelector("#bth").value, department: m.querySelector("#bd").value, sort: m.querySelector("#bo").value, active: m.querySelector("#ba").checked };
          return x.id ? api("PUT", "/api/admin/banners/" + x.id, d) : api("POST", "/api/admin/banners", d);
        } }] });
      if (ok) { toast("Banner saved"); marketing(el); }
    };
    el.querySelector("#badd").onclick = () => bdlg();
    el.querySelectorAll("[data-bp]").forEach((bt) => (bt.onclick = () => {
      const x = b.items.find((y) => y.id == bt.dataset.bp);
      modal({ title: "Banner photo · " + x.title, body: `<div style="text-align:center;margin-bottom:12px">${x.image_url ? `<img src="${esc(x.image_url)}" alt="" style="max-width:100%;max-height:220px;border-radius:12px">` : `<p class="muted" style="margin:0">No photo chosen. The store picks one automatically.</p>`}</div>
        <label class="fld"><span>Choose a photo (JPG, PNG or WEBP, up to 5 MB)</span><input type="file" id="bph" accept="image/*"></label>
        <p class="muted" style="font-size:13px;margin:6px 0 0">Tip: a square photo looks best.</p>`,
        actions: [{ label: "Close", cls: "btn-ghost" },
          ...(x.image_url ? [{ label: "Remove photo", cls: "", handler: async () => {
            try { await api("DELETE", `/api/admin/banners/${x.id}/image`); toast("Photo removed"); marketing(el); return true; } catch (e) { toast(e.message, "err"); return false; } } }] : []),
          { label: "Upload", cls: "btn-primary", handler: async (m) => {
            const f = m.querySelector("#bph").files[0];
            if (!f) { toast("Choose a photo first", "err"); return false; }
            const fd = new FormData(); fd.append("file", f);
            try { await api("POST", `/api/admin/banners/${x.id}/image`, fd); toast("Banner photo saved"); marketing(el); return true; } catch (e) { toast(e.message, "err"); return false; }
          } }] });
    }));
    el.querySelectorAll("[data-bv]").forEach((bt) => (bt.onclick = () => {
      const x = b.items.find((y) => y.id == bt.dataset.bv);
      modal({ title: "Banner video · " + x.title, body: `<div style="text-align:center;margin-bottom:12px">${x.video_url ? `<video src="${esc(x.video_url)}" controls muted playsinline style="max-width:100%;max-height:220px;border-radius:12px"></video>` : `<p class="muted" style="margin:0">No video yet. The banner shows its photo.</p>`}</div>
        <label class="fld"><span>Choose a video (MP4 or WEBM, up to 10 MB)</span><input type="file" id="bvf" accept="video/mp4,video/webm"></label>
        <p class="muted" style="font-size:13px;margin:6px 0 0">Tip: a short 5–10 second video without sound works best. It plays silently and loops. Your banner photo (if set) shows while it loads.</p>`,
        actions: [{ label: "Close", cls: "btn-ghost" },
          ...(x.video_url ? [{ label: "Remove video", cls: "", handler: async () => {
            try { await api("DELETE", `/api/admin/banners/${x.id}/video`); toast("Video removed"); marketing(el); return true; } catch (e) { toast(e.message, "err"); return false; } } }] : []),
          { label: "Upload", cls: "btn-primary", handler: async (m) => {
            const f = m.querySelector("#bvf").files[0];
            if (!f) { toast("Choose a video first", "err"); return false; }
            if (f.size > 10 * 1024 * 1024) { toast("Video is bigger than 10 MB", "err"); return false; }
            const fd = new FormData(); fd.append("file", f);
            try { await api("POST", `/api/admin/banners/${x.id}/video`, fd); toast("Banner video saved"); marketing(el); return true; } catch (e) { toast(e.message, "err"); return false; }
          } }] });
    }));
    el.querySelectorAll("[data-be]").forEach((bt) => (bt.onclick = () => bdlg(b.items.find((x) => x.id == bt.dataset.be))));
    el.querySelectorAll("[data-bd]").forEach((bt) => (bt.onclick = async () => { if (await confirmDialog("Delete banner", "Delete this banner?", { confirmLabel: "Delete", danger: true })) { await api("DELETE", "/api/admin/banners/" + bt.dataset.bd); toast("Banner deleted"); marketing(el); } }));
    const cdlg = async (x = { kind: "pct", active: 1 }) => {
      const ok = await modal({ title: x.id ? "Edit coupon" : "Add coupon", body: `<div class="row2"><label class="fld"><span>Code</span><input id="cc" value="${esc(x.code || "")}" style="text-transform:uppercase"></label><label class="fld"><span>Description</span><input id="cdsc" value="${esc(x.description || "")}"></label></div>
        <div class="row3"><label class="fld"><span>Type</span><select id="ck"><option value="pct" ${x.kind === "pct" ? "selected" : ""}>Percentage</option><option value="flat" ${x.kind === "flat" ? "selected" : ""}>Flat ₹</option></select></label><label class="fld"><span>Value</span><input id="cv" type="number" value="${x.value ?? ""}"></label><label class="fld"><span>Max discount ₹</span><input id="cm" type="number" value="${x.max_discount ?? ""}"></label></div>
        <div class="row3"><label class="fld"><span>Min order ₹</span><input id="cmo" type="number" value="${x.min_order ?? 0}"></label><label class="fld"><span>Starts</span><input id="cs" type="date" value="${(x.starts_at || "").slice(0, 10)}"></label><label class="fld"><span>Ends</span><input id="ce" type="date" value="${(x.ends_at || "").slice(0, 10)}"></label></div>
        <div class="row2"><label class="fld"><span>Usage limit (total)</span><input id="cu" type="number" value="${x.usage_limit ?? ""}"></label><label class="chk" style="margin-top:30px"><input type="checkbox" id="ca" ${x.active ? "checked" : ""}> Active</label></div>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (m) => {
          const d = { code: m.querySelector("#cc").value, description: m.querySelector("#cdsc").value, kind: m.querySelector("#ck").value, value: m.querySelector("#cv").value, max_discount: m.querySelector("#cm").value, min_order: m.querySelector("#cmo").value, starts_at: m.querySelector("#cs").value, ends_at: m.querySelector("#ce").value, usage_limit: m.querySelector("#cu").value, active: m.querySelector("#ca").checked };
          return x.id ? api("PUT", "/api/admin/coupons/" + x.id, d) : api("POST", "/api/admin/coupons", d);
        } }] });
      if (ok) { toast("Coupon saved"); marketing(el); }
    };
    el.querySelector("#cadd").onclick = () => cdlg();
    el.querySelectorAll("[data-ce]").forEach((bt) => (bt.onclick = () => cdlg(c.items.find((x) => x.id == bt.dataset.ce))));
    el.querySelectorAll("[data-cd]").forEach((bt) => (bt.onclick = async () => { if (await confirmDialog("Delete coupon", "Delete this coupon?", { confirmLabel: "Delete", danger: true })) { await api("DELETE", "/api/admin/coupons/" + bt.dataset.cd); toast("Coupon deleted"); marketing(el); } }));
  }

  // ------------------------------------------------------------------ STAFF
  async function staff(el) {
    const d = await api("GET", "/api/admin/staff");
    el.innerHTML = `<div class="toolbar"><div class="sub" style="color:var(--ink-3)">Staff see only the sections you allow. Only the owner can manage staff and settings.</div><span class="grow"></span><button class="btn btn-primary btn-sm" id="sadd">+ Add staff member</button></div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Permissions</th><th>Last sign-in</th><th>Status</th><th></th></tr></thead><tbody>
      ${d.items.map((s) => `<tr><td class="pname">${esc(s.name)}</td><td>${esc(s.email)}</td><td>${s.role === "owner" ? '<span class="pill teal">Owner</span>' : '<span class="pill">Staff</span>'}</td>
        <td style="max-width:360px">${s.role === "owner" ? "Full access" : s.permissions.map((p) => `<span class="pill" style="margin:2px">${esc(d.permissions[p] || p)}</span>`).join("") || '<span class="muted">None</span>'}</td>
        <td>${fmt.datetime(s.last_login_at)}</td><td>${s.status === "active" ? '<span class="pill ok">Active</span>' : '<span class="pill bad">Suspended</span>'}</td><td>${s.role === "staff" ? `<button class="btn btn-sm" data-se="${s.id}">Edit</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
    const dlg = async (s = { permissions: [], status: "active" }) => {
      const ok = await modal({ title: s.id ? "Edit " + s.name : "Add staff member", body: `<div class="row2"><label class="fld"><span>Name</span><input id="sn" value="${esc(s.name || "")}"></label><label class="fld"><span>Email</span><input id="se" type="email" value="${esc(s.email || "")}" ${s.id ? "disabled" : ""}></label></div>
        <label class="fld"><span>${s.id ? "New password (leave blank to keep)" : "Temporary password"}</span><input id="sp" type="password" autocomplete="new-password"><small>At least 8 characters with letters and numbers.</small></label>
        <div class="fld"><span>Permissions</span><div class="perm-grid">${Object.entries(d.permissions).map(([k, l]) => `<label class="chk"><input type="checkbox" value="${k}" class="pp" ${s.permissions.includes(k) ? "checked" : ""}> ${esc(l)}</label>`).join("")}</div></div>
        ${s.id ? `<label class="fld"><span>Status</span><select id="ss"><option value="active" ${s.status === "active" ? "selected" : ""}>Active</option><option value="suspended" ${s.status === "suspended" ? "selected" : ""}>Suspended</option></select></label>` : ""}`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (m) => {
          const perms = [...m.querySelectorAll(".pp:checked")].map((x) => x.value);
          const body = { name: m.querySelector("#sn").value, permissions: perms, password: m.querySelector("#sp").value };
          if (s.id) { body.status = m.querySelector("#ss").value; return api("PUT", "/api/admin/staff/" + s.id, body); }
          body.email = m.querySelector("#se").value; return api("POST", "/api/admin/staff", body);
        } }] });
      if (ok) { toast("Staff saved — changes apply at their next sign-in"); staff(el); }
    };
    el.querySelector("#sadd").onclick = () => dlg();
    el.querySelectorAll("[data-se]").forEach((b) => (b.onclick = () => dlg(d.items.find((x) => x.id == b.dataset.se))));
  }

  // ------------------------------------------------------------------ SETTINGS
  async function settings(el) {
    const d = await api("GET", "/api/admin/settings");
    const s = d.settings;
    const t = (k, l, extra = "") => `<label class="fld"><span>${l}</span><input name="${k}" value="${esc(s[k])}" ${extra}></label>`;
    const n = (k, l, extra = "") => `<label class="fld"><span>${l}</span><input name="${k}" type="number" value="${esc(s[k])}" ${extra}></label>`;
    const b = (k, l) => `<label class="chk"><input type="checkbox" name="${k}" ${s[k] ? "checked" : ""}> ${l}</label>`;
    el.innerHTML = `<form id="sf"><div class="cards">
      <div class="card c6"><h2>Store</h2><div class="sub">Shown to customers</div>${t("store_name", "Store name")}${t("tagline", "Tagline")}<div class="row2">${t("support_email", "Support email")}${t("support_phone", "Support phone")}</div></div>
      <div class="card c6"><h2>Payments</h2><div class="sub">Secret keys live in the server's .env file — never here</div>
        ${b("cod_enabled", "Cash on Delivery")}${n("cod_max_amount", "COD maximum order value (₹)")}
        ${b("upi_enabled", "Direct UPI to my UPI ID (you confirm each payment)")}
        <div class="row2">${t("upi_id", "Your UPI ID", 'placeholder="yourname@okhdfcbank"')}${t("upi_payee_name", "Name shown to payer", 'placeholder="e.g. PVC Paltan Store"')}</div>
        <div class="est-note" style="margin:-4px 0 10px">Customers pay to this UPI ID and enter the transaction ID. Check your bank/UPI app, then press <b>Confirm payment</b> on the order.</div>
        ${b("razorpay_enabled", "Razorpay (UPI, cards, netbanking)")}<div class="est-note" style="margin:-4px 0 10px">${esc(d.integrations.razorpay)}</div>
        ${b("sandbox_enabled", "Sandbox test payments (turn OFF before going live)")}${n("payment_expiry_minutes", "Unpaid online orders auto-cancel after (minutes)", 'min="5" max="1440"')}</div>
      <div class="card c6"><h2>Tax & ordering</h2>${b("prices_include_tax", "Selling prices include GST")}<div class="row2">${n("default_tax_rate", "Default GST %")}${n("max_qty_per_order", "Max units of one item per order")}</div>
        <div class="row2">${n("low_stock_default", "Default low-stock alert")}${n("reorder_lead_days", "Supplier lead time (days) for restock advice")}</div></div>
      <div class="card c6"><h2>Returns & policies</h2>${n("return_window_days", "Return window (days after delivery)")}
        <label class="fld"><span>Returns policy</span><textarea name="policy_returns" rows="3">${esc(s.policy_returns)}</textarea></label>
        <label class="fld"><span>Shipping policy</span><textarea name="policy_shipping" rows="2">${esc(s.policy_shipping)}</textarea></label>
        <label class="fld"><span>Privacy policy</span><textarea name="policy_privacy" rows="2">${esc(s.policy_privacy)}</textarea></label></div>
      <div class="card c12" style="display:flex;justify-content:flex-end"><button class="btn btn-primary" id="ssave">Save settings</button></div></div></form>
      <div class="cards" style="margin-top:14px">
      <div class="card c12"><div class="card-h"><div><h2>Delivery methods & charges</h2><div class="sub">Add new delivery services here without code changes</div></div><button class="btn btn-sm btn-primary" id="dadd">+ Add method</button></div>
        <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Name</th><th>Code</th><th class="num">Charge</th><th class="num">Free above</th><th>ETA</th><th>Status</th><th></th></tr></thead><tbody>
        ${d.delivery_methods.map((m) => `<tr><td class="pname">${esc(m.name)}<div class="muted">${esc(m.description || "")}</div></td><td class="muted">${esc(m.code)}</td><td class="num">${fmt.inr(m.charge)}</td><td class="num">${m.free_above ? fmt.inr(m.free_above) : "—"}</td><td>${m.eta_min_days}–${m.eta_max_days} days</td><td>${m.active ? '<span class="pill ok">Active</span>' : '<span class="pill">Off</span>'}</td><td><button class="btn btn-sm" data-de="${m.id}">Edit</button></td></tr>`).join("")}</tbody></table></div></div>
      <div class="card c6"><h2>Integrations</h2><table class="tbl"><tbody>${Object.entries(d.integrations).map(([k, v]) => `<tr><td style="text-transform:capitalize">${esc(k.replace(/_/g, " "))}</td><td>${/^Configured|PostgreSQL|SQLite/.test(v) ? '<span class="status-dot" style="background:var(--green)"></span>' : '<span class="status-dot" style="background:#a5a9ba"></span>'}${esc(v)}</td></tr>`).join("")}</tbody></table>
        <div class="est-note">To configure: add the values in Render → Environment (or the <code>.env</code> file when running on a computer) and redeploy. See DEPLOY-ONLINE.md.</div>
        <div class="test-mail"><label class="fld"><span>Send a test email to</span><input id="tm-to" type="email" placeholder="your Gmail address"></label>
          <button class="btn" id="tm-go" type="button">Send test email</button><div id="tm-out" class="est-note" hidden></div></div></div>
      <div class="card c6"><h2>Sample data</h2><div class="sub">Demonstration records created on first run</div>
        <p style="font-size:14px">${d.sample_counts.products} sample products · ${d.sample_counts.orders} sample orders · ${d.sample_counts.customers} sample customers</p>
        <p style="font-size:14px;color:var(--ink-2)">Remove them before going live. Sample products that appear in real orders are archived instead of deleted. Your own products, orders and customers are not touched.</p>
        <button class="btn btn-danger" id="clr" ${d.sample_counts.orders + d.sample_counts.products + d.sample_counts.customers ? "" : "disabled"}>Delete all sample data…</button></div></div>`;
    el.querySelector("#tm-go").onclick = async (e) => {
      const btn = e.currentTarget, out = el.querySelector("#tm-out");
      btn.disabled = true; btn.textContent = "Sending…"; out.hidden = true;
      try {
        const r = await api("POST", "/api/admin/test-email", { to: el.querySelector("#tm-to").value });
        out.innerHTML = (r.ok ? "✅ " : "❌ ") + esc(r.message) + (r.provider ? ` <span class="muted">(${esc(r.provider)})</span>` : "");
        out.style.borderColor = r.ok ? "var(--green)" : "#c62828";
      } catch (ex) { out.textContent = "❌ " + ex.message; }
      out.hidden = false; btn.disabled = false; btn.textContent = "Send test email";
    };
    el.querySelector("#sf").onsubmit = async (e) => {
      e.preventDefault();
      try { await api("PUT", "/api/admin/settings", { settings: formData(e.target) }); toast("Settings saved"); } catch (ex) { toast(ex.message, "err"); }
    };
    const ddlg = async (m = { active: 1, eta_min_days: 2, eta_max_days: 5, charge: 0, sort: d.delivery_methods.length }) => {
      const ok = await modal({ title: m.id ? "Edit delivery method" : "Add delivery method", body: `<div class="row2"><label class="fld"><span>Name</span><input id="dn" value="${esc(m.name || "")}"></label><label class="fld"><span>Code</span><input id="dc" value="${esc(m.code || "")}" placeholder="e.g. courier_x"></label></div>
        <label class="fld"><span>Description</span><input id="dd" value="${esc(m.description || "")}"></label>
        <div class="row2"><label class="fld"><span>Charge ₹</span><input id="dch" type="number" value="${m.charge}"></label><label class="fld"><span>Free above ₹ (optional)</span><input id="df" type="number" value="${m.free_above ?? ""}"></label></div>
        <div class="row3"><label class="fld"><span>ETA min days</span><input id="dmin" type="number" value="${m.eta_min_days}"></label><label class="fld"><span>ETA max days</span><input id="dmax" type="number" value="${m.eta_max_days}"></label><label class="fld"><span>Order</span><input id="ds" type="number" value="${m.sort}"></label></div>
        <label class="chk"><input type="checkbox" id="da" ${m.active ? "checked" : ""}> Active</label>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (x) => {
          const body = { name: x.querySelector("#dn").value, code: x.querySelector("#dc").value, description: x.querySelector("#dd").value, charge: x.querySelector("#dch").value, free_above: x.querySelector("#df").value, eta_min_days: x.querySelector("#dmin").value, eta_max_days: x.querySelector("#dmax").value, sort: x.querySelector("#ds").value, active: x.querySelector("#da").checked };
          return m.id ? api("PUT", "/api/admin/delivery-methods/" + m.id, body) : api("POST", "/api/admin/delivery-methods", body);
        } }] });
      if (ok) { toast("Delivery method saved"); settings(el); }
    };
    el.querySelector("#dadd").onclick = () => ddlg();
    el.querySelectorAll("[data-de]").forEach((x) => (x.onclick = () => ddlg(d.delivery_methods.find((m) => m.id == x.dataset.de))));
    el.querySelector("#clr").onclick = async () => {
      if (!(await confirmDialog("Delete sample data", "This permanently removes all sample orders, sample customers and sample products. It cannot be undone.", { confirmLabel: "Delete sample data", danger: true, requireText: "DELETE SAMPLE DATA" }))) return;
      try { const r = await api("POST", "/api/admin/settings/clear-sample-data", { confirm: "DELETE SAMPLE DATA" }); toast(r.message); settings(el); } catch (e) { toast(e.message, "err"); }
    };
  }

  async function audit(el) {
    let page = 1;
    const load = async () => {
      const d = await api("GET", "/api/admin/audit?page=" + page);
      el.innerHTML = `<div class="sub" style="color:var(--ink-3);margin-bottom:10px">Who changed what — sign-ins, price and stock changes, status updates, exports and settings.</div><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Item</th><th>Details</th><th>IP</th></tr></thead><tbody>
        ${d.items.map((a) => `<tr><td>${fmt.datetime(a.created_at)}</td><td>${esc(a.actor || "System")}</td><td>${esc(a.action.replace(/_/g, " "))}</td><td>${esc(a.entity || "")} ${esc(a.entity_id || "")}</td><td class="muted" style="max-width:420px">${esc(a.detail || "")}</td><td class="muted">${esc(a.ip || "")}</td></tr>`).join("") || `<tr><td colspan="6" class="empty-sm">No activity yet.</td></tr>`}</tbody></table></div>`;
      pager(el, d, (n) => { page = n; load(); });
    };
    await load();
  }

  boot();
})();
