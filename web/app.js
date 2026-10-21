/* US Inflation Calculator - front end.
   Plain ES2020, no build step, no external libraries. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  meta: null,
  series: null,
  stats: null,
};

/* ------------------------------ formatting ------------------------------ */

const usd = (n, digits = 2) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);

const usdSmart = (n) => {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return usd(n, 0);
  if (abs >= 100) return usd(n, 0);
  if (abs >= 1) return usd(n, 2);
  return usd(n, 4);
};

const pct = (n, digits = 2) =>
  `${n >= 0 ? "" : "-"}${Math.abs(n * 100).toFixed(digits)}%`;

const signedPct = (n, digits = 2) => `${n >= 0 ? "+" : "-"}${Math.abs(n * 100).toFixed(digits)}%`;

const num = (n, digits = 1) =>
  new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);

/** Compact axis label that stays readable across very different magnitudes. */
function axisLabel(v) {
  const abs = Math.abs(v);
  if (abs === 0) return "0";
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 10_000) return `${(v / 1000).toFixed(0)}k`;
  if (abs >= 1000) return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v);
  if (abs >= 10) return v.toFixed(0);
  if (abs >= 1) return v.toFixed(1);
  return v.toFixed(2);
}

/* ------------------------------ api ------------------------------ */

async function api(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  );
  const res = await fetch(`${path}${qs.toString() ? `?${qs}` : ""}`);
  const body = await res.json().catch(() => ({ error: "unreadable response" }));
  if (!res.ok) throw new Error(body.error || `request failed (${res.status})`);
  return body;
}

/* ------------------------------ chart helpers ------------------------------ */

const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}, text) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
};

/** Pick a "nice" axis step so labels land on round numbers. */
function niceStep(range, targetTicks = 5) {
  if (range <= 0) return 1;
  const rough = range / targetTicks;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
  return step * mag;
}

function ticks(min, max, target = 5) {
  const step = niceStep(max - min, target);
  const start = Math.ceil(min / step) * step;
  const out = [];
  for (let v = start; v <= max + 1e-9; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/**
 * Line chart of the index over time, with optional highlighted years.
 * Returns the <svg> element.
 */
function lineChart(points, opts = {}) {
  const {
    width = 940,
    height = 340,
    markers = [],
    areaFrom = null,
    yLabel = axisLabel,
  } = opts;
  const pad = { top: 18, right: 18, bottom: 34, left: 52 };
  const iw = width - pad.left - pad.right;
  const ih = height - pad.top - pad.bottom;

  const xs = points.map((p) => p.year);
  const ys = points.map((p) => p.value);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  let yMin = Math.min(...ys);
  let yMax = Math.max(...ys);
  if (yMin === yMax) { yMin -= 1; yMax += 1; }
  const yPad = (yMax - yMin) * 0.08;
  yMin = Math.max(0, yMin - yPad);
  yMax = yMax + yPad;

  const X = (year) => pad.left + (xMax === xMin ? iw / 2 : ((year - xMin) / (xMax - xMin)) * iw);
  const Y = (val) => pad.top + ih - ((val - yMin) / (yMax - yMin)) * ih;

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });

  const defs = el("defs");
  const grad = el("linearGradient", { id: "areaGrad", x1: "0", y1: "0", x2: "0", y2: "1" });
  grad.append(
    el("stop", { offset: "0%", "stop-color": "#b23a2e", "stop-opacity": "0.22" }),
    el("stop", { offset: "100%", "stop-color": "#b23a2e", "stop-opacity": "0.01" })
  );
  defs.append(grad);
  svg.append(defs);

  for (const t of ticks(yMin, yMax, 5)) {
    const y = Y(t);
    svg.append(el("line", { class: "grid-line", x1: pad.left, y1: y, x2: width - pad.right, y2: y }));
    svg.append(el("text", { x: pad.left - 8, y: y + 3.5, "text-anchor": "end" }, yLabel(t)));
  }

  const xTicks = ticks(xMin, xMax, 6).filter((t) => t >= xMin && t <= xMax);
  for (const t of xTicks) {
    svg.append(el("text", { x: X(t), y: height - 12, "text-anchor": "middle" }, String(Math.round(t))));
  }
  svg.append(el("line", { class: "axis-line", x1: pad.left, y1: pad.top + ih, x2: width - pad.right, y2: pad.top + ih }));

  const line = points.map((p, i) => `${i ? "L" : "M"}${X(p.year).toFixed(2)},${Y(p.value).toFixed(2)}`).join(" ");

  if (areaFrom !== null) {
    const base = Y(Math.max(yMin, areaFrom));
    svg.append(
      el("path", {
        class: "series-area",
        d: `${line} L${X(xMax).toFixed(2)},${base.toFixed(2)} L${X(xMin).toFixed(2)},${base.toFixed(2)} Z`,
      })
    );
  }
  svg.append(el("path", { class: "series-line", d: line }));

  for (const m of markers) {
    const x = X(m.year);
    if (x < pad.left - 1 || x > width - pad.right + 1) continue;
    svg.append(el("line", { class: "marker", x1: x, y1: pad.top, x2: x, y2: pad.top + ih }));
    svg.append(el("circle", { class: "series-dot", cx: x, cy: Y(m.value), r: 4 }));
    const anchor = x > width - pad.right - 70 ? "end" : "start";
    const dx = anchor === "end" ? -7 : 7;
    svg.append(
      el("text", { class: "label-strong", x: x + dx, y: pad.top + 12, "text-anchor": anchor }, String(m.year))
    );
  }
  return svg;
}

