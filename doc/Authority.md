# Authority

## Transitive trust in WikiOracle's truth system

An **authority** is a trust entry that references an external agent's knowledge base. Instead of containing facts directly, an `<authority>` entry points to a remote `llm.jsonl` file. At evaluation time, the server fetches that file, extracts its trust entries, and merges them into the local trust table with certainty scaled by the authority's own certainty value.

The key principle: **we trust what they trust, with some degree of certainty.**

Wikipedia links (core):
- [Decentralized Identifier (DID)](https://en.wikipedia.org/wiki/Decentralized_identifier)
- [ORCID](https://en.wikipedia.org/wiki/ORCID)
- [Web of trust](https://en.wikipedia.org/wiki/Web_of_trust)
- [Transitive trust](https://en.wikipedia.org/wiki/Transitive_trust)

---

## Storage format

Authority entries are trust entries whose `content` field contains an `<authority>` XML block:

```json
{
  "type": "truth",
  "id": "a_aristotle_01",
  "title": "Aristotle's Knowledge Base",
  "certainty": 0.85,
  "content": "<authority id=\"a_aristotle_01\" certainty=\"0.85\" title=\"Aristotle's Knowledge Base\" did=\"did:web:aristotle.example\" url=\"https://aristotle.example/kb.jsonl\"/>",
  "time": "2026-02-27T00:00:01Z"
}
```

Fields inside `<authority>`:
- `did` — Decentralized Identifier (optional; at least one of did/orcid should be present)
- `orcid` — ORCID identifier (optional)
- `url` — URL to a remote `llm.jsonl` file (required). May be `https://` or `file://` (within allowed data dir)
- `refresh` — seconds between re-fetches (optional, default: 3600)

Both attribute-style (`<authority did="..." url="..." />`) and child-element style (`<authority><did>...</did><url>...</url></authority>`) are supported, following the same pattern as `<provider>`.

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

## Abbreviated JSONL

The remote `llm.jsonl` file may be **abbreviated** — it does not need to contain a header or conversation records. Lines that are valid JSON with `"type": "truth"` are extracted; all other lines (headers, conversations, malformed JSON) are skipped.

Example abbreviated file:
```jsonl
{"type":"truth","id":"remote_01","title":"Water is wet","certainty":1.0,"content":"<fact id=\"remote_01\" certainty=\"1.0\" title=\"Water is wet\">Water is wet.</fact>","time":"2026-02-27T00:00:01Z"}
{"type":"truth","id":"remote_02","title":"Fire is hot","certainty":0.9,"content":"<fact id=\"remote_02\" certainty=\"0.9\" title=\"Fire is hot\">Fire is hot.</fact>","time":"2026-02-27T00:00:02Z"}
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

- Remote JSONL files are fetched via HTTP GET (for `https://` URLs) or local file read (for `file://` within the allowed data directory)
- Results are cached in memory with a TTL equal to the `refresh` field (default: 3600 seconds)
- If a fetch fails, the error is logged and the authority is skipped (no crash)
- The cache is keyed by URL

---

## Security considerations

- **URL scheme restriction**: Only `https://` and `file://` (within `ALLOWED_DATA_DIR`) are permitted
- **Max response size**: Fetched JSONL is capped at 1 MB
- **Max entries per authority**: At most 1000 trust entries are imported per authority
- **No recursive authorities**: If a remote JSONL contains `<authority>` entries, they are skipped. There is no transitive fetch chain — only one level of authority delegation is supported.
- **Rate limiting**: The in-memory cache prevents excessive re-fetching within the refresh interval

---

## Integration points

| File | Function |
|---|---|
| `bin/truth.py` | `parse_authority_block()`, `ensure_authority_id()`, `get_authority_entries()`, `resolve_authority_entries()`, `_fetch_authority_jsonl()` |
| `bin/response.py` | Excludes `<authority>` entries from RAG; resolves authority entries and includes their scaled trust entries as `kind="authority"` sources |
| `html/util.js` | Trust editor UI: unified XHTML textarea with authority template, authority badge display |
| `spec/hme.jsonl` | Test data with example authority entry (`auth_test_01`) |
| `spec/hme_authority_fragment.jsonl` | Test fragment JSONL with two remote trust entries |
| `tests/test_authority.py` | Unit tests covering parsing, ID generation, resolution, certainty scaling, and security |
