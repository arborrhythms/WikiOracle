// state.js — State persistence (no deps).
// Loaded after config.js; owns the state global.
//
// Exports:
//   state                — shared global: current conversation state (null until loaded)
//   _loadLocalState()    — read state from sessionStorage (stateless mode)
//   _saveLocalState()    — write state to sessionStorage (stateless mode)

// ─── State global (owned here, used everywhere) ───
let state = null;

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
