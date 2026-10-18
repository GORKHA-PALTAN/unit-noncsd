/* Shared browser helpers for the store and admin apps. No secrets live here: all checks happen on the server. */
(function () {
  const state = { csrf: null };

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function api(method, url, body, opts = {}) {
    const headers = { "X-Requested-With": "fetch" };
    if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
    let payload;
    if (body instanceof FormData) payload = body;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    let res;
    try {
      res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
    } catch (e) {
      const err = new Error("Network error — check your connection and try again."); err.status = 0; throw err;
    }
    if (opts.raw) return res;
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      const err = new Error(data.error || `Request failed (${res.status})`);
      err.status = res.status; err.data = data; throw err;
    }
    return data;
  }

  const fmt = {
    inr(n, dec) {
      const v = Number(n || 0);
      const d = dec ?? (Math.abs(v % 1) > 0.001 ? 2 : 0);
      return "₹" + v.toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
    },
    compact(n) {
      const v = Number(n || 0);
      if (Math.abs(v) >= 1e7) return "₹" + (v / 1e7).toFixed(2) + " Cr";
      if (Math.abs(v) >= 1e5) return "₹" + (v / 1e5).toFixed(2) + " L";
      if (Math.abs(v) >= 1e3) return "₹" + (v / 1e3).toFixed(1) + "K";
      return "₹" + v.toFixed(0);
    },
    num(n) { return Number(n || 0).toLocaleString("en-IN"); },
    date(s) {
      if (!s) return "—";
      const d = s.length > 10 ? new Date(s.endsWith("Z") ? s : s + "Z") : new Date(s + "T00:00:00");
      return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    },
    datetime(s) {
      if (!s) return "—";
      const d = new Date(s.endsWith("Z") ? s : s + "Z");
      return d.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
    },
    short(s) {
      if (!s) return "";
      const d = new Date(s + (s.length <= 10 ? "T00:00:00" : "Z"));
      return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
    },
    pct(n) { return n === null || n === undefined ? "—" : (n > 0 ? "+" : "") + Number(n).toFixed(1).replace(/\.0$/, "") + "%"; },
  };

  // ---------- toasts ----------
  function toast(msg, kind = "ok") {
    let host = document.getElementById("toasts");
    if (!host) { host = document.createElement("div"); host.id = "toasts"; host.setAttribute("aria-live", "polite"); document.body.appendChild(host); }
    const t = document.createElement("div");
    t.className = "toast toast-" + kind;
    t.setAttribute("role", kind === "err" ? "alert" : "status");
    t.innerHTML = `<span class="toast-ico">${kind === "err" ? "!" : kind === "warn" ? "!" : "✓"}</span><span>${esc(msg)}</span>`;
    host.appendChild(t);
    setTimeout(() => t.classList.add("out"), 3800);
    setTimeout(() => t.remove(), 4300);
  }

  // ---------- modal dialogs ----------
  function modal({ title, body, actions = [], wide = false, onOpen }) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "modal-wrap";
      wrap.innerHTML = `<div class="modal ${wide ? "modal-wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="mdl-t">
        <div class="modal-head"><h2 id="mdl-t">${esc(title)}</h2><button class="icon-btn modal-x" aria-label="Close">✕</button></div>
        <div class="modal-body"></div>
        <div class="modal-foot"></div></div>`;
      const bodyEl = wrap.querySelector(".modal-body");
      if (typeof body === "string") bodyEl.innerHTML = body; else if (body) bodyEl.appendChild(body);
      const foot = wrap.querySelector(".modal-foot");
      const close = (v) => { wrap.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      actions.forEach((a) => {
        const b = document.createElement("button");
        b.className = "btn " + (a.cls || "");
        b.textContent = a.label;
        b.onclick = async () => {
          if (a.handler) {
            b.disabled = true; const old = b.textContent; b.innerHTML = `<span class="spin"></span>${esc(old)}`;
            try { const r = await a.handler(bodyEl); if (r !== false) close(r === undefined ? a.value : r); }
            catch (e) { toast(e.message, "err"); }
            finally { b.disabled = false; b.textContent = old; }
          } else close(a.value);
        };
        foot.appendChild(b);
      });
      if (!actions.length) foot.remove();
      wrap.querySelector(".modal-x").onclick = () => close(null);
      wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) close(null); });
      const onKey = (e) => { if (e.key === "Escape") close(null); };
      document.addEventListener("keydown", onKey);
      document.body.appendChild(wrap);
      if (onOpen) onOpen(bodyEl, close);
      const first = wrap.querySelector("input,select,textarea,button.btn");
      if (first) setTimeout(() => first.focus(), 30);
    });
  }

  function confirmDialog(title, message, { confirmLabel = "Confirm", danger = false, requireText } = {}) {
    const body = `<p>${esc(message)}</p>${requireText ? `<label class="fld"><span>Type <b>${esc(requireText)}</b> to confirm</span><input id="cf-txt" autocomplete="off"></label>` : ""}`;
    return modal({
      title, body,
      actions: [
        { label: "Cancel", cls: "btn-ghost", value: false },
        { label: confirmLabel, cls: danger ? "btn-danger" : "btn-primary", handler: (el) => {
            if (requireText && el.querySelector("#cf-txt").value !== requireText) { toast(`Type ${requireText} to confirm`, "err"); return false; }
            return true;
          } },
      ],
    });
  }

  function promptDialog(title, label, { placeholder = "", confirmLabel = "Submit", textarea = false, required = true } = {}) {
    const body = `<label class="fld"><span>${esc(label)}</span>${textarea ? `<textarea id="pd-v" rows="3" placeholder="${esc(placeholder)}"></textarea>` : `<input id="pd-v" placeholder="${esc(placeholder)}">`}</label>`;
    return modal({
      title, body,
      actions: [{ label: "Cancel", cls: "btn-ghost", value: null },
        { label: confirmLabel, cls: "btn-primary", handler: (el) => {
          const v = el.querySelector("#pd-v").value.trim();
          if (required && !v) { toast("Please fill this in", "err"); return false; }
          return v;
        } }],
    });
  }

  function formData(form) {
    const out = {};
    form.querySelectorAll("[name]").forEach((el) => {
      if (el.type === "checkbox") out[el.name] = el.checked;
      else if (el.type === "radio") { if (el.checked) out[el.name] = el.value; }
      else out[el.name] = el.value;
    });
    return out;
  }

  function debounce(fn, ms = 300) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

  function stars(r) {
    const full = Math.round(Number(r || 0) * 2) / 2;
    return `<span class="stars" aria-label="${Number(r || 0).toFixed(1)} out of 5">${"★".repeat(Math.floor(full))}${full % 1 ? "½" : ""}</span>`;
  }

  window.NC = { state, esc, api, fmt, toast, modal, confirmDialog, promptDialog, formData, debounce, stars };
})();
