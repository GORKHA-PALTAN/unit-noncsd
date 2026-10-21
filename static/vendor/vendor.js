/* PVC Paltan Store — vendor portal. Vendors only ever see and change their own products; every call is checked again on the server. */
(function () {
  const { api, esc, fmt, toast, modal, confirmDialog, formData } = NC;
  const app = document.getElementById("app");
  const V = { me: null, cats: [] };
  const LOGO = `<img src="/static/common/gurkha-logo.svg" alt="" style="display:block;margin:0 auto 12px;width:auto;height:130px">`;

  async function boot() {
    let me;
    try { me = await api("GET", "/api/auth/me"); } catch (e) { app.innerHTML = `<div class="empty"><h3>Server unavailable</h3><p>${esc(e.message)}</p></div>`; return; }
    if (!me.user) return loginScreen();
    NC.state.csrf = me.user.csrf;
    if (me.user.role !== "vendor") {
      app.innerHTML = `<div class="login"><div class="login-box">${LOGO}<h1>Vendor account needed</h1><p>You are signed in with a different kind of account (${esc(me.user.email || "")}). Sign out and sign in with your vendor login.</p>
        <button class="btn btn-primary btn-block" id="lo">Sign out</button></div></div>`;
      document.getElementById("lo").onclick = async () => { await api("POST", "/api/auth/logout").catch(() => {}); location.reload(); };
      return;
    }
    const [vm, meta] = await Promise.all([api("GET", "/api/vendor/me"), api("GET", "/api/meta")]);
    V.me = vm.vendor; V.cats = meta.categories;
    home();
  }

  function loginScreen() {
    app.innerHTML = `<div class="login"><form class="login-box" id="lf">${LOGO}<h1>Vendor sign-in</h1><p>PVC Paltan Store — sell your products with us</p>
      <label class="fld"><span>Email</span><input name="email" type="email" required autocomplete="username"></label>
      <label class="fld"><span>Password</span><input name="password" type="password" required autocomplete="current-password"></label>
      <div id="le" role="alert" style="color:#c62828;font-weight:600;margin-bottom:10px" hidden></div>
      <button class="btn btn-primary btn-block" style="min-height:48px">Sign in</button>
      <p style="margin-top:14px;font-size:13px">No login yet? Ask the store owner to create one for you.</p><p><a href="/" style="color:var(--teal)">← Back to store</a></p></form></div>`;
    document.getElementById("lf").onsubmit = async (e) => {
      e.preventDefault();
      const err = document.getElementById("le"); err.hidden = true;
      const b = e.target.querySelector("button"); b.disabled = true;
      try {
        const r = await api("POST", "/api/auth/login", formData(e.target));
        if (r.user.role !== "vendor") { await api("POST", "/api/auth/logout").catch(() => {}); NC.state.csrf = null; throw new Error("This is not a vendor account."); }
        location.reload();
      } catch (ex) { err.textContent = ex.message; err.hidden = false; b.disabled = false; }
    };
  }

  const APPROVAL = { pending: ["Waiting for approval", "warn"], approved: ["Live in store", "ok"], rejected: ["Not approved", "bad"] };

  const TABS = [["overview", "Overview"], ["orders", "Orders"], ["products", "Products"], ["earnings", "Earnings"], ["returns", "Returns"], ["shop", "My shop page"], ["reports", "Reports"]];
  const tab = () => { const t = location.hash.replace(/^#\/?/, "").split("?")[0]; return TABS.some((x) => x[0] === t) ? t : "overview"; };

  function home() {
    app.innerHTML = `<div class="vtop"><img src="/static/common/logo.svg" alt=""><b>${esc(V.me.business_name)}</b><span class="grow"></span><button class="btn btn-sm" id="chpw">Password</button><button class="btn btn-sm" id="lo">Sign out</button></div>
      <nav class="vtabs" id="vtabs">${TABS.map(([k, l]) => `<a href="#/${k}" data-t="${k}">${l}</a>`).join("")}</nav><div class="vwrap" id="vbody"></div>`;
    document.getElementById("lo").onclick = async () => { await api("POST", "/api/auth/logout").catch(() => {}); location.reload(); };
    document.getElementById("chpw").onclick = () => modal({ title: "Change password", body: `<label class="fld"><span>Current password</span><input type="password" id="pc"></label><label class="fld"><span>New password</span><input type="password" id="pn"><small>At least 8 characters with letters and numbers.</small></label>`,
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Update", cls: "btn-primary", handler: async (m) => { try { await api("POST", "/api/auth/password", { current: m.querySelector("#pc").value, new: m.querySelector("#pn").value }); toast("Password updated"); } catch (e) { toast(e.message, "err"); return false; } } }] });
    if (!V.bound) { window.addEventListener("hashchange", render); V.bound = true; }
    render();
  }

  async function render() {
    const t = tab(), body = document.getElementById("vbody");
    if (!body) return;
    document.querySelectorAll("#vtabs a").forEach((a) => a.classList.toggle("on", a.dataset.t === t));
    body.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
    try { await ({ overview, orders: () => orders(body, "to_ship"), products, earnings, returns: () => orders(body, "returns", true), shop, reports })[t](body); }
    catch (e) { if (e.status === 401) { location.reload(); return; } body.innerHTML = `<div class="empty"><h3>Couldn't load this page</h3><p>${esc(e.message)}</p></div>`; }
  }

  const stat = (label, value, sub = "", cls = "") => `<div class="vstat ${cls}"><div class="l">${label}</div><div class="v">${value}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;

  async function overview(el) {
    const d = await api("GET", "/api/vendor/overview");
    const E = d.earnings;
    el.innerHTML = `${d.pending_products ? `<div class="vhelp">⏳ ${d.pending_products} product(s) waiting for the store owner to approve.</div>` : ""}
      <h2 class="vh">Your sales</h2>
      <div class="vstats">${stat("Today", fmt.inr(d.today.amount), `${d.today.orders} order(s)`)}${stat("Last 7 days", fmt.inr(d.week.amount), `${d.week.orders} orders · ${d.week.units} items`)}${stat("Last 30 days", fmt.inr(d.month.amount), `${d.month.orders} orders · ${d.month.units} items`)}
        ${stat("Orders to pack / ship", d.to_ship, d.to_ship ? '<a href="#/orders">Open orders →</a>' : "All caught up", d.to_ship ? "warn" : "")}</div>
      <div class="vcardbox"><h3>Sales in the last 30 days</h3><div id="vch"></div></div>
      <h2 class="vh">Your money</h2>
      <div class="vstats">${stat("Ready to be paid", fmt.inr(E.due_now), "The store will pay you this", E.due_now > 0 ? "ok" : "")}${stat("Clearing", fmt.inr(E.clearing), `Waiting for the ${E.window_days}-day return period`)}${stat("Already paid to you", fmt.inr(E.paid))}${stat("Store commission", `${d.commission_pct}%`, `${fmt.inr(E.commission)} so far`)}</div>
      <div class="vgrid2"><div class="vcardbox"><h3>Best-selling products (30 days)</h3><div id="vtop"></div></div>
        <div class="vcardbox"><h3>Low stock</h3>${d.low_stock.length ? d.low_stock.map((x) => `<div class="vrow"><span>${esc(x.name)}</span><b class="${x.avail <= 0 ? "bad" : ""}">${x.avail} left</b></div>`).join("") : '<p class="muted">All products have enough stock. 👍</p>'}</div></div>`;
    NCCharts.line(el.querySelector("#vch"), { labels: d.series.map((x) => x.day), series: [{ name: "Sales", color: NCCharts.S.s1, points: d.series.map((x) => ({ y: x.amount })) }], yFmt: (v) => "₹" + Math.round(v), xFmt: (l) => l.slice(5), height: 220, area: true });
    NCCharts.hbars(el.querySelector("#vtop"), d.top.map((x) => ({ label: x.name, sub: `${x.units} sold`, value: x.revenue })), { fmt: (v) => fmt.inr(v) });
  }

  const FILTERS = [["to_ship", "To pack / ship"], ["shipped", "Shipped"], ["delivered", "Delivered"], ["waiting", "Waiting for payment"], ["returns", "Returns & cancellations"]];

  async function orders(el, filter, locked = false) {
    const d = await api("GET", "/api/vendor/orders?filter=" + filter);
    el.innerHTML = `${locked ? `<h2 class="vh">Returns & cancellations</h2><p class="muted">These orders were cancelled or returned. The money for them is taken off your earnings.</p>` : `<h2 class="vh">Your orders</h2>
      <div class="vchips">${FILTERS.filter((f) => f[0] !== "returns").map(([k, l]) => `<button class="${k === filter ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div>`}
      <div class="vgrid">${d.items.map((o) => `<div class="vorder"><div class="vo-h"><b>${esc(o.order_no)}</b><span class="muted">${fmt.datetime(o.created_at)}</span><span class="pill ${o.status === "delivered" ? "ok" : o.status === "cancelled" || o.status === "refunded" ? "bad" : "info"}">${esc(o.status_label)}</span>${o.cod ? '<span class="pill warn">Cash on delivery</span>' : ""}</div>
        <div class="vo-items">${o.items.map((i) => `<div class="vo-i">${i.image ? `<img src="${esc(i.image)}" alt="">` : '<span class="noimg"></span>'}<div><b>${esc(i.name)}</b><div class="muted">${i.qty} × ${fmt.inr(i.unit_price)} = ${fmt.inr(i.line_total)}</div></div></div>`).join("")}</div>
        <div class="vo-ship"><b>Deliver to:</b> ${esc(o.ship_name || "")} · ${esc(o.ship_phone || "")}<br><span class="muted">${esc(o.address || "")}</span></div>
        <div class="vo-f"><span>Your items: <b>${fmt.inr(o.total)}</b></span>${o.fulfil === "shipped" ? `<span class="pill ok">Shipped${o.tracking_no ? " · " + esc(o.courier || "Courier") + " " + esc(o.tracking_no) : ""}</span>` : o.fulfil === "packed" ? `<span class="pill info">Packed</span>` : ""}
        ${!locked && o.can_act && o.fulfil !== "shipped" ? `<span class="grow"></span>${o.fulfil !== "packed" ? `<button class="btn btn-sm" data-pk="${o.id}">Mark packed</button>` : ""}<button class="btn btn-primary btn-sm" data-sh="${o.id}">Mark shipped</button>` : ""}</div></div>`).join("") || `<div class="empty"><h3>Nothing here</h3><p>${filter === "to_ship" ? "No orders waiting for you right now." : "No orders in this list."}</p></div>`}</div>`;
    el.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => orders(el, b.dataset.f)));
    el.querySelectorAll("[data-pk]").forEach((b) => (b.onclick = async () => { try { await api("POST", `/api/vendor/orders/${b.dataset.pk}/fulfil`, { action: "pack" }); toast("Marked as packed"); orders(el, filter, locked); } catch (e) { toast(e.message, "err"); } }));
    el.querySelectorAll("[data-sh]").forEach((b) => (b.onclick = () => modal({ title: "Mark as shipped", body: `<label class="fld"><span>Courier / transport name</span><input id="sc" maxlength="60" placeholder="e.g. BlueDart, India Post, own delivery"></label><label class="fld"><span>Tracking / receipt number</span><input id="st" maxlength="60"></label><small class="muted">The store owner is told, and updates the customer.</small>`,
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Mark shipped", cls: "btn-primary", handler: async (m) => { try { await api("POST", `/api/vendor/orders/${b.dataset.sh}/fulfil`, { action: "ship", courier: m.querySelector("#sc").value, tracking_no: m.querySelector("#st").value }); toast("Marked as shipped"); orders(el, filter, locked); return true; } catch (e) { toast(e.message, "err"); return false; } } }] })));
  }

  async function earnings(el) {
    const d = await api("GET", "/api/vendor/earnings");
    const S = d.summary;
    el.innerHTML = `<h2 class="vh">Your earnings</h2>
      <div class="vstats">${stat("Ready to be paid", fmt.inr(S.due_now), "Paid to you by the store", S.due_now > 0 ? "ok" : "")}${stat("Clearing", fmt.inr(S.clearing), `Return period (${S.window_days} days)`)}${stat("On hold", fmt.inr(S.hold), "A customer asked to return")}${stat("Already paid", fmt.inr(S.paid))}</div>
      <div class="vhelp">💡 <b>How it works:</b> when an order is delivered, you earn the sale amount minus the store's commission. The money becomes “Ready to be paid” after the ${S.window_days}-day return period. If an order is returned, it is taken off. ${S.clawback ? `<br><b>${fmt.inr(S.clawback)}</b> will be taken off your next payment because of returns after you were paid.` : ""}</div>
      <div class="vcardbox"><h3>Payments you received</h3>${d.payouts.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Date</th><th class="num">Amount</th><th>How</th><th>Reference</th></tr></thead><tbody>${d.payouts.map((p) => `<tr><td>${fmt.date(p.created_at)}</td><td class="num"><b>${fmt.inr(p.amount)}</b></td><td>${esc((p.method || "").toUpperCase())}</td><td class="muted">${esc(p.reference || "")}</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">No payment yet.</p>'}</div>
      <div class="vcardbox"><h3>Every sale</h3>${d.rows.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Order</th><th>Product</th><th class="num">Sale</th><th class="num">Commission</th><th class="num">You earn</th><th>Status</th></tr></thead><tbody>${d.rows.map((r) => `<tr><td>${esc(r.order_no)}</td><td>${esc(r.name)} × ${r.qty}</td><td class="num">${fmt.inr(r.gross)}</td><td class="num">${fmt.inr(r.commission)} <span class="muted">(${r.commission_pct}%)</span></td><td class="num"><b>${fmt.inr(r.net)}</b></td><td><span class="pill ${r.state === "payable" || r.label === "Paid" ? "ok" : r.state === "reversed" ? "bad" : "warn"}">${esc(r.label)}</span></td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">Earnings appear here after your first delivered order.</p>'}</div>`;
  }

  async function shop(el) {
    const d = await api("GET", "/api/vendor/shop");
    const link = `${location.origin}/#/vendor/${d.id}`;
    el.innerHTML = `<h2 class="vh">My shop page</h2><div class="vcardbox"><p class="muted">Customers can open a page with your name, picture and all your live products. Share this link with them:</p>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px"><input class="inp" readonly value="${esc(link)}" style="flex:1;min-width:220px"><button class="btn btn-sm" id="cp">Copy link</button><a class="btn btn-sm" href="${esc(link)}" target="_blank" rel="noopener">View my shop ↗</a></div>
      <div style="display:flex;gap:14px;align-items:center;margin-bottom:12px">${d.logo ? `<img src="${esc(d.logo)}" alt="" style="width:72px;height:72px;border-radius:50%;object-fit:cover">` : `<div class="noimg" style="width:72px;height:72px;border-radius:50%">No picture</div>`}
        <label class="fld" style="margin:0;flex:1"><span>Shop picture / logo (JPG, PNG or WEBP, up to 5 MB)</span><input type="file" id="lg" accept="image/*"></label><button class="btn btn-sm" id="lgu">Upload</button></div>
      <label class="fld"><span>About your shop (shown to customers)</span><textarea id="ab" rows="4" maxlength="600">${esc(d.about)}</textarea></label><button class="btn btn-primary" id="abs">Save</button></div>`;
    el.querySelector("#cp").onclick = () => { navigator.clipboard?.writeText(link); toast("Link copied"); };
    el.querySelector("#abs").onclick = async () => { try { await api("PUT", "/api/vendor/shop", { about: el.querySelector("#ab").value }); toast("Saved"); } catch (e) { toast(e.message, "err"); } };
    el.querySelector("#lgu").onclick = async () => {
      const f = el.querySelector("#lg").files[0]; if (!f) { toast("Choose a picture first", "err"); return; }
      const fd = new FormData(); fd.append("file", f);
      try { await api("POST", "/api/vendor/shop/logo", fd); toast("Picture saved"); shop(el); } catch (e) { toast(e.message, "err"); }
    };
  }

  async function reports(el) {
    const today = new Date().toISOString().slice(0, 10), from = new Date(Date.now() - 29 * 864e5).toISOString().slice(0, 10);
    el.innerHTML = `<h2 class="vh">Download reports</h2><div class="vcardbox"><p class="muted">Choose dates, then download a spreadsheet (opens in Excel or Google Sheets).</p>
      <div class="row2"><label class="fld"><span>From</span><input type="date" id="rf" value="${from}"></label><label class="fld"><span>To</span><input type="date" id="rt" value="${today}"></label></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn btn-primary" data-k="sales">⬇ Sales report</button><button class="btn" data-k="earnings">⬇ Earnings report</button><button class="btn" data-k="payouts">⬇ Payments received</button></div></div>`;
    el.querySelectorAll("[data-k]").forEach((b) => (b.onclick = () => { location.href = `/api/vendor/report?kind=${b.dataset.k}&from=${el.querySelector("#rf").value}&to=${el.querySelector("#rt").value}`; }));
  }

  async function products(el) {
    const d = await api("GET", "/api/vendor/products");
    el.innerHTML = `<div class="vhelp"><b>How it works:</b> add your product with a photo. The store owner checks it, then it goes live for customers. You can change your stock any time.</div>
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px"><h2 class="vh" style="margin:0;flex:1">My products (${d.items.length})</h2><button class="btn btn-primary" id="add">+ Add product</button></div>
      <div class="vgrid">${d.items.map((p) => { const a = APPROVAL[p.approval] || ["", ""]; return `<div class="vcard">${p.image ? `<img src="${esc(p.image)}" alt="">` : `<div class="noimg">No photo</div>`}
          <div><h3>${esc(p.name)}</h3><div class="meta">${esc(p.category || "")} · ${fmt.inr(p.price)}${p.mrp ? ` (MRP ${fmt.inr(p.mrp)})` : ""} · Stock: <b>${p.stock}</b></div>
          <div style="margin-top:4px"><span class="pill ${a[1]}">${a[0]}</span>${p.approval === "rejected" && p.note ? ` <span class="meta">Reason: ${esc(p.note)}</span>` : ""}</div>
          <div class="acts"><button class="btn btn-sm" data-ed="${p.id}">Edit</button><button class="btn btn-sm" data-ph="${p.id}">📷 Photos</button><button class="btn btn-sm" data-st="${p.id}" data-n="${p.stock}">Update stock</button></div></div></div>`; }).join("") || `<div class="empty"><h3>No products yet</h3><p>Press “+ Add product” to list your first item.</p></div>`}</div>`;
    el.querySelector("#add").onclick = () => productDlg(null);
    el.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = async () => productDlg(await api("GET", "/api/vendor/products/" + b.dataset.ed))));
    el.querySelectorAll("[data-ph]").forEach((b) => (b.onclick = () => photoDlg(+b.dataset.ph)));
    el.querySelectorAll("[data-st]").forEach((b) => (b.onclick = () => stockDlg(+b.dataset.st, +b.dataset.n)));
  }

  function stockDlg(id, n) {
    modal({ title: "Update stock", body: `<label class="fld"><span>Pieces you have now</span><input id="sn" type="number" min="0" value="${n}"></label>`,
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: async (m) => {
        try { await api("PATCH", `/api/vendor/products/${id}/stock`, { stock: m.querySelector("#sn").value }); toast("Stock updated"); render(); return true; } catch (e) { toast(e.message, "err"); return false; } } }] });
  }

  function productDlg(p) {
    const top = V.cats.filter((c) => !c.parent_id);
    const catOpts = (sel) => top.map((c) => `<option value="${c.id}" ${sel == c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
    const subOpts = (cid, sel) => `<option value="">— none —</option>` + ((top.find((c) => c.id == cid) || {}).children || []).map((c) => `<option value="${c.id}" ${sel == c.id ? "selected" : ""}>${esc(c.name)}</option>`).join("");
    modal({ title: p ? "Edit product" : "Add product", onOpen: (m) => { const c = m.querySelector("#pcat"); c.onchange = () => (m.querySelector("#psub").innerHTML = subOpts(c.value, "")); },
      body: `${p && p.approval === "approved" ? `<div class="vhelp" style="font-size:14px">This product is live. If you change its name, description or category, the owner has to approve it again.</div>` : ""}
        <label class="fld"><span>Product name</span><input id="pn" maxlength="150" value="${esc(p ? p.name : "")}"></label>
        <div class="row2"><label class="fld"><span>Category</span><select id="pcat">${catOpts(p ? p.category_id : (top[0] || {}).id)}</select></label>
        <label class="fld"><span>Sub-category</span><select id="psub">${subOpts(p ? p.category_id : (top[0] || {}).id, p ? p.subcategory_id : "")}</select></label></div>
        <div class="row2"><label class="fld"><span>Selling price ₹</span><input id="pp" type="number" min="1" step="0.01" value="${p ? p.selling_price : ""}"></label>
        <label class="fld"><span>MRP ₹ (optional)</span><input id="pm" type="number" min="0" step="0.01" value="${p && p.mrp ? p.mrp : ""}"></label></div>
        ${p ? "" : `<label class="fld"><span>Pieces in stock</span><input id="ps" type="number" min="0" value="0"></label>`}
        <label class="fld"><span>Brand (optional)</span><input id="pb" maxlength="60" value="${esc(p ? p.brand || "" : "")}"></label>
        <label class="fld"><span>Description</span><textarea id="pd" rows="4" maxlength="5000">${esc(p ? p.description || "" : "")}</textarea></label>`,
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: p ? "Save" : "Add product", cls: "btn-primary", handler: async (m) => {
        const g = (i) => m.querySelector("#" + i).value;
        const d = { name: g("pn"), category_id: g("pcat"), subcategory_id: g("psub"), selling_price: g("pp"), mrp: g("pm"), brand: g("pb"), description: g("pd") };
        try {
          if (p) {
            Object.assign(d, { sku: p.sku, tax_rate: p.tax_rate, specs: p.specs, low_stock_threshold: p.low_stock_threshold, max_per_order: p.max_per_order, weight_g: p.weight_g, dimensions: p.dimensions, shipping_req: p.shipping_req });
            const r = await api("PUT", "/api/vendor/products/" + p.id, d);
            toast(r.approval === "pending" ? "Saved — waiting for the owner to approve" : "Saved");
          } else {
            d.stock = g("ps");
            const r = await api("POST", "/api/vendor/products", d);
            toast("Added. Now add a photo so the owner can approve it.");
            render(); photoDlg(r.id); return true;
          }
          render(); return true;
        } catch (e) { toast(e.message, "err"); return false; }
      } }] });
  }

  async function photoDlg(id) {
    const p = await api("GET", "/api/vendor/products/" + id);
    modal({ title: "Photos · " + p.name, onOpen: (m) => {
      m.querySelectorAll("[data-di]").forEach((b) => (b.onclick = async () => { try { await api("DELETE", "/api/vendor/images/" + b.dataset.di); toast("Photo removed"); b.closest("div").remove(); render(); } catch (e) { toast(e.message, "err"); } }));
    }, body: `<div class="vimgs">${(p.images || []).map((i) => `<div><img src="${esc(i.url)}" alt=""><button type="button" data-di="${i.id}" aria-label="Remove photo">×</button></div>`).join("") || `<p class="muted">No photos yet.</p>`}</div>
      <label class="fld"><span>Add photos (JPG, PNG or WEBP, up to 5 MB each, max 8)</span><input type="file" id="pf" accept="image/*" multiple></label>
      <p class="muted" style="font-size:13px">Clear, bright photos on a plain background sell best.</p>`,
      actions: [{ label: "Close", cls: "btn-ghost" }, { label: "Upload", cls: "btn-primary", handler: async (m) => {
        const files = [...m.querySelector("#pf").files];
        if (!files.length) { toast("Choose a photo first", "err"); return false; }
        const fd = new FormData(); files.forEach((f) => fd.append("files", f));
        try { await api("POST", `/api/vendor/products/${id}/images`, fd); toast("Photos saved"); render(); return true; } catch (e) { toast(e.message, "err"); return false; }
      } }] });
  }

  boot();
})();
