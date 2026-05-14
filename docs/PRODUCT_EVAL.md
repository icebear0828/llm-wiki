# LLM-Wiki Product Evaluation

> Status: draft
>
> Date: 2026-05-08

LLM-Wiki is a NotebookLM-first, self-first, open-source personal knowledge OS.
It is not a SaaS product. NotebookLM is the primary RAG and source-grounded
generation engine; LLM-Wiki is the automation, preservation, wiki, and
verification layer around it. The primary user is the owner of the vault, but
the project should remain reproducible enough that another user can clone it,
set up their own credentials, and run the same closed loop.

The product promise:

> Knowledge dropped into the vault can be reliably fed into NotebookLM,
> found locally, traced, connected, generated from, and reused months later.

## Product Shape

The core loop is:

```text
capture -> source normalize -> NotebookLM workspace -> generate/chat
        -> artifact persist -> wiki/link -> local search -> preserve
```

- `capture`: heterogeneous inputs enter the vault with low friction.
- `source normalize`: raw material becomes traceable local source records.
- `NotebookLM workspace`: sources are organized in reusable NotebookLM notebooks.
- `generate/chat`: NotebookLM handles source-grounded synthesis and generation.
- `link`: knowledge lands in Markdown and Obsidian bidirectional links, not isolated files.
- `local search`: local RAG retrieves notes and source-backed context for quick lookup, agent context, Gateway injection, and offline fallback.
- `produce`: the vault can generate memos, reports, slides, flashcards, audio, or other outputs.
- `preserve`: local files, Git history, repair commands, and safety gates protect the corpus.

## Priority Stack

All product dimensions matter, but they do not have equal priority when they conflict.

1. **Do not lose, leak, or corrupt data.**
   Data loss, credential leaks, unsafe Git behavior, and unrecoverable states are product blockers.

2. **Make knowledge reusable through NotebookLM and local source records.**
   A personal knowledge base fails if old knowledge cannot be found, traced,
   and re-fed into the right NotebookLM workspace.

3. **Make knowledge worth keeping.**
   Generated notes should preserve useful structure, claims, sources, and links, not just produce summaries.

4. **Make input broad and low-friction.**
   Papers, web pages, voice notes, videos, chat snippets, images, and code documents should all have a path in.

5. **Make output useful.**
   Reports, slides, flashcards, audio, and synthesis notes are valuable only after the lower layers are trustworthy.

6. **Make the open-source path reproducible.**
   A clean install should have clear setup steps, diagnostics, and test expectations.

## Evaluation Levels

### L0 Safety

These are non-negotiable release gates.

| Metric | Target |
| --- | --- |
| Secret leak count | `0` |
| Data loss count | `0` |
| Unrecoverable processing states | `0` |
| Unsafe force push paths | `0` |
| Raw input overwrite without explicit conflict handling | `0` |

Evidence:

- Secret safety tests cover Git autopilot staging and push guards.
- Credentials and local config files are ignored or explicitly denied.
- Failed tasks leave inspectable status and actionable errors.
- `processing` notes can be repaired or retried.

### L1 Closed Loop Reliability

The system should run the full loop without manual repair in normal use.

| Metric | Target |
| --- | --- |
| Ingest success rate | `>= 95%` |
| Core task E2E success rate | `>= 90%` |
| Consecutive live E2E successes per external task | `>= 3` |
| Failed task has actionable error | `100%` |
| `wikictl status` explains current state | `100%` for pending, processing, done, error |

Core external-service tasks:

- NotebookLM-backed tasks: `audio`, `report`, `slides`, `video`, `quiz`, `flashcards`, `infographic`, `data-table`, `source-add`, `chat`
- STT: `transcribe`
- Imagen: `gen-image`
- IM ingress: Telegram and HTTP ingest
- Local RAG query path through the gateway, when enabled, as supporting context rather than the primary NotebookLM answer engine

Mock tests are useful for development, but external-service changes are not complete until live E2E calls pass at least three consecutive times.

### L2 Knowledge Quality

The vault should become a usable knowledge network, not a directory of generated files.

| Metric | Target |
| --- | --- |
| NotebookLM workflow source-grounding score | `>= 4 / 5` on sampled real workflows |
| Local RAG top-5 source hit rate | `>= 80%` on real personal lookup questions |
| Generated note usefulness score | `>= 4 / 5` average on sampled notes |
| Wiki notes with traceable `sources` | `>= 95%` |
| Notes with meaningful links when relevant | `>= 80%` |
| Answers with source-backed claims | `>= 90%` |

Manual usefulness rubric:

| Score | Meaning |
| --- | --- |
| 1 | Cannot be trusted or reused |
| 2 | Captures surface summary but lacks source traceability or structure |
| 3 | Useful as a rough note, but needs manual cleanup |
| 4 | Good enough to search, cite, and reuse |
| 5 | High-quality knowledge artifact with clear sources, links, and reusable synthesis |

