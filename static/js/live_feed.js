/**
 * live_feed.js
 * ============
 * Drives the real-time live log feed on the Monitor page.
 *
 * Strategy
 * --------
 * - Polls GET /api/monitor/live-feed?after_id=<N>&limit=50 every POLL_MS.
 * - Tracks the highest id seen so only genuinely new rows arrive each tick.
 * - Prepends new rows to the top of the live table (newest first).
 * - Caps the table at MAX_ROWS so the DOM doesn't grow forever.
 * - Shows a pulsing "LIVE" indicator while any monitor is active.
 * - Pauses polling when the browser tab is hidden (Page Visibility API).
 *
 * No external dependencies beyond the Fetch API (available in all modern
 * browsers).
 */

"use strict";

/* ── Config ──────────────────────────────────────────────────────────────── */
const POLL_MS  = 3_000;   // poll interval in milliseconds
const MAX_ROWS = 200;     // maximum table rows kept in the DOM

/* ── Level → badge class map ─────────────────────────────────────────────── */
const LEVEL_BADGE = {
  DEBUG:    "level-badge-debug",
  INFO:     "level-badge-info",
  WARNING:  "level-badge-warning",
  ERROR:    "level-badge-error",
  CRITICAL: "level-badge-critical",
};

const SEV_BADGE = {
  low:      "sev-low",
  medium:   "sev-medium",
  high:     "sev-high",
  critical: "sev-critical",
};

/* ── Module state ─────────────────────────────────────────────────────────── */
let _lastId        = 0;       // highest ParsedLog.id received so far
let _pollTimer     = null;    // setInterval handle
let _isPaused      = false;   // true when tab is hidden
let _totalReceived = 0;       // total rows received this session
let _activeIds     = new Set(); // log_file_ids with live observers

/* ── DOM refs (populated in init) ────────────────────────────────────────── */
let _tbody        = null;
let _liveIndicator= null;
let _rowCounter   = null;
let _statusText   = null;
let _clearBtn     = null;
let _pauseBtn     = null;
let _statsPanel   = null;

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function _esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _rowClass(level) {
  const map = {
    DEBUG:    "",
    INFO:     "",
    WARNING:  "log-row-warning",
    ERROR:    "log-row-error",
    CRITICAL: "log-row-critical",
  };
  return map[level] || "";
}

function _buildRow(entry) {
  const ts     = entry.timestamp || "—";
  const level  = entry.level  || "INFO";
  const sev    = entry.severity || "low";
  const msg    = entry.message  || "";
  const source = entry.source_file || "—";

  const levelClass = LEVEL_BADGE[level]  || "level-badge-info";
  const sevClass   = SEV_BADGE[sev]      || "sev-low";
  const rowClass   = _rowClass(level);

  return `
<tr class="${rowClass} live-row-new" data-entry-id="${entry.id}">
  <td class="ps-3 text-nowrap">
    <span class="font-monospace small text-secondary d-block">${_esc(ts.slice(0,10))}</span>
    <span class="font-monospace small text-info fw-semibold">${_esc(ts.slice(11,19))}</span>
  </td>
  <td><span class="badge ${levelClass} px-2 py-1">${_esc(level)}</span></td>
  <td><span class="badge sev-badge ${sevClass}">${_esc(sev)}</span></td>
  <td class="small text-break log-message">${_esc(msg)}</td>
  <td class="small text-secondary text-truncate" style="max-width:150px;" title="${_esc(source)}">${_esc(source)}</td>
</tr>`;
}

function _trimTable() {
  if (!_tbody) return;
  const rows = _tbody.querySelectorAll("tr");
  if (rows.length > MAX_ROWS) {
    for (let i = MAX_ROWS; i < rows.length; i++) {
      rows[i].remove();
    }
  }
}

function _updateLiveIndicator(hasActive) {
  if (!_liveIndicator) return;
  if (hasActive) {
    _liveIndicator.classList.remove("d-none");
  } else {
    _liveIndicator.classList.add("d-none");
  }
}

function _updateStatusText() {
  if (!_statusText) return;
  const paused = _isPaused ? " (paused)" : "";
  _statusText.textContent = `${_totalReceived} entries received this session${paused}`;
}

function _showEmptyState(show) {
  const empty = document.getElementById("liveFeedEmpty");
  const table = document.getElementById("liveFeedTableWrap");
  if (!empty || !table) return;
  empty.classList.toggle("d-none", !show);
  table.classList.toggle("d-none",  show);
}

/* ── Stats panel update ───────────────────────────────────────────────────── */

async function _refreshStats() {
  if (!_statsPanel) return;
  try {
    const res  = await fetch("/api/monitor/stats");
    if (!res.ok) return;
    const data = await res.json();
    _renderStats(data);
  } catch (_) { /* silent */ }
}

