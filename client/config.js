// config.js — Config persistence and normalization (no deps).
// Loaded first; owns the config global.
//
// The config object has the same shape as config.xml — no flattening or
// renaming.  Missing sections/keys are filled with sensible defaults by
// _normalizeConfig().  Runtime-only fields (server.providers, ui.model)
// round-trip harmlessly through config.
//
// Exports:
//   config                — shared global: current config (XML-shaped)
//   _loadLocalConfig()    — read config from sessionStorage
//   _saveLocalConfig()    — write config to sessionStorage
//   _normalizeConfig(cfg) — fill defaults, keep XML shape
//   _migrateOldPrefs()    — one-time migration from legacy wikioracle_prefs

// ─── Config global (owned here, used everywhere) ───
let config = {
  user: { name: "User" },
  chat: { temperature: 0.7, max_tokens: 128, timeout: 120,
          truth_weight: 0.7, truth_max_entries: 1000,
          store_particulars: false,
          url_fetch: false, confirm_actions: false },
  ui: { default_provider: "wikioracle", layout: "flat", theme: "system",
        splitter_pct: 0, swipe_nav_horizontal: true,
        swipe_nav_vertical: false },
  server: { stateless: false, url_prefix: "", providers: {} },
  defaults: { context: "<div/>", output: "" },
};

// ─── Storage persistence (sessionStorage + localStorage mirror) ───

const _CONFIG_KEY = "wikioracle_config";

// Config in sessionStorage (+ localStorage fallback for tab-close durability).
function _loadLocalConfig() {
  try {
    var raw = sessionStorage.getItem(_CONFIG_KEY);
    if (!raw) {
      // Fallback: restore from localStorage (survives tab close)
      raw = localStorage.getItem(_CONFIG_KEY);
      if (raw) sessionStorage.setItem(_CONFIG_KEY, raw);
    }
    if (!raw) return null;
    var data = JSON.parse(raw);
    // Handle legacy formats (raw string or old { parsed, config } bundle)
    if (typeof data === "string") return null;
    if (data.parsed && data.config) return data.config;  // upgrade old bundle
    return data;
  } catch { return null; }
}

function _saveLocalConfig(cfg) {
  try {
    var json = JSON.stringify(cfg);
    sessionStorage.setItem(_CONFIG_KEY, json);
    localStorage.setItem(_CONFIG_KEY, json);
  } catch {}
}

// ─── Config normalization ───

// Fill defaults in a config dict — mirrors server's _normalize_config().
function _normalizeConfig(cfg) {
  cfg = cfg || {};
  if (!cfg.user) cfg.user = {};
  if (!cfg.user.name) cfg.user.name = "User";
  if (!cfg.ui) cfg.ui = {};
  if (!cfg.ui.default_provider) cfg.ui.default_provider = "wikioracle";
  if (!cfg.ui.layout) cfg.ui.layout = "flat";
  if (!cfg.ui.theme) cfg.ui.theme = "system";
  if (cfg.ui.splitter_pct == null) cfg.ui.splitter_pct = 0;
  if (cfg.ui.swipe_nav_horizontal === undefined) cfg.ui.swipe_nav_horizontal = true;
  if (cfg.ui.swipe_nav_vertical === undefined) cfg.ui.swipe_nav_vertical = false;
  if (!cfg.chat) cfg.chat = {};
  if (cfg.chat.temperature === undefined) cfg.chat.temperature = 0.7;
  if (cfg.chat.max_tokens === undefined) cfg.chat.max_tokens = 128;
  if (cfg.chat.timeout === undefined) cfg.chat.timeout = 120;
  if (cfg.chat.truth_weight === undefined) cfg.chat.truth_weight = 0.7;
  if (cfg.chat.truth_max_entries === undefined) cfg.chat.truth_max_entries = 1000;
  if (cfg.chat.store_particulars === undefined) cfg.chat.store_particulars = false;
  if (cfg.chat.url_fetch === undefined) cfg.chat.url_fetch = false;
  if (cfg.chat.confirm_actions === undefined) cfg.chat.confirm_actions = false;
  // Migrate legacy rag boolean → truth_weight
  if (cfg.chat.rag !== undefined) {
    if (cfg.chat.truth_weight === undefined || cfg.chat.truth_weight === 0.7) {
      cfg.chat.truth_weight = cfg.chat.rag ? 0.7 : 0.0;
    }
    delete cfg.chat.rag;
  }
  if (!cfg.server) cfg.server = {};
  if (cfg.server.stateless === undefined) cfg.server.stateless = false;
  if (cfg.server.url_prefix === undefined) cfg.server.url_prefix = "";
  if (!cfg.server.providers) cfg.server.providers = {};
  return cfg;
}

// ─── XML serializer / parser (config editor) ───

// Coerce XML text to bool / number / string (matches server _xml_coerce).
function _xmlCoerce(text) {
  if (text === undefined || text === null) return "";
  var s = text.trim();
  if (s.toLowerCase() === "true") return true;
  if (s.toLowerCase() === "false") return false;
  if (s !== "" && !isNaN(s)) {
    var n = Number(s);
    if (isFinite(n)) return n;
  }
  return s;
}

function _xmlValStr(v) {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (v === null || v === undefined) return "";
  return String(v);
}

