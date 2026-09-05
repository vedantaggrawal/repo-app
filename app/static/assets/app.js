"use strict";

/* Platform demo console.
 * No framework and no build step: the container ships exactly these bytes,
 * which keeps the image small and the Trivy surface to the Python base alone.
 */

const $ = (id) => document.getElementById(id);

const MAX_LOG_ROWS = 100;
const state = { latencies: [], total: 0, ok: 0, err: 0, ready: true };

/* ---------------- identity ---------------- */

function renderInfo(info) {
  $("i-pod").textContent = info.pod;
  $("i-node").textContent = info.node;
  $("i-namespace").textContent = info.namespace;
  $("i-environment").textContent = info.environment;
  $("i-version").textContent = info.version;
  $("i-git").textContent = info.git_sha;
  $("i-python").textContent = info.python;
  $("i-uptime").textContent = formatUptime(info.uptime_seconds);
  $("env-badge").textContent = info.environment;
  $("build-version").textContent = `v${info.version} · ${info.git_sha.slice(0, 7)}`;
}

function formatUptime(seconds) {
  const s = Math.floor(seconds);
  const parts = [
    [Math.floor(s / 86400), "d"],
    [Math.floor((s % 86400) / 3600), "h"],
    [Math.floor((s % 3600) / 60), "m"],
    [s % 60, "s"],
  ].filter(([value], i) => value > 0 || i === 3);
  return parts.map(([value, unit]) => `${value}${unit}`).join(" ");
}

async function refreshInfo() {
  try {
    const response = await fetch("/api/info", { cache: "no-store" });
    if (response.ok) renderInfo(await response.json());
  } catch {
    /* A failed refresh is not worth a log row; the next tick retries. */
  }
}

/* ---------------- request plumbing ---------------- */

async function call(method, path, { label } = {}) {
  const started = performance.now();
  let status = 0;
  let detail = "";

  try {
    const response = await fetch(path, { method, cache: "no-store" });
    status = response.status;
    const body = await response.text();
    detail = summarize(body);
  } catch (error) {
    detail = error.message || "network error";
  }

  const elapsed = performance.now() - started;
  record(method, label || path, status, elapsed, detail);
  return { status, elapsed };
}

function summarize(body) {
  if (!body) return "";
  try {
    const parsed = JSON.parse(body);
    if (parsed.detail) return String(parsed.detail);
    return Object.entries(parsed)
      .slice(0, 4)
      .map(([k, v]) => `${k}=${typeof v === "object" ? "{…}" : v}`)
      .join("  ");
  } catch {
    return body.slice(0, 120);
  }
}

/* ---------------- stats + log ---------------- */

function record(method, path, status, elapsed, detail) {
  state.total += 1;
  const succeeded = status >= 200 && status < 400;
  if (succeeded) state.ok += 1;
  else state.err += 1;
  state.latencies.push(elapsed);

  renderStats();
  appendRow(method, path, status, elapsed, detail, succeeded);
}

function percentile(sorted, p) {
  if (!sorted.length) return null;
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1);
  return sorted[index];
}

function renderStats() {
  $("s-total").textContent = state.total;
  $("s-ok").textContent = state.ok;
  $("s-err").textContent = state.err;

  const sorted = [...state.latencies].sort((a, b) => a - b);
  const p50 = percentile(sorted, 50);
  const p95 = percentile(sorted, 95);
  $("s-p50").textContent = p50 === null ? "—" : Math.round(p50);
  $("s-p95").textContent = p95 === null ? "—" : Math.round(p95);
}

function appendRow(method, path, status, elapsed, detail, succeeded) {
  const tbody = $("log");
  tbody.querySelector("tr.empty")?.remove();

  const row = document.createElement("tr");
  const cells = [
    new Date().toLocaleTimeString(),
    method,
    path,
    status || "ERR",
    Math.round(elapsed),
    detail,
  ];
  cells.forEach((value, i) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    if (i === 3) cell.className = succeeded ? "status-ok" : "status-err";
    if (i === 4) cell.className = "num";
    if (i === 5) cell.className = "detail";
    row.appendChild(cell);
  });

  tbody.prepend(row);
  while (tbody.children.length > MAX_LOG_ROWS) tbody.lastElementChild.remove();
}

/* ---------------- load generation ---------------- */

/** Run `total` requests with at most `concurrency` in flight. */
async function runPool(total, concurrency, makeRequest) {
  let issued = 0;
  const worker = async () => {
    while (issued < total) {
      issued += 1;
      await makeRequest();
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, total) }, worker));
}

async function withBusy(button, work) {
  const wasDisabled = button.disabled;
  button.disabled = true;
  try {
    await work();
  } finally {
    button.disabled = wasDisabled;
  }
}

/* ---------------- wiring ---------------- */

function bindSlider(input, output) {
  const sync = () => { output.textContent = input.value; };
  input.addEventListener("input", sync);
  sync();
}

function init() {
  bindSlider($("latency"), $("latency-out"));
  bindSlider($("burn"), $("burn-out"));

  $("btn-load").addEventListener("click", (event) =>
    withBusy(event.currentTarget, () => {
      const ms = $("latency").value;
      const burn = $("burn").value;
      const total = Number($("count").value);
      const concurrency = Number($("concurrency").value);
      const path = `/api/work?ms=${ms}&burn_ms=${burn}`;
      return runPool(total, concurrency, () => call("GET", path, { label: "/api/work" }));
    }),
  );

  $("btn-error").addEventListener("click", (event) =>
    withBusy(event.currentTarget, () =>
      call("GET", `/api/error?code=${$("code").value}`, { label: "/api/error" }),
    ),
  );

  $("btn-downstream").addEventListener("click", (event) =>
    withBusy(event.currentTarget, () => call("GET", "/api/downstream")),
  );

  $("btn-echo").addEventListener("click", (event) =>
    withBusy(event.currentTarget, () => call("GET", "/api/echo")),
  );

  $("btn-ready").addEventListener("click", (event) =>
    withBusy(event.currentTarget, async () => {
      const next = !state.ready;
      const { status } = await call("POST", `/api/ready?ready=${next}`, { label: "/api/ready" });
      if (status === 200) {
        state.ready = next;
        event.currentTarget.textContent = next ? "Mark unready" : "Mark ready";
      }
    }),
  );

  $("btn-clear").addEventListener("click", () => {
    state.latencies = [];
    state.total = state.ok = state.err = 0;
    renderStats();
    $("log").innerHTML = '<tr class="empty"><td colspan="6">No requests yet.</td></tr>';
  });

  const clock = $("clock");
  const tick = () => {
    clock.textContent = new Date().toLocaleString(undefined, {
      weekday: "short", year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
    });
  };
  tick();
  setInterval(tick, 1000);

  refreshInfo();
  setInterval(refreshInfo, 5000);
}

document.addEventListener("DOMContentLoaded", init);
