/**
 * WhatsApp Bridge — Express HTTP server wrapping Baileys.
 *
 * FRIDAY (Python) talks to this over localhost HTTP.
 * Baileys handles the WhatsApp Web multi-device connection.
 *
 * Endpoints:
 *   GET  /status          — connection status + QR if pending
 *   POST /send            — send a text message
 *   GET  /chats           — list recent chats
 *   GET  /messages/:jid   — read messages from a chat
 *   GET  /search          — search messages by text
 *   POST /read            — mark messages as read
 *   POST /logout          — disconnect + clear auth
 */

const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");
const express = require("express");
const path = require("path");
const fs = require("fs");
const pino = require("pino");
const qrcode = require("qrcode-terminal");

const app = express();
app.use(express.json());

const PORT = process.env.WA_BRIDGE_PORT || 3100;
// Auth state lives outside the repo — credentials should never be committed
const HOME = require("os").homedir();
const AUTH_DIR = path.join(HOME, ".friday", "whatsapp", "auth_state");

// Quiet logger — only errors
const logger = pino({ level: "error" });

// ── State ──────────────────────────────────────────────────────────────────

let sock = null;
let connectionState = "disconnected"; // disconnected | qr_pending | connected
let currentQR = null;
let retryCount = 0;
const MAX_RETRIES = 5;

// Persistent message store — survives restarts
const STORE_FILE = path.join(HOME, ".friday", "whatsapp", "message_store.json");
const MAX_MESSAGES_PER_CHAT = 200;
let messageStore = new Map(); // jid -> [msg, msg, ...]
let chatMeta = new Map(); // jid -> { name, lastMessage, timestamp }
let contactNames = new Map(); // jid -> display name (from contacts sync + pushNames)
let _savePending = false;

function _loadStore() {
  try {
    if (fs.existsSync(STORE_FILE)) {
      const raw = JSON.parse(fs.readFileSync(STORE_FILE, "utf8"));
      if (raw.messages) {
        for (const [jid, msgs] of Object.entries(raw.messages)) {
          messageStore.set(jid, msgs);
        }
      }
      if (raw.chats) {
        for (const [jid, meta] of Object.entries(raw.chats)) {
          chatMeta.set(jid, meta);
        }
      }
      if (raw.contacts) {
        for (const [jid, name] of Object.entries(raw.contacts)) {
          contactNames.set(jid, name);
        }
      }
      console.log(`[WA Bridge] Loaded store: ${messageStore.size} chats, ${Array.from(messageStore.values()).reduce((a, b) => a + b.length, 0)} messages`);
    }
  } catch (err) {
    console.error("[WA Bridge] Failed to load store:", err.message);
  }
}

function _saveStore() {
  if (_savePending) return;
  _savePending = true;
  // Debounce — save at most once per 2 seconds
  setTimeout(() => {
    _savePending = false;
    try {
      const data = {
        messages: Object.fromEntries(messageStore),
        chats: Object.fromEntries(chatMeta),
        contacts: Object.fromEntries(contactNames),
        saved_at: new Date().toISOString(),
      };
      fs.writeFileSync(STORE_FILE, JSON.stringify(data), "utf8");
    } catch (err) {
      console.error("[WA Bridge] Failed to save store:", err.message);
    }
  }, 2000);
}

// Load on startup
_loadStore();

function storeMessage(jid, msg) {
  if (!messageStore.has(jid)) messageStore.set(jid, []);
  const msgs = messageStore.get(jid);
  // Deduplicate by message ID
  const id = msg.key?.id;
  if (id && msgs.some((m) => m.key?.id === id)) return;
  msgs.push(msg);
  if (msgs.length > MAX_MESSAGES_PER_CHAT) msgs.shift();
  _saveStore();
}

function serializeMessage(msg) {
  const key = msg.key || {};
  let text = "";

  if (msg.message) {
    const m = msg.message;
    text =
      m.conversation ||
      m.extendedTextMessage?.text ||
      m.interactiveMessage?.body?.text ||
      m.imageMessage?.caption ||
      m.videoMessage?.caption ||
      m.documentMessage?.fileName ||
      m.listMessage?.description ||
      m.templateMessage?.hydratedTemplate?.hydratedContentText ||
      m.buttonsMessage?.contentText ||
      m.listResponseMessage?.title ||
      m.buttonsResponseMessage?.selectedDisplayText ||
      (m.audioMessage ? "[voice note]" : "") ||
      (m.stickerMessage ? "[sticker]" : "") ||
      (m.contactMessage || m.contactsArrayMessage ? "[contact]" : "") ||
      (m.locationMessage
        ? `[location: ${m.locationMessage.degreesLatitude}, ${m.locationMessage.degreesLongitude}]`
        : "") ||
      (m.reactionMessage ? `[reaction: ${m.reactionMessage.text}]` : "") ||
      (m.pollCreationMessage || m.pollCreationMessageV3 ? `[poll: ${(m.pollCreationMessage || m.pollCreationMessageV3)?.name}]` : "") ||
      (m.protocolMessage ? "" : "") || // system messages, skip
      "";
  }

  return {
    id: key.id,
    from_me: !!key.fromMe,
    jid: key.remoteJid,
    participant: key.participant || null,
    text,
    timestamp: typeof msg.messageTimestamp === "object"
      ? msg.messageTimestamp.low
      : msg.messageTimestamp || 0,
    push_name: msg.pushName || null,
    status: msg.status || null,
  };
}

