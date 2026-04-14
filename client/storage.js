// storage.js — Dropbox-backed encrypted storage for WikiOracle.
// Loaded after query.js, before wikioracle.js.
// Depends on: api(), _apiPath() from query.js; _createDialog(), showErrorDialog() from util.js.

var _dropboxConnected = false;
var _dropboxConfigured = false;

// ─── Dropbox status ───

async function _checkDropboxStatus() {
  try {
    var resp = await api("GET", "/auth/dropbox/status");
    _dropboxConfigured = !!(resp && resp.configured);
    _dropboxConnected = !!(resp && resp.connected);
  } catch (e) {
    _dropboxConfigured = false;
    _dropboxConnected = false;
  }
  _updateDropboxUI();
  return _dropboxConnected;
}

function _updateDropboxUI() {
  var connectBtn = document.getElementById("btnDropboxConnect");
  var disconnectBtn = document.getElementById("btnDropboxDisconnect");
  if (!_dropboxConfigured) {
    if (connectBtn) { connectBtn.textContent = "Cloud Storage: Not configured"; connectBtn.style.display = ""; connectBtn.disabled = false; }
    if (disconnectBtn) disconnectBtn.style.display = "none";
  } else if (_dropboxConnected) {
    if (connectBtn) connectBtn.style.display = "none";
    if (disconnectBtn) { disconnectBtn.textContent = "Cloud Storage: Disconnect"; disconnectBtn.style.display = ""; }
  } else {
    if (connectBtn) { connectBtn.textContent = "Cloud Storage: Connect"; connectBtn.style.display = ""; }
    if (disconnectBtn) disconnectBtn.style.display = "none";
  }
}

function _startDropboxAuth() {
  window.location.href = _apiPath("/auth/dropbox/start");
}

async function _dropboxLogout() {
  try {
    await api("POST", "/auth/dropbox/logout");
  } catch (e) { /* ignore */ }
  _dropboxConnected = false;
  _updateDropboxUI();
}

// ─── Storage status ───

async function _checkStorageStatus() {
  try {
    return await api("GET", "/storage/status");
  } catch (e) {
    return { has_files: false };
  }
}

// ─── Password prompt ───
// Returns { name, password } or null if cancelled.
// The name field is visible+editable so the browser offers a username picker
// for previously saved credentials, and the name doubles as the Dropbox
// file prefix (e.g. "User" → User_config.zip, User_state.zip).

function _promptPassword(title, message, defaultName) {
  return new Promise(function(resolve) {
    var name = defaultName || "User";
    var body =
      '<form id="storagePwForm" method="post" action="#">' +
      '<p style="margin:0 0 1rem;font-size:0.9rem;">' + escapeHtml(message) + '</p>' +
      '<input type="text" id="storageUsernameInput" name="username" value="' + escapeHtml(name) + '"' +
      ' autocomplete="username"' +
      ' style="width:100%;padding:0.5rem;border:1px solid var(--border);border-radius:4px;' +
      'font-size:1rem;background:var(--bg);color:var(--fg);margin-bottom:0.5rem;"' +
      ' placeholder="Profile name">' +
      '<input type="password" id="storagePasswordInput" style="width:100%;padding:0.5rem;' +
      'border:1px solid var(--border);border-radius:4px;font-size:1rem;' +
      'background:var(--bg);color:var(--fg);" placeholder="Password" autocomplete="current-password">' +
      '<div class="settings-actions" style="margin-top:1rem;">' +
      '<button type="button" class="btn" id="storagePwCancel">Cancel</button>' +
      '<button type="submit" class="btn btn-primary" id="storagePwOk">OK</button>' +
      '</div></form>';
    var dlg = _createDialog("storagePasswordDlg_" + Date.now(), title, body, null, function() {
      if (dlg.overlay.parentNode) dlg.overlay.parentNode.removeChild(dlg.overlay);
      resolve(null);
    });
    var nameInput = dlg.overlay.querySelector("#storageUsernameInput");
    var pwInput = dlg.overlay.querySelector("#storagePasswordInput");
    var form = dlg.overlay.querySelector("#storagePwForm");
    dlg.overlay.querySelector("#storagePwCancel").addEventListener("click", function() {
      dlg.close();
    });
    form.addEventListener("submit", function(e) {
      e.preventDefault();
      var n = nameInput.value.trim();
      var pw = pwInput.value;
      dlg.overlay.parentNode.removeChild(dlg.overlay);
      if (!n || !pw) { resolve(null); return; }
      resolve({ name: n, password: pw });
    });
    requestAnimationFrame(function() {
      dlg.overlay.classList.add("active");
      pwInput.focus();
    });
  });
}