### L3 Personal Usage

The product is working only if it becomes part of the owner's real workflow.

| Metric | Target |
| --- | --- |
| Real inputs per week | `>= 30` |
| Real retrieval or reuse events per week | `>= 5` |
| Time from simple text capture to searchable note | `<= 30s` |
| Time from long-form source capture to searchable note | `<= 5m`, excluding slow external generation |
| Manual repair events per week | `<= 1` |

Examples of valid reuse events:

- Finding a previous paper, source, or claim instead of searching the web again.
- Generating a research memo from existing notes.
- Creating slides or flashcards from an already-ingested source.
- Asking a question and receiving an answer that points to the right wiki notes.

### L4 Open-Source Reproducibility

The project should be usable by another technical user without private context.

| Metric | Target |
| --- | --- |
| Clean install to first successful ingest | `<= 30m` |
| Hidden setup steps | `0` |
| Required credentials documented | `100%` |
| E2E skip conditions documented | `100%` |
| Failure messages include recovery hints | `>= 90%` |

## Product Eval Dataset

Create a small but realistic evaluation set under `tests/e2e` or a dedicated `eval/` directory.

Recommended seed set:

| Input type | Count | Expected path |
| --- | ---: | --- |
| arXiv papers | 10 | `raw/` -> `assets/arxiv/` -> `wiki/` |
| Web pages | 10 | `raw/` -> `wiki/` |
| Voice notes | 5 | `raw/` or IM -> `task/transcribe` -> `wiki/` |
| YouTube videos | 5 | `raw/` -> transcript/artifact -> `wiki/` |
| Images or screenshots | 5 | `raw/` -> `task/gen-image` or image-backed note |
| Project/code documents | 5 | `raw/` -> `wiki/` |

For each source, define:

- Source file or URL
- Expected title
- Expected `sources` value
- Expected artifact type, if any
- 2 to 3 natural-language questions a future user would ask
- Expected source note for each question
- Known claims that must not be hallucinated

## Required Product Scenarios

These scenarios define whether the product is usable.

1. Add an arXiv paper and verify PDF download, metadata, wiki note creation, source traceability, and RAG discoverability.
2. Generate report, slides, and audio from the same paper with live NotebookLM calls.
3. Send or import a voice note, transcribe it, and retrieve it by natural-language query.
4. Add a YouTube source and verify transcript or related artifact ingestion.
5. Add a web page and verify the generated wiki note preserves source URL and useful claims.
6. Ask a Chinese question against the relevant NotebookLM workspace and verify the answer is source-grounded.
7. Ask an English local lookup question and verify hybrid RAG returns the correct source notes.
8. Simulate an expired NotebookLM session and verify the error points to `npx notebooklm refresh-session`.
9. Simulate a stale `processing` note and verify repair or retry restores a valid state.
10. Add a same-name raw input and verify it does not overwrite existing data silently.
11. Place credential-like files in untracked directories and verify Git autopilot does not stage or commit them.
12. Run from a clean checkout and verify setup docs lead to first successful ingest without private knowledge.

## Acceptance Gates

A release or milestone should not be called product-ready unless:

- All L0 safety metrics pass.
- Core unit tests pass with `uv run`.
- External-service changes have live E2E evidence with at least three consecutive successes.
- NotebookLM workflow eval has recorded source-grounding evidence.
- Local RAG eval has a recorded source-hit score for lookup.
- At least one week of personal usage metrics has been reviewed.
- Setup docs have been checked from a clean environment or clean clone.

## Roadmap

The implementation roadmap is maintained in
[NotebookLM-first Roadmap](NOTEBOOKLM_FIRST_ROADMAP.md). The short version:

- P0: align positioning and setup docs around NotebookLM-first.
- P1: make NotebookLM workspaces first-class local objects.
- P2: strengthen source feed and provenance.
- P3: standardize recurring NotebookLM recipes.
- P4: make live E2E and recovery the release gate.
- P5: preserve the long-term wiki layer.

## What Not To Do Yet

- Do not build a SaaS control plane.
- Do not prioritize UI polish before reliability, traceability, and evals.
- Do not add many new task types before existing core tasks pass live E2E.
- Do not try to outbuild NotebookLM's RAG orchestration.
- Do not treat LLM-generated text as truth without source traceability.
- Do not bypass Markdown, frontmatter, Obsidian links, or Git history as the durable product layer.

## Product-Ready Definition

LLM-Wiki is product-ready for its intended self-first open-source shape when the owner can ask, after several months of real usage:

> What did I previously learn about this topic, where did it come from, and what can I produce from it now?

The system should return, within normal interactive latency:

- Relevant wiki notes
- Original sources
- Key claims or synthesis
- Related concepts and links
- Usable next outputs such as memo, slides, flashcards, or report
