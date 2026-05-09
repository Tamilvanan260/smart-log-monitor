/**
 * charts.js
 * =========
 * Chart.js analytics module for the Smart Log Monitoring dashboard.
 *
 * Renders three charts:
 *   1. levelChart     — Doughnut: log count by level
 *   2. trendChart     — Line:     Error & Warning counts over time (combined)
 *   3. levelBarChart  — Bar:      Same level data as a horizontal bar
 *
 * All data is fetched from the Flask JSON API.
 * Charts are responsive and re-render cleanly on window resize.
 *
 * Dependencies:
 *   Chart.js >= 4.x (loaded via CDN in base.html)
 */

"use strict";

/* ─────────────────────────────────────────────────────────────
   DESIGN TOKENS  (keep in sync with style.css CSS variables)
───────────────────────────────────────────────────────────── */
const COLORS = {
  debug:    { solid: "rgba(108, 117, 125, 0.85)", border: "#6c757d" },
  info:     { solid: "rgba( 13, 110, 253, 0.85)", border: "#0d6efd" },
  warning:  { solid: "rgba(255, 193,   7, 0.85)", border: "#ffc107" },
  error:    { solid: "rgba(220,  53,  69, 0.85)", border: "#dc3545" },
  critical: { solid: "rgba(220,  53,  69, 1.00)", border: "#ff0000" },

  // Trend line fills (semi-transparent)
  errorFill:   "rgba(220,  53,  69, 0.12)",
  warningFill: "rgba(255, 193,   7, 0.10)",

  gridLine:  "rgba(255, 255, 255, 0.06)",
  tickColor: "#6c757d",
  tooltipBg: "#1a1d27",
};

const LEVEL_ORDER  = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
const LEVEL_COLORS = LEVEL_ORDER.map(l => COLORS[l.toLowerCase()].solid);
const LEVEL_BORDERS= LEVEL_ORDER.map(l => COLORS[l.toLowerCase()].border);

/* ─────────────────────────────────────────────────────────────
   SHARED CHART DEFAULTS
───────────────────────────────────────────────────────────── */

/** Tooltip style shared across all charts */
function _tooltipDefaults() {
  return {
    backgroundColor: COLORS.tooltipBg,
    titleColor:      "#e2e8f0",
    bodyColor:       "#8b949e",
    borderColor:     "rgba(255,255,255,0.08)",
    borderWidth:     1,
    padding:         10,
    cornerRadius:    6,
    displayColors:   true,
    boxPadding:      4,
  };
}

/** Axis style shared across cartesian charts */
function _axisDefaults() {
  return {
    grid:  { color: COLORS.gridLine, drawBorder: false },
    ticks: { color: COLORS.tickColor, font: { size: 11 } },
  };
}

/* ─────────────────────────────────────────────────────────────
   CHART REGISTRY  (so we can destroy before re-creating)
───────────────────────────────────────────────────────── */
const _registry = {};

function _destroyIfExists(id) {
  if (_registry[id]) {
    _registry[id].destroy();
    delete _registry[id];
  }
}

/* ─────────────────────────────────────────────────────────────
   LOADING / ERROR HELPERS
───────────────────────────────────────────────────────── */

function _showLoading(wrapperId) {
  const el = document.getElementById(wrapperId);
  if (el) el.classList.add("chart-loading");
}

function _hideLoading(wrapperId) {
  const el = document.getElementById(wrapperId);
  if (el) el.classList.remove("chart-loading");
}

function _showError(wrapperId, msg) {
  const el = document.getElementById(wrapperId);
  if (!el) return;
  el.innerHTML = `
    <div class="chart-error-state">
      <i class="bi bi-exclamation-triangle text-warning fs-3 d-block mb-2"></i>
      <span class="text-secondary small">${msg}</span>
    </div>`;
}

/* ─────────────────────────────────────────────────────────────
   CHART 1 — DOUGHNUT: Log count by level
───────────────────────────────────────────────────────── */

