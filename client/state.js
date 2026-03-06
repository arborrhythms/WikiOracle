// state.js — State persistence (no deps).
// Loaded after config.js; owns the state global.
//
// Exports:
//   state                — shared global: current conversation state (null until loaded)
//   _loadLocalState()    — read state from sessionStorage (stateless mode)
//   _saveLocalState()    — write state to sessionStorage (stateless mode)

// ─── State global (owned here, used everywhere) ───
let state = null;

// ─── Truth type icons ───
// Maps XHTML root tag → display icon (Unicode).
const TRUTH_ICONS = {
  feeling:   "\u2661",   // ♡ white heart suit
  fact:      "\u25cf",   // ● solid circle
  reference: "\ud83d\udd17", // 🔗 link
  and:       "\u2227",   // ∧ logical and
  or:        "\u2228",   // ∨ logical or
  not:       "\u00ac",   // ¬ logical not
  non:       "\u00bf",   // ¿ non-affirming negation (uncertainty)
  provider:  "\u2699",   // ⚙ gear
  authority: "\u2020",   // † dagger (authoritative reference)
};

// ─── Storage persistence (sessionStorage + localStorage mirror) ───

const _STATE_KEY = "wikioracle_state";

function _loadLocalState() {
  try {
    var raw = sessionStorage.getItem(_STATE_KEY);
    if (raw) return JSON.parse(raw);
    // Fallback: restore from localStorage (survives tab close)
    raw = localStorage.getItem(_STATE_KEY);
    if (raw) {
      sessionStorage.setItem(_STATE_KEY, raw);
      return JSON.parse(raw);
    }
    return null;
  } catch { return null; }
}

function _saveLocalState() {
  try {
    var json = JSON.stringify(state);
    sessionStorage.setItem(_STATE_KEY, json);
    localStorage.setItem(_STATE_KEY, json);
  } catch {}
}

function _clearAllLocal() {
  var keys = [_STATE_KEY, "wikioracle_config", "wo_api_token"];
  for (var i = 0; i < keys.length; i++) {
    try { sessionStorage.removeItem(keys[i]); } catch {}
    try { localStorage.removeItem(keys[i]); } catch {}
  }
  try { sessionStorage.removeItem("wikioracle_prefs"); } catch {}
}
