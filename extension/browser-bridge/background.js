/**
 * FRIDAY Browser Bridge — service worker (Manifest V3).
 *
 * Maintains a persistent WebSocket to ws://127.0.0.1:3210 (FRIDAY's
 * browser-ext bridge), authenticates with the user-supplied token,
 * sends heartbeats listing open tabs, and dispatches incoming actions
 * to the right tab via chrome.tabs.sendMessage.
 *
 * Auto-reconnects on disconnect with exponential backoff (1s → 30s).
 *
 * Token storage: chrome.storage.local (user pastes it in the popup).
 */

const WS_URL = "ws://127.0.0.1:3210";
const HEARTBEAT_INTERVAL_MS = 5000;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const VERSION = "0.1.0";

let socket = null;
let connected = false;
let reconnectAttempt = 0;
let reconnectTimer = null;
let heartbeatTimer = null;
let pendingResults = new Map();   // for future use — we ack actions inline

// ── Token plumbing ────────────────────────────────────────────────────────

async function getToken() {
  const res = await chrome.storage.local.get("token");
  return (res.token || "").trim();
}

// ── Connection lifecycle ──────────────────────────────────────────────────

async function connect() {
  const token = await getToken();
  if (!token) {
    console.warn("[FRIDAY] no token set — open the popup to paste it.");
    setStatus({ connected: false, reason: "no token" });
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) return;

  try {
    socket = new WebSocket(WS_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({
      type: "hello",
      token,
      name: "FRIDAY Browser Bridge",
      version: VERSION,
    }));
  });

  socket.addEventListener("message", (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }

    if (msg.type === "hello_ack") {
      connected = true;
      reconnectAttempt = 0;
      setStatus({ connected: true });
      console.log("[FRIDAY] bridge connected");
      startHeartbeat();
      return;
    }

    // Anything else with an id is an action request from the bridge
    if (msg.id && msg.action) {
      handleAction(msg).catch(err => {
        sendResult(msg.id, false, null, String(err));
      });
    }
  });

  socket.addEventListener("close", (ev) => {
    connected = false;
    setStatus({ connected: false, reason: ev.reason || "closed" });
    stopHeartbeat();
    if (ev.code === 1008) {
      // Auth failure — don't auto-retry until user updates token
      console.warn("[FRIDAY] bridge auth failed:", ev.reason);
      return;
    }
    scheduleReconnect();
  });

  socket.addEventListener("error", () => {
    // close handler will fire next; reconnect from there
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectAttempt += 1;
  const wait = Math.min(
    RECONNECT_BASE_MS * Math.pow(2, reconnectAttempt - 1),
    RECONNECT_MAX_MS,
  );
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, wait);
}

// ── Heartbeat ─────────────────────────────────────────────────────────────

function startHeartbeat() {
  stopHeartbeat();
  heartbeatTimer = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
  sendHeartbeat();
}

function stopHeartbeat() {
  if (heartbeatTimer) {
    clearInterval(heartbeatTimer);
    heartbeatTimer = null;
  }
}

async function sendHeartbeat() {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  try {
    const tabs = await chrome.tabs.query({});
    socket.send(JSON.stringify({
      type: "heartbeat",
      tabs: tabs.map(t => ({
        id: t.id, url: t.url, title: t.title, active: t.active,
      })),
    }));
  } catch (e) {
    // best-effort
  }
}

// ── Action handler — dispatches each command to its appropriate target ─────

async function handleAction(msg) {
  const { id, action, metadata = {} } = msg;
  try {
    switch (action) {
      case "ping":
        return sendResult(id, true, { pong: true });

      // ── Tab control (no content script needed) ─────────────────────
      case "navigate":         return sendResult(id, ...await actNavigate(metadata));
      case "get_active_tab":   return sendResult(id, ...await actGetActiveTab(metadata));
      case "list_tabs":        return sendResult(id, ...await actListTabs(metadata));

      // ── DOM operations — forwarded to the content script ────────────
      case "click":
      case "fill":
      case "get_text":
      case "scroll":
      case "scanning_start":
      case "scanning_stop":
      case "highlight":
        return sendResult(id, ...await actForwardToContent(action, metadata));

      default:
        return sendResult(id, false, null, `unsupported action: ${action}`);
    }
  } catch (e) {
    sendResult(id, false, null, String(e?.message || e));
  }
}

// ── Action implementations ──────────────────────────────────────────────

async function actNavigate({ url, tab_id }) {
  if (!url) return [false, null, "url required"];
  let target = tab_id ? await chrome.tabs.get(tab_id).catch(() => null)
                      : await activeTab();
  if (!target) return [false, null, "no target tab"];
  await chrome.tabs.update(target.id, { url });
  // Wait for the page to start loading at minimum
  return [true, { tab_id: target.id, url }, null];
}

async function actGetActiveTab({ include_text = true } = {}) {
  const tab = await activeTab();
  if (!tab) return [false, null, "no active tab"];
  let text = "";
  let title = tab.title || "";
  if (include_text) {
    try {
      const resp = await chrome.tabs.sendMessage(tab.id, {
        type: "friday_get_text", selector: null,
      });
      if (resp?.ok) {
        text = (resp.data?.text || "").slice(0, 8000);
        title = resp.data?.title || title;
      }
    } catch {
      // content script not ready (e.g. chrome:// page)
    }
  }
  return [true, { tab_id: tab.id, url: tab.url, title, text }, null];
}

async function actListTabs() {
  const tabs = await chrome.tabs.query({});
  return [true, {
    tabs: tabs.map(t => ({
      id: t.id, url: t.url, title: t.title, active: t.active,
    })),
  }, null];
}

async function actForwardToContent(action, metadata) {
  const tab_id = metadata.tab_id || (await activeTab())?.id;
  if (!tab_id) return [false, null, "no tab"];
  try {
    const resp = await chrome.tabs.sendMessage(tab_id, {
      type: `friday_${action}`,
      ...metadata,
    });
    if (!resp) return [false, null, "no response from content script"];
    return [resp.ok === true, resp.data ?? null, resp.error || null];
  } catch (e) {
    return [false, null, `tabs.sendMessage failed: ${e.message}`];
  }
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

function sendResult(id, ok, data, error) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({
    type: "result",
    id,
    ok,
    data: data ?? null,
    error: error ?? null,
  }));
}

// ── Status surfacing for the popup ────────────────────────────────────────

let lastStatus = { connected: false, reason: "starting" };

function setStatus(s) {
  lastStatus = { ...lastStatus, ...s, at: Date.now() };
  chrome.storage.local.set({ status: lastStatus }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "status") {
    sendResponse(lastStatus);
    return true;
  }
  if (msg?.type === "reconnect") {
    if (socket) try { socket.close(); } catch {}
    reconnectAttempt = 0;
    connect();
    sendResponse({ ok: true });
    return true;
  }
});

// Boot
chrome.runtime.onInstalled.addListener(() => connect());
chrome.runtime.onStartup.addListener(() => connect());
connect();
