// config.js — Config persistence and normalization (no deps).
// Loaded first; owns the config global.
//
// The config object has the same shape as config.yaml — no flattening or
// renaming.  Missing sections/keys are filled with sensible defaults by
// _normalizeConfig().  Runtime-only fields (server.providers, ui.model)
// round-trip harmlessly through YAML.
//
// Exports:
//   config                — shared global: current config (YAML-shaped)
//   _loadLocalConfig()    — read config from sessionStorage
//   _saveLocalConfig()    — write config to sessionStorage
//   _normalizeConfig(cfg) — fill defaults, keep YAML shape
//   _migrateOldPrefs()    — one-time migration from legacy wikioracle_prefs

// ─── Config global (owned here, used everywhere) ───
let config = {
  user: { name: "User" },
  chat: { temperature: 0.7, rag: true,
          url_fetch: false, confirm_actions: false },
  ui: { default_provider: "wikioracle", layout: "flat", theme: "system",
        splitter_pct: 0, swipe_nav_horizontal: true,
        swipe_nav_vertical: false },
  server: { stateless: false, url_prefix: "", providers: {} },
  defaults: { context: "<div/>", output: "" },
};

// ─── SessionStorage persistence ───

const _CONFIG_KEY = "wikioracle_config";

// Config in sessionStorage: the YAML-shaped config dict directly.
function _loadLocalConfig() {
  try {
    const raw = sessionStorage.getItem(_CONFIG_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    // Handle legacy formats (raw YAML string or old { parsed, config } bundle)
    if (typeof data === "string") return null;
    if (data.parsed && data.config) return data.config;  // upgrade old bundle
    return data;
  } catch { return null; }
}

function _saveLocalConfig(cfg) {
  try { sessionStorage.setItem(_CONFIG_KEY, JSON.stringify(cfg)); } catch {}
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
  if (cfg.chat.rag === undefined) cfg.chat.rag = true;
  if (cfg.chat.url_fetch === undefined) cfg.chat.url_fetch = false;
  if (cfg.chat.confirm_actions === undefined) cfg.chat.confirm_actions = false;
  if (!cfg.server) cfg.server = {};
  if (cfg.server.stateless === undefined) cfg.server.stateless = false;
  if (cfg.server.url_prefix === undefined) cfg.server.url_prefix = "";
  if (!cfg.server.providers) cfg.server.providers = {};
  if (!cfg.defaults) cfg.defaults = { context: "<div/>", output: "" };
  return cfg;
}

// ─── Legacy migration ───

// One-time migration: wikioracle_prefs → YAML-shaped config
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

  // Build YAML-shaped config from old prefs
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
