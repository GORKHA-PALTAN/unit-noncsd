/* Unit Non-CSD App — customer storefront (single-page app, hash routing). */
(function () {
  const { api, esc, fmt, toast, modal, confirmDialog, promptDialog, formData, debounce, stars } = NC;
  const S = { me: null, counts: { cart: 0, wishlist: 0, notifications: 0 }, meta: null, dept: "", wish: new Set(), heroTimer: null };
  const main = document.getElementById("main");
  const ICON = { electronics: "📺", mobile: "📱", computers: "💻", audio: "🎧", clothing: "👕", shoes: "👟", watches: "⌚", accessories: "🎒",
    appliances: "🌀", kitchen: "🍳", sports: "🏋️", care: "🧴" };

  // ------------------------------------------------------------------ boot
  async function boot() {
    try {
      const [meta, me] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/auth/me")]);
      S.meta = meta;
      setMe(me);
    } catch (e) {
      main.innerHTML = `<div class="empty"><div class="ico">!</div><h3>Store is unavailable</h3><p>${esc(e.message)}</p><button class="btn btn-primary" onclick="location.reload()">Retry</button></div>`;
      return;
    }
    document.getElementById("brand-name").textContent = S.meta.store.store_name.replace(/ App$/, "");
    document.title = S.meta.store.store_name;
    const strip = document.getElementById("strip");
    if (S.meta.store.announcement) { strip.textContent = S.meta.store.announcement; strip.hidden = false; }
    renderTabs();
    renderFooter();
    bindChrome();
    window.addEventListener("hashchange", route);
    route();
  }

  function setMe(me) {
    S.me = me.user;
    NC.state.csrf = me.user ? me.user.csrf : null;
    S.counts = me.counts || { cart: 0, wishlist: 0, notifications: 0 };
    paintCounts();
    if (S.me && S.me.role === "customer") api("GET", "/api/wishlist").then((w) => { S.wish = new Set(w.items.map((i) => i.id)); }).catch(() => {});
    else S.wish = new Set();
  }

  async function refreshMe() { setMe(await api("GET", "/api/auth/me")); }

  function paintCounts() {
    document.querySelectorAll("[data-count]").forEach((el) => {
      const n = S.counts[el.dataset.count] || 0;
      el.textContent = n > 99 ? "99+" : n; el.hidden = !n;
    });
  }

  function renderTabs() {
    const tabs = ["", ...S.meta.departments];
    const html = tabs.map((d) => `<a href="#/${d ? "?dept=" + encodeURIComponent(d) : ""}" data-dept="${esc(d)}" class="${d === S.dept ? "on" : ""}">${esc(d || "All")}</a>`).join("");
    document.getElementById("dept-tabs").innerHTML = html;
  }

  function renderFooter() {
    const st = S.meta.store;
    document.getElementById("foot").innerHTML = `<div class="cols">
      <div><h4>Shop</h4>${S.meta.categories.slice(0, 6).map((c) => `<a href="#/c/${c.slug}">${esc(c.name)}</a>`).join("")}</div>
      <div><h4>My account</h4><a href="#/orders">Orders & tracking</a><a href="#/wishlist">Wishlist</a><a href="#/cart">Cart</a><a href="#/account">Profile & addresses</a></div>
      <div><h4>Policies</h4><a href="#/policy/returns">Returns & refunds</a><a href="#/policy/shipping">Shipping</a><a href="#/policy/privacy">Privacy</a></div>
      <div><h4>Customer support</h4><a href="mailto:${esc(st.support_email)}">${esc(st.support_email)}</a><a href="tel:${esc(st.support_phone.replace(/\s/g, ""))}">${esc(st.support_phone)}</a><a href="/admin">Staff sign-in</a></div></div>
      <div class="fine">© ${new Date().getFullYear()} ${esc(st.store_name)}. Products marked SAMPLE are demonstration data and are not real inventory.</div>
      <div class="fine foot-credit">Created &amp; managed by <b>Surjeet Choudhary</b></div>`;
  }

  function bindChrome() {
    const drawer = document.getElementById("drawer");
    const btn = document.getElementById("menu-btn");
    btn.onclick = () => openDrawer(true);
    document.getElementById("drawer-scrim").onclick = () => openDrawer(false);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer.classList.contains("open")) openDrawer(false); });
    drawer.addEventListener("click", (e) => { if (e.target.closest("a[href^='#']")) openDrawer(false); });
    document.getElementById("top-search").onsubmit = (e) => {
      e.preventDefault();
      const q = e.target.q.value.trim();
      if (q) location.hash = "#/search?q=" + encodeURIComponent(q);
    };
  }

  function openDrawer(open) {
    const drawer = document.getElementById("drawer");
    if (open) renderDrawer(S.dept || S.meta.departments[0]);
    drawer.classList.toggle("open", open);
    document.body.classList.toggle("drawer-open", open);
    drawer.setAttribute("aria-hidden", open ? "false" : "true");
    document.getElementById("menu-btn").setAttribute("aria-expanded", open);
    if (open) setTimeout(() => drawer.querySelector(".drawer-tabs button")?.focus(), 50);
  }

  function renderDrawer(dept) {
    const u = S.me;
    document.getElementById("drawer-head").innerHTML = `<img src="/static/common/logo.svg" alt="">
      <div><a href="${u ? "#/account" : "#/login"}" class="dh-name">${esc(u ? u.name : "Sign in / Register")} <span aria-hidden="true">›</span></a>
      <span class="dh-sub">${u ? (u.buyer ? "Buyer code " + esc(u.buyer.code) : u.role === "customer" ? "Unit customer" : esc(u.role)) : "Welcome to the unit store"}</span></div>`;
    const depts = S.meta.departments;
    document.getElementById("drawer-tabs").innerHTML = depts.map((d) => `<button data-d="${esc(d)}" class="${d === dept ? "on" : ""}">${esc(d.replace(" & Living", ""))}</button>`).join("");
    document.querySelectorAll("#drawer-tabs button").forEach((b) => (b.onclick = () => renderDrawer(b.dataset.d)));
    const cats = S.meta.categories.filter((c) => c.department === dept);
    const quick = [["Best sellers", "#/search?sort=popular", "🔥"], ["New arrivals", "#/search?sort=newest", "✨"], ["Offers", "#/search?offers=1&sort=discount", "🏷️"]];
    document.getElementById("drawer-body").innerHTML = `
      <div class="chip-rail">${quick.map((q) => `<a class="chip-card" href="${q[1]}${q[1].includes("?") ? "&" : "?"}dept=${encodeURIComponent(dept)}"><div class="cc-img" style="font-size:44px">${q[2]}</div><span>${q[0]}</span></a>`).join("")}
        ${cats.map((c) => `<a class="chip-card" href="#/c/${c.slug}"><div class="cc-img">${c.image ? `<img src="${esc(c.image)}" alt="">` : ICON[c.icon] || "🛍️"}</div><span>${esc(c.name)}</span></a>`).join("")}</div>
      <div class="acc"><button class="acc-h" aria-expanded="true" data-acc="all">Shop All <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 15 6-6 6 6"/></svg></button>
        <div class="acc-list" id="acc-all"><a href="#/search?dept=${encodeURIComponent(dept)}">All ${esc(dept)}</a>${cats.map((c) => `<a href="#/c/${c.slug}">${esc(c.name)} <small style="color:var(--ink-3)">(${c.count})</small></a>`).join("")}</div>
        <button class="acc-h" aria-expanded="true" data-acc="cats">Categories <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 15 6-6 6 6"/></svg></button>
        <div class="tile-grid" id="acc-cats">${cats.flatMap((c) => c.children.map((s) => ({ s, c }))).map(({ s, c }) => `
          <a class="tile" href="#/c/${s.slug}"><div class="t-img">${c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy">` : `<span style="font-size:40px">${ICON[c.icon] || "🛍️"}</span>`}</div>${esc(s.name)}</a>`).join("")}</div></div>
      <div class="drawer-links">
        <a href="#/orders">📦 My orders</a><a href="#/wishlist">♡ Wishlist</a><a href="#/notifications">🔔 Notifications</a>
        <button id="dr-lang">🌐 Language</button><a href="#/policy/returns">↩︎ Returns & refunds</a>${u ? `<button id="dr-logout">⎋ Sign out</button>` : `<a href="#/login">→ Sign in</a>`}
        ${u && u.role !== "customer" ? `<a href="/admin">⚙ Admin dashboard</a>` : ""}</div>
      <div class="credit">Created &amp; managed by <b>Surjeet Choudhary</b></div>`;
    document.querySelectorAll(".acc-h").forEach((h) => (h.onclick = () => {
      const open = h.getAttribute("aria-expanded") === "true";
      h.setAttribute("aria-expanded", !open);
      document.getElementById("acc-" + h.dataset.acc).hidden = open;
    }));
    document.getElementById("dr-lang").onclick = () => { openDrawer(false); NCI18N.dialog(); };
    const lo = document.getElementById("dr-logout");
    if (lo) lo.onclick = logout;
  }

  async function logout() {
    try { await api("POST", "/api/auth/logout"); } catch (e) { /* ignore */ }
    await refreshMe(); openDrawer(false); toast("Signed out"); location.hash = "#/";
  }

  // ------------------------------------------------------------------ router
  function parseHash() {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, qs] = h.split("?");
    return { parts: path.split("/").filter(Boolean), q: new URLSearchParams(qs || "") };
  }

  async function route() {
    clearInterval(S.heroTimer);
    const { parts, q } = parseHash();
    const r = parts[0] || "";
    document.querySelectorAll(".bottom-nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === ({ "": "home", wishlist: "wishlist", categories: "categories", orders: "orders", order: "orders", account: "account", notifications: "account" }[r] || "")));
    if (r === "" ) { S.dept = q.get("dept") || ""; renderTabs(); }
    document.getElementById("dept-tabs").hidden = !(r === "" || r === "categories");
    window.scrollTo(0, 0);
    main.innerHTML = `<div class="page-loading"><span class="spin lg"></span></div>`;
    try {
      if (r === "") await pageHome();
      else if (r === "c") await pageList({ category: parts[1] }, q);
      else if (r === "search") await pageList({}, q);
      else if (r === "p") await pageProduct(parts[1]);
      else if (r === "categories") pageCategories();
      else if (r === "cart") await needLogin(pageCart);
      else if (r === "checkout") await needLogin(pageCheckout);
      else if (r === "orders") await needLogin(pageOrders);
      else if (r === "order") await needLogin(() => pageOrder(parts[1]));
      else if (r === "wishlist") await needLogin(pageWishlist);
      else if (r === "account") await needLogin(pageAccount);
      else if (r === "notifications") await needLogin(pageNotifications);
      else if (r === "login") pageAuth("login", q.get("next"), q.get("pw") === "1");
      else if (r === "register") pageAuth("register", q.get("next"));
      else if (r === "policy") pagePolicy(parts[1]);
      else main.innerHTML = `<div class="empty"><div class="ico">?</div><h3>Page not found</h3><a class="btn btn-primary" href="#/">Go home</a></div>`;
    } catch (e) {
      if (e.status === 401) { location.hash = "#/login?next=" + encodeURIComponent(location.hash); return; }
      main.innerHTML = `<div class="empty"><div class="ico">!</div><h3>Couldn't load this page</h3><p>${esc(e.message)}</p><button class="btn btn-primary" id="retry">Try again</button></div>`;
      document.getElementById("retry").onclick = route;
    }
    main.focus({ preventScroll: true });
  }

  async function needLogin(fn) {
    if (!S.me) { location.hash = "#/login?next=" + encodeURIComponent(location.hash); return; }
    if (S.me.role !== "customer") {
      main.innerHTML = `<div class="empty"><div class="ico">i</div><h3>Signed in as ${esc(S.me.role)}</h3><p>Shopping features are for customer accounts. Use the admin dashboard to manage the store.</p><a class="btn btn-primary" href="/admin">Open admin dashboard</a></div>`;
      return;
    }
    await fn();
  }

  function requireCustomer() {
    if (!S.me) { toast("Please sign in to continue", "warn"); location.hash = "#/login?next=" + encodeURIComponent(location.hash); return false; }
    if (S.me.role !== "customer") { toast("Shopping is available on customer accounts only", "warn"); return false; }
    return true;
  }

  // ------------------------------------------------------------------ components
  function card(p) {
    const stock = p.stock === "out" ? `<span class="stock-out">Out of stock</span>` : p.stock === "low" ? `<span class="stock-low">Only ${p.available} left</span>` : "";
    return `<div class="pcard">
      <a href="#/p/${p.slug}" class="pc-img"><img src="${esc(p.image)}" alt="${esc(p.name)}" loading="lazy"></a>
      <button class="pc-wish ${S.wish.has(p.id) ? "on" : ""}" data-wish="${p.id}" aria-label="${S.wish.has(p.id) ? "Remove from" : "Add to"} wishlist" aria-pressed="${S.wish.has(p.id)}">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="${S.wish.has(p.id) ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.8"><path d="M12 20s-7-4.4-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.6-9 9-9 9z"/></svg></button>
      <div class="pc-body">
        <span class="pc-brand">${esc(p.brand || "")}</span>
        <a href="#/p/${p.slug}" class="pc-name">${esc(p.name)}</a>
        <div class="price"><b>${fmt.inr(p.price)}</b>${p.mrp && p.mrp > p.price ? `<s>${fmt.inr(p.mrp)}</s><span class="off">${p.discount}% off</span>` : ""}</div>
        <div class="pc-meta">${p.reviews ? `<span class="rate">${p.rating} ★</span><span>(${fmt.num(p.reviews)})</span>` : ""}${stock}</div>
        <div class="pc-add"><button class="btn btn-sm ${p.stock === "out" ? "" : "btn-dark"}" data-add="${p.id}" ${p.stock === "out" ? "disabled" : ""}>${p.stock === "out" ? "Out of stock" : "Add to cart"}</button></div>
      </div></div>`;
  }

  function bindCards(root) {
    root.querySelectorAll("[data-wish]").forEach((b) => (b.onclick = () => toggleWish(+b.dataset.wish, b)));
    root.querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => addToCart(+b.dataset.add, 1, b)));
  }

  async function toggleWish(id, btn) {
    if (!requireCustomer()) return;
    try {
      const r = await api("POST", "/api/wishlist", { product_id: id });
      if (r.added) S.wish.add(id); else S.wish.delete(id);
      S.counts.wishlist = r.count; paintCounts();
      document.querySelectorAll(`[data-wish="${id}"]`).forEach((b) => {
        b.classList.toggle("on", r.added); b.setAttribute("aria-pressed", r.added);
        b.querySelector("svg").setAttribute("fill", r.added ? "currentColor" : "none");
      });
      toast(r.added ? "Added to wishlist" : "Removed from wishlist");
      return r.added;
    } catch (e) { toast(e.message, "err"); }
  }

  async function addToCart(id, qty, btn) {
    if (!requireCustomer()) return false;
    const old = btn ? btn.innerHTML : null;
    if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spin"></span>`; }
    try {
      const r = await api("POST", "/api/cart", { product_id: id, qty, mode: "add" });
      S.counts.cart = r.items.reduce((a, i) => a + i.qty, 0); paintCounts();
      toast("Added to cart");
      return true;
    } catch (e) { toast(e.message, "err"); return false; }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = old; } }
  }

  function rail(title, items, link) {
    if (!items || !items.length) return "";
    return `<section class="sec"><div class="sec-h"><h2>${esc(title)}</h2>${link ? `<a href="${link}">View all ›</a>` : ""}</div>
      <div class="rail">${items.map(card).join("")}</div></section>`;
  }

  // ------------------------------------------------------------------ pages
  async function pageHome() {
    const deptQ = S.dept ? "?dept=" + encodeURIComponent(S.dept) : "";
    const h = await api("GET", "/api/home" + deptQ);
    const cats = S.meta.categories.filter((c) => !S.dept || c.department === S.dept);
    const banners = h.banners.length ? h.banners : [{ title: S.meta.store.store_name, subtitle: S.meta.store.tagline, theme: "navy", cta: "Start shopping", link: "#/search" }];
    const heroImgs = [...h.featured, ...h.best_sellers].map((p) => p.image);
    const dq = S.dept ? "&dept=" + encodeURIComponent(S.dept) : "";
    const exploreCat = cats.find((c) => c.icon === "accessories") || cats[0];
    const featureItems = h.best_sellers.slice(0, 6);
    main.innerHTML = `
      <section class="hero" aria-roledescription="carousel" aria-label="Promotions">
        <div class="hero-track" id="hero-track">${banners.map((b, i) => `
          <div class="hero-slide th-${esc(b.theme || "navy")}" role="group" aria-label="${i + 1} of ${banners.length}">
            <div><h2>${esc(b.title)}</h2>${b.subtitle ? `<p>${esc(b.subtitle)}</p>` : ""}${b.cta ? `<a class="btn" href="${esc(b.link || "#/search")}">${esc(b.cta)}</a>` : ""}</div>
            <div class="hero-art">${b.image_url || heroImgs[i] ? `<img src="${esc(b.image_url || heroImgs[i])}" alt="">` : ""}</div></div>`).join("")}</div>
        ${banners.length > 1 ? `<div class="dots" id="hero-dots">${banners.map((_, i) => `<button aria-label="Slide ${i + 1}" class="${i ? "" : "on"}"></button>`).join("")}</div>` : ""}
      </section>
      <section class="sec"><div class="sec-h"><h2>Shop by category</h2><a href="#/categories">All categories ›</a></div>
        <div class="cat-grid">${cats.map((c) => `<a class="tile" href="#/c/${c.slug}"><div class="t-img">${c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy">` : `<span style="font-size:40px">${ICON[c.icon] || "🛍️"}</span>`}</div>${esc(c.name)}</a>`).join("")}</div></section>
      ${rail("Featured", h.featured, "#/search?sort=rating" + dq)}
      ${exploreCat ? `<section class="sec"><a class="explore" href="#/c/${exploreCat.slug}"><h2>Explore<br>${esc(exploreCat.name)}</h2>
        ${exploreCat.image ? `<img src="${esc(exploreCat.image)}" alt="">` : "<span></span>"}<span class="vert">${exploreCat.children.slice(0, 3).map((c) => esc(c.name)).join(" | ")}</span></a>
        <div class="feature-grid">${featureItems.map((p) => `<a href="#/p/${p.slug}" aria-label="${esc(p.name)}"><img src="${esc(p.image)}" alt="" loading="lazy"></a>`).join("")}</div></section>` : ""}
      ${rail("Best sellers", h.best_sellers, "#/search?sort=popular" + dq)}
      ${rail("Special offers", h.offers, "#/search?offers=1&sort=discount" + dq)}
      ${rail("New arrivals", h.new_arrivals, "#/search?sort=newest" + dq)}
      ${rail(S.me && S.me.role === "customer" ? "Recommended for you" : "Top rated", h.recommended)}
      <section class="sec"><div class="sec-h"><h2>Popular categories</h2></div>
        <div class="subcat-row">${h.popular_categories.map((c) => `<a href="#/c/${c.slug}">${esc(c.name)} · ${c.count}</a>`).join("")}</div></section>`;
    bindCards(main);
    if (banners.length > 1) {
      let i = 0;
      const track = document.getElementById("hero-track");
      const dots = [...document.querySelectorAll("#hero-dots button")];
      const go = (n) => { i = (n + banners.length) % banners.length; track.style.transform = `translateX(-${i * 100}%)`; dots.forEach((d, k) => d.classList.toggle("on", k === i)); };
      dots.forEach((d, k) => (d.onclick = () => { go(k); clearInterval(S.heroTimer); }));
      let sx = null;
      track.addEventListener("touchstart", (e) => (sx = e.touches[0].clientX), { passive: true });
      track.addEventListener("touchend", (e) => { if (sx === null) return; const dx = e.changedTouches[0].clientX - sx; if (Math.abs(dx) > 40) { go(i + (dx < 0 ? 1 : -1)); clearInterval(S.heroTimer); } sx = null; });
      if (!matchMedia("(prefers-reduced-motion: reduce)").matches) S.heroTimer = setInterval(() => go(i + 1), 5000);
    }
  }

  function pageCategories() {
    main.innerHTML = `<div class="page"><h1>Categories</h1>${S.meta.departments.map((d) => `
      <h2 style="font-size:18px;margin:18px 0 10px;color:var(--teal)">${esc(d)}</h2>
      <div class="tile-grid" style="grid-template-columns:repeat(auto-fill,minmax(104px,1fr))">${S.meta.categories.filter((c) => c.department === d).map((c) => `
        <a class="tile" href="#/c/${c.slug}"><div class="t-img">${c.image ? `<img src="${esc(c.image)}" alt="" loading="lazy">` : ICON[c.icon] || ""}</div>${esc(c.name)}</a>`).join("")}</div>`).join("")}</div>`;
  }

  async function pageList(base, q) {
    const params = new URLSearchParams(q);
    if (base.category) params.set("category", base.category);
    const isSearch = !base.category;
    const cat = base.category ? findCat(base.category) : null;
    if (isSearch && !params.get("q") && !params.get("sort") && !params.get("dept") && !params.get("offers")) {
      main.innerHTML = `<div class="page"><form id="sform" role="search"><label class="fld"><span>Search the store</span>
        <input name="q" type="search" placeholder="Try “earbuds”, “shoes”, “kettle”" autofocus></label><button class="btn btn-primary btn-block">Search</button></form>
        <h2 style="font-size:17px;margin:20px 0 10px">Browse</h2><div class="subcat-row" style="padding:0;flex-wrap:wrap">${S.meta.categories.map((c) => `<a href="#/c/${c.slug}">${esc(c.name)}</a>`).join("")}</div></div>`;
      document.getElementById("sform").onsubmit = (e) => { e.preventDefault(); const v = e.target.q.value.trim(); if (v) location.hash = "#/search?q=" + encodeURIComponent(v); };
      return;
    }
    const data = await api("GET", "/api/products?" + params.toString());
    const title = cat ? cat.name : params.get("q") ? `Results for “${params.get("q")}”` : params.get("offers") ? "Special offers" :
      params.get("sort") === "newest" ? "New arrivals" : params.get("sort") === "popular" ? "Best sellers" : params.get("dept") || "All products";
    const sel = (k, v) => (params.get(k) === v ? "selected" : "");
    const brands = new Set((params.get("brand") || "").split(",").filter(Boolean));
    const parent = cat && cat.parent_id ? S.meta.categories.find((c) => c.id === cat.parent_id) : cat;
    const subs = parent ? parent.children : [];
    main.innerHTML = `
      <div class="list-head"><div><h1>${esc(title)}</h1><span class="count">${fmt.num(data.total)} product${data.total === 1 ? "" : "s"}</span></div>
        <div class="list-tools"><button class="btn btn-sm only-mobile" id="f-open">Filters</button>
        <select class="inp" id="sort" aria-label="Sort by" style="min-height:36px;padding:4px 10px;width:auto">
          <option value="popular" ${sel("sort", "popular")}>Popularity</option><option value="price_asc" ${sel("sort", "price_asc")}>Price: low to high</option>
          <option value="price_desc" ${sel("sort", "price_desc")}>Price: high to low</option><option value="newest" ${sel("sort", "newest")}>Newest arrivals</option>
          <option value="rating" ${sel("sort", "rating")}>Customer rating</option><option value="discount" ${sel("sort", "discount")}>Biggest discount</option></select></div></div>
      ${subs.length ? `<div class="subcat-row"><a href="#/c/${parent.slug}" class="${cat === parent ? "on" : ""}">All ${esc(parent.name)}</a>${subs.map((s) => `<a href="#/c/${s.slug}" class="${cat && cat.id === s.id ? "on" : ""}">${esc(s.name)}</a>`).join("")}</div>` : ""}
      <div class="list-layout">
        <aside class="filters" id="filters" aria-label="Filters">
          <div class="only-mobile-f"><h2 style="font-size:20px">Filters</h2><button class="icon-btn" id="f-close" aria-label="Close filters">✕</button></div>
          <div class="filter-group"><h3>Price</h3><div class="row2" style="gap:8px"><input class="inp" id="f-min" type="number" min="0" placeholder="Min ₹${Math.floor(data.facets.price.min)}" value="${esc(params.get("min") || "")}" aria-label="Minimum price">
            <input class="inp" id="f-max" type="number" min="0" placeholder="Max ₹${Math.ceil(data.facets.price.max)}" value="${esc(params.get("max") || "")}" aria-label="Maximum price"></div></div>
          <div class="filter-group"><h3>Brand</h3>${data.facets.brands.map((b) => `<label class="chk"><input type="checkbox" class="f-brand" value="${esc(b.name)}" ${brands.has(b.name) ? "checked" : ""}>${esc(b.name)} <small style="color:var(--ink-3)">(${b.n})</small></label>`).join("") || `<div class="empty-sm">—</div>`}</div>
          <div class="filter-group"><h3>Customer rating</h3>${[4, 3].map((r) => `<label class="chk"><input type="radio" name="f-rating" value="${r}" ${params.get("rating") == r ? "checked" : ""}>${r}★ & above</label>`).join("")}<label class="chk"><input type="radio" name="f-rating" value="" ${!params.get("rating") ? "checked" : ""}>Any</label></div>
          <div class="filter-group"><h3>Availability</h3><label class="chk"><input type="checkbox" id="f-stock" ${params.get("in_stock") === "1" ? "checked" : ""}>In stock only</label>
            <label class="chk"><input type="checkbox" id="f-offers" ${params.get("offers") === "1" ? "checked" : ""}>On offer</label></div>
          <div style="display:flex;gap:8px;padding-top:12px"><button class="btn btn-primary" id="f-apply" style="flex:1">Apply</button><button class="btn" id="f-clear">Clear</button></div>
        </aside>
        <div>${data.items.length ? `<div class="grid">${data.items.map(card).join("")}</div>` :
          `<div class="empty"><div class="ico">⌕</div><h3>No products found</h3><p>Try a different search or clear the filters.</p><button class="btn btn-primary" id="f-clear2">Clear filters</button></div>`}
          ${data.total > data.per ? `<div class="pager">${data.page > 1 ? `<button class="btn btn-sm" data-page="${data.page - 1}">‹ Previous</button>` : ""}<span style="align-self:center">Page ${data.page} of ${Math.ceil(data.total / data.per)}</span>${data.page * data.per < data.total ? `<button class="btn btn-sm" data-page="${data.page + 1}">Next ›</button>` : ""}</div>` : ""}
        </div></div>`;
    bindCards(main);
    const go = (mut) => {
      const p = new URLSearchParams(params);
      p.delete("category"); p.delete("page");
      mut(p);
      const path = base.category ? `#/c/${base.category}` : "#/search";
      location.hash = path + (p.toString() ? "?" + p.toString() : "");
    };
    document.getElementById("sort").onchange = (e) => go((p) => p.set("sort", e.target.value));
    const filters = document.getElementById("filters");
    const fo = document.getElementById("f-open"); if (fo) fo.onclick = () => filters.classList.add("open");
    document.getElementById("f-close").onclick = () => filters.classList.remove("open");
    document.getElementById("f-apply").onclick = () => go((p) => {
      const set = (k, v) => (v ? p.set(k, v) : p.delete(k));
      set("min", document.getElementById("f-min").value); set("max", document.getElementById("f-max").value);
      set("brand", [...document.querySelectorAll(".f-brand:checked")].map((x) => x.value).join(","));
      set("rating", (document.querySelector("[name=f-rating]:checked") || {}).value);
      set("in_stock", document.getElementById("f-stock").checked ? "1" : ""); set("offers", document.getElementById("f-offers").checked ? "1" : "");
    });
    const clear = () => go((p) => ["min", "max", "brand", "rating", "in_stock", "offers"].forEach((k) => p.delete(k)));
    document.getElementById("f-clear").onclick = clear;
    const c2 = document.getElementById("f-clear2"); if (c2) c2.onclick = clear;
    main.querySelectorAll("[data-page]").forEach((b) => (b.onclick = () => go((p) => p.set("page", b.dataset.page))));
  }

  function findCat(slug) {
    for (const c of S.meta.categories) { if (c.slug === slug) return c; for (const s of c.children) if (s.slug === slug) return s; }
    return null;
  }

  async function pageProduct(slug) {
    const p = await api("GET", "/api/products/" + encodeURIComponent(slug));
    api("POST", "/api/track", { type: "view", product_id: p.id }).catch(() => {});
    let qty = 1, img = 0;
    const total = Object.values(p.rating_distribution).reduce((a, b) => a + b, 0);
    main.innerHTML = `<div class="pd">
      <div class="pd-gallery"><div class="main"><img id="pd-img" src="${esc(p.images[0])}" alt="${esc(p.name)}"></div>
        ${p.images.length > 1 ? `<div class="thumbs">${p.images.map((u, i) => `<button data-img="${i}" class="${i ? "" : "on"}" aria-label="Image ${i + 1}"><img src="${esc(u)}" alt=""></button>`).join("")}</div>` : ""}</div>
      <div>
        <div style="font-size:14px;color:var(--ink-3)"><a href="#/">Home</a> › ${p.category ? `<a href="#/c/${p.category.slug}">${esc(p.category.name)}</a>` : ""}${p.subcategory ? ` › <a href="#/c/${p.subcategory.slug}">${esc(p.subcategory.name)}</a>` : ""}</div>
        <div class="pc-brand" style="margin-top:10px">${esc(p.brand || "")}</div>
        <h1>${esc(p.name)}</h1>
        ${p.reviews_count ? `<div class="pc-meta"><span class="rate">${p.rating} ★</span> ${fmt.num(p.reviews_count)} ratings</div>` : `<div class="pc-meta">No ratings yet</div>`}
        <div class="price" style="margin-top:10px"><b>${fmt.inr(p.price)}</b>${p.mrp && p.mrp > p.price ? `<s>MRP ${fmt.inr(p.mrp)}</s><span class="off">${p.discount}% off</span>` : ""}</div>
        <div style="font-size:13px;color:var(--ink-3)">Inclusive of all taxes (GST ${p.tax_rate}%)</div>
        ${p.sample ? `<div class="sample-note"><b>Sample product.</b> This is demonstration data, not real purchasable inventory. Orders you place for it are for testing the app.</div>` : ""}
        <div style="margin:12px 0">${p.stock === "out" ? `<span class="pill bad">Out of stock</span>` : p.stock === "low" ? `<span class="pill warn">Only ${p.available} left in stock</span>` : `<span class="pill ok">In stock</span>`}</div>
        ${p.stock !== "out" ? `<div style="display:flex;align-items:center;gap:12px"><span style="font-weight:600">Quantity</span>
          <div class="qty"><button id="q-dec" aria-label="Decrease quantity">−</button><span id="q-val" aria-live="polite">1</span><button id="q-inc" aria-label="Increase quantity">+</button></div>
          <small style="color:var(--ink-3)">Max ${p.max_qty}</small></div>` : ""}
        <div class="pd-actions">
          <button class="btn btn-dark" id="pd-add" ${p.stock === "out" ? "disabled" : ""}>Add to cart</button>
          <button class="btn btn-primary" id="pd-buy" ${p.stock === "out" ? "disabled" : ""}>Buy now</button>
          <button class="btn" id="pd-wish" aria-pressed="${p.in_wishlist}" style="flex:0 0 auto">${p.in_wishlist ? "♥ Wishlisted" : "♡ Wishlist"}</button>
        </div>
        <div class="box" style="font-size:14px">🚚 Delivery estimate shown at checkout · ↩︎ ${p.return_window_days}-day returns on eligible items · SKU ${esc(p.sku)}</div>
        <div class="pd-sec"><h2>Description</h2><p style="white-space:pre-line">${esc(p.description || "")}</p></div>
        <div class="pd-sec"><h2>Specifications</h2><table class="specs"><tbody>
          ${Object.entries(p.specs).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join("")}
          ${p.weight_g ? `<tr><th>Weight</th><td>${p.weight_g >= 1000 ? (p.weight_g / 1000).toFixed(2) + " kg" : p.weight_g + " g"}</td></tr>` : ""}
          ${p.dimensions ? `<tr><th>Dimensions</th><td>${esc(p.dimensions)}</td></tr>` : ""}${p.shipping_req ? `<tr><th>Shipping</th><td>${esc(p.shipping_req)}</td></tr>` : ""}</tbody></table></div>
        <div class="pd-sec"><h2>Ratings & reviews</h2>
          ${total ? `<div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap;margin-bottom:10px"><div style="font-size:40px;font-weight:700">${p.rating}<span style="font-size:20px;color:var(--ink-3)">/5</span></div>
            <div class="dist">${[5, 4, 3, 2, 1].map((s) => `<div><span>${s}★</span><i><b style="width:${(p.rating_distribution[s] / total) * 100}%"></b></i><span>${p.rating_distribution[s]}</span></div>`).join("")}</div></div>` : ""}
          ${p.can_review ? `<button class="btn btn-primary btn-sm" id="pd-review">Write a review</button>` : ""}
          ${p.reviews.map((r) => `<div class="review"><div><span class="rate">${r.rating} ★</span> <b>${esc(r.title || "")}</b></div>${r.body ? `<p style="margin:6px 0">${esc(r.body)}</p>` : ""}<div class="who">${esc(r.name)} · ${fmt.date(r.created_at)} · Verified buyer</div></div>`).join("") || `<div class="empty-sm">No reviews yet.</div>`}
        </div>
      </div></div>
      ${p.related.length ? rail("Similar products", p.related) : ""}`;
    bindCards(main);
    main.querySelectorAll("[data-img]").forEach((b) => (b.onclick = () => {
      img = +b.dataset.img; document.getElementById("pd-img").src = p.images[img];
      main.querySelectorAll("[data-img]").forEach((x) => x.classList.toggle("on", x === b));
    }));
    const qv = document.getElementById("q-val");
    const paintQ = () => { if (!qv) return; qv.textContent = qty; document.getElementById("q-dec").disabled = qty <= 1; document.getElementById("q-inc").disabled = qty >= p.max_qty; };
    if (qv) { document.getElementById("q-dec").onclick = () => { qty = Math.max(1, qty - 1); paintQ(); }; document.getElementById("q-inc").onclick = () => { qty = Math.min(p.max_qty, qty + 1); paintQ(); }; paintQ(); }
    document.getElementById("pd-add").onclick = (e) => addToCart(p.id, qty, e.currentTarget);
    document.getElementById("pd-buy").onclick = async (e) => { if (await addToCart(p.id, qty, e.currentTarget)) location.hash = "#/cart"; };
    document.getElementById("pd-wish").onclick = async (e) => {
      const added = await toggleWish(p.id);
      if (added !== undefined) { e.target.textContent = added ? "♥ Wishlisted" : "♡ Wishlist"; e.target.setAttribute("aria-pressed", added); }
    };
    const rv = document.getElementById("pd-review");
    if (rv) rv.onclick = () => reviewDialog(p);
  }

  function reviewDialog(p) {
    let rating = 0;
    modal({
      title: "Review " + p.name,
      body: `<div class="fld"><span>Your rating</span><div class="star-input" id="stars">${[1, 2, 3, 4, 5].map((i) => `<button type="button" data-s="${i}" aria-label="${i} star">★</button>`).join("")}</div></div>
        <label class="fld"><span>Title</span><input id="rv-t" maxlength="100"></label><label class="fld"><span>Review</span><textarea id="rv-b" maxlength="2000"></textarea></label>`,
      onOpen: (el) => el.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => {
        rating = +b.dataset.s; el.querySelectorAll("[data-s]").forEach((x) => x.classList.toggle("on", +x.dataset.s <= rating));
      })),
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Submit review", cls: "btn-primary", handler: async (el) => {
        if (!rating) { toast("Choose a star rating", "err"); return false; }
        await api("POST", "/api/reviews", { product_id: p.id, rating, title: el.querySelector("#rv-t").value, body: el.querySelector("#rv-b").value });
        toast("Thanks for your review!"); route();
      } }],
    });
  }

  // ------------------------------------------------------------------ cart
  async function pageCart() {
    const c = await api("GET", "/api/cart");
    S.counts.cart = c.items.reduce((a, i) => a + i.qty, 0); paintCounts();
    if (!c.items.length) {
      main.innerHTML = `<div class="empty"><div class="ico">🛒</div><h3>Your cart is empty</h3><p>Browse the store and add something you like.</p><a class="btn btn-primary" href="#/">Continue shopping</a></div>`;
      return;
    }
    const q = c.quote;
    main.innerHTML = `<div class="page"><h1>Cart (${S.counts.cart})</h1><div class="two-col">
      <div class="box">${c.items.map((i) => `<div class="citem"><a href="#/p/${i.slug}"><img src="${esc(i.image)}" alt=""></a>
        <div><a href="#/p/${i.slug}" class="ci-name">${esc(i.name)}</a>
          <div class="price"><b>${fmt.inr(i.price)}</b>${i.mrp && i.mrp > i.price ? `<s>${fmt.inr(i.mrp)}</s><span class="off">${i.discount}% off</span>` : ""}</div>
          ${i.issue ? `<div class="issue">⚠ ${esc(i.issue)}</div>` : ""}
          <div class="ci-row"><div class="qty"><button data-dec="${i.id}" ${i.qty <= 1 ? "disabled" : ""} aria-label="Decrease">−</button><span>${i.qty}</span><button data-inc="${i.id}" ${i.qty >= i.available_qty ? "disabled" : ""} aria-label="Increase">+</button></div>
            <span>Subtotal <b>${fmt.inr(i.line_total)}</b></span>
            <button class="btn-link" data-rm="${i.id}" style="color:#c62828">Remove</button></div></div></div>`).join("")}</div>
      <div class="sticky"><div class="box"><h2>Price details</h2>
        <div class="sumrow"><span>Price (MRP)</span><span>${fmt.inr(q.mrp_total)}</span></div>
        <div class="sumrow"><span>Discount</span><span class="save">− ${fmt.inr(q.mrp_total - q.subtotal)}</span></div>
        <div class="sumrow"><span>Estimated delivery</span><span>${q.delivery_charge ? fmt.inr(q.delivery_charge) : "Free"}</span></div>
        <div class="sumrow total"><span>Total</span><span>${fmt.inr(q.grand_total)}</span></div>
        <div style="font-size:13px;color:var(--ink-3)">Includes GST of ${fmt.inr(q.tax_total)}. Final delivery charge depends on the method you choose.</div>
        ${q.savings > 0 ? `<div class="pill ok" style="margin:10px 0">You save ${fmt.inr(q.savings)}</div>` : ""}
        ${q.problems.length ? `<div class="issue" style="margin:10px 0">Please fix the highlighted items before checkout.</div>` : ""}
        <button class="btn btn-primary btn-block" id="to-checkout" ${q.problems.length ? "disabled" : ""} style="margin-top:12px;min-height:50px">Proceed to checkout</button></div></div></div></div>`;
    const set = async (id, qty) => { try { await api("POST", "/api/cart", { product_id: id, qty }); pageCart(); } catch (e) { toast(e.message, "err"); } };
    main.querySelectorAll("[data-dec]").forEach((b) => (b.onclick = () => { const it = c.items.find((x) => x.id == b.dataset.dec); set(it.id, it.qty - 1); }));
    main.querySelectorAll("[data-inc]").forEach((b) => (b.onclick = () => { const it = c.items.find((x) => x.id == b.dataset.inc); set(it.id, it.qty + 1); }));
    main.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Remove item", "Remove this item from your cart?", { confirmLabel: "Remove", danger: true }))) return;
      try { await api("DELETE", "/api/cart/" + b.dataset.rm); toast("Removed from cart"); pageCart(); } catch (e) { toast(e.message, "err"); }
    }));
    document.getElementById("to-checkout").onclick = () => (location.hash = "#/checkout");
  }

  // ------------------------------------------------------------------ checkout
  async function pageCheckout() {
    const [addrs, cart] = await Promise.all([api("GET", "/api/account/addresses"), api("GET", "/api/cart")]);
    if (!cart.items.length) { location.hash = "#/cart"; return; }
    const st = { address: (addrs.items.find((a) => a.is_default) || addrs.items[0] || {}).id, delivery: null, payment: null, coupon: "", quote: null };
    const pays = S.meta.payments;
    const payOpts = [
      { code: "upi", name: "UPI — GPay, PhonePe, Paytm, BHIM", desc: "Pay directly to the store's UPI ID, then enter the transaction ID", ok: !!(pays.upi && pays.upi.enabled), hideOff: true },
      { code: "cod", name: "Cash on Delivery", desc: `Pay in cash when your order arrives (up to ${fmt.inr(pays.cod.max)})`, ok: pays.cod.enabled },
      { code: "razorpay", name: "UPI / Card / Netbanking (Razorpay)", desc: "Secure online payment", ok: pays.razorpay.enabled, hideOff: true },
      { code: "sandbox", name: "Test payment (Sandbox)", desc: "Simulated online payment for testing. No real money is charged.", ok: pays.sandbox.enabled },
    ];
    st.payment = (payOpts.find((p) => p.ok) || {}).code;

    async function requote() {
      st.quote = await api("POST", "/api/checkout/quote", { delivery_method: st.delivery, coupon: st.coupon || null, payment_method: st.payment });
      if (!st.delivery) st.delivery = st.quote.delivery_method;
      paint();
    }
    function paint() {
      const q = st.quote;
      main.innerHTML = `<div class="page"><h1>Checkout</h1><div class="two-col"><div>
        <div class="box" style="margin-bottom:14px"><h2>1. Delivery address</h2>
          ${addrs.items.map((a) => `<label class="opt ${a.id === st.address ? "on" : ""}"><input type="radio" name="addr" value="${a.id}" ${a.id === st.address ? "checked" : ""}>
            <div><b>${esc(a.name)}</b> ${a.label ? `<span class="pill">${esc(a.label)}</span>` : ""}<small>${esc(a.line1)}${a.line2 ? ", " + esc(a.line2) : ""}, ${esc(a.city)}, ${esc(a.state)} ${esc(a.pincode)} · ${esc(a.phone)}</small></div></label>`).join("") || `<p>No saved addresses yet.</p>`}
          <button class="btn btn-sm" id="add-addr">+ Add new address</button></div>
        <div class="box" style="margin-bottom:14px"><h2>2. Delivery method</h2>
          ${q.delivery_methods.map((d) => `<label class="opt ${d.code === st.delivery ? "on" : ""}"><input type="radio" name="dm" value="${d.code}" ${d.code === st.delivery ? "checked" : ""}>
            <div><b>${esc(d.name)}</b> — ${d.charge && !(d.free_above && q.subtotal >= d.free_above) ? fmt.inr(d.charge) : "Free"}<small>${esc(d.description || "")} · ${d.eta[0]}–${d.eta[1]} days${d.free_above ? ` · free above ${fmt.inr(d.free_above)}` : ""}</small></div></label>`).join("")}
          ${q.eta ? `<div style="font-size:14px;color:var(--ink-2)">Estimated delivery: <b>${fmt.date(q.eta[0])} – ${fmt.date(q.eta[1])}</b></div>` : ""}</div>
        <div class="box" style="margin-bottom:14px"><h2>3. Payment method</h2>
          ${payOpts.filter((p) => p.ok || !p.hideOff).map((p) => `<label class="opt ${p.code === st.payment ? "on" : ""} ${p.ok ? "" : "disabled"}"><input type="radio" name="pm" value="${p.code}" ${p.code === st.payment ? "checked" : ""} ${p.ok ? "" : "disabled"}>
            <div><b>${esc(p.name)}</b>${p.ok ? "" : ' <span class="pill">Unavailable</span>'}<small>${esc(p.desc)}</small></div></label>`).join("")}
          ${q.payment_message ? `<div class="issue">${esc(q.payment_message)}</div>` : ""}</div>
        <div class="box"><h2>4. Review items</h2>${q.lines.map((l) => `<div class="sumrow"><span>${esc(l.name)} × ${l.qty}</span><span>${fmt.inr(l.line_total)}</span></div>`).join("")}
          ${q.problems.map((p) => `<div class="issue">⚠ ${esc(p.message)}</div>`).join("")}</div>
      </div>
      <div class="sticky"><div class="box"><h2>Order summary</h2>
        <div class="coupon-row"><input class="inp" id="coupon" placeholder="Coupon code" value="${esc(st.coupon)}" aria-label="Coupon code" style="min-height:40px"><button class="btn btn-sm" id="apply-coupon">${q.coupon ? "Remove" : "Apply"}</button></div>
        ${q.coupon_message ? `<div style="font-size:14px;margin-top:6px;color:${q.coupon ? "var(--green)" : "#c62828"}">${esc(q.coupon_message)}</div>` : ""}
        <div style="margin-top:12px">
        <div class="sumrow"><span>Items (MRP)</span><span>${fmt.inr(q.mrp_total)}</span></div>
        <div class="sumrow"><span>Product discount</span><span class="save">− ${fmt.inr(q.mrp_total - q.subtotal)}</span></div>
        ${q.coupon_discount ? `<div class="sumrow"><span>Coupon (${esc(q.coupon)})</span><span class="save">− ${fmt.inr(q.coupon_discount)}</span></div>` : ""}
        <div class="sumrow"><span>Delivery</span><span>${q.delivery_charge ? fmt.inr(q.delivery_charge) : "Free"}</span></div>
        <div class="sumrow"><span>GST (included)</span><span>${fmt.inr(q.tax_total)}</span></div>
        <div class="sumrow total"><span>Amount payable</span><span>${fmt.inr(q.grand_total)}</span></div></div>
        ${S.me.buyer ? `<div style="font-size:14px;color:var(--ink-2);margin-top:6px">Buyer code: <b>${esc(S.me.buyer.code)}</b></div>` : ""}
        <button class="btn btn-primary btn-block" id="place" style="margin-top:14px;min-height:52px" ${!st.address || !st.payment || q.problems.length || !q.payment_ok ? "disabled" : ""}>Place order · ${fmt.inr(q.grand_total)}</button>
        ${!st.address ? `<div style="font-size:13px;color:var(--ink-3);margin-top:6px">Add a delivery address to continue.</div>` : ""}
      </div></div></div></div>`;
      main.querySelectorAll("[name=addr]").forEach((r) => (r.onchange = () => { st.address = +r.value; paint(); }));
      main.querySelectorAll("[name=dm]").forEach((r) => (r.onchange = () => { st.delivery = r.value; requote(); }));
      main.querySelectorAll("[name=pm]").forEach((r) => (r.onchange = () => { st.payment = r.value; requote(); }));
      document.getElementById("add-addr").onclick = async () => {
        const a = await addressDialog();
        if (a) { addrs.items.unshift(a); st.address = a.id; paint(); }
      };
      document.getElementById("apply-coupon").onclick = () => {
        st.coupon = q.coupon ? "" : document.getElementById("coupon").value.trim();
        requote().catch((e) => toast(e.message, "err"));
      };
      document.getElementById("place").onclick = placeOrder;
    }
    async function placeOrder(e) {
      const btn = e.currentTarget;
      btn.disabled = true; btn.innerHTML = `<span class="spin"></span> Placing order…`;
      try {
        const r = await api("POST", "/api/orders", { address_id: st.address, delivery_method: st.delivery, payment_method: st.payment,
          coupon: st.quote.coupon, expected_total: st.quote.grand_total });
        S.counts.cart = 0; paintCounts();
        if (r.payment) { await runPayment(r.order_no, r.payment); }
        else { toast("Order placed!"); location.hash = "#/order/" + r.order_no + "?placed=1"; }
      } catch (err) {
        toast(err.message, "err");
        if (err.data && err.data.quote) { st.quote = err.data.quote; paint(); } else { btn.disabled = false; btn.textContent = "Place order"; }
      }
    }
    await requote();
  }

  async function runPayment(orderNo, p) {
    if (p.method === "upi") {
      const isPhone = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
      const res = await modal({
        title: "Pay with UPI",
        body: `<div class="upi-pay">
          <div class="upi-amt"><div>Amount to pay</div><b>${fmt.inr(p.amount)}</b><div>Order ${esc(orderNo)}</div></div>
          ${isPhone ? `<a class="btn btn-primary btn-block upi-open" href="${esc(p.link)}">Open UPI app to pay</a>
            <div class="upi-or">or scan this code from another phone</div>` : `<div class="upi-or">Scan with any UPI app — GPay, PhonePe, Paytm, BHIM</div>`}
          <div class="upi-qr">${NCQR.svg(p.link, 5)}</div>
          <div class="upi-id">Pay to <b>${esc(p.payee)}</b><br><span id="upi-id-t">${esc(p.upi_id)}</span> <button type="button" class="linkbtn" id="upi-copy">Copy UPI ID</button></div>
          <ol class="upi-steps"><li>Pay exactly <b>${fmt.inr(p.amount)}</b>.</li><li>Copy the <b>UPI transaction ID / UTR</b> (12 digits) from your UPI app's payment receipt.</li><li>Paste it below and tap <b>Submit</b>.</li></ol>
          <label class="fld"><span>UPI transaction ID / UTR</span><input id="upi-utr" inputmode="text" autocomplete="off" placeholder="e.g. 428812345678" maxlength="35"></label>
          <p class="muted" style="font-size:13px">The store checks its account and confirms your order — usually within a few hours.</p></div>`,
        actions: [
          { label: "Pay later", cls: "btn-ghost", value: null },
          { label: "Submit", cls: "btn-primary", handler: async (b) => {
            const utr = b.querySelector("#upi-utr").value.trim();
            if (!utr) { toast("Enter the transaction ID from your UPI app", "warn"); b.querySelector("#upi-utr").focus(); return false; }
            await api("POST", `/api/orders/${orderNo}/upi-submit`, { utr });
            return { ok: true };
          } },
        ],
        onOpen: (b) => {
          b.querySelector("#upi-copy").onclick = async () => {
            try { await navigator.clipboard.writeText(p.upi_id); toast("UPI ID copied"); } catch { toast(p.upi_id); }
          };
        },
      });
      if (res && res.ok) toast("Thank you! The store will confirm your payment shortly.");
      else toast("You can pay and submit the transaction ID from your order page.", "warn");
      location.hash = "#/order/" + orderNo;
      route();
      return;
    }
    if (p.method === "sandbox") {
      const result = await modal({
        title: "Test payment",
        body: `<div class="sandbox">${esc(p.notice)}</div>
          <div style="text-align:center;margin:18px 0"><div style="color:var(--ink-3)">Amount</div><div style="font-size:32px;font-weight:700">${fmt.inr(p.amount)}</div><div style="color:var(--ink-3)">Order ${esc(orderNo)}</div></div>
          <p style="font-size:14px;color:var(--ink-2)">Choose an outcome to test how the store handles successful and failed payments. The server verifies a signed token before marking anything paid.</p>`,
        actions: [
          { label: "Simulate failure", cls: "btn-danger", handler: async () => api("POST", "/api/payments/sandbox/complete", { payment_id: p.payment_id, token: p.token, outcome: "fail" }) },
          { label: "Simulate success", cls: "btn-primary", handler: async () => api("POST", "/api/payments/sandbox/complete", { payment_id: p.payment_id, token: p.token, outcome: "success" }) },
        ],
      });
      if (result && result.ok) toast("Payment successful");
      else if (result) toast(result.message, "err");
      else toast("Payment not completed. You can retry from your order page.", "warn");
      location.hash = "#/order/" + orderNo + "?placed=1";
      if (location.hash === "#/order/" + orderNo + "?placed=1") route();
      return;
    }
    if (p.method === "razorpay") {
      try { await loadScript("https://checkout.razorpay.com/v1/checkout.js"); }
      catch (e) { toast("Could not load the payment window. Retry from your order page.", "err"); location.hash = "#/order/" + orderNo; return; }
      await new Promise((resolve) => {
        const rz = new window.Razorpay({
          key: p.key_id, amount: p.amount, currency: p.currency, name: p.name, description: p.description, order_id: p.razorpay_order_id, prefill: p.prefill,
          theme: { color: "#1f8a8a" },
          handler: async (resp) => {
            try { await api("POST", "/api/payments/razorpay/verify", resp); toast("Payment verified"); }
            catch (e) { toast(e.message, "err"); }
            resolve();
          },
          modal: { ondismiss: () => { toast("Payment not completed. You can retry from your order page.", "warn"); resolve(); } },
        });
        rz.on("payment.failed", () => toast("Payment failed. You can retry.", "err"));
        rz.open();
      });
      location.hash = "#/order/" + orderNo;
      route();
    }
  }

  function loadScript(src) {
    return new Promise((res, rej) => {
      if (document.querySelector(`script[src="${src}"]`)) return res();
      const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
  }

  function addressDialog(a = {}) {
    return modal({
      title: a.id ? "Edit address" : "Add delivery address",
      body: `<form id="af"><div class="row2"><label class="fld"><span>Full name</span><input name="name" required value="${esc(a.name || S.me.name)}" autocomplete="name"></label>
        <label class="fld"><span>Phone</span><input name="phone" required inputmode="tel" value="${esc(a.phone || S.me.phone || "")}" autocomplete="tel"></label></div>
        <label class="fld"><span>Address line 1</span><input name="line1" required value="${esc(a.line1 || "")}" placeholder="Quarter / house no., block" autocomplete="address-line1"></label>
        <label class="fld"><span>Address line 2 (optional)</span><input name="line2" value="${esc(a.line2 || "")}" placeholder="Area, landmark" autocomplete="address-line2"></label>
        <div class="row3"><label class="fld"><span>City</span><input name="city" required value="${esc(a.city || "")}"></label>
        <label class="fld"><span>State</span><input name="state" required value="${esc(a.state || "")}"></label>
        <label class="fld"><span>PIN code</span><input name="pincode" required inputmode="numeric" maxlength="6" value="${esc(a.pincode || "")}"></label></div>
        <div class="row2"><label class="fld"><span>Label</span><input name="label" value="${esc(a.label || "Home")}"></label>
        <label class="chk" style="margin-top:30px"><input type="checkbox" name="is_default" ${a.is_default || !a.id ? "checked" : ""}> Make default</label></div></form>`,
      actions: [{ label: "Cancel", cls: "btn-ghost", value: null }, { label: "Save address", cls: "btn-primary", handler: async (el) => {
        const d = formData(el.querySelector("#af"));
        return a.id ? api("PUT", "/api/account/addresses/" + a.id, d) : api("POST", "/api/account/addresses", d);
      } }],
    });
  }

  // ------------------------------------------------------------------ orders
  function statusPill(st, label) {
    const cls = { delivered: "ok", refunded: "ok", cancelled: "bad", delivery_failed: "bad", payment_pending: "warn", cancel_requested: "warn", return_requested: "warn",
      refund_processing: "warn", return_in_progress: "warn", returned: "info" }[st] || "teal";
    return `<span class="pill ${cls}">${esc(label)}</span>`;
  }

  async function pageOrders() {
    const r = await api("GET", "/api/orders");
    if (!r.items.length) {
      main.innerHTML = `<div class="empty"><div class="ico">📦</div><h3>No orders yet</h3><p>When you place an order it will appear here with live tracking.</p><a class="btn btn-primary" href="#/">Start shopping</a></div>`;
      return;
    }
    main.innerHTML = `<div class="page"><h1>My orders</h1>${r.items.map((o) => `<a class="ocard" href="#/order/${o.order_no}">
      <div class="oc-top"><div><b>Order ${esc(o.order_no)}</b><div style="font-size:13px;color:var(--ink-3)">${fmt.datetime(o.created_at)} · ${fmt.inr(o.grand_total)}</div></div>${statusPill(o.status, o.status_label)}</div>
      <div class="oc-imgs">${o.items.slice(0, 4).map((i) => `<img src="${esc(i.image)}" alt="${esc(i.name)}">`).join("")}<div style="font-size:14px;align-self:center;color:var(--ink-2)">${esc(o.items.map((i) => i.name).join(", ")).slice(0, 90)}</div></div>
      ${o.status === "payment_pending" ? `<div class="issue" style="margin-top:8px">Payment pending — tap to complete payment</div>` : o.est_delivery_to && !["delivered", "cancelled", "refunded", "returned"].includes(o.status) ? `<div style="font-size:14px;margin-top:8px">Expected by <b>${fmt.date(o.est_delivery_to)}</b></div>` : ""}
    </a>`).join("")}</div>`;
  }

  async function pageOrder(no) {
    const o = await api("GET", "/api/orders/" + encodeURIComponent(no));
    const { q } = parseHash();
    const done = o.progress.filter((s) => s.done).length;
    const terminalBad = ["cancelled", "refund_processing", "refunded", "delivery_failed", "returned", "return_requested", "return_in_progress", "cancel_requested", "payment_pending"].includes(o.status);
    const addr = o.ship_address;
    main.innerHTML = `<div class="page">
      ${q.get("placed") ? `<div class="box" style="background:var(--teal-soft);border-color:var(--teal);margin-bottom:14px"><b>${o.status === "payment_pending" ? "Order saved — payment pending" : "Thank you! Your order has been placed."}</b><div style="font-size:14px">Order number ${esc(o.order_no)}. ${o.status === "payment_pending" ? "Complete payment below to confirm it." : "You'll get updates here and in notifications."}</div></div>` : ""}
      <div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;align-items:center"><h1 style="margin:0">Order ${esc(o.order_no)}</h1>${statusPill(o.status, o.status_label)}</div>
      <div style="color:var(--ink-3);font-size:14px;margin:4px 0 14px">Placed ${fmt.datetime(o.created_at)}${o.buyer_code ? " · Buyer " + esc(o.buyer_code) : ""}</div>
      <div class="two-col"><div>
        <div class="box" style="margin-bottom:14px"><h2>Tracking</h2>
          ${!terminalBad || o.status === "delivery_failed" ? `<div class="track" role="list">${o.progress.map((s) => `<div class="st ${s.done ? "done" : ""}" role="listitem"><i>${s.done ? "✓" : ""}</i>${esc(s.label)}</div>`).join("")}
            <div class="bar" style="width:calc(${Math.max(0, done - 1) / (o.progress.length - 1)} * (100% - 24px))"></div></div>` : ""}
          ${o.est_delivery_to && !["delivered", "cancelled", "refunded", "refund_processing", "returned"].includes(o.status) ? `<p>Estimated delivery: <b>${fmt.date(o.est_delivery_from)} – ${fmt.date(o.est_delivery_to)}</b></p>` : ""}
          ${o.delivered_at ? `<p>Delivered on <b>${fmt.datetime(o.delivered_at)}</b></p>` : ""}
          ${o.tracking_no ? `<p>Courier: <b>${esc(o.courier || "—")}</b> · Tracking no. <b>${esc(o.tracking_no)}</b></p>` : ""}
          <ul class="timeline">${o.timeline.slice().reverse().map((e) => `<li class="${["cancelled", "delivery_failed"].includes(e.status) ? "alert" : ""}"><div class="tl-l">${esc(e.label)}</div>${e.note ? `<div class="tl-n">${esc(e.note)}</div>` : ""}<div class="tl-t">${fmt.datetime(e.at)}</div></li>`).join("")}</ul>
        </div>
        <div class="box"><h2>Items</h2>${o.items.map((i) => `<div class="citem"><img src="${esc(i.image)}" alt=""><div><div class="ci-name">${esc(i.name)}</div>
          <div style="font-size:14px;color:var(--ink-2)">${i.qty} × ${fmt.inr(i.unit_price)} = <b>${fmt.inr(i.line_total)}</b></div></div></div>`).join("")}</div>
      </div>
      <div class="sticky"><div class="box" style="margin-bottom:14px"><h2>Payment</h2>
        <div class="sumrow"><span>Items</span><span>${fmt.inr(o.subtotal)}</span></div>
        ${o.coupon_discount ? `<div class="sumrow"><span>Coupon ${esc(o.coupon_code || "")}</span><span class="save">− ${fmt.inr(o.coupon_discount)}</span></div>` : ""}
        <div class="sumrow"><span>Delivery</span><span>${o.delivery_charge ? fmt.inr(o.delivery_charge) : "Free"}</span></div>
        <div class="sumrow"><span>GST (included)</span><span>${fmt.inr(o.tax_total)}</span></div>
        <div class="sumrow total"><span>Total</span><span>${fmt.inr(o.grand_total)}</span></div>
        <div style="font-size:14px;margin-top:6px">Method: <b>${{ cod: "Cash on Delivery", razorpay: "Razorpay", sandbox: "Sandbox test payment", upi: "UPI" }[o.payment_method] || esc(o.payment_method)}</b> · Status: <b>${esc({ pending: o.payment_method === "cod" ? "Pay on delivery" : "Pending", paid: "Paid", failed: "Failed", refunded: "Refunded", cancelled: "Not charged" }[o.payment_status] || o.payment_status)}</b></div>
        ${o.refunds.map((r) => `<div style="font-size:14px;margin-top:6px">Refund ${fmt.inr(r.amount)}: <b>${r.status === "completed" ? "Completed" : "Processing"}</b>${r.reference ? " · Ref " + esc(r.reference) : ""}</div>`).join("")}
        ${o.upi && o.upi.status === "submitted" && o.payment_status !== "paid" ? `<div class="upi-note">⏳ UPI payment submitted (Txn ID <b>${esc(o.upi.utr)}</b>). The store is checking it and will confirm your order soon.</div>` : ""}
        ${o.upi && o.upi.status === "failed" && o.status === "payment_pending" ? `<div class="issue" style="margin-top:8px">Payment not confirmed: ${esc(o.upi.error || "")} Please pay again or submit the correct transaction ID.</div>` : ""}
        ${o.actions.can_pay ? `<button class="btn btn-primary btn-block" id="o-pay" style="margin-top:12px">${o.payment_method === "upi" ? "Pay with UPI / enter transaction ID" : "Complete payment"}</button>` : ""}
      </div>
      <div class="box" style="margin-bottom:14px"><h2>Delivery address</h2><div style="font-size:15px"><b>${esc(o.ship_name)}</b><br>${esc(addr.line1)}${addr.line2 ? ", " + esc(addr.line2) : ""}<br>${esc(addr.city)}, ${esc(addr.state)} ${esc(addr.pincode)}<br>${esc(o.ship_phone)}</div></div>
      ${o.requests.length ? `<div class="box" style="margin-bottom:14px"><h2>Requests</h2>${o.requests.map((r) => `<div style="font-size:14px;margin-bottom:6px">${r.kind === "cancel" ? "Cancellation" : "Return"}: <b>${esc(r.status)}</b>${r.resolution_note ? " — " + esc(r.resolution_note) : ""}</div>`).join("")}</div>` : ""}
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        ${o.actions.can_cancel ? `<button class="btn" id="o-cancel" style="color:#c62828">${o.actions.cancel_needs_approval ? "Request cancellation" : "Cancel order"}</button>` : ""}
        ${o.actions.can_return ? `<button class="btn" id="o-return">Request return</button>` : ""}
        <a class="btn btn-ghost" href="#/orders">All orders</a></div>
      </div></div></div>`;
    const pay = document.getElementById("o-pay");
    if (pay) pay.onclick = async () => {
      try {
        const P = S.meta.payments;
        const choice = P[o.payment_method] && P[o.payment_method].enabled ? o.payment_method : P.razorpay.enabled ? "razorpay" : "sandbox";
        const p = await api("POST", `/api/orders/${o.order_no}/pay`, { method: choice });
        await runPayment(o.order_no, p);
      } catch (e) { toast(e.message, "err"); }
    };
    const c = document.getElementById("o-cancel");
    if (c) c.onclick = async () => {
      const reason = await promptDialog(o.actions.cancel_needs_approval ? "Request cancellation" : "Cancel order", "Reason for cancelling", { confirmLabel: o.actions.cancel_needs_approval ? "Send request" : "Cancel order", placeholder: "e.g. Ordered by mistake" });
      if (!reason) return;
      try { await api("POST", `/api/orders/${o.order_no}/cancel`, { reason }); toast(o.actions.cancel_needs_approval ? "Cancellation requested" : "Order cancelled"); route(); } catch (e) { toast(e.message, "err"); }
    };
    const rt = document.getElementById("o-return");
    if (rt) rt.onclick = async () => {
      const reason = await promptDialog("Request return", "Why are you returning this order?", { confirmLabel: "Request return", textarea: true, placeholder: "e.g. Wrong size, damaged item" });
      if (!reason) return;
      try { await api("POST", `/api/orders/${o.order_no}/return`, { reason }); toast("Return requested"); route(); } catch (e) { toast(e.message, "err"); }
    };
  }

  // ------------------------------------------------------------------ wishlist / account / auth
  async function pageWishlist() {
    const r = await api("GET", "/api/wishlist");
    S.wish = new Set(r.items.map((i) => i.id));
    main.innerHTML = r.items.length ? `<div class="page"><h1>Wishlist (${r.items.length})</h1><div class="grid">${r.items.map(card).join("")}</div></div>` :
      `<div class="empty"><div class="ico">♡</div><h3>Your wishlist is empty</h3><p>Tap the heart on any product to save it for later.</p><a class="btn btn-primary" href="#/">Discover products</a></div>`;
    bindCards(main);
    main.querySelectorAll("[data-wish]").forEach((b) => (b.onclick = async () => { await toggleWish(+b.dataset.wish); pageWishlist(); }));
  }

  async function pageAccount() {
    const u = S.me;
    const addrs = await api("GET", "/api/account/addresses");
    main.innerHTML = `<div class="acct-head"><div class="av">${esc(u.name[0] || "?")}</div><div><div style="font-size:20px;font-weight:700">${esc(u.name)}</div>
      <div style="opacity:.85;font-size:14px">${esc(u.email || "")}${u.phone ? " · " + esc(u.phone) : ""}</div>
      ${u.buyer ? `<div style="margin-top:4px"><span class="pill" style="background:rgba(255,255,255,.15);color:#fff">Buyer code ${esc(u.buyer.code)}</span></div>` : `<div style="font-size:13px;opacity:.8;margin-top:4px">No unit buyer code linked — ask the store to link yours.</div>`}</div></div>
      <div class="page"><div class="two-col"><div>
        <div class="box" style="margin-bottom:14px"><div class="menu-list">
          <a href="#/orders">📦 My orders <span>›</span></a><a href="#/wishlist">♡ Wishlist <span>›</span></a>
          <a href="#/notifications">🔔 Notifications ${S.counts.notifications ? `<span class="pill bad">${S.counts.notifications}</span>` : "<span>›</span>"}</a>
          <button id="edit-prof">✎ Edit profile <span>›</span></button><button id="chg-pw">🔒 Change password <span>›</span></button><button id="chg-lang">🌐 Language <span>›</span></button>
          <button id="logout" style="color:#c62828">⎋ Sign out</button></div></div></div>
        <div class="box"><h2>Saved addresses</h2>${addrs.items.map((a) => `<div class="addr"><b>${esc(a.name)}</b> ${a.is_default ? '<span class="pill teal">Default</span>' : ""} ${a.label ? `<span class="pill">${esc(a.label)}</span>` : ""}
          <div>${esc(a.line1)}${a.line2 ? ", " + esc(a.line2) : ""}, ${esc(a.city)}, ${esc(a.state)} ${esc(a.pincode)}</div><div style="color:var(--ink-3)">${esc(a.phone)}</div>
          <div style="display:flex;gap:14px;margin-top:6px"><button class="btn-link" data-ed="${a.id}">Edit</button><button class="btn-link" style="color:#c62828" data-del="${a.id}">Delete</button></div></div>`).join("") || `<div class="empty-sm">No saved addresses.</div>`}
          <button class="btn btn-sm" id="new-addr">+ Add address</button></div></div></div>`;
    document.getElementById("logout").onclick = logout;
    document.getElementById("new-addr").onclick = async () => { if (await addressDialog()) { toast("Address saved"); pageAccount(); } };
    main.querySelectorAll("[data-ed]").forEach((b) => (b.onclick = async () => { if (await addressDialog(addrs.items.find((a) => a.id == b.dataset.ed))) { toast("Address updated"); pageAccount(); } }));
    main.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      if (!(await confirmDialog("Delete address", "Delete this saved address?", { confirmLabel: "Delete", danger: true }))) return;
      await api("DELETE", "/api/account/addresses/" + b.dataset.del); toast("Address deleted"); pageAccount();
    }));
    document.getElementById("edit-prof").onclick = async () => {
      const ok = await modal({ title: "Edit profile", body: `<label class="fld"><span>Name</span><input id="p-n" value="${esc(u.name)}"></label><label class="fld"><span>Phone</span><input id="p-p" value="${esc(u.phone || "")}"></label>`,
        actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Save", cls: "btn-primary", handler: (el) => api("PUT", "/api/account/profile", { name: el.querySelector("#p-n").value, phone: el.querySelector("#p-p").value }) }] });
      if (ok) { await refreshMe(); toast("Profile updated"); pageAccount(); }
    };
    document.getElementById("chg-pw").onclick = () => passwordDialog();
    document.getElementById("chg-lang").onclick = () => NCI18N.dialog();
  }

  function passwordDialog() {
    return modal({ title: "Change password", body: `<label class="fld"><span>Current password</span><input type="password" id="pw-c" autocomplete="current-password"></label>
      <label class="fld"><span>New password</span><input type="password" id="pw-n" autocomplete="new-password"><small>At least 8 characters with letters and numbers.</small></label>`,
      actions: [{ label: "Cancel", cls: "btn-ghost" }, { label: "Update password", cls: "btn-primary", handler: async (el) => {
        await api("POST", "/api/auth/password", { current: el.querySelector("#pw-c").value, new: el.querySelector("#pw-n").value }); toast("Password updated");
      } }] });
  }

  async function pageNotifications() {
    const r = await api("GET", "/api/notifications");
    main.innerHTML = `<div class="page"><h1>Notifications</h1>${r.items.map((n) => `<div class="notif ${n.is_read ? "" : "unread"}"><b>${esc(n.title)}</b><div style="font-size:15px">${esc(n.body || "")}</div>
      <div style="font-size:13px;color:var(--ink-3)">${fmt.datetime(n.created_at)} ${n.link ? `· <a href="${esc(n.link)}" style="color:var(--teal)">View</a>` : ""}</div></div>`).join("") || `<div class="empty"><div class="ico">🔔</div><h3>No notifications</h3><p>Order and delivery updates will appear here.</p></div>`}</div>`;
    if (r.items.some((n) => !n.is_read)) { await api("POST", "/api/notifications/read"); S.counts.notifications = 0; paintCounts(); }
  }

  function pageAuth(mode, next, usePassword) {
    if (S.me) { location.hash = next || "#/account"; return; }
    const reg = mode === "register";
    const gid = S.meta.google_client_id;
    const go = () => { location.hash = next && next.startsWith("#/") ? next : "#/"; };
    const swap = `${reg ? `Already have an account? <a href="#/login${next ? "?next=" + encodeURIComponent(next) : ""}" style="color:var(--teal);font-weight:600">Sign in</a>`
      : `New here? Just enter your email above — we'll create your account.`}`;
    main.innerHTML = `<div class="auth"><div style="margin-bottom:14px"><label style="display:block;font-size:14px;font-weight:600;color:var(--ink-2);margin-bottom:6px">🌐 Language</label>${NCI18N.selectHtml("lang-sel")}</div><h1>${reg ? "Create your account" : "Sign in"}</h1>
      <p class="muted">${reg ? "Register to order, track deliveries and save a wishlist." : "Welcome to " + esc(S.meta.store.store_name)}</p>
      ${gid ? `<div class="g-wrap"><div id="g-btn"></div><div class="issue" id="g-err" role="alert" hidden></div></div>
        <div class="or-line"><span>or use your email</span></div>` : ""}
      <div id="auth-box"></div>
      <p style="text-align:center;margin-top:16px;font-size:15px">${swap}</p>
      <p style="text-align:center;font-size:13px;color:var(--ink-3)">Staff and owner: <a href="/admin" style="color:var(--teal)">admin sign-in</a></p></div>`;
    NCI18N.bindSelect(document.getElementById("lang-sel"));
    const box = document.getElementById("auth-box");
    let email = "", resendTimer = null;

    const finish = async (r) => {
      await refreshMe();
      toast(r.created ? "Account created — welcome!" : "Signed in");
      go();
    };
    const busy = (btn, on, label) => { btn.disabled = on; if (label) btn.textContent = label; };
    const showErr = (id, msg) => { const e = document.getElementById(id); e.textContent = msg; e.hidden = !msg; };

    function stepEmail() {
      clearInterval(resendTimer);
      box.innerHTML = `<form id="otp-e" novalidate>
        <label class="fld"><span>Email address</span><input name="email" type="email" inputmode="email" required autocomplete="email" value="${esc(email)}" placeholder="you@gmail.com"></label>
        <div class="issue" id="e-err" role="alert" hidden></div>
        <button class="btn btn-primary btn-block" style="min-height:50px;margin-top:6px">Send code</button>
        <p class="muted" style="font-size:13px;text-align:center;margin-top:10px">We'll email you a 6-digit code. No password needed.</p></form>
        <p style="text-align:center;font-size:14px;margin-top:4px"><a href="#" id="to-pw" style="color:var(--ink-2)">Sign in with a password instead</a></p>`;
      const f = document.getElementById("otp-e");
      f.email.focus();
      document.getElementById("to-pw").onclick = (e) => { e.preventDefault(); stepPassword(); };
      f.onsubmit = async (e) => {
        e.preventDefault();
        const btn = f.querySelector("button"); showErr("e-err", "");
        email = f.email.value.trim().toLowerCase();
        busy(btn, true, "Sending…");
        try { await api("POST", "/api/auth/otp/request", { email }); stepCode(); }
        catch (ex) { showErr("e-err", ex.message); busy(btn, false, "Send code"); }
      };
    }

    function stepCode(needName) {
      box.innerHTML = `<form id="otp-c" novalidate>
        <p style="margin:0 0 12px">We sent a 6-digit code to <b>${esc(email)}</b>. <a href="#" id="chg" style="color:var(--teal)">Change</a></p>
        <label class="fld"><span>Enter code</span><input name="code" class="otp-in" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]*" required placeholder="••••••"></label>
        <div id="new-fields" ${needName ? "" : "hidden"}>
          <p class="muted" style="margin:4px 0 10px">New here — tell us your name to finish creating your account.</p>
          <label class="fld"><span>Full name</span><input name="name" autocomplete="name"></label>
          <label class="fld"><span>Mobile number (optional)</span><input name="phone" inputmode="tel" autocomplete="tel"></label></div>
        <div class="issue" id="c-err" role="alert" hidden></div>
        <button class="btn btn-primary btn-block" style="min-height:50px;margin-top:6px">${needName ? "Create account" : "Verify & sign in"}</button>
        <p style="text-align:center;font-size:14px;margin-top:12px"><button type="button" class="linkbtn" id="resend" disabled>Resend code</button></p>
        <p class="muted" style="font-size:13px;text-align:center">Can't find it? Check your Spam or Promotions folder.</p></form>`;
      const f = document.getElementById("otp-c");
      const resend = document.getElementById("resend");
      (needName ? f.name : f.code).focus();
      document.getElementById("chg").onclick = (e) => { e.preventDefault(); stepEmail(); };
      let wait = 45;
      const tick = () => { if (!document.body.contains(resend)) return clearInterval(resendTimer);
        resend.disabled = wait > 0; resend.textContent = wait > 0 ? `Resend code in ${wait}s` : "Resend code"; wait--; if (wait < -1) clearInterval(resendTimer); };
      clearInterval(resendTimer); tick(); resendTimer = setInterval(tick, 1000);
      resend.onclick = async () => {
        showErr("c-err", ""); resend.disabled = true;
        try { await api("POST", "/api/auth/otp/request", { email }); toast("New code sent"); f.code.value = ""; wait = 45; clearInterval(resendTimer); tick(); resendTimer = setInterval(tick, 1000); }
        catch (ex) { showErr("c-err", ex.message); resend.disabled = false; }
      };
      f.code.oninput = () => {
        f.code.value = f.code.value.replace(/\D/g, "").slice(0, 6);
        if (f.code.value.length === 6 && document.getElementById("new-fields").hidden) f.requestSubmit();
      };
      f.onsubmit = async (e) => {
        e.preventDefault();
        const btn = f.querySelector("button[type=submit], button:not([type])"); showErr("c-err", "");
        const body = { email, code: f.code.value };
        if (!document.getElementById("new-fields").hidden) {
          body.name = f.name.value.trim(); body.phone = f.phone.value.trim();
          if (body.name.length < 2) { showErr("c-err", "Please enter your full name."); f.name.focus(); return; }
        }
        const label = btn.textContent; busy(btn, true, "Checking…");
        try {
          const r = await api("POST", "/api/auth/otp/verify", body);
          if (r.need_name) {
            document.getElementById("new-fields").hidden = false; f.name.focus();
            busy(btn, false, "Create account"); return;
          }
          clearInterval(resendTimer); await finish(r);
        } catch (ex) { showErr("c-err", ex.message); busy(btn, false, label); }
      };
    }

    function stepPassword() {
      clearInterval(resendTimer);
      box.innerHTML = `<form id="auth-f" novalidate>
        <label class="fld"><span>Email or phone</span><input name="email" required autocomplete="username" value="${esc(email)}"></label>
        <label class="fld"><span>Password</span><input name="password" type="password" required autocomplete="current-password"></label>
        <div class="issue" id="auth-err" role="alert" hidden></div>
        <button class="btn btn-primary btn-block" style="min-height:50px;margin-top:6px">Sign in</button></form>
        <p style="text-align:center;font-size:14px;margin-top:8px"><a href="#" id="to-otp" style="color:var(--teal);font-weight:600">Sign in with an email code instead</a></p>`;
      document.getElementById("to-otp").onclick = (e) => { e.preventDefault(); stepEmail(); };
      const f = document.getElementById("auth-f");
      f.onsubmit = async (e) => {
        e.preventDefault();
        const btn = f.querySelector("button"); showErr("auth-err", ""); busy(btn, true);
        try { const r = await api("POST", "/api/auth/login", formData(f)); await finish(r); }
        catch (ex) { showErr("auth-err", ex.message); busy(btn, false); }
      };
    }

    usePassword ? stepPassword() : stepEmail();
    if (gid) setupGoogle(gid, next);
  }

  async function setupGoogle(clientId, next) {
    const box = document.getElementById("g-btn"), err = document.getElementById("g-err");
    try { await loadScript("https://accounts.google.com/gsi/client"); }
    catch { err.textContent = "Google sign-in could not load. Use your email instead."; err.hidden = false; return; }
    if (!document.body.contains(box) || !window.google?.accounts?.id) return;
    google.accounts.id.initialize({
      client_id: clientId, ux_mode: "popup", auto_select: false,
      callback: async (resp) => {
        err.hidden = true;
        try {
          const r = await api("POST", "/api/auth/google", { credential: resp.credential });
          await refreshMe();
          toast(r.created ? "Account created with Google — welcome!" : "Signed in with Google");
          location.hash = next && next.startsWith("#/") ? next : "#/";
        } catch (ex) { err.textContent = ex.message; err.hidden = false; }
      },
    });
    google.accounts.id.renderButton(box, { theme: "outline", size: "large", shape: "pill", text: "continue_with", width: Math.min(box.clientWidth || 320, 400), logo_alignment: "center" });
  }

  function pagePolicy(k) {
    const st = S.meta.store;
    const map = { returns: ["Returns & refunds", st.policy_returns + ` Return window: ${st.return_window_days} days from delivery.`], shipping: ["Shipping", st.policy_shipping], privacy: ["Privacy", st.policy_privacy] };
    const [t, b] = map[k] || ["Policy", "Not found."];
    main.innerHTML = `<div class="page" style="max-width:760px"><h1>${esc(t)}</h1><p style="white-space:pre-line">${esc(b)}</p><p>Questions? Contact <a href="mailto:${esc(st.support_email)}" style="color:var(--teal)">${esc(st.support_email)}</a>.</p></div>`;
  }

  boot();
})();