async function renderLevelDoughnut() {
  const wrapperId = "levelDoughnutWrapper";
  const canvasId  = "levelDoughnutChart";
  _showLoading(wrapperId);

  try {
    const res  = await fetch("/api/charts/level-distribution");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _hideLoading(wrapperId);
    _destroyIfExists(canvasId);

    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // Filter out levels that have zero entries so the chart isn't cluttered
    const nonZeroIdx = data.counts
      .map((c, i) => ({ c, i }))
      .filter(({ c }) => c > 0)
      .map(({ i }) => i);

    const labels = nonZeroIdx.map(i => data.labels[i]);
    const counts = nonZeroIdx.map(i => data.counts[i]);
    const colors = nonZeroIdx.map(i => LEVEL_COLORS[i]);
    const borders= nonZeroIdx.map(i => LEVEL_BORDERS[i]);
    const total  = counts.reduce((a, b) => a + b, 0);

    _registry[canvasId] = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{
          data:            counts,
          backgroundColor: colors,
          borderColor:     borders,
          borderWidth:     2,
          hoverOffset:     8,
        }],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: true,
        cutout:              "68%",
        plugins: {
          legend: {
            position:  "right",
            labels: {
              color:     "#c9d1d9",
              font:      { size: 12 },
              padding:   16,
              boxWidth:  14,
              boxHeight: 14,
              usePointStyle: true,
              pointStyle:    "circle",
              // Append the count to each legend label
              generateLabels(chart) {
                return chart.data.labels.map((label, i) => ({
                  text:            `${label}  ${chart.data.datasets[0].data[i]}`,
                  fillStyle:       chart.data.datasets[0].backgroundColor[i],
                  strokeStyle:     chart.data.datasets[0].borderColor[i],
                  lineWidth:       2,
                  hidden:          false,
                  index:           i,
                  pointStyle:      "circle",
                }));
              },
            },
          },
          tooltip: {
            ..._tooltipDefaults(),
            callbacks: {
              label(ctx) {
                const val = ctx.parsed;
                const pct = total > 0 ? ((val / total) * 100).toFixed(1) : 0;
                return `  ${ctx.label}: ${val} (${pct}%)`;
              },
            },
          },
          // Centre label showing total
          title: { display: false },
        },
      },
      plugins: [{
        // Draw "Total\nN" in the doughnut hole
        id: "centreLabel",
        afterDraw(chart) {
          const { ctx: c, chartArea: { left, right, top, bottom } } = chart;
          const cx = (left + right) / 2;
          const cy = (top  + bottom) / 2;
          c.save();
          c.textAlign    = "center";
          c.textBaseline = "middle";
          c.fillStyle    = "#8b949e";
          c.font         = "500 11px system-ui, sans-serif";
          c.fillText("TOTAL", cx, cy - 10);
          c.fillStyle = "#e2e8f0";
          c.font      = "700 24px system-ui, sans-serif";
          c.fillText(total, cx, cy + 12);
          c.restore();
        },
      }],
    });

  } catch (err) {
    _hideLoading(wrapperId);
    _showError(wrapperId, `Could not load level distribution: ${err.message}`);
    console.error("[charts] levelDoughnut:", err);
  }
}

/* ─────────────────────────────────────────────────────────────
   CHART 2 — LINE: Error & Warning trend over time
───────────────────────────────────────────────────────── */