/** Diverging bar chart for year-over-year inflation rates. */
function barChart(rows, opts = {}) {
  const { width = 940, height = 320 } = opts;
  const pad = { top: 20, right: 14, bottom: 34, left: 46 };
  const iw = width - pad.left - pad.right;
  const ih = height - pad.top - pad.bottom;

  const years = rows.map((r) => r.year);
  const rates = rows.map((r) => r.rate);
  const xMin = Math.min(...years);
  const xMax = Math.max(...years) + 1;
  const yAbs = Math.max(0.05, Math.max(...rates.map(Math.abs)));
  const yMin = -yAbs * 1.08;
  const yMax = yAbs * 1.08;

  const X = (year) => pad.left + ((year - xMin) / (xMax - xMin)) * iw;
  const Y = (rate) => pad.top + ih - ((rate - yMin) / (yMax - yMin)) * ih;

  const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, role: "img" });
  const zero = Y(0);

  for (const t of ticks(yMin, yMax, 5)) {
    const y = Y(t);
    svg.append(el("line", { class: "grid-line", x1: pad.left, y1: y, x2: width - pad.right, y2: y }));
    svg.append(el("text", { x: pad.left - 8, y: y + 3.5, "text-anchor": "end" }, `${(t * 100).toFixed(0)}%`));
  }

  const bw = Math.max(1, (iw / (xMax - xMin)) * 0.72);
  for (const r of rows) {
    const x = X(r.year) - bw / 2;
    const y = r.rate >= 0 ? Y(r.rate) : zero;
    const h = Math.max(0.6, Math.abs(Y(r.rate) - zero));
    const bar = el("rect", {
      class: r.rate >= 0 ? "bar-pos" : "bar-neg",
      x: x.toFixed(2), y: y.toFixed(2), width: bw.toFixed(2), height: h.toFixed(2), rx: 1,
    });
    bar.append(el("title", {}, `${r.year}: ${signedPct(r.rate)}`));
    svg.append(bar);
  }

  svg.append(el("line", { class: "axis-line", x1: pad.left, y1: zero, x2: width - pad.right, y2: zero }));
  for (const t of ticks(xMin, xMax - 1, 6)) {
    if (t < xMin || t > xMax) continue;
    svg.append(el("text", { x: X(t), y: height - 12, "text-anchor": "middle" }, String(Math.round(t))));
  }
  return svg;
}

function render(host, svg) {
  host.replaceChildren(svg);
}

/* ------------------------------ convert tab ------------------------------ */

async function updateConvert() {
  const amount = Math.max(0, Number($("#c-amount").value) || 0);
  const fromYear = clampYear(Number($("#c-from").value));
  const toYear = clampYear(Number($("#c-to").value));
  $("#c-from").value = fromYear;
  $("#c-to").value = toYear;

  let data;
  try {
    data = await api("/api/convert", { amount, from_year: fromYear, to_year: toYear });
  } catch (err) {
    $("[data-c-result]").textContent = "—";
    $("[data-c-caption]").textContent = err.message;
    return;
  }

  $("[data-c-result]").textContent = usdSmart(data.result);
  const dir = data.total_change >= 0 ? "is-up" : "is-down";
  const big = $("[data-c-result]");
  big.classList.remove("is-up", "is-down");
  big.classList.add(dir);

  $("[data-c-caption]").textContent =
    data.from_year === data.to_year
      ? `No change between ${data.from_year} and ${data.to_year}.`
      : `${usdSmart(data.amount)} in ${data.from_year} has the same buying power as ${usdSmart(data.result)} in ${data.to_year}.`;

  $("[data-c-total]").textContent = signedPct(data.total_change);
  $("[data-c-factor]").textContent = `${num(data.factor, 2)}×`;
  $("[data-c-annual]").textContent = data.years > 0 ? `${pct(data.annualized)} a year` : "—";
  $("[data-c-index]").textContent = `${data.from_index.toFixed(1)} → ${data.to_index.toFixed(1)}`;

  const flag = $("[data-c-flag]");
  const messages = [];
  if (data.projected) messages.push(`${data.to_year} is beyond the latest measured data (${state.meta.last_year}), so that value uses your assumed rate.`);
  if (data.from_year < 1913 || data.to_year < 1913) messages.push("Years before 1913 rely on historical estimates and are less precise than the official CPI.");
  flag.hidden = messages.length === 0;
  flag.textContent = messages.join(" ");

  updateConvertChart(data);
}

