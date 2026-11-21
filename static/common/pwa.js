// Installable app support: registers the service worker and shows an "Install app" button
// on computers (in the header), phones and tablets (a floating button). It disappears once the app is installed.
(function () {
  if ("serviceWorker" in navigator) window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  if (standalone) return;
  var deferred = null;
  var APP = (document.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content || "PVC Paltan";
  var ua = navigator.userAgent || "";

  var css = ".pwa-install{display:none;align-items:center;gap:8px;font:700 14px/1 system-ui,sans-serif;color:#1d2433;background:#e2b93b;border:0;border-radius:10px;padding:10px 14px;cursor:pointer;white-space:nowrap}" +
    ".pwa-install:hover{background:#f0c94e}.pwa-install:focus-visible{outline:3px solid #fff;outline-offset:2px}" +
    ".pwa-head{margin-right:8px}" +
    ".pwa-float{display:inline-flex;position:fixed;right:max(12px,env(safe-area-inset-right,0px));bottom:max(16px,env(safe-area-inset-bottom,0px));z-index:60;box-shadow:0 6px 20px rgba(0,0,0,.3);border-radius:99px;padding:12px 18px}" +
    ".pwa-float.pwa-above-nav{bottom:calc(84px + env(safe-area-inset-bottom,0px))}" +
    "@media (min-width:960px){.pwa-head{display:inline-flex}.pwa-float.pwa-small{display:none}}" +
    ".pwa-ov{position:fixed;inset:0;z-index:200;background:rgba(15,20,10,.55);display:flex;align-items:center;justify-content:center;padding:16px}" +
    ".pwa-dlg{background:#fff;color:#1d2433;border-radius:16px;max-width:460px;width:100%;max-height:100%;overflow:auto;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,.35);font:400 15px/1.5 system-ui,sans-serif}" +
    ".pwa-dlg h2{margin:0 0 4px;font:800 20px/1.2 system-ui,sans-serif}.pwa-dlg p{margin:0 0 12px;color:#4a4e60}" +
    ".pwa-dlg ol{margin:0 0 14px;padding-left:22px}.pwa-dlg li{margin:6px 0}.pwa-dlg small{display:block;color:#667;margin-bottom:14px}" +
    ".pwa-dlg button{background:#4f6128;color:#fff;border:0;border-radius:10px;padding:11px 20px;font:700 15px system-ui,sans-serif;cursor:pointer}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  function steps() {
    var ios = /iphone|ipad|ipod/i.test(ua) || (/macintosh/i.test(ua) && navigator.maxTouchPoints > 1);
    var android = /android/i.test(ua);
    var edge = /edg\//i.test(ua), opera = /opr\//i.test(ua), samsung = /samsungbrowser/i.test(ua);
    var chrome = /chrome|crios/i.test(ua) && !edge && !opera && !samsung;
    var safari = /safari/i.test(ua) && !/chrome|crios|chromium|android/i.test(ua), firefox = /firefox|fxios/i.test(ua);
    if (ios) return ["Tap the <b>Share</b> button (a square with an arrow). It is at the bottom of the screen in Safari, or at the top right on an iPad.", "Scroll down and tap <b>Add to Home Screen</b>.", "Tap <b>Add</b>."];
    if (android && samsung) return ["Tap the menu (three lines) at the bottom.", "Tap <b>Add page to</b>, then <b>Home screen</b>.", "Tap <b>Add</b>."];
    if (android && firefox) return ["Tap the menu (three dots).", "Tap <b>Install</b>.", "Tap <b>Add</b>."];
    if (android) return ["Tap the menu (three dots) at the top right.", "Tap <b>Install app</b> (or <b>Add to Home screen</b>).", "Tap <b>Install</b>."];
    if (edge) return ["Click the menu (three dots) at the top right.", "Choose <b>Apps</b>, then <b>Install this site as an app</b>.", "Click <b>Install</b>."];
    if (chrome) return ["Look at the right end of the address bar and click the <b>install icon</b> (a small screen with a down arrow).", "If you do not see it, open the menu (three dots), choose <b>Cast, save and share</b>, then <b>Install page as app</b>.", "Click <b>Install</b>."];
    if (safari) return ["Open the <b>File</b> menu at the top of the screen.", "Choose <b>Add to Dock</b> (needs macOS Sonoma or newer).", "Click <b>Add</b>."];
    if (firefox) return ["Firefox on a computer cannot install apps.", "Open this page in <b>Chrome</b> or <b>Edge</b>, then use the install button there."];
    return ["Open this page in <b>Chrome</b> or <b>Edge</b>.", "Use the install icon in the address bar, or the browser menu."];
  }
  function dialog() {
    if (document.getElementById("pwa-ov")) return;
    var o = document.createElement("div"); o.id = "pwa-ov"; o.className = "pwa-ov"; o.setAttribute("role", "dialog"); o.setAttribute("aria-modal", "true"); o.setAttribute("aria-label", "Install " + APP);
    o.innerHTML = '<div class="pwa-dlg"><h2>Install ' + APP + '</h2><p>Open the store like an app, straight from your home screen, desktop or Start menu.</p><ol>' +
      steps().map(function (s) { return "<li>" + s + "</li>"; }).join("") + '</ol><small>Already installed? Open it from your home screen, Start menu, Launchpad or desktop.</small><button id="pwa-ok">Got it</button></div>';
    function close() { o.remove(); document.removeEventListener("keydown", esc); }
    function esc(e) { if (e.key === "Escape") close(); }
    o.addEventListener("click", function (e) { if (e.target === o) close(); });
    document.addEventListener("keydown", esc);
    document.body.appendChild(o);
    document.getElementById("pwa-ok").onclick = close; document.getElementById("pwa-ok").focus();
  }
  function install() {
    if (!deferred) return dialog();
    var d = deferred; deferred = null;
    d.prompt();
    d.userChoice.then(function (c) { if (c && c.outcome === "accepted") removeButtons(); }, function () {});
  }
  function removeButtons() { [].forEach.call(document.querySelectorAll(".pwa-install"), function (b) { b.remove(); }); }
  function make(cls) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "pwa-install " + cls; b.setAttribute("aria-label", "Install " + APP + " app");
    b.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0-5-5m5 5 5-5"/><path d="M4 20h16"/></svg><span>Install app</span>';
    b.onclick = install;
    return b;
  }
  function addButtons() {
    if (document.querySelector(".pwa-install")) return;
    var host = document.querySelector(".top-actions");
    if (host) host.insertBefore(make("pwa-head"), host.firstChild);       // computers: in the header
    var f = make("pwa-float" + (host ? " pwa-small" : ""));                  // phones and tablets: floating button
    if (document.querySelector(".bottom-nav")) f.className += " pwa-above-nav";
    document.body.appendChild(f);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addButtons); else addButtons();
  window.addEventListener("appinstalled", removeButtons);
  window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); deferred = e; });
})();
