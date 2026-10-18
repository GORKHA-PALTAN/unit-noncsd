/* Minimal accessible SVG charts (no external libraries): line/area with crosshair tooltip,
   forecast (recorded history solid, estimate dashed with range band), horizontal bars, column bars. */
(function () {
  const S = {
    s1: "#2a78d6", s2: "#eb6834", s3: "#1baf7a", s4: "#eda100", s5: "#e87ba4", s6: "#008300", s7: "#6250d6", s8: "#e34948",
    grid: "#e6e7ec", axis: "#8a8d99", ink: "#1d1f2b", ink2: "#52514e",
  };
  const esc = (v) => NC.esc(v);

  function niceMax(v) {
    if (v <= 0) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  }

  function tooltip(host) {
    let tip = host.querySelector(".viz-tip");
    if (!tip) { tip = document.createElement("div"); tip.className = "viz-tip"; tip.hidden = true; host.appendChild(tip); }
    return tip;
  }

  /* series: [{name, color, points:[{x:label, y:number}], dashed, band:[{lo,hi}]}] ; all share x labels */
  function line(host, { labels, series, yFmt = (v) => v, height = 240, xFmt = (l) => l, area = false, splitIndex = null, splitLabel = "" }) {
    host.classList.add("viz-root");
    const W = Math.max(host.clientWidth || 600, 280), H = height;
    const m = { l: 56, r: 14, t: 14, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const all = series.flatMap((s) => s.points.map((p) => (s.band ? Math.max(p.y ?? 0, p.hi ?? 0) : p.y ?? 0)));
    const ymax = niceMax(Math.max(...all, 0) * 1.05);
    const n = labels.length;
    const x = (i) => m.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw);
    const y = (v) => m.t + ih - (v / ymax) * ih;
    let g = "";
    for (let k = 0; k <= 4; k++) {
      const v = (ymax / 4) * k, yy = y(v);
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}" stroke="${S.grid}" stroke-width="1"/>`;
      g += `<text x="${m.l - 8}" y="${yy + 4}" text-anchor="end" class="viz-ax">${esc(yFmt(v))}</text>`;
    }
    const step = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / 70))));
    for (let i = 0; i < n; i += step) g += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle" class="viz-ax">${esc(xFmt(labels[i]))}</text>`;
    if (splitIndex !== null && splitIndex >= 0 && splitIndex < n) {
      const sx = x(splitIndex);
      g += `<rect x="${sx}" y="${m.t}" width="${W - m.r - sx}" height="${ih}" fill="#f4f5f8"/>`;
      g += `<line x1="${sx}" x2="${sx}" y1="${m.t}" y2="${m.t + ih}" stroke="${S.axis}" stroke-dasharray="3 3"/>`;
      g += `<text x="${sx + 6}" y="${m.t + 12}" class="viz-ax viz-strong">${esc(splitLabel)}</text>`;
    }
    series.forEach((s) => {
      if (s.band) {
        const pts = s.points.map((p, i) => (p.hi == null ? null : [x(i), y(p.hi)])).filter(Boolean);
        const low = s.points.map((p, i) => (p.lo == null ? null : [x(i), y(p.lo)])).filter(Boolean).reverse();
        if (pts.length) g += `<path d="M${pts.concat(low).map((p) => p.join(",")).join("L")}Z" fill="${s.color}" opacity=".14"/>`;
      }
    });
    series.forEach((s) => {
      const segs = [];
      let cur = [];
      s.points.forEach((p, i) => { if (p.y == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push([x(i), y(p.y)]); });
      if (cur.length) segs.push(cur);
      segs.forEach((seg) => {
        if (area && !s.dashed && seg.length > 1) g += `<path d="M${seg[0][0]},${y(0)}L${seg.map((p) => p.join(",")).join("L")}L${seg[seg.length - 1][0]},${y(0)}Z" fill="${s.color}" opacity=".10"/>`;
        g += `<path d="M${seg.map((p) => p.join(",")).join("L")}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" ${s.dashed ? 'stroke-dasharray="6 4"' : ""}/>`;
      });
    });
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))} chart">${g}
      <line class="viz-cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="${S.axis}" stroke-width="1" visibility="hidden"/>
      <g class="viz-dots"></g><rect class="viz-hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    const svg = host.querySelector("svg");
    const tip = tooltip(host);
    const cross = svg.querySelector(".viz-cross");
    const dots = svg.querySelector(".viz-dots");
    const hit = svg.querySelector(".viz-hit");
    function show(evt) {
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      let rows = "", d = "";
      series.forEach((s) => {
        const p = s.points[i];
        if (!p || p.y == null) return;
        d += `<circle cx="${x(i)}" cy="${y(p.y)}" r="4.5" fill="${s.color}" stroke="#fff" stroke-width="2"/>`;
        rows += `<div class="viz-tip-row"><i style="background:${s.color}"></i>${esc(s.name)}<b>${esc(yFmt(p.y))}</b></div>`;
        if (s.band && p.lo != null) rows += `<div class="viz-tip-sub">Range ${esc(yFmt(p.lo))} – ${esc(yFmt(p.hi))}</div>`;
      });
      dots.innerHTML = d;
      tip.innerHTML = `<div class="viz-tip-h">${esc(xFmt(labels[i], true))}</div>${rows}`;
      tip.hidden = false;
      const left = (x(i) / W) * r.width;
      tip.style.left = Math.min(Math.max(left + 12, 0), r.width - 190) + "px";
      tip.style.top = "8px";
    }
    hit.addEventListener("mousemove", show);
    hit.addEventListener("touchstart", (e) => show(e.touches[0]), { passive: true });
    hit.addEventListener("mouseleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); dots.innerHTML = ""; });
  }

  /* rows: [{label, value, sub}] horizontal bars, single hue */
  function hbars(host, rows, { fmt = (v) => v, color = S.s1, max = null, onClick } = {}) {
    host.classList.add("viz-root");
    if (!rows.length) { host.innerHTML = `<div class="empty-sm">No data for this period.</div>`; return; }
    const mx = max || Math.max(...rows.map((r) => r.value), 1);
    host.innerHTML = `<div class="hbars">${rows.map((r, i) => `
      <div class="hbar ${onClick ? "clickable" : ""}" data-i="${i}" title="${esc(r.label)}: ${esc(fmt(r.value))}">
        <div class="hbar-l">${esc(r.label)}${r.sub ? `<small>${esc(r.sub)}</small>` : ""}</div>
        <div class="hbar-track"><div class="hbar-fill" style="width:${Math.max(1.5, (r.value / mx) * 100)}%;background:${r.color || color}"></div></div>
        <div class="hbar-v">${esc(fmt(r.value))}</div></div>`).join("")}</div>`;
    if (onClick) host.querySelectorAll(".hbar").forEach((el) => (el.onclick = () => onClick(rows[+el.dataset.i])));
  }

  /* columns: [{label, value}] */
  function columns(host, rows, { fmt = (v) => v, color = S.s1, height = 180 } = {}) {
    host.classList.add("viz-root");
    if (!rows.length) { host.innerHTML = `<div class="empty-sm">No data.</div>`; return; }
    const W = Math.max(host.clientWidth || 400, 260), H = height, m = { l: 8, r: 8, t: 18, b: 24 };
    const mx = niceMax(Math.max(...rows.map((r) => r.value), 1));
    const bw = (W - m.l - m.r) / rows.length;
    const gap = Math.min(10, bw * 0.3);
    let g = `<line x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}" stroke="${S.grid}"/>`;
    rows.forEach((r, i) => {
      const h = ((H - m.t - m.b) * r.value) / mx;
      const x0 = m.l + i * bw + gap / 2, w = bw - gap, y0 = H - m.b - h;
      const rad = Math.min(4, w / 2, h);
      g += `<path d="M${x0},${H - m.b} L${x0},${y0 + rad} Q${x0},${y0} ${x0 + rad},${y0} L${x0 + w - rad},${y0} Q${x0 + w},${y0} ${x0 + w},${y0 + rad} L${x0 + w},${H - m.b}Z" fill="${color}"><title>${esc(r.label)}: ${esc(fmt(r.value))}</title></path>`;
      g += `<text x="${x0 + w / 2}" y="${H - 7}" text-anchor="middle" class="viz-ax">${esc(r.label)}</text>`;
    });
    host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="Column chart">${g}</svg>`;
  }

  window.NCCharts = { line, hbars, columns, S };
})();
