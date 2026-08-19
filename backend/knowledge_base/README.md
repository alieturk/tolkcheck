# `knowledge_base/` — RAG corpus for grounded feedback

This is the source corpus for TolkCheck's retrieval-augmented feedback generation
(see `app/services/retrieval.py`). When a client→officer or officer→client pair
scores below `retrieval.RETRIEVAL_SCORE_CEILING` (currently 0.70, mirroring the
"semantically correct" cut-off in `feedback.py`'s system prompt), the pipeline
embeds the pair, searches this corpus by cosine similarity, and passes the nearest
chunks to Claude as supporting context — so it can ground a flagged issue in an
actual source instead of only its own priors.

**Nothing in this directory is scraped or auto-generated.** Every file was written
by paraphrasing a source that was opened and read (per the verification discipline
in the `tolkcheck-bronnenonderzoek` skill: "an unverified citation is worse than no
citation"). Each file's `status` field says exactly what was and wasn't checked —
read it before trusting a claim, especially anything marked "niet onafhankelijk
bevestigd".

## Format

One `*.md` file per source. A `key: value` frontmatter block (not YAML — no parser
dependency for four flat strings), then the body. **Each blank-line-separated
paragraph in the body becomes one embedded chunk**, sharing that file's metadata.

```markdown
---
source_id: unique-slug-for-this-source
category: taxonomy | ind_procedure | linguistic_case
title: Full citation string (APA-ish) — shown to the LLM and, if it cites the
  chunk, to the IND officer reading the feedback. Keep it pasteable as-is.
language: nl
status: geverifieerd | editie geverifieerd | niet onafhankelijk bevestigd
---

First paragraph — becomes chunk 0.

Second paragraph — becomes chunk 1.
```

`source_id` must be unique across the corpus; re-ingesting a file with the same
`source_id` replaces its chunks rather than duplicating them.

## Categories

- **taxonomy** — error-type definitions and detection-methodology sources (why
  omission/addition/mistranslation are the right categories, how threshold
  calibration should be evaluated).
- **ind_procedure** — how an IND asielgehoor with a tolk is structured, and what
  the tolk's role/obligations formally are.
- **linguistic_case** — documented findings about actual interpreting behaviour at
  asylum hearings (discourse markers, hedges, repairs, neutrality breaks).

## Ingest / re-ingest

```bash
# from backend/, inside the container (needs the LaBSE weights + DB access)
uv run python -m app.cli ingest-knowledge knowledge_base
```

Safe to re-run any time — it re-embeds and replaces chunks per `source_id`, so
editing a file and re-running is the update path.

## Current corpus (2026-08-19) and what it does/doesn't cover

| source_id | category | status |
|---|---|---|
| `mqm-core-typology` | taxonomy | ✅ geverifieerd |
| `davis-goadrich-2006-pr-roc` | taxonomy | ✅ geverifieerd |
| `euaa-2024-asielgehoor-structuur` | ind_procedure | ✅ geverifieerd |
| `ind-wi-2024-5-werken-met-tolk` | ind_procedure | ✅ geverifieerd (via spiegel — origineel op puc.overheid.nl niet direct opgehaald) |
| `bannink-kramp-2023-rol-tolk-asielgehoren` | linguistic_case | ✅ inhoud geverifieerd, ⚠️ publicatiedatum/editie niet onafhankelijk bevestigd |

**This is a starter set, not a finished bronnenlijst.** Five sources across three
categories is enough to prove the retrieval pipeline works end to end; it is not
enough breadth for a defensible knowledge base. Known gaps:

- No second `linguistic_case` source — one paper carrying an entire category is
  thin, and everything in it is about Dutch-hearing interpreting generally, not
  Turkish–Dutch specifically (this project's actual language pair).
- No DV1/DV3 material (legal framework — Wbtv/Rbtv, AVG/BIO) — out of scope for
  *this* corpus (it grounds feedback text, not the architecture chapter), but
  worth a second corpus category if TolkCheck ever surfaces privacy/legal
  context to the officer too.
- `ind-wi-2024-5-werken-met-tolk` was read through a law-faculty mirror because
  `puc.overheid.nl` blocked automated fetching directly — re-verify against the
  original before using its exact wording in the afstudeerrapport itself (the
  paraphrase here is fine for RAG grounding, citation strings for the report
  need the primary source confirmed).
- No adversarial/negative examples — every `linguistic_case` chunk describes a
  real deviation. The corpus has nothing that looks like a deviation but isn't,
  which is exactly the kind of case DV4's false-positive concern is about.

Extending this corpus is exactly the kind of task the `tolkcheck-bronnenonderzoek`
skill is built for — use it per deelvraag, verify every candidate, then write the
paraphrased chunk file here (never paste more than a short quoted phrase from the
original; paraphrase, and cite).
