// config.js — Config persistence and XML (de)serialization (no deps).
// Loaded first; owns the config global.
//
// The config object mirrors config.xml exactly — { server: {...}, client: {...} }.
// There are NO defaults in code: the server's /bootstrap response is the
// canonical source.  Every value the UI displays must originate in
// data/config.xml (or its user override).
//
// Exports:
//   config              — shared global: current config (canonical shape)
//   _loadLocalConfig()  — read config from sessionStorage
//   _saveLocalConfig()  — write config to sessionStorage
//   configToXml(obj)    — serialize config object to XML string
//   xmlToConfig(text)   — parse XML string into canonical shape

// ─── Config global (owned here, used everywhere) ───
let config = { server: {}, client: {} };

// ─── Storage persistence (sessionStorage + localStorage mirror) ───

const _CONFIG_KEY = "wikioracle_config";

// Config in sessionStorage (+ localStorage fallback for tab-close durability).
function _loadLocalConfig() {
  try {
    var raw = sessionStorage.getItem(_CONFIG_KEY);
    if (!raw) {
      raw = localStorage.getItem(_CONFIG_KEY);
      if (raw) sessionStorage.setItem(_CONFIG_KEY, raw);
    }
    if (!raw) return null;
    var data = JSON.parse(raw);
    if (typeof data === "string") return null;
    if (data && data.parsed && data.config) return data.config;  // legacy bundle
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

// ─── XML serializer / parser (config editor) ───

// Section keys that live alongside <provider> entries inside
// <server><providers> — they describe shared prompt context, not a
// specific provider, so they must be skipped when iterating providers.
var _SERVER_PROVIDER_SECTION_KEYS = ["context", "output", "truth_context", "conversation_context"];

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

// Serialize a flat key→scalar dict as one XML subsection.
function _addFlatSubsection(lines, indent, tag, data) {
  if (!data || typeof data !== "object") return;
  lines.push(indent + "<" + tag + ">");
  for (var key in data) {
    if (!data.hasOwnProperty(key)) continue;
    lines.push(indent + "  <" + key + ">" + _xmlEsc(_xmlValStr(data[key])) + "</" + key + ">");
  }
  lines.push(indent + "</" + tag + ">");
}

// Serialize config dict → XML string (matches server config_to_xml).
function configToXml(obj) {
  if (!obj || typeof obj !== "object") {
    return '<?xml version="1.0" encoding="UTF-8"?>\n<config/>\n';
  }
  var lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"];

  // ── server ──
  var srv = obj.server || {};
  lines.push("  <server>");
  ["server_name", "server_id", "stateless", "url_prefix"].forEach(function(sk) {
    if (srv[sk] !== undefined) {
      lines.push("    <" + sk + ">" + _xmlEsc(_xmlValStr(srv[sk])) + "</" + sk + ">");
    }
  });
  if (srv.truthset)   _addFlatSubsection(lines, "    ", "truthset",   srv.truthset);
  if (srv.evaluation) _addFlatSubsection(lines, "    ", "evaluation", srv.evaluation);
  if (srv.training)   _addFlatSubsection(lines, "    ", "training",   srv.training);
  if (Array.isArray(srv.allowed_urls)) {
    lines.push("    <allowed_urls>");
    srv.allowed_urls.forEach(function(u) {
      lines.push("      <url>" + _xmlEsc(u) + "</url>");
    });
    lines.push("    </allowed_urls>");
  }
  // Provider definitions under <server><providers>.
  var srvProvs = srv.providers;
  if (srvProvs && typeof srvProvs === "object") {
    lines.push("    <providers>");
    _SERVER_PROVIDER_SECTION_KEYS.forEach(function(sk) {
      if (srvProvs[sk] !== undefined) {
        lines.push("      <" + sk + ">" + _xmlEsc(_xmlValStr(srvProvs[sk])) + "</" + sk + ">");
      }
    });
    for (var pk in srvProvs) {
      if (!srvProvs.hasOwnProperty(pk)) continue;
      if (_SERVER_PROVIDER_SECTION_KEYS.indexOf(pk) !== -1) continue;
      var prov = srvProvs[pk];
      if (!prov || typeof prov !== "object") continue;
      lines.push("      <provider>");
      lines.push("        <name>" + _xmlEsc(pk) + "</name>");
      for (var fk in prov) {
        if (!prov.hasOwnProperty(fk)) continue;
        if (fk === "name" || fk === "api_key" || fk === "models") continue;
        lines.push("        <" + fk + ">" + _xmlEsc(_xmlValStr(prov[fk])) + "</" + fk + ">");
      }
      lines.push("      </provider>");
    }
    lines.push("    </providers>");
  }
  lines.push("  </server>");

  // ── client ──
  var cli = obj.client || {};
  lines.push("  <client>");
  if (cli.storage) lines.push("    <storage/>");
  ["temperature", "url_fetch", "thought_free"].forEach(function(k) {
    if (cli[k] !== undefined) {
      lines.push("    <" + k + ">" + _xmlEsc(_xmlValStr(cli[k])) + "</" + k + ">");
    }
  });
  if (cli.ui && typeof cli.ui === "object") {
    lines.push("    <ui>");
    for (var uk in cli.ui) {
      if (!cli.ui.hasOwnProperty(uk)) continue;
      lines.push("      <" + uk + ">" + _xmlEsc(_xmlValStr(cli.ui[uk])) + "</" + uk + ">");
    }
    lines.push("    </ui>");
  }
  var cliProvs = cli.providers;
  if (cliProvs && typeof cliProvs === "object") {
    lines.push("    <providers>");
    if (cliProvs.default_provider) {
      lines.push("      <default_provider>" + _xmlEsc(_xmlValStr(cliProvs.default_provider)) + "</default_provider>");
    }
    if (cliProvs.default_model) {
      lines.push("      <default_model>" + _xmlEsc(_xmlValStr(cliProvs.default_model)) + "</default_model>");
    }
    for (var pk2 in cliProvs) {
      if (!cliProvs.hasOwnProperty(pk2)) continue;
      if (pk2 === "default_provider" || pk2 === "default_model") continue;
      var p = cliProvs[pk2];
      if (p && typeof p === "object" && p.api_key) {
        lines.push("      <provider>");
        lines.push("        <name>" + _xmlEsc(pk2) + "</name>");
        lines.push("        <api_key>" + _xmlEsc(_xmlValStr(p.api_key)) + "</api_key>");
        lines.push("      </provider>");
      }
    }
    lines.push("    </providers>");
  }
  lines.push("  </client>");

  lines.push("</config>");
  return lines.join("\n") + "\n";
}

// Parse XML string → canonical config dict (matches server _load_config_xml).
// Returns null on parse error.
function xmlToConfig(text) {
  try {
    var parser = new DOMParser();
    var doc = parser.parseFromString(text, "application/xml");
    var err = doc.querySelector("parsererror");
    if (err) return null;
    var root = doc.documentElement;
    if (root.tagName !== "config") return null;

    function readSimple(el) {
      var obj = {};
      for (var i = 0; i < el.children.length; i++) {
        var child = el.children[i];
        obj[child.tagName] = _xmlCoerce(child.textContent);
      }
      return obj;
    }

    var data = { server: {}, client: {} };

    // ── server ──
    var srvEl = root.querySelector(":scope > server");
    if (srvEl) {
      var srv = {};
      for (var i = 0; i < srvEl.children.length; i++) {
        var child = srvEl.children[i];
        var tag = child.tagName;
        if (tag === "providers" || tag === "dropbox") continue;
        if (tag === "truthset" || tag === "evaluation" || tag === "training") {
          srv[tag] = readSimple(child);
        } else if (tag === "allowed_urls") {
          var urls = [];
          child.querySelectorAll("url").forEach(function(u) {
            var t = u.textContent.trim();
            if (t) urls.push(t);
          });
          srv.allowed_urls = urls;
        } else {
          srv[tag] = _xmlCoerce(child.textContent);
        }
      }
      // Server provider definitions (shared sections + per-provider defs)
      var srvProvsEl = srvEl.querySelector(":scope > providers");
      if (srvProvsEl) {
        var sProvs = {};
        _SERVER_PROVIDER_SECTION_KEYS.forEach(function(sk) {
          var el = srvProvsEl.querySelector(":scope > " + sk);
          if (el) sProvs[sk] = el.textContent.trim();
        });
        srvProvsEl.querySelectorAll(":scope > provider").forEach(function(pel) {
          var prov = {};
          var provName = null;
          for (var i = 0; i < pel.children.length; i++) {
            var child = pel.children[i];
            var tag = child.tagName;
            var val = _xmlCoerce(child.textContent);
            if (tag === "name") provName = String(val);
            else if (tag === "api_key") continue;
            else prov[tag] = val;
          }
          if (provName) sProvs[provName] = prov;
        });
        srv.providers = sProvs;
      }
      data.server = srv;
    }

    // ── client ──
    var clientEl = root.querySelector(":scope > client");
    if (clientEl) {
      var cli = {};
      var storageEl = clientEl.querySelector(":scope > storage");
      if (storageEl) {
        cli.storage = {};
        if (storageEl.getAttribute("state_key")) {
          cli.storage.state_key = storageEl.getAttribute("state_key");
        }
      }
      ["temperature", "url_fetch", "thought_free"].forEach(function(f) {
        var el = clientEl.querySelector(":scope > " + f);
        if (el) cli[f] = _xmlCoerce(el.textContent);
      });
      var uiEl = clientEl.querySelector(":scope > ui");
      if (uiEl) cli.ui = readSimple(uiEl);

      var clientProvsEl = clientEl.querySelector(":scope > providers");
      if (clientProvsEl) {
        var cProvs = {};
        var dpEl = clientProvsEl.querySelector(":scope > default_provider");
        if (dpEl) cProvs.default_provider = dpEl.textContent.trim();
        var dmEl = clientProvsEl.querySelector(":scope > default_model");
        if (dmEl) cProvs.default_model = dmEl.textContent.trim();
        clientProvsEl.querySelectorAll(":scope > provider").forEach(function(pel) {
          var nameEl = pel.querySelector("name");
          var keyEl = pel.querySelector("api_key");
          if (nameEl && keyEl) {
            var pName = nameEl.textContent.trim();
            if (!cProvs[pName]) cProvs[pName] = {};
            cProvs[pName].api_key = keyEl.textContent.trim();
          }
        });
        cli.providers = cProvs;
      }
      data.client = cli;
    }

    return data;
  } catch (e) {
    return null;
  }
}
