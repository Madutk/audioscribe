---
name: wiki-query
description: Answers questions exclusively from an LLM wiki (folder with CLAUDE.md, raw/, wiki/), with citations and pointers to contradictions. Use for 'ask the wiki', 'what does the wiki say about ...', 'query' or questions about requirements, processes and systems of the wiki's domain.
---

# Wiki Query

Answers a question from the content of an LLM wiki. The wiki is a folder with `CLAUDE.md` (schema), `raw/` (raw sources) and `wiki/` (pages).

## Preparation

1. Determine the wiki's root folder: the folder containing `CLAUDE.md` and `wiki/`. If the user gives no path, use the current working directory. If there is no wiki there, ask for the path.
2. Read `CLAUDE.md`. It is binding and takes precedence over this skill where the two differ.

## Procedure

Carry out the QUERY workflow from `CLAUDE.md`:

1. Read `wiki/index.md` and choose the relevant pages. Read them in full. Additionally run a full-text search for the key terms of the question and their synonyms from `wiki/glossary.md`.
2. Read raw sources in `raw/` only to verify a citation that a wiki page gives. They are no substitute for missing wiki knowledge.
3. Answer only from the wiki. Every statement carries its reference: page and citation, e.g. `ANF-012 [Q-003 · 00:14:32]`.
4. If the wiki says nothing about the question or part of it, say exactly that. Do not fill the gap with your own knowledge. Name the role that could answer.
5. Point out open contradictions and open items that affect the answer. For an open contradiction, give both statements and do not commit to either.
6. Distinguish the status in the answer: `bestätigt` (confirmed), `entwurf` (draft), `strittig` (disputed), `überholt` (superseded), `⚠️ inferred`.

## Writing

- Default: you write nothing. The answer appears only in the chat.
- Only if the user explicitly asks to file the answer: create an analysis page in `wiki/analyses/` (next free AN number, marked as AI-generated per `CLAUDE.md`), add it to `wiki/index.md` and append to `wiki/log.md`. Do not change any other pages in doing so.
- If you notice an error in the wiki while reading, do not change it. Mention it at the end of the answer and recommend a lint run.