// ─── Save to Dropbox (config + state, one password) ───

async function _saveToDropbox() {
  if (!_dropboxConnected) {
    showErrorDialog("Not connected", "Please connect Dropbox in Settings first.");
    return;
  }
  var defaultName = (typeof state === "object" && state.client_name) || "User";
  var cred = await _promptPassword("Save to Dropbox", "Profile name selects which files to save.", defaultName);
  if (!cred) return;
  try {
    // Sync client config to server so API keys, model, etc. are included
    if (typeof _showProgress === "function") _showProgress(-1, "Syncing config\u2026");
    if (!config.server.stateless) {
      await api("POST", "/config", { config: config });
    }
    if (typeof _showProgress === "function") _showProgress(20, "Saving config\u2026");
    // Always send the local config so stateless mode (where the server
    // never receives client selections) still snapshots the user's
    // chosen provider, model, API keys, and UI prefs.
    var cfgResp = await api("POST", "/storage/save", {
      password: cred.password, which: "config", name: cred.name,
      config: config
    });
    if (!cfgResp || !cfgResp.ok) {
      showErrorDialog("Save failed", "Config: " + ((cfgResp && cfgResp.error) || "Unknown error"));
      return;
    }
    if (typeof _showProgress === "function") _showProgress(50, "Saving state\u2026");
    var stResp = await api("POST", "/storage/save", {
      password: cred.password, which: "state", name: cred.name
    });
    if (!stResp || !stResp.ok) {
      showErrorDialog("Save failed", "State: " + ((stResp && stResp.error) || "Unknown error"));
      return;
    }
    if (typeof setStatus === "function") setStatus("Saved " + cred.name + " to Dropbox");
  } catch (e) {
    showErrorDialog("Save failed", e.message || String(e));
  } finally {
    if (typeof _hideProgress === "function") _hideProgress();
  }
}

// ─── Share state to Dropbox (separate name+password, no config, shows QR) ───

async function _shareStateToDropbox() {
  if (!_dropboxConnected) {
    showErrorDialog("Not connected", "Please connect Dropbox in Settings first.");
    return;
  }
  var cred = await _promptPassword(
    "Share State",
    "Choose a profile name and sharing password.\nOnly state is shared (no config or API keys).",
    "public"
  );
  if (!cred) return;
  try {
    if (typeof _showProgress === "function") _showProgress(-1, "Encrypting state\u2026");
    var resp = await api("POST", "/storage/save", {
      password: cred.password, which: "state", name: cred.name
    });
    if (resp && resp.ok) {
      if (typeof setStatus === "function") setStatus("Shared state as " + cred.name);
      if (resp.qr_png) _showAuthorityQR(resp.qr_png, resp.authority_uri);
    } else {
      showErrorDialog("Share failed", (resp && resp.error) || "Unknown error");
    }
  } catch (e) {
    showErrorDialog("Share failed", e.message || String(e));
  } finally {
    if (typeof _hideProgress === "function") _hideProgress();
  }
}

// ─── Load from Dropbox (config + state, one password) ───