function updateConvertChart(data) {
  const annual = state.series.annual;
  const points = Object.keys(annual)
    .map(Number)
    .sort((a, b) => a - b)
    .map((year) => ({ year, value: annual[year] }));
  const markers = [
    { year: data.from_year, value: valueAtYear(data.from_year, data.from_index) },
    { year: data.to_year, value: valueAtYear(data.to_year, data.to_index) },
  ].filter((m) => m.value !== null);
  render($("[data-c-chart]"), lineChart(points, { markers, areaFrom: 0 }));
}

function valueAtYear(year, fallback) {
  const annual = state.series?.annual || {};
  return annual[year] !== undefined ? annual[year] : fallback;
}

function clampYear(year) {
  if (!Number.isFinite(year)) return state.meta.current_year;
  return Math.min(2200, Math.max(state.meta.first_year, Math.round(year)));
}

/* ------------------------------ project tab ------------------------------ */

async function updateProject() {
  const baseYear = state.meta.last_year;
  const years = Number($("#p-years").value);
  const rate = Number($("#p-rate").value) / 100;
  const amount = Math.max(0, Number($("#p-amount").value) || 0);

  $("[data-p-years-out]").textContent = years;
  $("[data-p-rate-out]").textContent = `${(rate * 100).toFixed(1)}%`;
  $("[data-p-base-year]").textContent = baseYear;
  $("[data-p-legend-amount]").textContent = usdSmart(amount);

  const endYear = baseYear + years;
  const data = await api("/api/project", {
    amount,
    base_year: baseYear,
    end_year: endYear,
    forward_rate: rate,
  });

  const final = data.points[data.points.length - 1];
  $("[data-p-result]").textContent = usdSmart(final.value);
  $("[data-p-caption]").textContent =
    `${usdSmart(amount)} of ${baseYear} money needs to be ${usdSmart(final.value)} in ${final.year} to buy the same things.`;
  $("[data-p-increase]").textContent = signedPct(final.value / amount - 1);
  $("[data-p-power]").textContent = `${((amount / final.value) * 100).toFixed(1)}%`;
  $("[data-p-span]").textContent = `${years} year${years === 1 ? "" : "s"}`;
  $("[data-p-rate-stat]").textContent = pct(rate, 1);

  const baseIndex = data.points[0].index;
  const realPoints = data.points.map((p) => ({
    year: p.year,
    value: amount * (baseIndex / p.index),
  }));
  const finalReal = realPoints[realPoints.length - 1];
  render(
    $("[data-p-chart]"),
    lineChart(realPoints, {
      markers: [{ year: finalReal.year, value: finalReal.value }],
      areaFrom: 0,
    })
  );

  const half = data.points.find((p) => p.value >= amount * 2);
  const halfBody = half
    ? `At this rate the same goods cost double by ${half.year}, ${half.year - baseYear} years from now.`
    : `Even after ${years} years the cumulative rise stays under 100% at this rate.`;
  $("[data-p-callout-title]").textContent = half ? "Doubling point" : "Cumulative effect";
  $("[data-p-callout-body]").textContent = halfBody;
}

/* ------------------------------ history tab ------------------------------ */

