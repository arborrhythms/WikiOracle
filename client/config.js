// config.js — Config persistence and normalization (no deps).
// Loaded first; owns the config global.
//
// The config object has the same shape as config.xml — server and providers
// sections only.  UI preferences and client identity live in state, not here.
// Missing sections/keys are filled with sensible defaults by
// _normalizeConfig().
//
// Exports:
//   config                — shared global: current config (XML-shaped)
//   _loadLocalConfig()    — read config from sessionStorage
//   _saveLocalConfig()    — write config to sessionStorage
//   _normalizeConfig(cfg) — fill defaults, keep XML shape
//   _migrateOldPrefs()    — one-time migration from legacy wikioracle_prefs

// ─── Config global (owned here, used everywhere) ───
let config = {
  server: { stateless: false, url_prefix: "", providers: {},
            truthset: { truth_symmetry: true, store_concrete: false, truth_weight: 0.7 },
            evaluation: { temperature: 0.7, max_tokens: 128, timeout: 120, url_fetch: false },
            training: { enabled: false } },
  providers: { default: "wikioracle" },
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
  // --- server ---
  if (!cfg.server) cfg.server = {};
  if (cfg.server.stateless === undefined) cfg.server.stateless = false;
  if (cfg.server.url_prefix === undefined) cfg.server.url_prefix = "";
  if (!cfg.server.providers) cfg.server.providers = {};
  // server.truthset
  if (!cfg.server.truthset) cfg.server.truthset = {};
  if (cfg.server.truthset.truth_symmetry === undefined) cfg.server.truthset.truth_symmetry = true;
  if (cfg.server.truthset.store_concrete === undefined) cfg.server.truthset.store_concrete = false;
  if (cfg.server.truthset.truth_weight === undefined) cfg.server.truthset.truth_weight = 0.7;
  // server.evaluation
  if (!cfg.server.evaluation) cfg.server.evaluation = {};
  if (cfg.server.evaluation.temperature === undefined) cfg.server.evaluation.temperature = 0.7;
  if (cfg.server.evaluation.max_tokens === undefined) cfg.server.evaluation.max_tokens = 128;
  if (cfg.server.evaluation.timeout === undefined) cfg.server.evaluation.timeout = 120;
  if (cfg.server.evaluation.url_fetch === undefined) cfg.server.evaluation.url_fetch = false;
  // --- providers ---
  if (!cfg.providers) cfg.providers = {};
  if (!cfg.providers.default) cfg.providers.default = "wikioracle";
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

  function addSubsection(indent, tag, data) {
    if (!data || typeof data !== "object") return;
    lines.push(indent + "<" + tag + ">");
    for (var key in data) {
      if (!data.hasOwnProperty(key)) continue;
      lines.push(indent + "  <" + key + ">" + _xmlEsc(_xmlValStr(data[key])) + "</" + key + ">");
    }
    lines.push(indent + "</" + tag + ">");
  }

  // server
  var srv = obj.server;
  if (srv && typeof srv === "object") {
    lines.push("  <server>");
    // Flat server fields
    var flatKeys = ["server_name", "server_id", "stateless", "url_prefix"];
    flatKeys.forEach(function(sk) {
      if (srv[sk] !== undefined && sk !== "providers") {
        lines.push("    <" + sk + ">" + _xmlEsc(_xmlValStr(srv[sk])) + "</" + sk + ">");
      }
    });
    // Subsections
    if (srv.truthset && typeof srv.truthset === "object") addSubsection("    ", "truthset", srv.truthset);
    if (srv.evaluation && typeof srv.evaluation === "object") addSubsection("    ", "evaluation", srv.evaluation);
    if (srv.training && typeof srv.training === "object") addSubsection("    ", "training", srv.training);
    // allowed_urls
    if (Array.isArray(srv.allowed_urls)) {
      lines.push("    <allowed_urls>");
      srv.allowed_urls.forEach(function(u) { lines.push("      <url>" + _xmlEsc(u) + "</url>"); });
      lines.push("    </allowed_urls>");
    }
    lines.push("  </server>");
  }

  // providers — section-level elements + <provider name="key">
  var provs = obj.providers;
  if (provs && typeof provs === "object") {
    lines.push("  <providers>");
    // Section-level elements
    var sectionKeys = ["default", "context", "output", "truth_context", "conversation_context"];
    sectionKeys.forEach(function(sk) {
      if (provs[sk] !== undefined) {
        lines.push("    <" + sk + ">" + _xmlEsc(_xmlValStr(provs[sk])) + "</" + sk + ">");
      }
    });
    // Per-provider entries
    for (var pk in provs) {
      if (!provs.hasOwnProperty(pk)) continue;
      if (sectionKeys.indexOf(pk) !== -1) continue;
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

    // server
    var srvEl = root.querySelector("server");
    if (srvEl) {
      var srv = {};
      for (var i = 0; i < srvEl.children.length; i++) {
        var child = srvEl.children[i];
        if (child.tagName === "truthset" || child.tagName === "evaluation" || child.tagName === "training") {
          srv[child.tagName] = readSimple(child);
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

    // providers — section-level + per-provider
    var provsEl = root.querySelector("providers");
    if (provsEl) {
      data.providers = {};
      // Section-level elements
      var sectionKeys = ["default", "context", "output", "truth_context", "conversation_context"];
      sectionKeys.forEach(function(sk) {
        var el = provsEl.querySelector(":scope > " + sk);
        if (el) data.providers[sk] = (sk === "default") ? el.textContent.trim() : el.textContent.trim();
      });
      // Per-provider entries
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
  if (existing && existing.providers) {
    // Config already exists — just clean up
    sessionStorage.removeItem(_OLD_PREFS_KEY);
    return;
  }

  // Build XML-shaped config from old prefs (user name migrates to state, not config)
  const migrated = _normalizeConfig({
    providers: {
      default: oldPrefs.provider || "wikioracle",
    },
  });
  // Store old username in state (will be picked up by _initStateful/_initStateless)
  if (oldPrefs.username && typeof state !== "undefined" && state) {
    state.client_name = oldPrefs.username;
  }

  _saveLocalConfig(migrated);
  sessionStorage.removeItem(_OLD_PREFS_KEY);
}
