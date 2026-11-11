# Testopzet DV4 — detectie op synthetische sessies

Vastgelegd op 2026-11-11, vóór het genereren van de sessies en vóór elke run op test.

## Sessies

- dev = S20–S29
- test = S30–S49
- Map: `eval/data/tolkcheck_dv4/sessions_v4/`

## Varianten

- A: huidige tool, Claude met drempelregels (`LLM_SCORE_RULES=true`), drempel 0,70
- B: Claude zonder drempelregels (`LLM_SCORE_RULES=false`); optioneel, script nog niet gebouwd
- C: alleen LaBSE, drempel gekozen op dev (S20–S29)

## Drempel en runs

- De drempel van variant C wordt alleen op dev gekozen, met de procedure uit
  `backend/evaluation/detection_check.py` (`choose_threshold` op de dev-sessies).
  Criterium: hoogste recall (alle categorieën samen) bij FPR ≤ 0,10 op dev; bij
  gelijke recall de laagste FPR (`choose_threshold`, criterium `recall_at_fpr`,
  `max_fpr=0.10`).
  Gewijzigd op 2026-11-11 na een voorlopige run op dev (f1 koos 0,942 met FPR 0,64);
  de testset was op dat moment niet gelezen of gescoord.
- Op test wordt daarna precies één run gedaan met variant A en variant C.
- Er wordt niets meer aangepast nadat de testresultaten bekend zijn.

## Generator

- model: claude-haiku-5-5
- temperature: niet instelbaar bij dit model (API weigert de parameter); standaard sampling
- reproduceerbaarheid: de gegenereerde sessies worden opgeslagen en na review bevroren;
  het generatielog (model, promptversie, tokens, kosten, duur) wordt meegecommit
- prompt: tolkcheck-sessies-v4 (commit 059fcd2)

## Detectie

- LaBSE is deterministisch.
- Variant A (feedbackmodel) draait met `llm_temperature=0`.

## Wijzigingen

- 2026-11-11: prompt van feedback.py aangepast na voorlopige dev-run (vals alarm op zelfcorrectie S29-P07); testset niet gelezen of gescoord.
