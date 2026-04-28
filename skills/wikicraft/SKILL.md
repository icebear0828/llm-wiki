---
name: wikicraft
description: Weave raw/ notes into the wiki/ bidirectional-link knowledge network. TRIGGER when user says "absorb", "weave", "organize wiki", "find missing articles", "audit wiki", "wiki cleanup", or any /wikicraft subcommand. SKIP for plain queries (use `wikictl rag query`), mechanical file moves (use `wikictl ingest`), or multimodal artifact generation (task/* tags auto-trigger notecraft).
---

## Core Principle

**Weave, don't archive.** The essence of this skill is to **understand and weave** scattered material into a thematic article network.
"What does this raw note tell me that I didn't know before?" — that's the working mindset, not "which folder does this belong in?"

Derived from farzaa's personal-wiki-skill (gist `c35ac0cfbeb957788650e36aabea836d`), adapted for this project's vault architecture:

- **No `_index.md` / `_backlinks.json`**: This repo uses Obsidian `[[link]]` as the source of truth; no duplicate indexes are maintained.
- **No ingest subcommand**: Raw material enters the vault via `wikictl im` (IM gateway) / `wikictl ingest` (HTTP `/ingest`) / user manually writing to raw/. This skill starts from "content already in raw/".
- **Leave task tags to the watcher**: `tags: [task/*]` are run by `label_watcher` via notecraft. This skill **must not touch** them.
- **Three core actions**: absorb / cleanup / breakdown. Queries go through `wikictl rag query`, status through `wikictl status`.

## Commands

### `/wikicraft absorb [raw-note-path | "all" | date-range]`

**Weave** raw notes into existing wiki articles. This is not file-moving — it's content re-creation.

**Steps** (per raw note):

1. Read the raw note; understand what topics it covers and which named entities it mentions (people, places, projects, concepts)
2. `grep -l` + read `wiki/` to find related articles
3. Candidate actions (by priority):
   - Existing related article found: **re-read the full article** before deciding how to weave in (don't mechanically append paragraphs)
   - Named entity appearing for the first time with sufficient material (≥3 meaningful sentences): create a new article
   - Named entity appearing for the first time but only a passing mention: keep it inline in the existing article
   - Topic/pattern recurring across multiple notes: create a conceptual article (philosophies/, patterns/, tensions/)
4. After editing a wiki article:
   - Add the raw note ID as a **wikilink** in the `sources:` frontmatter (e.g. `sources: ["[[arxiv-2401.12345]]"]`) — bare strings produce no Obsidian graph edge.
   - Include at least one inline `[[<raw-note-id>]]` reference in the article body (e.g. a closing "## Source" line citing `[[arxiv-2401.12345]]`). Required so the graph edge from wiki article → raw stub is rendered even when readers ignore frontmatter.
   - Update `last_updated`.
5. **Keep** the raw note (do not unlink) — it is the source of truth; the ingest pipeline handles decisions about moving to wiki/

**Anti-cramming**: If you're about to add a third same-topic paragraph to an existing article, **create a new article instead**.

**Anti-event-log**: Articles should read like thematic narratives, not "what happened that day" chronologies. When rewriting, remove chronological structure and reorganize by thematic sections.

Pause every ~15 raw notes for self-check:
- Is the number of new articles created = 0? If so, you may be cramming — consider splitting.
- Randomly re-read 3 of the articles you edited: do they read like knowledge, or like a diary?

### `/wikicraft cleanup [article-path-or-glob]`

Audit existing wiki articles for richness and consistency.

Three phases (can spawn sub-Agents in parallel):

1. **Inventory**: Build a title list + wikilink graph of all wiki articles; flag orphan nodes
2. **Per-article assessment**: Length, tone, quote density, narrative vs. event-log, broken links. Rewrite event-driven sections (`## 2024-03-15` style) into thematic sections (`## Core Conflict During This Period`)
3. **Patch**: Deduplicate, add links, remove placeholders

Don't fix structural big-picture issues here — that's for `breakdown`.

### `/wikicraft breakdown [--reorganize]`

Identify **missing** and **overloaded** articles; generate new entries.

Four phases:

1. **Survey**: Scan wiki/ for overloaded (>150 lines), orphaned, and miscategorized articles
2. **Extract entities**: grep all wiki articles; extract named entities mentioned repeatedly but lacking their own page
3. **Rank + categorize**: Sort candidates by reference count; assign to the directory taxonomy below
4. **Parallel article creation**: Spawn a writing Agent per candidate; after writing, grep the entire vault to add backlinks

`--reorganize` mode: Move miscategorized articles (e.g., `life/some-belief.md` → `philosophies/`).

## Directory Taxonomy

Articles are organized by topic into directories. **Directories emerge from content — do not pre-create empty ones.**

- Core: `people/` `projects/` `places/` `events/` `companies/` `institutions/`
- Media: `books/` `films/` `music/` `games/` `tools/` `platforms/` `courses/`
- Inner: `philosophies/` `patterns/` `tensions/` `identities/` `life/`
- Narrative: `eras/` `transitions/` `decisions/` `experiments/` `setbacks/`
- Relationships: `relationships/` `mentorships/` `communities/`
- Work: `strategies/` `techniques/` `skills/` `ideas/` `artifacts/`
- Misc: `restaurants/` `health/` `routines/` `metaphors/` `assessments/` `touchstones/`

## Writing Guidelines

### Golden Rule

> "This is not Wikipedia about the thing. This is about the thing's role in the subject's life."

### Tone: Encyclopedic, Not AI-esque

**Avoid**: em-dash piling, big words (legendary / visionary / groundbreaking), editorial commentary (interestingly / importantly), rhetorical questions, progressive narratives, hedge stacking (perhaps / arguably / generally).

**Use**: Flat factual statements, one assertion per sentence, simple tenses, attributed phrasing ("described as energizing", not "was energizing"), quotes limited to the two most impactful at most.

### Length Targets

| Type | Lines |
|---|---|
| Person (1 mention) | 20-30 |
| Person (3+ mentions) | 40-80 |
| Place / Restaurant | 20-40 |
| Company | 25-50 |
| Philosophy / Pattern | 40-80 |
| Era | 60-100 |
| Decision / Transition | 40-70 |
| Minimum | 15 |

> 150 lines → split candidate.

### Article Structure Skeleton

```markdown
---
title: <Title>
type: person | project | place | concept | event
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
related: ["[[Article A]]", "[[Article B]]"]
sources: ["<raw-note-id-1>", "<raw-note-id-2>"]
---

# <Title>

<Thematic paragraphs, not chronological order.>

## Timeline (only when temporal anchoring is genuinely needed)

## Backlinks (optional; omit when Obsidian renders them automatically)
```

### Organized by Type

- **Person**: By role phase / relationship phase, not by when you met them
- **Place**: What happened there + what it signifies
- **Project**: Conception → development → outcome
- **Event**: What happened (brief) + why it matters (emphasis) + aftermath
- **Philosophy**: Thesis → evolution → validation / invalidation
- **Pattern**: Trigger → cycle → breaking attempts
- **Decision**: Situation → options → reasoning → choice
- **Era**: Context / projects / team / emotional tone

## Agreements with This Project

1. **Do not touch `tags: [task/*]`**: That is the watcher's domain; it triggers notecraft.
2. **Do not write to raw/**: raw/ is the source of truth — read-only. To update understanding, edit the references and summaries in wiki/ articles.
3. **Frontmatter `sources:`** must use the raw note filename (without `.md`) so RAG can trace back.
4. **No need to manually commit after editing wiki articles**: The `git_autopilot` daemon handles commits automatically.
5. **Plan before major changes**: When cleanup / breakdown involves moving/reorganizing multiple files, align with the user first via ExitPlanMode workflow.
6. **Obsidian `[[shortest]]` link format**: `.obsidian/app.json` has `newLinkFormat: shortest`; write links as `[[Title]]` not `[[wiki/path/to/Title]]`.
7. **Aliases when title ≠ filename**: Obsidian resolves `[[X]]` to a file named `X.md` OR a file whose `aliases:` frontmatter contains `X`. When the article's `title:` differs from its filename slug (e.g. Chinese title with English slug, or any rename), add `aliases: [<title>]` to frontmatter. Without this the `[[<title>]]` links from other articles render as unresolved (orange) graph nodes.

## Do Not

- Do not create `_index.md` / `_backlinks.json` duplicate indexes — Obsidian handles this itself.
- Do not pre-create empty directories as placeholders — directories emerge from content.
- Do not copy raw note source material verbatim into articles — absorb means **digest and restructure**.
- Do not do style unification/rewriting during the absorb phase — that belongs to cleanup.
- Do not run cleanup/breakdown as "rewrite every article" — only touch what's broken.