async function renderTrendLine(days = 30) {
  const wrapperId = "trendLineWrapper";
  const canvasId  = "trendLineChart";
  _showLoading(wrapperId);

  try {
    const res  = await fetch(`/api/charts/combined-trend?days=${days}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _hideLoading(wrapperId);
    _destroyIfExists(canvasId);

    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // Show only every N-th label to avoid overcrowding the x-axis
    const labelStep = days <= 7 ? 1 : days <= 14 ? 2 : days <= 30 ? 5 : 10;
    const displayLabels = data.labels.map((l, i) =>
      i % labelStep === 0 ? l.slice(5) : ""  // "MM-DD" format
    );

    _registry[canvasId] = new Chart(ctx, {
      type: "line",
      data: {
        labels: displayLabels,
        datasets: [
          {
            label:           "Errors",
            data:            data.errors,
            borderColor:     COLORS.error.border,
            backgroundColor: COLORS.errorFill,
            borderWidth:     2,
            pointRadius:     data.errors.map(v => v > 0 ? 4 : 0),
            pointHoverRadius:6,
            pointBackgroundColor: COLORS.error.border,
            fill:            true,
            tension:         0.35,
          },
          {
            label:           "Warnings",
            data:            data.warnings,
            borderColor:     COLORS.warning.border,
            backgroundColor: COLORS.warningFill,
            borderWidth:     2,
            pointRadius:     data.warnings.map(v => v > 0 ? 4 : 0),
            pointHoverRadius:6,
            pointBackgroundColor: COLORS.warning.border,
            fill:            true,
            tension:         0.35,
          },
        ],
      },
      options: {
        responsive:          true,
        maintainAspectRatio: false,
        interaction:         { mode: "index", intersect: false },
        plugins: {
          legend: {
            position: "top",
            align:    "end",
            labels: {
              color:         "#c9d1d9",
              font:          { size: 12 },
              usePointStyle: true,
              pointStyle:    "circle",
              padding:       16,
            },
          },
          tooltip: {
            ..._tooltipDefaults(),
            callbacks: {
              title(items) {
                // Show the full date in the tooltip title
                const idx = items[0].dataIndex;
                return data.labels[idx] || items[0].label;
              },
              label(item) {
                return `  ${item.dataset.label}: ${item.parsed.y}`;
              },
            },
          },
        },
        scales: {
          x: {
            ..._axisDefaults(),
            grid: { display: false },
          },
          y: {
            ..._axisDefaults(),
            beginAtZero: true,
            ticks: {
              color:     COLORS.tickColor,
              font:      { size: 11 },
              precision: 0,           // integer ticks only
            },
          },
        },
      },
    });

  } catch (err) {
    _hideLoading(wrapperId);
    _showError(wrapperId, `Could not load trend data: ${err.message}`);
    console.error("[charts] trendLine:", err);
  }
}

/* ─────────────────────────────────────────────────────────────
   CHART 3 — HORIZONTAL BAR: Log count by level
───────────────────────────────────────────────────────── */

async function renderLevelBar() {
  const wrapperId = "levelBarWrapper";
  const canvasId  = "levelBarChart";
  _showLoading(wrapperId);

  try {
    const res  = await fetch("/api/charts/level-distribution");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    _hideLoading(wrapperId);
    _destroyIfExists(canvasId);

    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    _registry[canvasId] = new Chart(ctx, {
      type: "bar",
      data: {
        labels:   data.labels,
        datasets: [{
          label:           "Log Entries",
          data:            data.counts,
          backgroundColor: LEVEL_COLORS,
          borderColor:     LEVEL_BORDERS,
          borderWidth:     1,
          borderRadius:    4,
          borderSkipped:   false,
        }],
      },
      options: {
        indexAxis:           "y",        // horizontal bars
        responsive:          true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ..._tooltipDefaults(),
            callbacks: {
              label(item) {
                return `  Count: ${item.parsed.x}`;
              },
            },
          },
        },
        scales: {
          x: {
            ..._axisDefaults(),
            beginAtZero: true,
            ticks: {
              color:     COLORS.tickColor,
              font:      { size: 11 },
              precision: 0,
            },
          },
          y: {
            ..._axisDefaults(),
            grid: { display: false },
            ticks: {
              color: "#c9d1d9",
              font:  { size: 12, weight: "600" },
            },
          },
        },
      },
    });

  } catch (err) {
    _hideLoading(wrapperId);
    _showError(wrapperId, `Could not load level bar data: ${err.message}`);
    console.error("[charts] levelBar:", err);
  }
}

/* ─────────────────────────────────────────────────────────────
   TREND WINDOW SWITCHER  (7 / 14 / 30 / 60 days buttons)
───────────────────────────────────────────────────────── */

function initTrendSwitcher() {
  const btns = document.querySelectorAll("[data-trend-days]");
  if (!btns.length) return;

  btns.forEach(btn => {
    btn.addEventListener("click", async () => {
      btns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      await renderTrendLine(parseInt(btn.dataset.trendDays, 10));
    });
  });
}

/* ─────────────────────────────────────────────────────────────
   INITIALISE ALL CHARTS
───────────────────────────────────────────────────────── */

async function initDashboardCharts() {
  // Render all three charts concurrently for speed
  await Promise.all([
    renderLevelDoughnut(),
    renderTrendLine(30),
    renderLevelBar(),
  ]);
  initTrendSwitcher();
}

// Boot when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  // Only run on the dashboard page (canvas elements must be present)
  if (document.getElementById("levelDoughnutChart")) {
    initDashboardCharts();
  }
});
