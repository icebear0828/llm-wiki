# NotebookLM-first Roadmap

> Status: accepted planning baseline
>
> Date: 2026-05-14

LLM-Wiki is a NotebookLM-powered personal knowledge OS.

NotebookLM is the primary RAG and source-grounded generation engine. LLM-Wiki
is the automation and preservation layer around it: capture inputs, route tasks,
reuse NotebookLM workspaces, persist artifacts, keep Obsidian Markdown usable,
record Git history, and verify that the live external workflow still works.

## Product Boundary

### NotebookLM owns

- Source-grounded RAG over uploaded sources.
- Notebook-level source organization and answer grounding.
- Generation of reports, audio, slides, video links, flashcards, quizzes,
  infographics, data tables, and NotebookLM chat answers.
- Deep synthesis inside a notebook or topic workspace.

### LLM-Wiki owns

- Low-friction capture into `raw/` from CLI, IM, web, arXiv, YouTube, voice,
  screenshots, PDFs, and local notes.
- The `task/*` frontmatter protocol and watcher state machine.
- NotebookLM workspace reuse through frontmatter `notebook_id` and
  `<vault>/.llmwiki/notebooks.json`.
- Source manifests, artifact paths, local embeds, run records, status, repair
  hints, and Git autopilot.
- Durable Markdown knowledge in `wiki/`, with Obsidian links and traceable
  `sources`.
- Local search/RAG for agent context, quick lookup, Gateway injection, and
  offline fallback.

### Explicit non-goals

- Do not try to outbuild NotebookLM's RAG orchestration.
- Do not treat local RAG as the main answer engine when a NotebookLM workspace
  is available.
- Do not add new generation task types before the existing NotebookLM-backed
  tasks are reliable in live E2E.
- Do not let generated artifacts become untraceable files detached from
  `raw/`, `wiki/`, notebook ids, and source records.

## North Star Flow

```text
capture -> source normalize -> NotebookLM workspace -> generate/chat
        -> artifact persist -> wiki/link -> local search -> preserve
```

The first-class object is no longer a one-off generated file. It is a reusable
NotebookLM workspace tied to local source records and durable Markdown notes.

## Phases

### P0: Align Positioning and Documentation

Goal: make the repo, docs, and future issues say the same thing.

Tasks:

- Update README language to describe the product as NotebookLM-first.
- Update setup docs so NotebookLM session and workspace reuse are presented as
  the core path, not an optional integration.
- Fix documentation drift around `<vault>/.llmwiki/notebooks.json`: keys are
  vault-relative POSIX paths such as `raw/foo.md`, not note stems.
- Reframe local RAG as support infrastructure: quick lookup, agent context,
  Gateway injection, and offline fallback.

Acceptance:

- No primary docs imply that LLM-Wiki is trying to replace NotebookLM RAG.
- The setup path makes NotebookLM session export and workspace reuse explicit.
- NotebookIndex docs match the current schema.

### P1: Make NotebookLM Workspaces First-class

Goal: treat notebooks as stable knowledge containers, not subprocess side
effects.

Tasks:

- Define a workspace model with `notebook_id`, `scope`, `key`, local source
  refs, status, and last verification time.
- Support note-scoped workspaces for one source note.
- Support topic-scoped workspaces for multi-source synthesis.
- Extend `wikictl notecraft` or an equivalent command surface for
  `list`, `status`, `verify`, and garbage collection.

Acceptance:

- A note can reliably reuse its NotebookLM workspace across generation tasks.
- A topic can accumulate multiple sources into one NotebookLM workspace.
- CLI status shows notebook health without requiring manual log spelunking.

### P2: Strengthen Source Feed

Goal: feed NotebookLM better sources and preserve the local evidence chain.

Tasks:

- Normalize arXiv, YouTube, web, PDF, IM, voice transcription, and local notes
  into source records that can be added to NotebookLM.
- Track which local sources have been added to which notebook.
- Prevent accidental duplicate source-add operations where the local manifest
  can prove the source was already added.
- Keep local `raw/`, `wiki/`, and `assets/` records traceable to source URLs,
  source files, notebook ids, and generated artifacts.

Acceptance:

- Re-running source feed does not blindly duplicate already recorded sources.
- Generated outputs can be traced back to original local sources and a
  NotebookLM notebook id.
- Topic workspaces can grow over time without losing local provenance.

### P3: Standardize NotebookLM Recipes

Goal: turn recurring generation flows into stable recipes.

Priority recipes:

- Paper -> report + slides + audio.
- YouTube transcript -> summary + flashcards.
- Topic notebook -> synthesis memo.
- Topic notebook -> Q&A/chat.
- Weekly sources -> review memo.

Tasks:

- Define input rules, notebook selection rules, output paths, and frontmatter
  write-back behavior for each recipe.
- Normalize artifact naming and embed placement.
- Productize vendor quirks: video may only return a URL, audio may be an mp4
  container, and CDN retries can be slow.

Acceptance:

- Multiple generation tasks can run against the same notebook without losing
  notebook identity.
- Outputs land predictably in `assets/` and `wiki/`.
- Failure states are visible through `wikictl status` with a next action.

### P4: Make Live E2E and Recovery the Gate

Goal: make NotebookLM private API/session fragility operationally manageable.

Tasks:

- Add or harden NotebookLM session health checks.
- Make `SessionExpired` recovery point clearly to `npx notebooklm
  refresh-session` and `npx notebooklm export-session`.
- Surface `NOTECRAFT_DEBUG_LOG_DIR` in status and troubleshooting docs.
- Keep the NotebookLM E2E matrix focused on live calls, not mock-only success.

Acceptance:

- Minimal NotebookLM live E2E passes three consecutive times before a
  NotebookLM behavior change is called done.
- The full NotebookLM task matrix has recorded live evidence when a release or
  milestone claims it is healthy.
- Failures are classified as local wrapper bug, session expiry, rate limit,
  upstream flake, or CDN/download behavior.

### P5: Preserve the Long-term Wiki Layer

Goal: keep Markdown as durable memory while NotebookLM handles deep reasoning.

Tasks:

- Keep wikicraft focused on `absorb`, `cleanup`, and `breakdown`; it must not
  take over watcher-owned `task/*` behavior.
- Require generated wiki notes to carry source traceability, key claims, and
  useful links where relevant.
- Evaluate local RAG on whether it finds the right local notes and sources,
  not whether it out-answers NotebookLM.
- Add a periodic review flow for new sources, missing topic notes, stale
  notebooks, and reusable outputs.

Acceptance:

- `wiki/` remains searchable, linkable, source-backed, and useful months later.
- Deep source-grounded Q&A goes through NotebookLM when a notebook exists.
- Local retrieval can still recover the right notes when NotebookLM is not in
  the loop.

## Verification Policy

- Documentation-only changes must at least validate links and referenced paths.
- Python behavior changes require `uv run ruff check .` and
  `uv run pytest tests/ --ignore=tests/e2e`.
- NotebookLM behavior changes require live E2E, with at least three consecutive
  successful real calls before the change is considered complete.
- Mock tests are useful for wrapper logic but do not prove the NotebookLM path
  works.

## Immediate Backlog

1. Align README and setup docs with this NotebookLM-first boundary.
2. Create issues for P1 through P5 so implementation work has stable handles.
3. Design the first-class workspace model before adding more recipes.
4. Add source manifest semantics before expanding topic-level synthesis.
5. Keep local RAG improvements scoped to lookup, agent context, Gateway
   injection, and offline fallback.
