---
name: wiki-lint
description: Checks an LLM wiki (folder with CLAUDE.md, raw/, wiki/) for contradictions, unsupported statements, broken links, gaps and requirement quality, and writes a review report with a question catalog. Use for 'lint', 'check the wiki', 'wiki status' or 'health check for the wiki'.
---

# Wiki Lint

Checks the state of an LLM wiki. The wiki is a folder with `CLAUDE.md` (schema), `raw/` (raw sources) and `wiki/` (pages).

## Preparation

1. Determine the wiki's root folder: the folder containing `CLAUDE.md` and `wiki/`. If the user gives no path, use the current working directory. If there is no wiki there, ask for the path.
2. Read `CLAUDE.md` in full. It is binding and takes precedence over this skill where the two differ.

## Three levels

Choose the level according to what the user asks for:

- **Status** ("status", "what's new", "quick check"): only the structure check below, result in the chat, write nothing.
- **Lint** (default): structure check plus content check, report to `wiki/lint/lint-<YYYY-MM-DD>.md`, entry in `wiki/log.md`. Change nothing else.
- **Lint with fixes** (only when explicitly requested, e.g. "and fix it", "fix"): additionally fix what is listed under Fixes.

## Structure check

Check mechanically across all pages under `wiki/` except `wiki/lint/`. If `wiki.py` is in the root folder, you can run `python3 wiki.py status` instead and adopt its result.

- Broken links: `[[target]]` with no file `target.md`.
- Orphans: pages without an incoming link from another content page (index and log do not count).
- Pages missing from `wiki/index.md`, and index entries without a page.
- Missing or faulty frontmatter, duplicate IDs, file name not matching the ID.
- Missing back-links.
- Raw sources under `raw/` without a source page with a matching `rohquelle:` entry.

## Content check

Read all pages for this, not just the index. Check the points from the LINT workflow in `CLAUDE.md`:

- Contradictions between pages that do not yet have a contradiction page.
- Superseded statements that are not marked as superseded.
- Statements without a citation. Additionally check a sample of citations against the raw source: does it really say that, at the given timestamp? State in the report how many citations you checked.
- Systems, roles, terms or processes mentioned several times without a page of their own.
- Requirements: duplicates, conflicts among each other, vague wording without an open item, status `bestätigt` (confirmed) without explicit confirmation, missing process reference. Processes without requirements.
- Gaps: processes with `not captured` for trigger, frequency, roles or systems.
- Names of people in the wiki.

## Report

Organize by severity: first whatever endangers the wiki's reliability (contradictions, unsupported statements, wrong citations), then structure, then gaps. Each finding names the page and the location. Close with a question catalog for the next workshop, ordered by the role that can answer. The report is marked as AI-generated.

In the chat, give a short summary: number of findings per group, the three most important, path to the report.

## Fixes

Only with an explicit request, and only this:

- Fix structural errors: links, back-links, index, frontmatter.
- Create missing contradiction and open-item pages.

Never: decide content contradictions, delete statements, set status to `bestätigt` (confirmed), write to `raw/` or to `CLAUDE.md`. List in the report what you changed.