function renderHistory() {
  const s = state.stats;
  const strip = $("[data-h-strip]");
  const items = [
    { k: "Years of data", v: `${s.first_year}–${s.last_year}`, s: `${s.observations} annual averages` },
    { k: "Average inflation", v: pct(s.mean_inflation), s: `per year since ${s.first_year + 1}` },
    { k: "Highest year", v: signedPct(s.highest_year.rate, 1), s: `${s.highest_year.year} · sharpest rise` },
    { k: "Deflation years", v: String(s.deflation_years), s: "years prices fell" },
  ];
  strip.replaceChildren(
    ...items.map((it) => {
      const d = document.createElement("div");
      d.innerHTML = `<span class="k">${it.k}</span><span class="v">${it.v}</span><span class="s">${it.s}</span>`;
      return d;
    })
  );

  render($("[data-h-chart]"), barChart(s.year_over_year));

  const yoy = s.year_over_year;
  const deflation = yoy.filter((r) => r.rate < 0);
  const extremes = yoy
    .filter((r) => r.rate >= 0)
    .sort((a, b) => b.rate - a.rate)
    .slice(0, 6);
  const rows = [
    ...deflation.map((r) => ({ ...r, tag: "Deflation" })),
    ...extremes.map((r) => ({ ...r, tag: "Sharp rise" })),
  ].sort((a, b) => a.year - b.year);

  $("[data-h-episodes]").replaceChildren(
    ...rows.map((r) => {
      const d = document.createElement("div");
      d.className = "episode";
      d.innerHTML = `<span class="yr">${r.year}</span>
        <span class="rt ${r.rate >= 0 ? "pos" : "neg"}">${signedPct(r.rate, 1)}</span>
        <span class="tag">${r.tag}</span>`;
      return d;
    })
  );
}

/* ------------------------------ data tab ------------------------------ */

function renderData() {
  const meta = state.meta.meta;
  $("[data-sources]").replaceChildren(
    ...meta.sources.map((src) => {
      const d = document.createElement("div");
      d.className = "source";
      d.innerHTML = `<h3>${src.name}</h3>
        <p>${src.detail} <a href="${src.url}" rel="noopener noreferrer" target="_blank">Source</a></p>
        <p class="cover">Series ${src.series} · coverage ${src.coverage}</p>`;
      return d;
    })
  );

  const annual = state.series.annual;
  const years = Object.keys(annual).map(Number).sort((a, b) => b - a);
  const tbody = $("[data-table] tbody");
  tbody.replaceChildren(
    ...years.map((year) => {
      const value = annual[year];
      const prev = annual[year - 1];
      const rate = prev ? value / prev - 1 : null;
      const tr = document.createElement("tr");
      const rateCell =
        rate === null
          ? `<td class="pre">—</td>`
          : `<td class="${rate < 0 ? "neg" : ""}">${signedPct(rate)}</td>`;
      tr.innerHTML = `<td class="${year < 1913 ? "pre" : ""}">${year}${year < 1913 ? "*" : ""}</td>
        <td>${value.toFixed(1)}</td>${rateCell}`;
      return tr;
    })
  );

  $("[data-footer-meta]").textContent =
    `Series generated ${meta.generated_utc}. ${state.series.first_year}–${state.meta.last_year}, ${state.stats.observations} annual averages. * pre-1913 estimates.`;
}

/* ------------------------------ boot ------------------------------ */

function wireTabs() {
  $$(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".tab").forEach((t) => {
        const on = t === tab;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", String(on));
      });
      $$(".panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === tab.dataset.tab));
    });
  });
}

function debounce(fn, ms = 180) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function boot() {
  $$("[data-now]").forEach((n) => (n.textContent = String(new Date().getFullYear())));

  const [meta, series, stats] = await Promise.all([
    api("/api/meta"),
    api("/api/series"),
    api("/api/stats"),
  ]);
  state.meta = meta;
  state.series = series;
  state.stats = stats;

  const last = meta.last_year;
  $("#c-to").value = last;
  $("#c-to").max = "2200";
  $("#c-from").max = "2200";
  $("#c-from").min = String(meta.first_year);
  $("[data-range-hint]").textContent =
    `Data covers ${meta.first_year} to ${meta.last_year}. Later years are projected at your assumed rate.`;
  $("#p-amount").value = 1000;

  const run = debounce(updateConvert, 150);
  ["#c-amount", "#c-from", "#c-to"].forEach((sel) =>
    $(sel).addEventListener("input", run)
  );
  $$("[data-quick]").forEach((chip) =>
    chip.addEventListener("click", () => {
      $("#c-from").value = chip.dataset.quick;
      $("#c-to").value = last;
      updateConvert();
    })
  );

  const runP = debounce(updateProject, 120);
  ["#p-amount", "#p-years", "#p-rate"].forEach((sel) =>
    $(sel).addEventListener("input", () => {
      if (sel === "#p-years") $("[data-p-years-out]").textContent = $("#p-years").value;
      if (sel === "#p-rate") $("[data-p-rate-out]").textContent = `${Number($("#p-rate").value).toFixed(1)}%`;
      runP();
    })
  );

  wireTabs();
  renderHistory();
  renderData();
  await updateConvert();
  await updateProject();
}

boot().catch((err) => {
  console.error(err);
  document.body.insertAdjacentHTML(
    "afterbegin",
    `<div style="padding:1rem;background:#b23a2e;color:#fff;font:14px system-ui">
      Could not start the calculator: ${err.message}</div>`
  );
});
