// FRIDAY Browser Bridge — popup script

async function refreshStatus() {
  const status = document.getElementById("status");
  try {
    const res = await chrome.runtime.sendMessage({ type: "status" });
    if (!res) {
      status.className = "status bad";
      status.textContent = "Background worker not responding.";
      return;
    }
    if (res.connected) {
      status.className = "status ok";
      status.textContent = "✓ Connected to FRIDAY bridge.";
    } else {
      status.className = "status bad";
      status.textContent = `✗ Not connected — ${res.reason || "no token / FRIDAY off"}`;
    }
  } catch (e) {
    status.className = "status bad";
    status.textContent = `Error: ${e.message}`;
  }
}

document.getElementById("save").addEventListener("click", async () => {
  const tok = document.getElementById("token").value.trim();
  if (!tok) return;
  await chrome.storage.local.set({ token: tok });
  await chrome.runtime.sendMessage({ type: "reconnect" });
  setTimeout(refreshStatus, 600);
});

document.getElementById("reconnect").addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "reconnect" });
  setTimeout(refreshStatus, 600);
});

// Pre-fill the existing token (masked) so user can see they've set one.
chrome.storage.local.get("token").then(({ token }) => {
  if (token) {
    document.getElementById("token").value = token;
  }
});

refreshStatus();
setInterval(refreshStatus, 2000);
