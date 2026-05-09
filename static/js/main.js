/**
 * main.js
 * Global JavaScript for Smart Log Monitoring & Alert System.
 */

"use strict";

/* ── Alert badge updater ─────────────────────────────────── */

/**
 * Polls the /api/alerts/unread-count endpoint every 30 seconds
 * and updates the navbar badge accordingly.
 */
async function refreshAlertBadge() {
  try {
    const res = await fetch("/api/alerts/unread-count");
    if (!res.ok) return;

    const data = await res.json();
    const badge = document.getElementById("alert-badge");
    if (!badge) return;

    if (data.unread > 0) {
      badge.textContent = data.unread > 99 ? "99+" : data.unread;
      badge.classList.remove("d-none");
    } else {
      badge.classList.add("d-none");
    }
  } catch (_err) {
    // Silently fail — badge is non-critical UI
  }
}

// Run once on load, then every 30 seconds
refreshAlertBadge();
setInterval(refreshAlertBadge, 30_000);


/* ── Auto-dismiss flash messages ────────────────────────── */

/**
 * Automatically dismiss Bootstrap alert banners after 5 seconds.
 */
document.addEventListener("DOMContentLoaded", () => {
  const flashAlerts = document.querySelectorAll(".alert.alert-dismissible");
  flashAlerts.forEach(el => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });
});


/* ── Table row click navigation ─────────────────────────── */

/**
 * Makes table rows with a data-href attribute navigable on click.
 * Usage: <tr data-href="/logs/5"> ... </tr>
 */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("tr[data-href]").forEach(row => {
    row.style.cursor = "pointer";
    row.addEventListener("click", () => {
      window.location.href = row.dataset.href;
    });
  });
});


/* ── Utility: format bytes ───────────────────────────────── */

/**
 * Convert a byte count into a human-readable string.
 * @param {number} bytes
 * @returns {string}
 */
function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}


/* ── Monitor status dot ──────────────────────────────────── */

/**
 * Polls /api/monitor/status every 8 seconds.
 * If any observer is alive, shows a pulsing green dot on the
 * "Live Monitor" nav link.
 */
async function refreshMonitorDot() {
  try {
    const res  = await fetch("/api/monitor/status");
    if (!res.ok) return;
    const data = await res.json();
    const dot  = document.getElementById("monitor-dot");
    if (!dot) return;
    if (Array.isArray(data) && data.some(m => m.observer_alive)) {
      dot.classList.remove("d-none");
    } else {
      dot.classList.add("d-none");
    }
  } catch (_) { /* silent */ }
}

refreshMonitorDot();
setInterval(refreshMonitorDot, 8_000);
