"""LLM feedback generation via Anthropic Message Batches API (50% cost reduction).

Submits a single-request batch, polls with exponential back-off until the batch
ends, then returns the result. Interface is unchanged — callers receive a string.
"""
from __future__ import annotations

import asyncio

import anthropic

from app.config import settings

_client: anthropic.AsyncAnthropic | None = None

_SYSTEM_PROMPT = """\
Je bent een expert-beoordelaar van professionele tolken die werkzaam zijn in IND-gehoren \
(Immigratie- en Naturalisatiedienst).

Jouw taak is het beoordelen van de tolkprestatie op basis van een geannoteerd transcript \
en semantische gelijkheidsscores per segment.

Beoordelingscriteria:
1. **Nauwkeurigheid** – Hoe getrouw geeft de tolk de betekenis van het brongeluid weer?
2. **Volledigheid** – Wordt alle informatie overgebracht zonder weglating?
3. **Terminologie** – Correct gebruik van juridische en asielprocedure-gerelateerde terminologie.
4. **Vloeiendheid** – Heldere, natuurlijke overbrenging zonder onnodige aarzeling of fouten.
5. **Onpartijdigheid** – De tolk voegt geen mening toe, parafraseert niet tendentieus en mengt zich niet.

Geef voor elk criterium een score van 0 tot 100 en een overall score.
Onderbouw elke score met concrete voorbeelden uit het transcript.
Sluit af met maximaal drie concrete verbeterpunten.
Antwoord volledig in het Nederlands."""


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def generate_feedback(
    transcript: dict,
    similarity_scores: list[float],
) -> str:
    """Submit a batch request, poll until complete, return feedback as plain text."""
    client = _get_client()

    mean_score = sum(similarity_scores) / len(similarity_scores) if similarity_scores else 0.0
    user_content = (
        f"Gemiddelde semantische gelijkenis: {mean_score:.2f}\n\n"
        f"Transcript:\n{_format_transcript(transcript)}"
    )

    batch = await client.beta.messages.batches.create(
        requests=[
            {
                "custom_id": "feedback",
                "params": {
                    "model": settings.llm_model,
                    "max_tokens": 2048,
                    "system": [
                        {
                            "type": "text",
                            "text": _SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    "messages": [{"role": "user", "content": user_content}],
                },
            }
        ]
    )

    # Exponential back-off: 5s → 10s → 20s → 40s → 60s (cap)
    delay = 5
    while batch.processing_status != "ended":
        await asyncio.sleep(delay)
        batch = await client.beta.messages.batches.retrieve(batch.id)
        delay = min(delay * 2, 60)

    async for result in await client.beta.messages.batches.results(batch.id):
        if result.result.type == "succeeded":
            return result.result.message.content[0].text  # type: ignore[index]
        raise RuntimeError(
            f"Batch request failed ({result.result.type}): "
            f"{getattr(result.result, 'error', '')}"
        )

    raise RuntimeError("Batch completed but returned no results")


def _format_transcript(transcript: dict) -> str:
    lines = []
    for seg in transcript.get("segments", []):
        speaker = seg.get("speaker", "?")
        start = seg.get("start", 0.0)
        text = seg.get("text", "")
        lines.append(f"[{start:.1f}s] {speaker}: {text}")
    return "\n".join(lines)