// ── Baileys connection ─────────────────────────────────────────────────────

async function connectWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    // QR handled manually via connection.update event + qrcode-terminal
    browser: ["FRIDAY", "Desktop", "1.0.0"],
    syncFullHistory: true,
    markOnlineOnConnect: false,
    generateHighQualityLinkPreview: false,
    getMessage: async (key) => {
      // Try to retrieve from store for retry/resend
      const msgs = messageStore.get(key.remoteJid) || [];
      const found = msgs.find((m) => m.key?.id === key.id);
      return found?.message || undefined;
    },
  });

  // Save credentials on update
  sock.ev.on("creds.update", saveCreds);

  // Connection state
  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentQR = qr;
      connectionState = "qr_pending";
      console.log("\n[WA Bridge] Scan this QR code with WhatsApp → Linked Devices → Link a Device:\n");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      connectionState = "connected";
      currentQR = null;
      retryCount = 0;
      console.log("[WA Bridge] Connected to WhatsApp");

      // Fetch group names for all group chats in the store
      setTimeout(async () => {
        let fetched = 0;
        for (const jid of chatMeta.keys()) {
          if (!jid.endsWith("@g.us")) continue;
          const meta = chatMeta.get(jid);
          // Always fetch group metadata — pushNames often overwrite the real group subject
          try {
            const groupMeta = await sock.groupMetadata(jid);
            if (groupMeta?.subject) {
              meta.name = groupMeta.subject;
              chatMeta.set(jid, meta);
              fetched++;
            }
          } catch {}
        }
        if (fetched > 0) {
          console.log(`[WA Bridge] Fetched ${fetched} group names`);
          _saveStore();
        }
      }, 3000);
    }

    if (connection === "close") {
      connectionState = "disconnected";
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect =
        statusCode !== DisconnectReason.loggedOut;

      console.log(
        `[WA Bridge] Disconnected (code=${statusCode}), reconnect=${shouldReconnect}`
      );

      if (shouldReconnect && retryCount < MAX_RETRIES) {
        retryCount++;
        const delay = Math.min(retryCount * 2000, 15000);
        console.log(
          `[WA Bridge] Reconnecting in ${delay / 1000}s (attempt ${retryCount}/${MAX_RETRIES})`
        );
        setTimeout(connectWhatsApp, delay);
      } else if (statusCode === DisconnectReason.loggedOut) {
        console.log("[WA Bridge] Logged out — clearing auth state");
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
      }
    }
  });

  // Incoming messages
  sock.ev.on("messages.upsert", ({ messages, type }) => {
    for (const msg of messages) {
      const jid = msg.key?.remoteJid;
      if (!jid || jid === "status@broadcast") continue;
      storeMessage(jid, msg);

      // Save pushName as contact name (live messages have this, history doesn't)
      if (msg.pushName && !msg.key?.fromMe) {
        const senderJid = msg.key?.participant || jid;
        contactNames.set(senderJid, msg.pushName);
      }

      // Update chat metadata — don't overwrite group names with individual pushNames
      const serialized = serializeMessage(msg);
      const existingMeta = chatMeta.get(jid);
      const isGroup = jid.endsWith("@g.us");
      const keepName = isGroup && existingMeta?.name && !/^\d+[-\d]*$/.test(existingMeta.name);
      chatMeta.set(jid, {
        jid,
        name: keepName ? existingMeta.name : (isGroup ? (existingMeta?.name || jid.split("@")[0]) : (msg.pushName || contactNames.get(jid) || jid.split("@")[0])),
        lastMessage: serialized.text,
        timestamp: serialized.timestamp,
        fromMe: serialized.from_me,
      });
    }
    _saveStore();
  });

  // History sync — store messages from history
  sock.ev.on("messaging-history.set", ({ messages, chats }) => {
    for (const msg of messages) {
      const jid = msg.key?.remoteJid;
      if (!jid || jid === "status@broadcast") continue;
      storeMessage(jid, msg);
    }
    for (const chat of chats) {
      if (chat.id && chat.id !== "status@broadcast") {
        chatMeta.set(chat.id, {
          jid: chat.id,
          name: chat.name || chat.id.split("@")[0],
          lastMessage: chatMeta.get(chat.id)?.lastMessage || "",
          timestamp: chat.conversationTimestamp || 0,
          fromMe: false,
        });
      }
    }
    console.log(
      `[WA Bridge] History sync: ${messages.length} messages, ${chats.length} chats`
    );
    _saveStore();
  });

  // Contact name sync — this is how we get real names
  sock.ev.on("contacts.upsert", (contacts) => {
    for (const c of contacts) {
      if (c.id && c.id !== "status@broadcast") {
        const name = c.notify || c.verifiedName || c.name || null;
        if (name) {
          contactNames.set(c.id, name);
          // Also update chatMeta name if it's just a number
          const meta = chatMeta.get(c.id);
          if (meta && /^\d+$/.test(meta.name)) {
            meta.name = name;
            chatMeta.set(c.id, meta);
          }
        }
      }
    }
    _saveStore();
  });

  sock.ev.on("contacts.update", (updates) => {
    for (const c of updates) {
      if (c.id && c.id !== "status@broadcast") {
        const name = c.notify || c.verifiedName || c.name || null;
        if (name) {
          contactNames.set(c.id, name);
          const meta = chatMeta.get(c.id);
          if (meta && /^\d+$/.test(meta.name)) {
            meta.name = name;
            chatMeta.set(c.id, meta);
          }
        }
      }
    }
    _saveStore();
  });

  // Chat updates (name changes, etc.)
  sock.ev.on("chats.upsert", (chats) => {
    for (const chat of chats) {
      if (!chat.id || chat.id === "status@broadcast") continue;
      const existing = chatMeta.get(chat.id) || {};
      chatMeta.set(chat.id, {
        ...existing,
        jid: chat.id,
        name: chat.name || existing.name || chat.id.split("@")[0],
      });
    }
    _saveStore();
  });
}

