"use strict";

// Dashboard statis: membaca data/*.json yang ditulis oleh `python -m monitor fetch`.

const SVG_NS = "http://www.w3.org/2000/svg";
const PAGE_SIZE = 10;
const ALL = "all";

const state = {
  summary: { centers: [] },
  history: {},
  reviews: [],
  center: ALL,
  period: "30",
  metric: "rating",
  stars: "all",
  sortKey: "name",
  sortDir: 1,
  chartAsTable: false,
  reviewLimit: PAGE_SIZE,
};

const $ = (selector) => document.querySelector(selector);

const numberFormat = (digits) =>
  new Intl.NumberFormat("id-ID", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const fmtRating = (value, digits = 1) => (value == null ? "–" : numberFormat(digits).format(value));
const fmtInt = (value) => (value == null ? "–" : new Intl.NumberFormat("id-ID").format(value));
const fmtDate = (isoDate) =>
  new Date(isoDate + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
const fmtShortDate = (isoDate) =>
  new Date(isoDate + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "short" });
const fmtDateTime = (iso) =>
  new Date(iso).toLocaleString("id-ID", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jakarta",
  }) + " WIB";

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function svg(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

// Data dari Google tidak dipercaya: hanya link https yang dipasang sebagai href/src.
const safeUrl = (url) => (typeof url === "string" && url.startsWith("https://") ? url : null);

/* ---------- Perhitungan ---------- */

function addDays(isoDate, days) {
  const date = new Date(isoDate + "T00:00:00Z");
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function latestDate() {
  if (state.summary.date) return state.summary.date;
  const dates = Object.values(state.history).flat().map((p) => p.date).sort();
  return dates.at(-1) || new Date().toISOString().slice(0, 10);
}

function cutoffDate() {
  return state.period === "all" ? null : addDays(latestDate(), -Number(state.period));
}

// Titik terakhir pada/sebelum tanggal; kalau tidak ada, titik pertama yang tersedia.
function pointAt(points, date) {
  let found = null;
  for (const point of points) {
    if (point.date <= date) found = point;
    else break;
  }
  return found;
}

function centerStats(center) {
  const points = state.history[center.place_id] || [];
  const latest = points.at(-1) || null;
  const cutoff = cutoffDate();
  const start = cutoff ? pointAt(points, cutoff) || points[0] || null : points[0] || null;
  const partial = Boolean(cutoff && points.length && points[0].date > cutoff);
  const deltaRating =
    latest && start && latest.rating != null && start.rating != null ? latest.rating - start.rating : null;
  const newReviews = latest && start ? latest.count - start.count : null;
  const low = filteredReviews({ center: center.place_id, stars: "low" });
  return { latest, start, partial, deltaRating, newReviews, lowReviews: low.length, unreplied: low.filter(isUnreplied).length };
}

function weightedRating(rows) {
  let sum = 0;
  let weight = 0;
  for (const row of rows) {
    if (row.rating == null || !row.count) continue;
    sum += row.rating * row.count;
    weight += row.count;
  }
  return weight ? sum / weight : null;
}

function selectedCenters() {
  const centers = state.summary.centers;
  return state.center === ALL ? centers : centers.filter((c) => c.place_id === state.center);
}

// Seri gabungan (rata-rata rating tertimbang / total ulasan) dari semua cabang yang punya data di tanggal itu.
function aggregateSeries(centers) {
  const dates = [...new Set(centers.flatMap((c) => (state.history[c.place_id] || []).map((p) => p.date)))].sort();
  return dates.map((date) => {
    const rows = centers
      .map((c) => pointAt(state.history[c.place_id] || [], date))
      .filter(Boolean);
    return {
      date,
      rating: weightedRating(rows),
      count: rows.reduce((total, row) => total + (row.count || 0), 0),
    };
  });
}

function seriesFor(placeId) {
  if (placeId === ALL) return aggregateSeries(state.summary.centers);
  return state.history[placeId] || [];
}

function inPeriod(points) {
  const cutoff = cutoffDate();
  if (!cutoff) return points;
  const start = pointAt(points, cutoff);
  return points.filter((p) => p.date > cutoff || p === start);
}

function filteredReviews({ center = state.center, stars = state.stars } = {}) {
  const active = new Set(state.summary.centers.map((c) => c.place_id));
  const cutoff = cutoffDate();
  return state.reviews.filter((review) => {
    if (!active.has(review.place_id)) return false;
    if (center !== ALL && review.place_id !== center) return false;
    if (stars === "low" && !(review.rating <= 3)) return false;
    if (stars === "high" && !(review.rating >= 4)) return false;
    if (stars === "unreplied" && !isUnreplied(review)) return false;
    if (cutoff && (review.publish_time || "").slice(0, 10) < cutoff) return false;
    return true;
  });
}

function periodLabel() {
  return state.period === "all" ? "sejak data pertama" : `${state.period} hari terakhir`;
}

/* ---------- Komponen kecil ---------- */

function deltaNode(value, { digits = 1, invert = false, suffix = "" } = {}) {
  if (value == null) return el("span", { class: "delta flat", text: "–" });
  const rounded = Number(value.toFixed(digits));
  if (rounded === 0) return el("span", { class: "delta flat", text: "tetap" });
  const good = invert ? rounded < 0 : rounded > 0;
  const arrow = rounded > 0 ? "▲" : "▼";
  const text = `${arrow} ${rounded > 0 ? "+" : "−"}${numberFormat(digits).format(Math.abs(rounded))}${suffix}`;
  return el("span", { class: `delta ${good ? "up" : "down"}`, text });
}

function starsNode(rating) {
  const full = Math.round(rating || 0);
  return el(
    "span",
    { class: "stars", "aria-hidden": "true" },
    "★".repeat(full),
    el("span", { class: "off", text: "★".repeat(Math.max(0, 5 - full)) }),
  );
}

function statusNode(row) {
  if (row.error) return el("span", { class: "status bad", title: row.error, text: "⚠ Gagal diambil" });
  if (!row.last_fetched) return el("span", { class: "status warn", text: "○ Menunggu giliran" });
  return el("span", { class: "status ok", text: "● Aktif" });
}

function lastCheckedNode(row) {
  if (!row.last_fetched) return null;
  const date = new Date(row.last_fetched).toLocaleDateString("id-ID", { day: "numeric", month: "short", timeZone: "Asia/Jakarta" });
  return el("div", { class: "address", text: `dicek ${date}` });
}

const isUnreplied = (review) => review.rating <= 3 && !review.response_text;

/* ---------- Render ---------- */

function renderFilters() {
  const select = $("#filter-center");
  const options = [el("option", { value: ALL, text: `Semua cabang (${state.summary.centers.length})` })];
  const sorted = [...state.summary.centers].sort((a, b) => a.name.localeCompare(b.name, "id"));
  for (const center of sorted) options.push(el("option", { value: center.place_id, text: center.name }));
  select.replaceChildren(...options);
  select.value = state.center;

  for (const button of document.querySelectorAll("[data-period]")) {
    button.setAttribute("aria-pressed", String(button.dataset.period === state.period));
  }
  for (const button of document.querySelectorAll("[data-metric]")) {
    button.setAttribute("aria-pressed", String(button.dataset.metric === state.metric));
  }
  for (const button of document.querySelectorAll("[data-stars]")) {
    button.setAttribute("aria-pressed", String(button.dataset.stars === state.stars));
  }
}

function kpi(label, value, note, hero = false) {
  return el("div", { class: `kpi${hero ? " hero" : ""}` },
    el("div", { class: "label", text: label }),
    el("div", { class: "value", text: value }),
    note ? el("div", { class: "note" }, note) : null,
  );
}

function renderKpis() {
  const centers = selectedCenters();
  const stats = centers.map((c) => ({ center: c, ...centerStats(c) }));
  const current = weightedRating(centers.map((c) => ({ rating: c.rating, count: c.user_rating_count })));
  const startRating = weightedRating(stats.map((s) => s.start).filter(Boolean));
  const ratingDelta = current != null && startRating != null ? current - startRating : null;
  const total = centers.reduce((sum, c) => sum + (c.user_rating_count || 0), 0);
  const newReviews = stats.reduce((sum, s) => sum + (s.newReviews || 0), 0);
  const lowList = filteredReviews({ stars: "low" });
  const unreplied = lowList.filter(isUnreplied).length;
  const partial = stats.some((s) => s.partial);
  const periodNote = partial ? `${periodLabel()} (data sebagian cabang belum lengkap)` : periodLabel();

  const tiles = [
    kpi(
      state.center === ALL ? "Rata-rata rating (tertimbang)" : "Rating",
      fmtRating(current, state.center === ALL ? 2 : 1),
      [deltaNode(ratingDelta, { digits: 2 }), ` · ${periodNote}`],
      true,
    ),
    kpi("Total ulasan di Google", fmtInt(total)),
    kpi("Ulasan baru", fmtInt(newReviews), periodNote),
    kpi("Ulasan 1–3 ★", fmtInt(lowList.length), [
      unreplied ? el("span", { class: "delta down", text: `${fmtInt(unreplied)} belum dibalas` }) : "semua sudah dibalas",
      ` · ${periodLabel()}`,
    ]),
  ];
  if (state.center === ALL) {
    const failing = centers.filter((c) => c.error).length;
    tiles.push(kpi("Cabang dimonitor", fmtInt(centers.length), failing ? `⚠ ${failing} gagal diambil` : null));
  } else if (centers[0]) {
    tiles.push(kpi("Status", "", statusNode(centers[0])));
  }
  $("#kpis").replaceChildren(...tiles);
}

function niceTicks(min, max, { count = 4, minStep = 0 } = {}) {
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const rawStep = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const step = Math.max(minStep, [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep));
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) ticks.push(Number(v.toFixed(6)));
  const digits = Number.isInteger(step) ? 0 : Number.isInteger(Number((step * 10).toFixed(6))) ? 1 : 2;
  return { ticks, digits };
}

function chartData() {
  const metric = state.metric;
  const main = inPeriod(seriesFor(state.center)).filter((p) => p[metric] != null);
  // Konteks abu-abu: cabang lain, hanya untuk rating (jumlah ulasan beda skala antar cabang).
  const context =
    metric === "rating"
      ? state.summary.centers
          .filter((c) => c.place_id !== state.center)
          .map((c) => inPeriod(state.history[c.place_id] || []).filter((p) => p.rating != null))
          .filter((points) => points.length > 1)
      : [];
  return { main, context };
}

function renderChart() {
  const metric = state.metric;
  const centerName =
    state.center === ALL ? "semua cabang" : (state.summary.centers.find((c) => c.place_id === state.center) || {}).name;
  $("#chart-title").textContent = metric === "rating" ? "Tren rating" : "Tren jumlah ulasan";
  $("#chart-subtitle").textContent =
    (metric === "rating"
      ? state.center === ALL
        ? "Garis biru: rata-rata tertimbang semua cabang. Garis abu-abu: tiap cabang."
        : `Garis biru: ${centerName}. Garis abu-abu: cabang lain.`
      : `Total ulasan di Google, ${centerName}.`) + ` ${periodLabel()[0].toUpperCase()}${periodLabel().slice(1)}.`;

  const { main, context } = chartData();
  const valueFmt = (v) => (metric === "rating" ? fmtRating(v, state.center === ALL ? 2 : 1) : fmtInt(v));

  renderChartTable(main, valueFmt);
  $("#chart").hidden = state.chartAsTable;
  $("#chart-table").hidden = !state.chartAsTable;
  $("#chart-toggle").textContent = state.chartAsTable ? "Lihat grafik" : "Lihat tabel";

  const container = $("#chart");
  const width = Math.max(container.clientWidth, 280);
  const height = 260;
  const margin = { top: 16, right: 52, bottom: 28, left: 44 };
  const plotW = width - margin.left - margin.right;
  const plotH = height - margin.top - margin.bottom;
  const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height });

  if (!main.length) {
    root.append(Object.assign(svg("text", { x: margin.left, y: height / 2, class: "chart-note" }), {
      textContent: "Belum ada data untuk periode ini.",
    }));
    container.replaceChildren(root);
    container.setAttribute("aria-label", "Grafik kosong");
    return;
  }

  const allPoints = [...main, ...context.flat()];
  const dates = [...new Set(allPoints.map((p) => p.date))].sort();
  const values = allPoints.map((p) => p[metric]);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (metric === "rating") {
    lo = Math.max(1, lo - 0.1);
    hi = Math.min(5, hi + 0.1);
  }
  const { ticks, digits } = niceTicks(lo, hi, { minStep: metric === "count" ? 1 : 0 });
  const yMin = ticks[0];
  const yMax = ticks.at(-1);
  const t0 = Date.parse(dates[0]);
  const t1 = Date.parse(dates.at(-1));
  const x = (date) => margin.left + (t1 === t0 ? plotW / 2 : ((Date.parse(date) - t0) / (t1 - t0)) * plotW);
  const y = (value) => margin.top + plotH - ((value - yMin) / (yMax - yMin || 1)) * plotH;

  for (const tick of ticks) {
    root.append(svg("line", { class: "grid", x1: margin.left, x2: margin.left + plotW, y1: y(tick), y2: y(tick) }));
    const label = svg("text", { class: "tick", x: margin.left - 8, y: y(tick) + 4, "text-anchor": "end" });
    label.textContent = metric === "rating" ? fmtRating(tick, digits) : compact(tick);
    root.append(label);
  }
  root.append(svg("line", { class: "baseline", x1: margin.left, x2: margin.left + plotW, y1: y(yMin), y2: y(yMin) }));

  const xTickCount = Math.min(dates.length, Math.max(2, Math.floor(plotW / 90)));
  for (let i = 0; i < xTickCount; i++) {
    const date = dates[Math.round((i * (dates.length - 1)) / Math.max(1, xTickCount - 1))];
    const anchor = i === 0 ? "start" : i === xTickCount - 1 ? "end" : "middle";
    const label = svg("text", { class: "tick", x: x(date), y: height - 8, "text-anchor": dates.length === 1 ? "middle" : anchor });
    label.textContent = fmtShortDate(date);
    root.append(label);
  }

  const path = (points) => points.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p[metric]).toFixed(1)}`).join("");
  for (const points of context) root.append(svg("path", { class: "context", d: path(points) }));
  if (main.length > 1) root.append(svg("path", { class: "series", d: path(main) }));
  const last = main.at(-1);
  root.append(svg("circle", { class: "dot", cx: x(last.date), cy: y(last[metric]), r: 4 }));
  const endLabel = svg("text", { class: "end-label", x: x(last.date) + 8, y: y(last[metric]) + 4 });
  endLabel.textContent = valueFmt(last[metric]);
  root.append(endLabel);
  if (main.length === 1) {
    const note = svg("text", { class: "chart-note", x: margin.left, y: margin.top + 12 });
    note.textContent = "Grafik akan terisi setelah beberapa hari pengambilan data.";
    root.append(note);
  }

  // Crosshair + tooltip: snap ke tanggal terdekat; bisa juga digeser dengan tombol panah.
  const crosshair = svg("line", { class: "crosshair", y1: margin.top, y2: margin.top + plotH, visibility: "hidden" });
  const hoverDot = svg("circle", { class: "dot", r: 4, visibility: "hidden" });
  const overlay = svg("rect", { x: margin.left, y: margin.top, width: plotW, height: plotH, fill: "transparent" });
  root.append(crosshair, hoverDot, overlay);

  const tooltip = el("div", { class: "tooltip", hidden: true });
  const seriesName = state.center === ALL ? (metric === "rating" ? "Rata-rata semua cabang" : "Semua cabang") : centerName;
  let activeIndex = main.length - 1;

  function show(index) {
    activeIndex = Math.max(0, Math.min(main.length - 1, index));
    const point = main[activeIndex];
    const px = x(point.date);
    const py = y(point[metric]);
    crosshair.setAttribute("x1", px);
    crosshair.setAttribute("x2", px);
    crosshair.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", px);
    hoverDot.setAttribute("cy", py);
    hoverDot.setAttribute("visibility", "visible");
    tooltip.replaceChildren(
      el("div", { class: "tt-date", text: fmtDate(point.date) }),
      el("div", { class: "tt-row" }, el("span", { class: "tt-key" }), el("strong", { text: valueFmt(point[metric]) }), seriesName),
    );
    tooltip.hidden = false;
    const scale = container.clientWidth / width;
    const left = px * scale;
    tooltip.style.top = `${Math.max(0, py * scale - 64)}px`;
    tooltip.style.left = left > container.clientWidth / 2 ? "" : `${left + 12}px`;
    tooltip.style.right = left > container.clientWidth / 2 ? `${container.clientWidth - left + 12}px` : "";
  }
  function hide() {
    crosshair.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  }
  function nearest(clientX) {
    const box = root.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * width;
    let best = 0;
    main.forEach((p, i) => {
      if (Math.abs(x(p.date) - px) < Math.abs(x(main[best].date) - px)) best = i;
    });
    return best;
  }
  overlay.addEventListener("pointermove", (event) => show(nearest(event.clientX)));
  overlay.addEventListener("pointerleave", hide);
  container.onkeydown = (event) => {
    if (event.key === "ArrowLeft") show(activeIndex - 1);
    else if (event.key === "ArrowRight") show(activeIndex + 1);
    else return;
    event.preventDefault();
  };
  container.onfocus = () => show(activeIndex);
  container.onblur = hide;

  container.setAttribute(
    "aria-label",
    `${$("#chart-title").textContent} ${seriesName}: ${valueFmt(main[0][metric])} pada ${fmtDate(main[0].date)}, ` +
      `${valueFmt(last[metric])} pada ${fmtDate(last.date)}. Gunakan tombol panah untuk melihat tiap tanggal.`,
  );
  container.replaceChildren(root, tooltip);
}

function compact(value) {
  return new Intl.NumberFormat("id-ID", { notation: value >= 1000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value);
}

function renderChartTable(points, valueFmt) {
  const label = state.metric === "rating" ? "Rating" : "Jumlah ulasan";
  const header = el("tr", {}, el("th", { text: "Tanggal" }), el("th", { class: "num", text: label }));
  const rows = [...points].reverse().map((p) =>
    el("tr", {}, el("td", { text: fmtDate(p.date) }), el("td", { class: "num", text: valueFmt(p[state.metric]) })),
  );
  $("#chart-table").replaceChildren(
    el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, header), el("tbody", {}, rows))),
  );
}

const COLUMNS = [
  { key: "name", label: "Cabang" },
  { key: "rating", label: "Rating", num: true },
  { key: "deltaRating", label: "Perubahan", num: true },
  { key: "count", label: "Ulasan", num: true },
  { key: "newReviews", label: "Ulasan baru", num: true },
  { key: "lowReviews", label: "1–3 ★", num: true },
  { key: "unreplied", label: "Belum dibalas", num: true },
  { key: "status", label: "Status" },
  { key: "link", label: "", sortable: false },
];

function renderTable() {
  $("#table-subtitle").textContent =
    `Perubahan dan ulasan baru dihitung untuk ${periodLabel()}. Klik nama cabang untuk melihat detailnya.`;
  const rows = state.summary.centers.map((center) => {
    const stats = centerStats(center);
    return {
      center,
      stats,
      name: center.name,
      rating: center.rating,
      deltaRating: stats.deltaRating,
      count: center.user_rating_count,
      newReviews: stats.newReviews,
      lowReviews: stats.lowReviews,
      unreplied: stats.unreplied,
      status: center.error ? 0 : center.last_fetched ? 2 : 1,
    };
  });
  const { sortKey, sortDir } = state;
  rows.sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return (typeof av === "string" ? av.localeCompare(bv, "id") : av - bv) * sortDir;
  });

  const head = el("tr", {}, COLUMNS.map((col) => {
    if (col.sortable === false) return el("th", { "aria-label": "Link" });
    const active = col.key === sortKey;
    return el("th", {
      class: col.num ? "num" : null,
      "aria-sort": active ? (sortDir > 0 ? "ascending" : "descending") : null,
    }, el("button", {
      type: "button",
      "data-dir": active ? (sortDir > 0 ? "↑" : "↓") : null,
      onclick: () => {
        state.sortDir = active ? -sortDir : col.num ? -1 : 1;
        state.sortKey = col.key;
        renderTable();
      },
    }, col.label));
  }));

  const body = rows.map(({ center, stats, ...row }) =>
    el("tr", { class: center.place_id === state.center ? "selected" : null },
      el("td", {},
        el("button", { type: "button", class: "center-name", text: center.name, onclick: () => setState({ center: center.place_id }) }),
        el("div", { class: "address", text: center.address || "" }),
      ),
      el("td", { class: "num", text: fmtRating(row.rating) }),
      el("td", { class: "num" }, deltaNode(row.deltaRating), stats.partial ? el("div", { class: "address", text: `sejak ${fmtShortDate(stats.start.date)}` }) : null),
      el("td", { class: "num", text: fmtInt(row.count) }),
      el("td", { class: "num" }, row.newReviews ? `+${fmtInt(row.newReviews)}` : row.newReviews === 0 ? "0" : "–"),
      el("td", { class: "num", text: fmtInt(row.lowReviews) }),
      el("td", { class: "num" }, row.unreplied ? el("span", { class: "badge-low", text: fmtInt(row.unreplied) }) : "0"),
      el("td", {}, statusNode(center), lastCheckedNode(center)),
      el("td", {}, safeUrl(center.maps_url) ? el("a", { href: safeUrl(center.maps_url), target: "_blank", rel: "noopener", text: "Maps ↗" }) : null),
    ),
  );

  $("#centers").replaceChildren(el("thead", {}, head), el("tbody", {}, body));
}

function renderReviews() {
  const names = Object.fromEntries(state.summary.centers.map((c) => [c.place_id, c.name]));
  const reviews = filteredReviews();
  const items = reviews.slice(0, state.reviewLimit).map((review) => {
    const author = safeUrl(review.author_uri);
    const photo = safeUrl(review.author_photo);
    const date = review.publish_time ? fmtDate(review.publish_time.slice(0, 10)) : "";
    const showOriginal = review.original_text && review.original_text !== review.text;
    return el("li", { class: "review" },
      el("div", { class: "review-head" },
        photo ? el("img", { src: photo, alt: "", loading: "lazy", referrerpolicy: "no-referrer" }) : null,
        el("div", { class: "review-meta" },
          author
            ? el("a", { class: "author", href: author, target: "_blank", rel: "noopener", text: review.author || "Pengulas Google" })
            : el("span", { class: "author", text: review.author || "Pengulas Google" }),
          el("span", { class: "sub", text: `${names[review.place_id] || ""} · ${date}` }),
        ),
      ),
      el("div", { style: "margin-top:6px" },
        starsNode(review.rating),
        el("span", { class: "rating-text", text: `${review.rating}/5` }),
        isUnreplied(review) ? [" ", el("span", { class: "badge-low", text: "Belum dibalas" })] : null,
      ),
      el("p", { class: `review-text${review.text ? "" : " empty"}`, text: review.text || "Tanpa teks, hanya rating." }),
      showOriginal ? el("details", {}, el("summary", { text: "Teks asli" }), el("p", { text: review.original_text })) : null,
      review.response_text
        ? el("div", { class: "owner-reply" },
            el("div", { class: "sub", text: `Balasan pemilik${review.response_time ? " · " + fmtDate(review.response_time.slice(0, 10)) : ""}` }),
            el("p", { text: review.response_text }),
          )
        : null,
      safeUrl(review.maps_uri)
        ? el("div", { class: "review-links" }, el("a", { href: safeUrl(review.maps_uri), target: "_blank", rel: "noopener", text: "Lihat di Google Maps ↗" }))
        : null,
    );
  });
  $("#reviews").replaceChildren(...(items.length ? items : [el("li", { class: "empty-list", text: "Tidak ada ulasan tercatat untuk filter ini." })]));
  const more = $("#reviews-more");
  more.hidden = reviews.length <= state.reviewLimit;
  more.textContent = `Tampilkan lebih banyak (${fmtInt(reviews.length - state.reviewLimit)} lagi)`;
}

function render() {
  renderFilters();
  const hasData = state.summary.centers.length > 0;
  $("#empty").hidden = hasData;
  $("#content").hidden = !hasData;
  if (!hasData) return;
  renderKpis();
  renderChart();
  renderTable();
  renderReviews();
}

function setState(patch) {
  Object.assign(state, patch);
  if (!("reviewLimit" in patch)) state.reviewLimit = PAGE_SIZE;
  render();
}

/* ---------- Init ---------- */

async function loadJson(name, fallback) {
  try {
    const response = await fetch(`data/${name}`, { cache: "no-store" });
    if (!response.ok) return fallback;
    return await response.json();
  } catch {
    return fallback;
  }
}

async function init() {
  const [summary, history, reviews] = await Promise.all([
    loadJson("summary.json", { centers: [] }),
    loadJson("history.json", {}),
    loadJson("reviews.json", []),
  ]);
  state.summary = summary && Array.isArray(summary.centers) ? summary : { centers: [] };
  state.history = history || {};
  state.reviews = Array.isArray(reviews) ? reviews : [];

  $("#updated").textContent = state.summary.updated_at
    ? `Diperbarui ${fmtDateTime(state.summary.updated_at)}`
    : "Belum pernah diperbarui";

  $("#filter-center").addEventListener("change", (event) => setState({ center: event.target.value }));
  for (const button of document.querySelectorAll("[data-period]")) {
    button.addEventListener("click", () => setState({ period: button.dataset.period }));
  }
  for (const button of document.querySelectorAll("[data-metric]")) {
    button.addEventListener("click", () => setState({ metric: button.dataset.metric }));
  }
  for (const button of document.querySelectorAll("[data-stars]")) {
    button.addEventListener("click", () => setState({ stars: button.dataset.stars }));
  }
  $("#chart-toggle").addEventListener("click", () => setState({ chartAsTable: !state.chartAsTable }));
  $("#reviews-more").addEventListener("click", () => setState({ reviewLimit: state.reviewLimit + PAGE_SIZE }));

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => state.summary.centers.length && !state.chartAsTable && renderChart(), 150);
  });

  render();
  $("#app").setAttribute("aria-busy", "false");
}

init();
