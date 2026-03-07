# Authority

## Transitive trust in WikiOracle's truth system

An **authority** is a trust entry that references an external agent's knowledge base. Instead of containing facts directly, an `<authority>` entry points to a remote state file. At evaluation time, the server fetches that file, extracts its trust entries, and merges them into the local trust table with certainty scaled by the authority's own certainty value.

The key principle: **we trust what they trust, with some degree of certainty.**

Wikipedia links (core):
- [Decentralized Identifier (DID)](https://en.wikipedia.org/wiki/Decentralized_identifier)
- [ORCID](https://en.wikipedia.org/wiki/ORCID)
- [Web of trust](https://en.wikipedia.org/wiki/Web_of_trust)
- [Transitive trust](https://en.wikipedia.org/wiki/Transitive_trust)

---

## Storage format

Authority entries are truth records whose internal `content` field contains an `<authority>` XML block, and whose XML state form is a typed `<authority>` element:

```json
{
  "type": "truth",
  "id": "a_aristotle_01",
  "title": "Aristotle's Knowledge Base",
  "trust": 0.85,
  "content": "<authority><url>https://aristotle.example/kb.xml</url><refresh>3600</refresh></authority>",
  "time": "2026-02-27T00:00:01Z"
}
```

Fields inside `<authority>`:
- `url` — URL to a remote state file (required). May be `https://` or `file://` (within allowed data dir)
- `refresh` — seconds between re-fetches (optional, default: 3600)

The canonical XML state form is:

```xml
<authority id="a_aristotle_01" title="Aristotle's Knowledge Base" DoT="0.85" time="2026-02-27T00:00:01Z">
  <url>https://aristotle.example/kb.xml</url>
  <refresh>3600</refresh>
</authority>
```

`bin/truth.py` still accepts legacy attribute-style authority blocks when they appear inside internal `content` strings.

Authority entries use bare IDs (no prefixes), the same as all other trust entries. IDs are UUIDs or human-readable slugs.

---

## Certainty scaling

When an authority's remote trust entries are imported, each entry's certainty is scaled by the authority's own certainty:

```
scaled_certainty = authority_certainty × remote_certainty
```

Examples with authority certainty = 0.5:
- Remote entry at +1.0 → scaled to +0.5
- Remote entry at +0.9 → scaled to +0.45
- Remote entry at -0.8 → scaled to -0.4

This preserves the [-1, +1] Kleene range and naturally dampens remote beliefs proportionally to how much we trust the authority.

---

## Remote state format

The remote state file is an XML document containing a `<truth>` section. It may be a full WikiOracle State file (with `<state>` root) or an abbreviated file with just a `<truth>` root:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<truth>
  <fact id="remote_01" title="Water is wet" DoT="1.0" time="2026-02-27T00:00:01Z">
    Water is wet.
  </fact>
  <fact id="remote_02" title="Fire is hot" DoT="0.9" time="2026-02-27T00:00:02Z">
    Fire is hot.
  </fact>
</truth>
```

---

## ID namespacing

To prevent collisions between local and imported entries, imported entry IDs are prefixed with the authority's ID:

```
a_aristotle_01:t_fact_42
```

This means the same remote entry imported through different authorities will have different namespaced IDs, reflecting that its certainty may differ depending on which authority it came from.

---

## Fetch and caching

- Remote state files are fetched via HTTP GET (for `https://` URLs) or local file read (for `file://` within the allowed data directory)
- Results are cached in memory with a TTL equal to the `refresh` field (default: 3600 seconds)
- If a fetch fails, the error is logged and the authority is skipped (no crash)
- The cache is keyed by URL

---

## Security considerations

- **URL scheme restriction**: Only `https://` and `file://` (within `ALLOWED_DATA_DIR`) are permitted
- **Max response size**: Fetched data is capped at 1 MB
- **Max entries per authority**: At most 1000 trust entries are imported per authority
- **No recursive authorities**: If a remote state file contains `<authority>` entries, they are skipped. There is no transitive fetch chain — only one level of authority delegation is supported.
- **Rate limiting**: The in-memory cache prevents excessive re-fetching within the refresh interval

---

## Integration points

| File | Function |
|---|---|
| `bin/truth.py` | `parse_authority_block()`, `ensure_authority_id()`, `get_authority_entries()`, `resolve_authority_entries()`, `_fetch_authority()` |
| `bin/response.py` | Excludes `<authority>` entries from RAG; resolves authority entries and includes their scaled trust entries as `kind="authority"` sources |
| `client/util.js` | Trust editor UI: unified XHTML textarea with authority template, authority badge display |
| `test/hme.xml` | Test data with example authority entry (`auth_test_01`) |
| `test/hme_authority_fragment.xml` | Test fragment XML with two remote trust entries |
| `tests/test_authority.py` | Unit tests covering parsing, ID generation, resolution, certainty scaling, and security |

---

## See also

- [Constitution.md](./Constitution.md) — Section V defines authority delegation invariants.
- [HierarchicalMixtureOfExperts.md](./HierarchicalMixtureOfExperts.md) — authorities as part of the HME pipeline.
- [Logic.md](./Logic.md) — certainty scaling follows Kleene [-1, +1] semantics.
- [Security.md](./Security.md) — broader security considerations for the local-first system.
- [Entanglement.md](./Entanglement.md) — persistence policies governing imported entries.
- [BuddhistLogic.md](./BuddhistLogic.md) — authorities map to testimony (āgama/śabda) in pramana theory.
- [FutureWork.md](./FutureWork.md) — the "Network of Trust" roadmap extends authority delegation.
