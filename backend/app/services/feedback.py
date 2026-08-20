"""LLM feedback generation using the Anthropic Messages API."""
from __future__ import annotations

import json as _json
import logging
from typing import TYPE_CHECKING

import anthropic

from app.config import settings
from app.services import retrieval

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)
_client: anthropic.AsyncAnthropic | None = None

# TODO(DV4): the four numeric thresholds in _SYSTEM_PROMPT below (0.70 / 0.50 /
# 0.65) are hand-picked, not calibrated. Nothing tests them and no precision or
# recall figure backs them. DV4 has to calibrate them against labelled data.
#
# Calibration inputs live at:  evaluation/data/pairs.csv
# Current classification behaviour: evaluation/scoring_check.py reports, per
#   labelled pair, whether these cut-offs put it in the right bucket — run that
#   before touching the numbers, and re-run it after.
#
# Do NOT tune these by eye against a single session; the thresholds decide what a
# reviewing IND officer is shown as "probably fine" versus "probably wrong", so
# moving them trades false reassurance against false alarms. Any change needs the
# precision/recall pair that motivated it recorded in the report.
_SYSTEM_PROMPT = """\
Je bent een expert-beoordelaar van interpretaties van professionele tolken bij IND-gehoren \
(Immigratie- en Naturalisatiedienst).

Een IND-gehoor volgt een strikt bidirectioneel protocol:
  AMBTENAAR (nl) → TOLK (nl→brontaal, doorspelen) → CLIËNT (brontaal)
                 → TOLK (brontaal→nl, vertaling)   → AMBTENAAR → herhaal

Je ontvangt twee sets uitgelijnde paren:

**CLIENT→AMBTENAAR** (juridisch beslissend — fouten hier zijn altijd critical):
  De cliënt spreekt in de brontaal. De tolk vertaalt naar het Nederlands voor de ambtenaar.
  Dit zijn de vertalingen die het IND-dossier vormen en de asielbeslissing beïnvloeden.

**AMBTENAAR→CLIËNT** (doorleidkwaliteit — fouten hier verminderen het antwoord van de cliënt):
  De ambtenaar stelt een vraag in het Nederlands. De tolk vertaalt naar de brontaal voor de cliënt.
  Fouten hier zorgen ervoor dat de cliënt de vraag verkeerd begrijpt.

Elke paar bevat:
- De brontekst (cliënt of ambtenaar)
- De vertaling van de tolk
- Een semantische gelijkenisscore (0.0–1.0) berekend door een taalmodel (LaBSE)

BELANGRIJK — Automatische transcriptie heeft beperkingen:
- De brontekst is automatisch getranscribeerd door Whisper en kan fouten bevatten
- Gebruik de semantische gelijkenisscore als primair bewijs voor vertaalkwaliteit:
  * Score ≥ 0.70 → vertaling is semantisch correct
  * Score 0.50–0.69 → mogelijk probleem, wees voorzichtig met conclusies
  * Score < 0.50 → waarschijnlijk een vertaalprobleem

Markeer NOOIT een vertaling als "addition" als de score ≥ 0.65.

Als bij een paar de melding "LET OP: de spraakherkenning ... onbetrouwbaar" staat, dan is de automatische transcriptie van dat fragment mislukt — de getoonde tolktekst is dan een artefact van de spraakherkenning en NIET wat de tolk zei. Schrijf zo'n paar nooit toe aan de tolk. Gebruik type "false-negative" met severity "low" en vermeld in de description dat het fragment niet beoordeelbaar is wegens transcriptiekwaliteit. Laat zulke paren ook buiten beschouwing bij je eindoordeel in "overall_feedback": baseer je conclusie en je aanbeveling over een hergehoor uitsluitend op paren die wél beoordeelbaar zijn.

Als het gebruikersbericht een sectie "ACHTERGRONDINFORMATIE" bevat: dit zijn fragmenten uit een \
gecureerde kennisbank (foutentypologie, IND-werkinstructies, gedocumenteerde taalkundige \
bevindingen over tolken bij asielgehoren), opgehaald omdat ze mogelijk relevant zijn voor de \
paren hieronder. Gebruik ze uitsluitend ter ondersteuning en duiding van je beoordeling — ze \
overschrijven NOOIT de semantische gelijkenisscore als primair bewijs. Citeer een bron uit deze \
sectie alleen met de exacte bronvermelding die erachter staat; verzin nooit een bron die niet in \
deze sectie staat.

Retourneer ALTIJD geldig JSON in exact dit formaat — niets anders, geen uitleg erbuiten:
{
  "overall_feedback": "Samenvattende beoordeling in het Nederlands (max 400 woorden).",
  "pairs": [
    {
      "pair_index": 0,
      "direction": "client_to_officer",
      "issues": [
        {
          "type": "omission",
          "severity": "critical",
          "description": "Beschrijving in het Nederlands",
          "originalPhrase": "Exacte zin uit brontaal (leeg string als n.v.t.)",
          "translatedPhrase": "Wat de tolk zei (leeg string als n.v.t.)"
        }
      ]
    }
  ]
}

Geldige waarden voor direction: client_to_officer, officer_to_client
Geldige waarden voor type: omission, addition, mistranslation, false-negative
Geldige waarden voor severity: critical, high, medium, low
Als er geen problemen zijn voor een paar, gebruik een lege array: "issues": []
Voeg voor elk paar een entry toe in "pairs", ook als er geen issues zijn.\
"""