async function _initFromDropbox() {
  if (!_dropboxConnected) {
    showErrorDialog("Not connected", "Please connect Dropbox in Settings first.");
    return;
  }
  var defaultName = (typeof state === "object" && state.client_name) || "User";
  var cred = await _promptPassword("Open from Dropbox", "Profile name selects which files to load.", defaultName);
  if (!cred) return;
  try {
    // Load config
    if (typeof _showProgress === "function") _showProgress(-1, "Loading config\u2026");
    var cfgResp = await api("POST", "/storage/load", {
      password: cred.password, which: "config", name: cred.name
    });
    if (cfgResp && cfgResp.ok) {
      var loadedClient = cfgResp.config && cfgResp.config.client;
      if (loadedClient && typeof config === "object") {
        if (loadedClient.providers) config.client.providers = loadedClient.providers;
        if (loadedClient.storage) config.client.storage = loadedClient.storage;
        if (loadedClient.ui) config.client.ui = loadedClient.ui;
        if (loadedClient.temperature != null) config.client.temperature = loadedClient.temperature;
        if (loadedClient.url_fetch != null) config.client.url_fetch = loadedClient.url_fetch;
        if (loadedClient.thought_free != null) config.client.thought_free = loadedClient.thought_free;
        _saveLocalConfig(config);
      }
    } else if (cfgResp && cfgResp.error === "bad_password") {
      showErrorDialog("Wrong password", "The password is incorrect.");
      return;
    } else if (cfgResp && cfgResp.error === "not_found") {
      // No config for this profile — that's fine (e.g. shared profile)
    }

    // Load state with same password
    if (typeof _showProgress === "function") _showProgress(50, "Loading state\u2026");
    var stResp = await api("POST", "/storage/load", {
      password: cred.password, which: "state", name: cred.name
    });
    if (stResp && stResp.ok) {
      if (stResp.state && typeof _clientMerge === "function") _clientMerge(stResp.state);
      if (typeof setStatus === "function") setStatus("Loaded " + cred.name + " from Dropbox");
    } else if (stResp && stResp.error === "bad_password") {
      if (typeof setStatus === "function") setStatus("Config loaded (state uses a different password)");
    } else if (stResp && stResp.error === "not_found") {
      if (typeof setStatus === "function") setStatus("Config loaded (no state file for " + cred.name + ")");
    }

    // Reflect the loaded defaults in the input bar / theme / layout.
    if (typeof _updatePlaceholder === "function") _updatePlaceholder();
    if (config.client && config.client.ui) {
      if (typeof applyLayout === "function" && config.client.ui.layout) {
        applyLayout(config.client.ui.layout);
      }
      if (typeof applyTheme === "function" && config.client.ui.theme) {
        applyTheme(config.client.ui.theme);
      }
      // applyLayout clears tree.style.width/height, so restore the saved
      // divider position after it runs (matches the init path at
      // wikioracle.js:2008-2019).
      if (config.client.ui.divider_pos != null) {
        var tree = document.getElementById("treeContainer");
        if (tree) {
          var pct = Math.max(0, Math.min(100, config.client.ui.divider_pos));
          if (document.body.classList.contains("layout-vertical")) {
            tree.style.width = (pct / 100 * window.innerWidth) + "px";
          } else {
            tree.style.height = (pct / 100 * window.innerHeight) + "px";
          }
          tree.classList.toggle("tree-collapsed", pct === 0);
        }
      }
    }
    if (typeof renderMessages === "function") renderMessages();
  } catch (e) {
    if (e.message && e.message.indexOf("403") >= 0) {
      showErrorDialog("Wrong password", "The password is incorrect.");
      return;
    }
    showErrorDialog("Load failed", e.message || String(e));
  } finally {
    if (typeof _hideProgress === "function") _hideProgress();
  }
}

// ─── Authority QR toast ───

