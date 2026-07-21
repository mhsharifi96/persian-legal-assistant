---
name: iranian-legal-citation
description: Use when drafting a Persian legal answer that must preserve source identity and provide verifiable citations from retrieved evidence.
---

# Iranian legal citation

- Write in formal, readable Persian.
- Place the exact retrieved source marker after the supported claim: `[S1]`.
- Every substantive paragraph must contain at least one source marker supporting it.
- Use only source IDs returned by tools during this run.
- Preserve printed Persian legal names, article numbers, note numbers, and decision numbers exactly as shown in evidence.
- Distinguish the rule stated by a source from your analysis of how it may apply.
- Do not cite a search score, graph relationship, title, or metadata field as if it were legal text.
- Do not fabricate missing dates, amendment status, jurisdiction, quotations, or URLs.
- Return every cited marker in `cited_source_ids` in order of first use.
