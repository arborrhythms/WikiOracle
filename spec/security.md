# Security notes

## API keys in sessionStorage + proxying via stateless server

### Assumption
Strict CSP is implemented and enforced (no inline scripts/events, no untrusted script origins).

### Short answer
Acceptable only for low-risk/single-user trusted-origin scenarios; not strong security.

### Risks (even with HTTPS tunnel)
- CSP materially reduces script-injection paths, but does not eliminate XSS.
- Any JS that does execute on origin can still read sessionStorage (key theft remains possible).
- sessionStorage is scoped per-tab/window but still accessible to same-origin code in that tab.
- sessionStorage survives reloads in the same tab and is only cleared when that tab/window closes.
- Keys can still leak server-side via request logging/crash traces if not explicitly redacted.

### CSP impact (implemented)
- Strongly reduces risk from inline/eval-based script injection.
- Raises attacker cost for common reflected/stored XSS payloads.
- Does not protect against compromised trusted scripts, browser extensions, or origin compromise.

### Migration impact: localStorage -> sessionStorage
- Reduced persistence at rest compared with localStorage (no long-term browser-profile retention).
- Reduced cross-tab exposure by default (keys are not shared globally across all tabs).
- XSS risk remains essentially unchanged: injected JS can still read sessionStorage.
- Operational tradeoff: users may need to re-enter keys after tab/browser close.

### What HTTPS helps with
- Protects keys in transit from network interception.
- Does NOT protect against XSS, malicious extensions, or compromised origin code.

### Minimum mitigations if keeping this design
- [x] Enforce strict CSP (no inline scripts, no untrusted script origins).
- [ ] Redact/disable request-body logging on reverse proxy + Flask app.
- [ ] Add explicit key redaction in exception paths.
- [ ] Send `Cache-Control: no-store` for sensitive API responses.
- [ ] Add key rotation guidance + short-lived keys where provider supports it.
- [ ] Never commit real keys to repo-tracked `config.yaml`.
