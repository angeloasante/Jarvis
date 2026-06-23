/**
 * FRIDAY Browser Bridge — content script.
 *
 * Lives inside every web page. Listens for `friday_*` messages from the
 * extension's service worker (background.js), runs DOM operations, and
 * paints the "AI is reading" visual overlay.
 *
 * Visual overlay borrowed in spirit from Moonwalk (MIT) — page-wide
 * scanning frame with a moving beam, plus per-element highlight rings.
 */

(function () {
  if (window.__FRIDAY_BRIDGE_LOADED__) return;
  window.__FRIDAY_BRIDGE_LOADED__ = true;
  console.debug("[FRIDAY] content script loaded —", location.hostname);

  // ── Message router ────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg?.type || !msg.type.startsWith("friday_")) return false;
    const handler = HANDLERS[msg.type];
    if (!handler) {
      sendResponse({ ok: false, error: `unknown action: ${msg.type}` });
      return true;
    }
    Promise.resolve()
      .then(() => handler(msg))
      .then((result) => sendResponse({ ok: true, data: result }))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true; // async response
  });

  // ── DOM helpers ───────────────────────────────────────────────────────

  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || cs.opacity === "0") return false;
    return true;
  }

  function findBySelectorOrText({ selector, text }) {
    if (selector) {
      const el = document.querySelector(selector);
      if (el && visible(el)) return el;
    }
    if (text) {
      const needle = text.toLowerCase().trim();
      // Prioritise interactive elements
      const candidates = document.querySelectorAll(
        "button, a, [role='button'], [role='link'], input[type='button'], input[type='submit']"
      );
      for (const el of candidates) {
        const t = (el.innerText || el.value || el.getAttribute("aria-label") || "").toLowerCase().trim();
        if (t && t.includes(needle) && visible(el)) return el;
      }
    }
    return null;
  }

  function readabilityText(rootSelector) {
    const root = rootSelector ? document.querySelector(rootSelector) : document.body;
    if (!root) return "";
    // Only strip the *truly noisy* tags — script/style/noscript. Stripping
    // nav/aside/footer is too aggressive: portfolio + landing pages put
    // their main content inside semantic header/aside/nav and removing
    // those leaves an empty body. The LLM filters minor chrome on its
    // own; better to send too much than nothing.
    const clone = root.cloneNode(true);
    clone.querySelectorAll("script, style, noscript, template").forEach(n => n.remove());
    let text = (clone.innerText || "").replace(/\s+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    // Fallback for sites that hide content with display:none until a
    // route renders — innerText returns nothing but textContent has it.
    if (text.length < 30) {
      const fallback = (clone.textContent || "").replace(/\s+/g, " ").trim();
      if (fallback.length > text.length) text = fallback;
    }
    return text;
  }

  // ── Action handlers ──────────────────────────────────────────────────

  const HANDLERS = {
    friday_click(msg) {
      const el = findBySelectorOrText(msg);
      if (!el) throw new Error(`element not found: ${msg.selector || msg.text}`);
      flashHighlight(el, 600);
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      el.click();
      return { tag: el.tagName, text: (el.innerText || el.value || "").slice(0, 80) };
    },

    friday_fill(msg) {
      const el = msg.selector ? document.querySelector(msg.selector) : null;
      if (!el) throw new Error(`element not found: ${msg.selector}`);
      el.focus();
      flashHighlight(el, 600);
      // Set value + dispatch native events so React/Vue/Angular notice
      const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
                  : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
      setter.call(el, msg.value || "");
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return { value: el.value };
    },

    friday_get_text(msg) {
      const text = readabilityText(msg.selector);
      return { title: document.title, url: location.href, text };
    },

    friday_scroll(msg) {
      const { x = 0, y = 0, by = false } = msg;
      if (by) window.scrollBy({ left: x, top: y, behavior: "smooth" });
      else   window.scrollTo({ left: x, top: y, behavior: "smooth" });
      return { scrollX: window.scrollX, scrollY: window.scrollY };
    },

    friday_scanning_start(msg) {
      startScanning(msg.label || "FRIDAY analysing page…", Number(msg.duration_ms) || 4000);
      return { started: true };
    },

    friday_scanning_stop() {
      stopScanning();
      return { stopped: true };
    },

    friday_highlight(msg) {
      const el = findBySelectorOrText(msg);
      if (!el) throw new Error("element not found");
      flashHighlight(el, Number(msg.duration_ms) || 1500);
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      return { ok: true };
    },
  };

  // ── Visual overlay (CSS-only animations, max-z-index, isolated stacking) ─

  ensureStyles();

  function ensureStyles() {
    if (document.getElementById("__friday_bridge_styles")) return;
    const style = document.createElement("style");
    style.id = "__friday_bridge_styles";
    style.textContent = `
      @property --fr-angle {
        syntax: '<angle>';
        initial-value: 0deg;
        inherits: false;
      }
      @keyframes fr-rotate { to { --fr-angle: 360deg; } }
      @keyframes fr-fade-in { from { opacity: 0; } to { opacity: 1; } }
      @keyframes fr-fade-out { from { opacity: 1; } to { opacity: 0; } }
      @keyframes fr-beam {
        0%   { top: -8px;     opacity: 0; }
        5%   { opacity: 1; }
        95%  { opacity: 1; }
        100% { top: 100vh;    opacity: 0; }
      }
      .friday-hl {
        position: relative !important;
        isolation: isolate !important;
        outline: 2px solid transparent !important;
        outline-offset: 2px !important;
      }
      .friday-hl::before {
        content: '' !important;
        position: absolute !important;
        inset: -3px !important;
        border-radius: 12px !important;
        pointer-events: none !important;
        z-index: 2147483640 !important;
        background: conic-gradient(
          from var(--fr-angle),
          transparent 55%,
          #af52de 75%,
          #007aff 95%,
          transparent 100%
        ) !important;
        -webkit-mask:
          linear-gradient(#fff 0 0) content-box,
          linear-gradient(#fff 0 0) !important;
        -webkit-mask-composite: xor !important;
                mask-composite: exclude !important;
        padding: 2px !important;
        animation: fr-rotate 3s linear infinite, fr-fade-in 0.35s ease both !important;
      }
      .friday-hl-out::before {
        animation: fr-fade-out 0.35s ease forwards !important;
      }
      .friday-scanning-frame {
        position: fixed !important;
        inset: 0 !important;
        z-index: 2147483646 !important;
        pointer-events: none !important;
        border: 2px solid transparent !important;
        border-image: linear-gradient(135deg, #007aff, #af52de, #ff2d55) 1 !important;
        opacity: 0.55 !important;
        animation: fr-fade-in 0.35s ease both !important;
      }
      .friday-scanning-beam {
        position: fixed !important;
        left: 0 !important;
        height: 4px !important;
        width: 100vw !important;
        background: linear-gradient(90deg, transparent, #007aff, #af52de, transparent) !important;
        z-index: 2147483646 !important;
        pointer-events: none !important;
        animation: fr-beam 3s linear infinite !important;
      }
      .friday-scanning-label {
        position: fixed !important;
        top: 16px !important;
        right: 16px !important;
        background: rgba(20,20,20,0.85) !important;
        color: white !important;
        font-family: -apple-system, system-ui, sans-serif !important;
        font-size: 12px !important;
        padding: 6px 10px !important;
        border-radius: 999px !important;
        z-index: 2147483647 !important;
        pointer-events: none !important;
        animation: fr-fade-in 0.35s ease both !important;
      }
    `;
    document.documentElement.appendChild(style);
  }

  function flashHighlight(el, duration) {
    el.classList.add("friday-hl");
    setTimeout(() => {
      el.classList.add("friday-hl-out");
      setTimeout(() => {
        el.classList.remove("friday-hl");
        el.classList.remove("friday-hl-out");
      }, 350);
    }, duration);
  }

  let _scanCleanup = null;
  function startScanning(label, durationMs) {
    stopScanning();
    const frame = document.createElement("div");
    frame.className = "friday-scanning-frame";
    const beam = document.createElement("div");
    beam.className = "friday-scanning-beam";
    const labelEl = document.createElement("div");
    labelEl.className = "friday-scanning-label";
    labelEl.textContent = label;
    document.documentElement.appendChild(frame);
    document.documentElement.appendChild(beam);
    document.documentElement.appendChild(labelEl);
    const t = setTimeout(stopScanning, durationMs);
    _scanCleanup = () => {
      clearTimeout(t);
      [frame, beam, labelEl].forEach(n => n.remove());
      _scanCleanup = null;
    };
  }
  function stopScanning() {
    if (_scanCleanup) _scanCleanup();
  }
})();