function _renderStats(stats) {
  if (!_statsPanel) return;
  if (!stats.length) {
    _statsPanel.innerHTML = `
      <p class="text-secondary small text-center mb-0">No files are being monitored yet.</p>`;
    return;
  }

  const rows = stats.map(s => {
    const isActive = s.is_active;
    const dot  = isActive
      ? `<span class="live-pulse-dot me-2"></span>`
      : `<span class="d-inline-block rounded-circle bg-secondary me-2"
              style="width:8px;height:8px;"></span>`;
    const badge = isActive
      ? `<span class="badge bg-success">LIVE</span>`
      : `<span class="badge bg-secondary">STOPPED</span>`;
    const seen = s.last_seen_at
      ? `<span class="text-secondary small">Last event: ${_esc(s.last_seen_at)}</span>`
      : `<span class="text-secondary small">No events yet</span>`;

    return `
<div class="d-flex align-items-center justify-content-between flex-wrap gap-2 py-2
            border-bottom border-secondary border-opacity-25">
  <div class="d-flex align-items-center gap-2">
    ${dot}
    <div>
      <span class="fw-semibold small text-white">${_esc(s.source_filename)}</span>
      <div class="d-flex gap-2 mt-1 flex-wrap">
        ${seen}
        <span class="text-secondary small">·</span>
        <span class="text-secondary small">${s.total_entries} entries</span>
        ${s.error_count > 0
          ? `<span class="text-danger small">${s.error_count} errors</span>`
          : ""}
        ${s.critical_count > 0
          ? `<span class="text-danger small fw-bold">${s.critical_count} critical</span>`
          : ""}
      </div>
    </div>
  </div>
  ${badge}
</div>`;
  }).join("");

  _statsPanel.innerHTML = rows;
}

/* ── Core poll ────────────────────────────────────────────────────────────── */

async function _poll() {
  if (_isPaused) return;

  try {
    const url = `/api/monitor/live-feed?limit=50&after_id=${_lastId}`;
    const res = await fetch(url);
    if (!res.ok) return;

    const data = await res.json();

    // Update active set for indicator
    _activeIds = new Set(data.active_ids || []);
    _updateLiveIndicator(_activeIds.size > 0);

    const rows = data.rows || [];
    if (rows.length === 0) return;

    // Update the highest id seen
    if (data.max_id > _lastId) {
      _lastId = data.max_id;
    }

    _totalReceived += rows.length;
    _updateStatusText();

    // Build HTML for all new rows (they arrive newest-first from the API)
    const html = rows.map(_buildRow).join("");

    if (_tbody) {
      // Hide empty state, show table
      _showEmptyState(false);

      // Prepend rows (rows are already newest-first from API, so prepend keeps newest at top)
      _tbody.insertAdjacentHTML("afterbegin", html);
      _trimTable();

      // Flash animation — remove class after 1.5 s
      requestAnimationFrame(() => {
        setTimeout(() => {
          _tbody.querySelectorAll(".live-row-new").forEach(r => {
            r.classList.remove("live-row-new");
          });
        }, 1_500);
      });
    }

  } catch (_err) {
    // Network error — continue silently, next tick will retry
  }
}

/* ── Pause / resume on tab visibility ────────────────────────────────────── */

function _handleVisibility() {
  if (document.hidden) {
    _isPaused = true;
  } else {
    _isPaused = false;
    _poll();  // immediate poll on tab focus
  }
  _updateStatusText();
}

/* ── Public init ─────────────────────────────────────────────────────────── */

function initLiveFeed(options = {}) {
  _lastId = options.initialMaxId || 0;

  _tbody         = document.getElementById("liveFeedTbody");
  _liveIndicator = document.getElementById("liveIndicator");
  _rowCounter    = document.getElementById("liveRowCount");
  _statusText    = document.getElementById("liveStatusText");
  _clearBtn      = document.getElementById("liveClearBtn");
  _pauseBtn      = document.getElementById("livePauseBtn");
  _statsPanel    = document.getElementById("monitorStatsPanel");

  if (!_tbody) return;  // not on the monitor page

  // Clear button
  if (_clearBtn) {
    _clearBtn.addEventListener("click", () => {
      _tbody.innerHTML = "";
      _totalReceived   = 0;
      _updateStatusText();
      _showEmptyState(true);
    });
  }

  // Pause / Resume button
  if (_pauseBtn) {
    _pauseBtn.addEventListener("click", () => {
      _isPaused = !_isPaused;
      _pauseBtn.innerHTML = _isPaused
        ? `<i class="bi bi-play-fill me-1"></i>Resume`
        : `<i class="bi bi-pause-fill me-1"></i>Pause`;
      _pauseBtn.classList.toggle("btn-outline-warning", !_isPaused);
      _pauseBtn.classList.toggle("btn-outline-success",  _isPaused);
      _updateStatusText();
    });
  }

  // Page visibility
  document.addEventListener("visibilitychange", _handleVisibility);

  // Initial fetch
  _poll();
  _refreshStats();

  // Start polling loop
  _pollTimer = setInterval(() => {
    _poll();
    _refreshStats();
  }, POLL_MS);
}

// Auto-boot when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("liveFeedTbody")) {
    // Read the server-injected initial max id if provided
    const meta = document.getElementById("liveFeedMeta");
    const initialMaxId = meta ? parseInt(meta.dataset.maxId || "0", 10) : 0;
    initLiveFeed({ initialMaxId });
  }
});