// ── Helper: resolve phone number to JID ────────────────────────────────────

function toJid(input) {
  if (!input) return null;
  input = input.trim();
  // Already a JID
  if (input.includes("@")) return input;
  // Strip everything except digits and leading +
  let digits = input.replace(/[^\d]/g, "");
  if (!digits) return null;
  return `${digits}@s.whatsapp.net`;
}

// Find JID by contact name (fuzzy match against contacts, chat names, pushNames)
function findJidByName(name) {
  const lower = name.toLowerCase();
  const matches = [];
  const seen = new Set();

  // 1. Check contactNames map (most reliable — real names)
  for (const [jid, cName] of contactNames.entries()) {
    const cl = (cName || "").toLowerCase();
    if (cl.includes(lower) || lower.includes(cl)) {
      seen.add(jid);
      matches.push({ jid, name: cName, score: cl === lower ? 3 : 2 });
    }
  }

  // 2. Check chatMeta names
  for (const [jid, meta] of chatMeta.entries()) {
    if (seen.has(jid)) continue;
    const chatName = (meta.name || "").toLowerCase();
    if (chatName.includes(lower) || lower.includes(chatName)) {
      seen.add(jid);
      matches.push({ jid, name: meta.name, score: chatName === lower ? 2 : 1 });
    }
  }

  // 3. Check pushNames from messages (fallback)
  for (const [jid, msgs] of messageStore.entries()) {
    if (seen.has(jid)) continue;
    for (const msg of msgs) {
      const pushName = (msg.pushName || "").toLowerCase();
      if (pushName && (pushName.includes(lower) || lower.includes(pushName))) {
        matches.push({ jid, name: msg.pushName, score: pushName === lower ? 2 : 1 });
        break;
      }
    }
  }

  // Prefer individual chats over groups
  matches.sort((a, b) => {
    const aIsGroup = a.jid.endsWith("@g.us") ? 0 : 1;
    const bIsGroup = b.jid.endsWith("@g.us") ? 0 : 1;
    if (aIsGroup !== bIsGroup) return bIsGroup - aIsGroup;
    return b.score - a.score;
  });

  return matches[0] || null;
}

// ── API Endpoints ──────────────────────────────────────────────────────────

// Health + connection status
app.get("/status", (req, res) => {
  const user = sock?.user || null;
  res.json({
    status: connectionState,
    qr: currentQR,
    user: user
      ? { id: user.id, name: user.name || user.id.split("@")[0] }
      : null,
  });
});