# Appended to any pair whose text Whisper's own decode metrics distrust. Without
# it the model reads a hallucinated block as something the interpreter said and
# writes it up as a critical omission — which is how "Erveys inaarefbeidehevaadah."
# became a recommendation to re-run the hearing.
_ASR_WARNING = (
    "⚠ LET OP: de spraakherkenning is voor dit fragment onbetrouwbaar "
    "(automatische transcriptie mislukt). De weergegeven tolktekst is mogelijk "
    "geen weergave van wat de tolk werkelijk zei. Beoordeel dit paar NIET als "
    "tolkfout; meld het als 'niet beoordeelbaar door opnamekwaliteit'."
)


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def translate_to_dutch(texts: list[str], source_lang: str) -> list[str]:
    """Translate a list of utterances to Dutch using Claude.

    Falls back to the original texts if parsing fails so scoring can still proceed.
    """
    client = _get_client()
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"Vertaal elk van de volgende uitspraken (taal: {source_lang}) naar het Nederlands. "
        "Geef alleen de vertalingen terug als een JSON-array van strings, in dezelfde volgorde. "
        "Geen extra tekst, alleen de JSON-array.\n\n"
        + numbered
    )
    message = await client.messages.create(
        model=settings.llm_model,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw: str = message.content[0].text.strip()  # type: ignore[index]
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")]
    try:
        result = _json.loads(raw)
        if isinstance(result, list) and len(result) == len(texts):
            log.info("translate_to_dutch  source_lang=%s  count=%d  OK", source_lang, len(texts))
            return [str(item) for item in result]
        log.warning("translate_to_dutch  unexpected list length: got %d expected %d — falling back",
                    len(result) if isinstance(result, list) else -1, len(texts))
    except (_json.JSONDecodeError, ValueError) as exc:
        log.warning("translate_to_dutch  JSON parse failed (%s) — falling back to originals", exc)
    return texts


async def generate_feedback(
    c2o_pairs: list[dict],
    c2o_scores: list[float],
    o2c_pairs: list[dict] | None = None,
    o2c_scores: list[float] | None = None,
    db: AsyncSession | None = None,
) -> dict:
    """Call the Messages API and return structured directional feedback.

    Each c2o pair must have a ``scoring_text`` key with the Dutch translation of
    the client's utterance (set by pipeline.py before calling this function).

    If ``db`` is given, pairs scoring below retrieval.RETRIEVAL_SCORE_CEILING are
    used to pull relevant background material from the knowledge base (see
    app/services/retrieval.py) and it is added to the prompt as supporting
    context. This is best-effort: any retrieval failure is logged and feedback
    generation proceeds exactly as it would with ``db=None``.

    Returns ``{"overall_feedback": str, "structured_issues": list[dict]}``.
    Falls back gracefully if JSON parsing fails.
    """
    client = _get_client()
    o2c_pairs = o2c_pairs or []
    o2c_scores = o2c_scores or []

    lines: list[str] = []

    # ── CLIENT→OFFICER section ────────────────────────────────────────────────
    c2o_mean = sum(c2o_scores) / len(c2o_scores) if c2o_scores else 0.0
    lines.append("=== CLIENT→AMBTENAAR (vertaalkwaliteit voor het dossier) ===")
    lines.append(f"Gemiddelde semantische gelijkenis: {c2o_mean:.2f}\n")
    for i, pair in enumerate(c2o_pairs):
        score = c2o_scores[i] if i < len(c2o_scores) else 0.0
        source_text = pair.get("scoring_text") or pair["source_block"]["text"]
        interp_text = pair["interp_block"]["text"]
        lines.append(f"Paar {i} (gelijkenis: {score:.3f}):")
        lines.append(f"  Cliënt:  {source_text}")
        lines.append(f"  Tolk:    {interp_text}")
        if pair.get("unassessable"):
            lines.append(f"  {_ASR_WARNING}")
        lines.append("")

    # ── OFFICER→CLIENT section ────────────────────────────────────────────────
    if o2c_pairs:
        o2c_mean = sum(o2c_scores) / len(o2c_scores) if o2c_scores else 0.0
        lines.append("=== AMBTENAAR→CLIËNT (doorgeleide vragen) ===")
        lines.append(f"Gemiddelde semantische gelijkenis: {o2c_mean:.2f}\n")
        for i, pair in enumerate(o2c_pairs):
            score = o2c_scores[i] if i < len(o2c_scores) else 0.0
            source_text = pair["source_block"]["text"]
            interp_text = pair["interp_block"]["text"]
            lines.append(f"Paar {i} (gelijkenis: {score:.3f}):")
            lines.append(f"  Ambtenaar: {source_text}")
            lines.append(f"  Tolk:      {interp_text}")
            if pair.get("unassessable"):
                lines.append(f"  {_ASR_WARNING}")
            lines.append("")

    # ── RAG context — best-effort, never blocks feedback generation ─────────────
    if db is not None:
        try:
            all_pairs = list(c2o_pairs) + list(o2c_pairs)
            all_scores = list(c2o_scores) + list(o2c_scores)
            chunks = await retrieval.retrieve_for_pairs(db, all_pairs, all_scores)
            context_block = retrieval.format_context_block(chunks)
            if chunks:
                log.info("generate_feedback  retrieved %d knowledge chunk(s): %s",
                         len(chunks), [c.source_id for c in chunks])
                lines.append(context_block)
        except Exception:
            log.warning("generate_feedback  retrieval failed — continuing without context",
                        exc_info=True)

    user_content = "\n".join(lines)

    # One JSON object covering every pair in both directions. A 40-block hearing
    # runs ~18 c2o + ~15 o2c pairs and each finding carries a paragraph of Dutch
    # rationale plus quoted phrases, which overran the previous 4096 and truncated
    # the response mid-string — json.loads then failed and every structured issue
    # was dropped (the UI showed "Kritieke problemen (0)" against a feedback panel
    # full of critical findings). Budget for the whole document; _parse_feedback_json
    # below still salvages a truncated one rather than discarding it.
    message = await client.messages.create(
        model=settings.llm_model,
        max_tokens=16000,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    response_text: str = message.content[0].text  # type: ignore[index]

    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]

    usage = message.usage
    log.info("generate_feedback  c2o_pairs=%d  o2c_pairs=%d  input_tokens=%d  output_tokens=%d",
             len(c2o_pairs), len(o2c_pairs), usage.input_tokens, usage.output_tokens)

    if message.stop_reason == "max_tokens":
        log.warning("generate_feedback  response hit max_tokens (%d output) — "
                    "salvaging what parsed", message.usage.output_tokens)

    parsed = _parse_feedback_json(cleaned)
    if parsed is None:
        log.error("generate_feedback  JSON unparseable even after repair — "
                  "returning prose only, no structured issues")
        return {"overall_feedback": _extract_overall(cleaned) or response_text,
                "structured_issues": []}

    pairs = parsed.get("pairs", []) or []
    issues_total = sum(len(p.get("issues", [])) for p in pairs)
    log.info("generate_feedback  parsed_pairs=%d  total_issues=%d",
             len(pairs), issues_total)
    return {
        "overall_feedback": parsed.get("overall_feedback", response_text),
        "structured_issues": pairs,
    }


def _parse_feedback_json(text: str) -> dict | None:
    """Parse the model's JSON, repairing a response cut off by the token limit.

    A truncated response is still mostly valid: `overall_feedback` and every
    complete entry in `pairs` before the cut are intact, and only the final
    partial entry is broken. Rather than discard the whole document, walk to the
    last point where a pair object closed cleanly, then shut the array and the
    root object there. Returns None when not even one pair survived.
    """
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        pass

    depth = 0
    in_string = False
    escaped = False
    last_pair_end: int | None = None

    for i, ch in enumerate(text):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            # depth 1 = root object, 2 = inside the "pairs" array, so a close
            # landing on 2 is one complete pair object.
            if depth == 2:
                last_pair_end = i

    if last_pair_end is None:
        return None

    try:
        repaired = _json.loads(text[: last_pair_end + 1] + "]}")
    except _json.JSONDecodeError:
        return None

    log.warning("generate_feedback  repaired truncated JSON — kept %d complete pair(s)",
                len(repaired.get("pairs", []) or []))
    return repaired


def _extract_overall(text: str) -> str | None:
    """Last resort: pull overall_feedback out of a response too broken to parse.

    Without this the caller stores the entire raw JSON blob as the feedback text,
    which is what the reviewer then reads in the UI. Scanned by hand rather than
    by regex because the value is a long Dutch paragraph containing escaped quotes.
    """
    key = '"overall_feedback"'
    k = text.find(key)
    if k == -1:
        return None
    open_quote = text.find('"', text.find(":", k + len(key)))
    if open_quote == -1:
        return None

    i = open_quote + 1
    while i < len(text):
        ch = text[i]
        if ch == '\\':
            i += 2
            continue
        if ch == '"':
            try:
                return _json.loads(text[open_quote:i + 1])
            except _json.JSONDecodeError:
                return None
        i += 1
    return None  # value itself was truncated
