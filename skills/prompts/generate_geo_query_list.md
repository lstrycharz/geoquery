# Generate GEO Query List — 25-Query Buyer Journey

## ⚠️ CRITICAL: this skill runs on a fast model (Haiku) for a reason

Thinking and Pro/Opus models over-reason these queries and produce expert-sounding text. Real buyers do not search the way an expert does. They use casual phrasing, half-formed questions, and drop filler words. **Match buyer voice, not SEO-professional voice.**

If this prompt is being executed by a slow/thinking model, stop and refuse — the output will be unfit for purpose.

## Task

Generate a **25-query buyer journey** for the given `(market, ICP segment)`, distributed across **five buyer framings**. Each framing gets exactly 5 queries. The queries should progress from broad/exploratory (positions 1–14) to refined/specific (positions 15–25).

## The five framings

1. **novice** — knows the problem exists but doesn't know the category name yet. ("what is X", "do I need Y", "is Y still a thing")
2. **problem-aware** — names the problem in their own words. ("our team can't find docs", "X is fragmented", "we keep losing knowledge")
3. **power-user** — knows the category, asks about implementation details. ("X with markdown", "self-hosted Y", "git-style versioning")
4. **vendor-comparing** — names specific products. ("A vs B", "alternatives to C", "best X for Y in 2026")
5. **price-driven** — money-and-ROI framing. ("cheap X", "free Y", "Z under $N/month", "X pricing 2026")

## Quality rules

- **Conversational tone.** Use buyer vocabulary. Skip filler words like a real query: `notion vs confluence engineering` not `What are the differences between Notion and Confluence for engineering teams?`
- **Refinement only on positions 15–25.** Earlier queries stay broad. Refined queries name competitors, specifics (SSO, audit log, soc2, markdown, etc.), and money.
- **Realistic redundancy.** Real buyers re-search with slightly different phrasing. Don't aggressively deduplicate.
- **Match the ICP's `language_patterns` where they exist.** If the segment uses the phrase "single source of truth", at least one query should contain it.
- **Numbering is sequential 1..25.** Positions must match list order exactly.

After the 25 queries, produce a `journey_arc_summary` (3–5 sentences) describing how a real buyer's search vocabulary progresses through the list.

Emit via the `emit_generate_geo_query_list` tool.