// Send a text message
app.post("/send", async (req, res) => {
  try {
    const { to, message, quote_id } = req.body;
    if (!to || !message) {
      return res.status(400).json({ error: "Missing 'to' and/or 'message'" });
    }
    if (connectionState !== "connected") {
      return res.status(503).json({ error: "WhatsApp not connected", status: connectionState });
    }

    // Resolve recipient — try JID, then phone, then name lookup
    let jid = toJid(to);
    if (!jid) {
      const match = findJidByName(to);
      if (match) jid = match.jid;
    }
    if (!jid) {
      return res.status(400).json({ error: `Could not resolve recipient: ${to}` });
    }

    const content = { text: message };

    // If quoting a message
    if (quote_id) {
      const msgs = messageStore.get(jid) || [];
      const quoted = msgs.find((m) => m.key?.id === quote_id);
      if (quoted) content.quoted = quoted;
    }

    const sent = await sock.sendMessage(jid, content);
    res.json({
      success: true,
      id: sent?.key?.id,
      to: jid,
      timestamp: sent?.messageTimestamp,
    });
  } catch (err) {
    console.error("[WA Bridge] Send error:", err.message);
    res.status(500).json({ error: err.message });
  }
});

// List recent chats
app.get("/chats", (req, res) => {
  const limit = parseInt(req.query.limit) || 30;
  const chats = Array.from(chatMeta.values())
    .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
    .slice(0, limit)
    .map((c) => ({
      jid: c.jid,
      name: contactNames.get(c.jid) || c.name,
      last_message: c.lastMessage,
      timestamp: c.timestamp,
      from_me: c.fromMe,
      is_group: c.jid?.endsWith("@g.us") || false,
    }));
  res.json({ chats, count: chats.length });
});

// Read messages from a specific chat
app.get("/messages/:jid", (req, res) => {
  const jid = req.params.jid;
  const limit = parseInt(req.query.limit) || 30;

  const msgs = (messageStore.get(jid) || [])
    .slice(-limit)
    .map(serializeMessage);

  res.json({ messages: msgs, count: msgs.length, jid });
});

// Read messages by contact name or phone
app.get("/messages", (req, res) => {
  const { contact, phone, limit: limitStr } = req.query;
  const limit = parseInt(limitStr) || 30;

  let jid = null;
  if (phone) {
    jid = toJid(phone);
  } else if (contact) {
    const match = findJidByName(contact);
    if (match) jid = match.jid;
  }

  if (!jid) {
    return res.status(404).json({
      error: `Contact not found: ${contact || phone}`,
      hint: "Try using the phone number with country code, or check /chats for available contacts.",
    });
  }

  const msgs = (messageStore.get(jid) || [])
    .slice(-limit)
    .map(serializeMessage);

  res.json({ messages: msgs, count: msgs.length, jid, name: contactNames.get(jid) || chatMeta.get(jid)?.name || null });
});

// Search messages across all chats
app.get("/search", (req, res) => {
  const { query, limit: limitStr } = req.query;
  const limit = parseInt(limitStr) || 20;

  if (!query) {
    return res.status(400).json({ error: "Missing 'query' parameter" });
  }

  const lower = query.toLowerCase();
  const results = [];

  for (const [jid, msgs] of messageStore.entries()) {
    for (const msg of msgs) {
      const serialized = serializeMessage(msg);
      if (serialized.text.toLowerCase().includes(lower)) {
        results.push({
          ...serialized,
          chat_name: chatMeta.get(jid)?.name || jid.split("@")[0],
        });
      }
      if (results.length >= limit) break;
    }
    if (results.length >= limit) break;
  }

  results.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));
  res.json({ results: results.slice(0, limit), count: results.length, query });
});

// Mark messages as read
app.post("/read", async (req, res) => {
  try {
    const { jid, ids } = req.body;
    if (!jid) {
      return res.status(400).json({ error: "Missing 'jid'" });
    }
    if (connectionState !== "connected") {
      return res.status(503).json({ error: "WhatsApp not connected" });
    }

    const keys = (ids || []).map((id) => ({
      remoteJid: jid,
      id,
      fromMe: false,
    }));

    if (keys.length) {
      await sock.readMessages(keys);
    }

    res.json({ success: true, marked: keys.length });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Check if a number is on WhatsApp
app.get("/check/:phone", async (req, res) => {
  try {
    if (connectionState !== "connected") {
      return res.status(503).json({ error: "WhatsApp not connected" });
    }
    const jid = toJid(req.params.phone);
    if (!jid) return res.status(400).json({ error: "Invalid phone number" });

    const [result] = await sock.onWhatsApp(jid.split("@")[0]);
    res.json({
      exists: !!result?.exists,
      jid: result?.jid || null,
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Logout and clear auth
app.post("/logout", async (req, res) => {
  try {
    if (sock) {
      await sock.logout("User requested logout");
    }
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    connectionState = "disconnected";
    currentQR = null;
    res.json({ success: true, message: "Logged out and auth cleared" });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Start ──────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`[WA Bridge] HTTP server listening on port ${PORT}`);
  connectWhatsApp().catch((err) => {
    console.error("[WA Bridge] Failed to connect:", err.message);
  });
});
