# Labelled test sessions (DV4)

One JSON file per synthetic hearing, read by `evaluation/sessions.py` and scored by
`evaluation/detection_check.py`. `S12.json` is the format example; it is a
**draft** (`split: "draft"`, `reviewed: false`) and therefore not counted.

## Session fields

| field | meaning |
|---|---|
| `session_id` | unique id, e.g. `S12` |
| `split` | `dev` (threshold is chosen here), `test` (results are reported here) or `draft` (not counted) |
| `reviewed` | `true` only after a native Turkish speaker has checked the texts and labels |
| `language_pair` | e.g. `tr-nl` |
| `voices.interpreter` | must be **one** voice for an audio run; two voice profiles make the diarizer hear four speakers |
| `pairs` | ordered list, see below |

## Pair fields

| field | meaning |
|---|---|
| `pair_id`, `order` | unique id and position in the hearing |
| `direction` | `nl->tr` (officer to client) or `tr->nl` (client to officer) |
| `source`, `rendering` | `{speaker, lang, text}`; languages must match `direction` |
| `label` | `omissie`, `toevoeging`, `betekenisverschuiving`, `entiteitsfout`, `register_en_nadruk`, or any label starting with `controle` for a pair that must not be flagged |
| `subtype`, `severity`, `normbron` | free text; reported per pair, not used for scoring |
| `expected_flag` | `true` for deviations, `false` for controls (a control with `true` is rejected) |
| `reference_rendering` | optional correct rendering; never used for detection, only to show how far a deviation moves the score |

## Before a session counts

- one deviation per pair, and no unlabelled side effects (S12 renders *kişi*,
  "person", as *mannen*, "men", in P02 and P04 — a small gender addition that is
  in the reference too)
- controls include the permitted exceptions from DV1: a paraphrase the
  interpreter announces, a request to repeat, a language-variant notice
- spread every category over many sessions and voices; pairs within one session
  are not independent
- assign `dev`/`test` before scoring, and never move a session afterwards
