"""LLM feedback generation using the Anthropic Messages API."""
from __future__ import annotations

import json as _json
import logging

import anthropic

from app.config import settings

log = logging.getLogger(__name__)
_client: anthropic.AsyncAnthropic | None = None

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
) -> dict:
    """Call the Messages API and return structured directional feedback.

    Each c2o pair must have a ``scoring_text`` key with the Dutch translation of
    the client's utterance (set by pipeline.py before calling this function).

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
            lines.append("")

    user_content = "\n".join(lines)

    message = await client.messages.create(
        model=settings.llm_model,
        max_tokens=4096,
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

    try:
        parsed = _json.loads(cleaned)
        issues_total = sum(len(p.get("issues", [])) for p in parsed.get("pairs", []))
        log.info("generate_feedback  parsed_pairs=%d  total_issues=%d",
                 len(parsed.get("pairs", [])), issues_total)
        return {
            "overall_feedback": parsed.get("overall_feedback", response_text),
            "structured_issues": parsed.get("pairs", []),
        }
    except (_json.JSONDecodeError, AttributeError) as exc:
        log.warning("generate_feedback  JSON parse failed (%s) — returning raw text", exc)
        return {"overall_feedback": response_text, "structured_issues": []}