function _xmlEsc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Serialize config dict → XML string (matches server config_to_xml).
function configToXml(obj) {
  if (!obj || typeof obj !== "object") return '<?xml version="1.0" encoding="UTF-8"?>\n<config/>\n';
  var lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"];

  function addSimpleSection(tag, data) {
    if (!data || typeof data !== "object") return;
    lines.push("  <" + tag + ">");
    for (var key in data) {
      if (!data.hasOwnProperty(key)) continue;
      lines.push("    <" + key + ">" + _xmlEsc(_xmlValStr(data[key])) + "</" + key + ">");
    }
    lines.push("  </" + tag + ">");
  }

  // user
  addSimpleSection("user", obj.user);

  // providers — <provider name="key"> with display_name mapping
  var provs = obj.providers;
  if (provs && typeof provs === "object") {
    lines.push("  <providers>");
    for (var pk in provs) {
      if (!provs.hasOwnProperty(pk)) continue;
      var prov = provs[pk];
      if (!prov || typeof prov !== "object") continue;
      lines.push('    <provider name="' + _xmlEsc(pk) + '">');
      for (var fk in prov) {
        if (!prov.hasOwnProperty(fk)) continue;
        var xmlTag = fk === "name" ? "display_name" : fk;
        lines.push("      <" + xmlTag + ">" + _xmlEsc(_xmlValStr(prov[fk])) + "</" + xmlTag + ">");
      }
      lines.push("    </provider>");
    }
    lines.push("  </providers>");
  }

  // chat, ui
  addSimpleSection("chat", obj.chat);
  addSimpleSection("ui", obj.ui);

  // server — special handling for online_training and allowed_urls
  var srv = obj.server;
  if (srv && typeof srv === "object") {
    lines.push("  <server>");
    for (var sk in srv) {
      if (!srv.hasOwnProperty(sk)) continue;
      if (sk === "providers") continue; // runtime-only, strip
      if (sk === "online_training" && typeof srv[sk] === "object") {
        lines.push("    <online_training>");
        var ot = srv[sk];
        for (var otk in ot) {
          if (!ot.hasOwnProperty(otk)) continue;
          lines.push("      <" + otk + ">" + _xmlEsc(_xmlValStr(ot[otk])) + "</" + otk + ">");
        }
        lines.push("    </online_training>");
      } else if (sk === "allowed_urls" && Array.isArray(srv[sk])) {
        lines.push("    <allowed_urls>");
        srv[sk].forEach(function(u) { lines.push("      <url>" + _xmlEsc(u) + "</url>"); });
        lines.push("    </allowed_urls>");
      } else {
        lines.push("    <" + sk + ">" + _xmlEsc(_xmlValStr(srv[sk])) + "</" + sk + ">");
      }
    }
    lines.push("  </server>");
  }

  // defaults
  addSimpleSection("defaults", obj.defaults);

  lines.push("</config>");
  return lines.join("\n") + "\n";
}

// Parse XML string → config dict (matches server _load_config_xml).
// Returns null on parse error.
function xmlToConfig(text) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString(text, "application/xml");
    var err = doc.querySelector("parsererror");
    if (err) return null;
    var root = doc.documentElement;
    if (root.tagName !== "config") return null;
    var data = {};

    function readSimple(el) {
      var obj = {};
      for (var i = 0; i < el.children.length; i++) {
        var child = el.children[i];
        obj[child.tagName] = _xmlCoerce(child.textContent);
      }
      return obj;
    }

    // user
    var userEl = root.querySelector("user");
    if (userEl) data.user = readSimple(userEl);

    // providers
    var provsEl = root.querySelector("providers");
    if (provsEl) {
      data.providers = {};
      var provEls = provsEl.querySelectorAll("provider");
      provEls.forEach(function(pel) {
        var key = pel.getAttribute("name") || "";
        var prov = {};
        for (var i = 0; i < pel.children.length; i++) {
          var child = pel.children[i];
          var tag = child.tagName === "display_name" ? "name" : child.tagName;
          prov[tag] = _xmlCoerce(child.textContent);
        }
        data.providers[key] = prov;
      });
    }

    // chat
    var chatEl = root.querySelector("chat");
    if (chatEl) data.chat = readSimple(chatEl);

    // ui
    var uiEl = root.querySelector("ui");
    if (uiEl) data.ui = readSimple(uiEl);

    // server
    var srvEl = root.querySelector("server");
    if (srvEl) {
      var srv = {};
      for (var i = 0; i < srvEl.children.length; i++) {
        var child = srvEl.children[i];
        if (child.tagName === "online_training") {
          srv.online_training = readSimple(child);
        } else if (child.tagName === "allowed_urls") {
          var urls = [];
          var urlEls = child.querySelectorAll("url");
          urlEls.forEach(function(u) { var t = u.textContent.trim(); if (t) urls.push(t); });
          srv.allowed_urls = urls;
        } else {
          srv[child.tagName] = _xmlCoerce(child.textContent);
        }
      }
      data.server = srv;
    }

    // defaults
    var defEl = root.querySelector("defaults");
    if (defEl) data.defaults = readSimple(defEl);

    return data;
  } catch (e) {
    return null;
  }
}

// ─── Legacy migration ───

// One-time migration: wikioracle_prefs → XML-shaped config
async function _migrateOldPrefs() {
  const _OLD_PREFS_KEY = "wikioracle_prefs";
  let oldPrefs;
  try {
    const raw = sessionStorage.getItem(_OLD_PREFS_KEY);
    if (!raw) return; // nothing to migrate
    oldPrefs = JSON.parse(raw);
  } catch { return; }

  const existing = _loadLocalConfig();
  if (existing && existing.ui) {
    // Config already exists — just clean up
    sessionStorage.removeItem(_OLD_PREFS_KEY);
    return;
  }

  // Build XML-shaped config from old prefs
  const migrated = _normalizeConfig({
    user: { name: oldPrefs.username || "User" },
    ui: {
      default_provider: oldPrefs.provider || "wikioracle",
      layout: oldPrefs.layout || "flat",
      theme: oldPrefs.theme || "system",
    },
    chat: { ...(oldPrefs.chat || {}) },
  });

  _saveLocalConfig(migrated);
  sessionStorage.removeItem(_OLD_PREFS_KEY);
}