function _showAuthorityQR(qrBase64, authorityXml) {
  // Remove any existing toast
  var old = document.querySelector(".qr-toast");
  if (old) old.parentNode.removeChild(old);

  var toast = document.createElement("div");
  toast.className = "qr-toast qr-toast-compact";

  // Compact view
  var compact = document.createElement("div");
  compact.className = "qr-toast-compact-inner";
  compact.innerHTML = '<span>Share link ready</span>';
  var expandBtn = document.createElement("button");
  expandBtn.className = "btn";
  expandBtn.textContent = "Show";
  expandBtn.style.marginLeft = "0.5rem";
  compact.appendChild(expandBtn);

  // Expanded view
  var expanded = document.createElement("div");
  expanded.className = "qr-toast-expanded";
  expanded.style.display = "none";

  var img = document.createElement("img");
  img.src = "data:image/png;base64," + qrBase64;
  img.alt = "Authority QR Code";
  expanded.appendChild(img);

  var qrLabel = document.createElement("div");
  qrLabel.style.cssText = "font-size:0.72rem; color:var(--fg-muted); margin-bottom:0.4rem;";
  qrLabel.textContent = "Scan to copy, then paste into Truth editor";
  expanded.appendChild(qrLabel);

  var uriInput = document.createElement("input");
  uriInput.type = "text";
  uriInput.className = "qr-toast-uri";
  uriInput.value = authorityXml;
  uriInput.readOnly = true;
  expanded.appendChild(uriInput);

  var copyBtn = document.createElement("button");
  copyBtn.className = "btn btn-full";
  copyBtn.textContent = "Copy";
  copyBtn.addEventListener("click", function() {
    uriInput.select();
    navigator.clipboard.writeText(authorityXml).then(function() {
      copyBtn.textContent = "Copied!";
      setTimeout(function() { copyBtn.textContent = "Copy"; }, 1500);
    });
  });
  expanded.appendChild(copyBtn);

  // Close button
  var closeBtn = document.createElement("button");
  closeBtn.className = "qr-toast-close";
  closeBtn.innerHTML = "&times;";
  closeBtn.addEventListener("click", function() {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  });

  // Toggle expand/compact
  expandBtn.addEventListener("click", function() {
    toast.classList.remove("qr-toast-compact");
    compact.style.display = "none";
    expanded.style.display = "";
  });

  toast.appendChild(closeBtn);
  toast.appendChild(compact);
  toast.appendChild(expanded);
  document.body.appendChild(toast);

  // Auto-dismiss after 60 seconds
  setTimeout(function() {
    if (toast.parentNode) toast.parentNode.removeChild(toast);
  }, 60000);
}

// ─── Header dropdown helper ───

function _showHeaderDropdown(anchorBtn, options) {
  // Close any existing dropdown
  var old = document.querySelector(".header-dropdown");
  if (old) old.parentNode.removeChild(old);

  var dropdown = document.createElement("div");
  dropdown.className = "header-dropdown";

  for (var i = 0; i < options.length; i++) {
    var opt = options[i];
    var item = document.createElement("button");
    item.className = "header-dropdown-item";
    item.textContent = opt.label;
    item.addEventListener("click", (function(fn) {
      return function() {
        dropdown.parentNode.removeChild(dropdown);
        fn();
      };
    })(opt.action));
    dropdown.appendChild(item);
  }

  // Position relative to the anchor button; open upward if near screen bottom
  anchorBtn.style.position = "relative";
  anchorBtn.appendChild(dropdown);
  var rect = anchorBtn.getBoundingClientRect();
  if (rect.bottom + 120 > window.innerHeight) {
    dropdown.style.top = "auto";
    dropdown.style.bottom = "100%";
    dropdown.style.marginTop = "0";
    dropdown.style.marginBottom = "2px";
  }

  // Close on outside click
  function closeOnOutside(e) {
    if (!dropdown.contains(e.target) && e.target !== anchorBtn) {
      if (dropdown.parentNode) dropdown.parentNode.removeChild(dropdown);
      document.removeEventListener("click", closeOnOutside, true);
    }
  }
  // Defer to avoid the current click closing it immediately
  setTimeout(function() {
    document.addEventListener("click", closeOnOutside, true);
  }, 0);
}
