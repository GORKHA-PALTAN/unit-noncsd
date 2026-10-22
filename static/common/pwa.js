// Registers the service worker and offers an "Install app" banner (Android/Chrome) or a hint (iPhone).
(function () {
  if ("serviceWorker" in navigator) window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  var KEY = "pwa-dismissed", dismissed = false, deferred = null;
  try { dismissed = localStorage.getItem(KEY) === "1"; } catch (e) {}
  var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;
  if (standalone || dismissed) return;
  function banner(text, withButton) {
    if (document.getElementById("pwa-bar")) return;
    var d = document.createElement("div");
    d.id = "pwa-bar";
    d.setAttribute("style", "position:fixed;left:12px;right:12px;bottom:78px;z-index:60;background:#2b3047;color:#fff;border-radius:14px;padding:12px 14px;display:flex;align-items:center;gap:12px;box-shadow:0 8px 24px rgba(0,0,0,.28);font:600 15px/1.3 system-ui,sans-serif");
    d.innerHTML = '<img src="/static/common/pwa-192.png" alt="" width="40" height="40" style="border-radius:10px"><span style="flex:1">' + text + '</span>' +
      (withButton ? '<button id="pwa-go" style="background:#1f8f8a;color:#fff;border:0;border-radius:9px;padding:9px 14px;font:700 14px system-ui">Install</button>' : "") +
      '<button id="pwa-x" aria-label="Close" style="background:none;border:0;color:#cfd3e6;font-size:20px;padding:2px 6px">✕</button>';
    document.body.appendChild(d);
    document.getElementById("pwa-x").onclick = function () { d.remove(); try { localStorage.setItem(KEY, "1"); } catch (e) {} };
    var go = document.getElementById("pwa-go");
    if (go) go.onclick = function () { if (deferred) { deferred.prompt(); deferred.userChoice.finally(function () { d.remove(); }); } };
  }
  window.addEventListener("beforeinstallprompt", function (e) { e.preventDefault(); deferred = e; banner("Install the " + ((document.querySelector('meta[name="apple-mobile-web-app-title"]') || {}).content || "PVC Paltan") + " app", true); });
  var ua = navigator.userAgent || "";
  if (/iphone|ipad|ipod/i.test(ua) && !/crios|fxios/i.test(ua)) setTimeout(function () { banner("Install: tap <b>Share</b> then <b>Add to Home Screen</b>", false); }, 4000);
})();
