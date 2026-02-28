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
  fact:      "\u25cf",   // ● solid circle
  reference: "\ud83d\udd17", // 🔗 link
  and:       "\u2227",   // ∧ logical and
  or:        "\u2228",   // ∨ logical or
  not:       "\u00ac",   // ¬ logical not
  non:       "\u2234",   // ∴ therefore (non-affirming negation)
  provider:  "\u2699",   // ⚙ gear
  authority: "\u229e",   // ⊞ squared plus
};

// ─── SessionStorage persistence ───

const _STATE_KEY = "wikioracle_state";

function _loadLocalState() {
  try {
    const raw = sessionStorage.getItem(_STATE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function _saveLocalState() {
  try { sessionStorage.setItem(_STATE_KEY, JSON.stringify(state)); } catch {}
}
