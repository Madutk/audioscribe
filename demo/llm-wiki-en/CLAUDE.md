# CLAUDE.md: LLM wiki for the Assistant domain

This document is the schema of the wiki. It defines how the wiki is structured and how you maintain it. Read it in full before any work. Never change it yourself; proposed changes belong in the final report.

## 1. Purpose

The wiki is the knowledge base for **requirements analysis in the Assistant domain**. It brings together everything that was said and shown in process recordings and requirements workshops: processes, requirements, systems, roles, terms, decisions, open items and contradictions.

The human supplies sources and asks questions. You take care of maintenance: summarizing, filing, linking, reconciling, keeping records. One wiki covers exactly one domain.

Other tools also **only read** the wiki (e.g. for live reconciliation in meetings). That is why statements must be individually findable and backed by a source.

## 2. Three layers

```
CLAUDE.md            Schema (this document). Do not change.
raw/                 Raw sources. Immutable. Read only.
  <YYYY-MM-DD>_<shortname>/   one folder per workshop or recording:
                              transcript, images, possibly a companion file with markers
wiki/                The wiki. This is the only place you write.
  index.md           Catalog of all pages
  log.md             Chronicle, append-only
  overview.md        Situation overview of the domain
  glossary.md        Terms and confirmed misrecognitions
  sources/           Q-nnn    one page per raw source
  processes/         PRO-nnn
  requirements/      ANF-nnn
  systems/           SYS-nnn  system catalog
  roles/             ROL-nnn
  decisions/         ENT-nnn
  open-items/        OP-nnn
  contradictions/    WID-nnn
  analyses/          AN-nnn   saved answers to questions
  lint/              check reports
```

## 3. Iron rules

1. **Raw sources are immutable.** Nothing in `raw/` is ever written, renamed or deleted.
2. **Make nothing up.** Only what a source supports goes into the wiki. No world knowledge of your own about the domain, even if it would be plausible.
3. **Every statement carries a citation** (section 5). Logical additions are allowed if they are marked `⚠️ inferred` and briefly justified.
4. **Contradictions are reported, not decided.** If a new source contradicts the wiki, both statements stay with their citations, and a WID page is created. The human decides who is right.
5. **Never overwrite silently.** Outdated statements are not deleted but marked as superseded, with a reference to the source that replaced them.
6. **Roles, not people.** The wiki contains no names of people, even if they appear in the transcript. Write "Assistant", "manager", "travel office". Exception: names of systems, products and organizational units.
7. **Documented and AI-generated content stay separate.** Your analyses, assessments and summaries only go in `analyses/`, `lint/` and `overview.md`, where they are marked as AI-generated. They are never evidence for a knowledge page.
8. **Language:** English, factual, concise.

## 4. Pages

### File names, IDs, links

- File name: `<ID>-<short-slug>.md`, e.g. `ANF-012-booking-without-follow-up.md`. Lowercase, hyphens, ASCII only in the slug.
- IDs are three digits, sequential per type, and never reassigned. The next free number comes from `index.md`.
- Links as wikilinks to the file name without extension: `[[ANF-012-booking-without-follow-up|ANF-012]]`.
- Every page links to the pages it is related to in substance (process ↔ requirement ↔ system ↔ role). Always maintain links in both directions.

### Frontmatter (all pages except index, log, lint)

The frontmatter keys and their values (`typ`, `status`, `art`, `prioritaet`) are machine-readable and stay as listed here; only `titel` is free text.

```yaml
---
id: ANF-012
typ: anforderung          # quelle | prozess | anforderung | system | rolle | entscheidung | offener-punkt | widerspruch | analyse
titel: Booking without follow-up up to an amount limit
status: entwurf           # per type, see below
quellen: [Q-003, Q-005]
aktualisiert: 2026-10-06
---
```

Value meanings: `quelle` source, `prozess` process, `anforderung` requirement, `rolle` role, `entscheidung` decision, `offener-punkt` open item, `widerspruch` contradiction, `analyse` analysis; `entwurf` draft, `bestätigt` confirmed, `strittig` disputed, `überholt` superseded, `offen` open, `geklärt` resolved, `entschieden` decided, `skizze` sketch, `aufgenommen` recorded, `genannt` named, `beschrieben` described.

### Page types

**Source (Q)**, additionally in the frontmatter: `rohquelle: raw/<folder-or-file>`, `datum`, `art` (workshop | prozessaufnahme | dokument | bild | sonstiges). The `titel` has the form `<kind> <n> – <topic>`. Content: roles involved, summary in five to ten sentences, key statements as a list with timestamps, list of images with one sentence each, wiki pages touched.

**Process (PRO)**, status `skizze | aufgenommen | bestätigt`. Fixed sections: purpose, trigger, frequency, roles, systems, flow (numbered steps), decisions in the flow, variants and special cases, pain points, derived requirements, open items. If the sources do not provide something, write `not captured`, not a guess.

**Requirement (ANF)**, status `entwurf | bestätigt | strittig | überholt`. Additionally in the frontmatter: `art` (funktional | nicht-funktional | randbedingung), `prioritaet` (muss | soll | kann | unbekannt). Content: the requirement in one sentence, rationale, affected processes, systems and roles, acceptance criterion. Rules:

- One requirement per page.
- New requirements always start as `entwurf`. Someone saying something in a workshop or describing the current state is not a confirmation. `bestätigt` only if the business side explicitly confirms an already formulated requirement in a later source, or the human sets the status.
- Priority and acceptance criterion only if stated. Otherwise `unbekannt` or `not captured`.
- Take vague wording ("fast", "simple", "as far as possible") verbatim and create an open item to make it precise.
- Check for duplicates before creating. Same requirement from a new source: extend the existing page, add the source.

**System (SYS)**, status `genannt | beschrieben`. Content: exact name, purpose in the domain, who uses it, in which processes, interfaces and media breaks, known limitations.

**Role (ROL)**: tasks in the domain, processes involved, systems used, authority and limits.

**Decision (ENT)**: what was decided, when, by which role, rationale, impact.

**Open item (OP)**, status `offen | geklärt`. Content: the question, why it is open, which role can answer it, affected pages. When resolved: enter the answer with a citation, change the status, keep the page.

**Contradiction (WID)**, status `offen | entschieden`. Content: statement A with citation, statement B with citation, affected pages, possible explanation (as `⚠️ inferred`). Only the human, or a source that explicitly settles the point, enters the decision.

**Analysis (AN)**: saved answer to a question. First line after the frontmatter: `> AI-generated on <date> based on the state of the wiki.`

### glossary.md

A table: term, meaning in the domain, synonyms, misrecognitions (how speech recognition mangles the term), citation. Enter new suspected misrecognitions with `⚠️ uncertain` until they are confirmed. Confirmed misrecognitions additionally go into a table with the header `| Misrecognition | Correct |`; tools use it to correct transcripts when searching.

## 5. Citations

- Form: `[Q-003 · 00:14:32]` for transcript passages, `[Q-003 · image-02.png]` for images, `[Q-003]` if there is no more precise anchor.
- The citation goes at the end of the statement, one statement per bullet or sentence. That keeps every statement individually findable.
- Images beat the transcript on facts (system name, field label, screen). The transcript beats images on intent and rationale.
- Transcripts come from automatic speech recognition. Correct mangled terms using `glossary.md` and the images. When in doubt, quote the source verbatim and add `⚠️ uncertain`.
- Superseded statement: `~~old statement~~ [Q-002 · 00:03:10] (superseded by [Q-005 · 00:21:40])`.

## 6. Workflows

### INGEST: incorporate a raw source

Always exactly one raw source per run.

1. Read all files of the raw source, images included. If there is a companion file with markers (contradiction, open item, question), those are hints to follow up on. They are not facts.
2. Read `wiki/index.md` and `wiki/glossary.md`, then the pages the source may touch.
3. Create the source page (next free Q number) with `rohquelle:` in the frontmatter.
4. Extract from the source: processes, requirements, systems, roles, terms, decisions, open items. For each finding: extend an existing page or create a new one. Citation on every statement.
5. Reconcile every new statement with the existing content. On a deviation: rules 4 and 5 from section 3, create a WID page, set the affected requirements to `strittig`.
6. Check whether the source resolves existing open items or contradictions, and record that there.
7. Maintain cross-references in both directions, `glossary.md`, `index.md` and, for significant changes, `overview.md`.
8. Append an entry to `log.md`.
9. Final report in the chat: new pages, changed pages, new contradictions, new open items, questions for the next workshop.

Small talk, organizational matters and digressions are not recorded.

### QUERY: answer a question

1. Read `wiki/index.md`, then the relevant pages. Raw sources only if a wiki page is not enough to verify a citation.
2. Answer only from the wiki. Every statement with its location: page and citation, e.g. `ANF-012 [Q-003 · 00:14:32]`.
3. If the wiki says nothing about it, say exactly that. Do not fill the gap with your own knowledge. Name the role that could answer the question.
4. Point out open contradictions and open items that affect the answer.
5. Only if explicitly requested: save the answer as an AN page in `analyses/`, add it to `index.md`, extend `log.md`.

### LINT: check the wiki

Check and write a report to `wiki/lint/lint-<YYYY-MM-DD>.md`:

1. **Contradictions** between pages that do not have a WID page yet.
2. **Outdated content:** statements superseded by a newer source without being marked.
3. **Unsupported content:** statements without a citation, or with a citation the source page does not support (spot check against `raw/`).
4. **Structure:** broken links, orphans, pages missing from `index.md`, missing back-links, missing or faulty frontmatter, raw sources without a source page.
5. **Missing pages:** systems, roles, terms or processes that are mentioned several times but have no page of their own.
6. **Requirements quality:** duplicates, conflicts between requirements, vague wording without an open item, requirements without a process, processes without requirements.
7. **Gaps:** processes with `not captured` for trigger, frequency, roles or systems. Names of people in the wiki (rule 6).
8. **Question list for the next workshop:** from open items, contradictions and gaps, ordered by the role that can answer.

Without a fix order you only write the report and the log entry. With a fix order you additionally fix item 4 as well as missing WID and OP pages. You never decide contradictions in substance.

## 7. index.md and log.md

**index.md** lists every page exactly once, grouped by type, one line each: link, title, status, one sentence of content. At the top, the highest assigned number per type.

**log.md** is append-only, newest entries at the bottom. Format:

```
## [2026-10-06] ingest | Q-003 Workshop travel booking
- new: ANF-012, ANF-013, SYS-004
- changed: PRO-002
- contradictions: WID-002
- open items: OP-007
```

Operations: `ingest`, `query`, `lint`.
