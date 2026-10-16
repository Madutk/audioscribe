---
name: wiki-ingest
description: Ingests new raw sources (workshop transcripts, images) from raw/ into an LLM wiki following the Karpathy pattern. Use for 'ingest', 'process this source', 'new transcript into the wiki', or when a wiki should be created from scratch.
---

# Wiki Ingest

Ingests raw sources into an LLM wiki. The wiki is a folder with `CLAUDE.md` (schema), `raw/` (raw sources) and `wiki/` (pages).

## Preparation

1. Determine the wiki's root folder: the folder containing `CLAUDE.md` and `raw/`. If the user gives no path, use the current working directory. If there is no wiki there, ask for the path.
2. Read `CLAUDE.md` in full. It is binding and takes precedence over this skill where the two differ. If it is missing, stop and say so.
3. If `wiki/` is missing or empty, create the structure described in section 2 of `CLAUDE.md`, including `index.md`, `log.md`, `overview.md` and `glossary.md` as empty starter pages. Tell the user that you created the wiki from scratch.

## Which sources

- If the user names a raw source, ingest exactly that one.
- Otherwise determine the new sources: every entry directly under `raw/` (folder or file) for which there is no page in `wiki/sources/` with `rohquelle: raw/<name>` in its frontmatter.
- If there is no new source, say so and stop.
- Ingest multiple new sources one after another, in order of their names, each one completely before the next begins. A source is a folder as a whole, not each file individually.

## Procedure per source

Carry out the INGEST workflow from `CLAUDE.md`. Pay particular attention to:

- Read all files of the source, including images.
- Before writing, read `wiki/index.md`, `wiki/glossary.md` and the pages that may be affected. Check for duplicates before creating a new page.
- Enter `rohquelle: raw/<name>` in the frontmatter of the source page exactly like this. This is how the source is recognized as ingested.
- Every statement carries a citation with source and timestamp.
- If the source contradicts the existing content: keep both statements, create a contradiction page, set the affected requirements to `strittig` (disputed). Never decide yourself who is right.
- New requirements start as `entwurf` (draft).
- No names of people, only roles.
- Finally, maintain cross-references in both directions, the glossary, index, overview and log.

## Boundaries

- Write only under `wiki/`. Change nothing in `raw/` or in `CLAUDE.md`, not even to tidy up or rename.
- Do not invent anything. What the source does not provide appears in the wiki as `not captured` or becomes an open item.

## Wrap-up

For each source, check that the source page exists and is listed in the index. Then give the closing report from `CLAUDE.md`: new pages, changed pages, new contradictions, new open items, follow-up questions for the next workshop.
