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
- 2026-11-11: parser van feedback.py aangepast na voorlopige dev-run (S26: antwoord in twee JSON-blokken, alle issues vielen weg); meerdere blokken worden samengevoegd en onleesbare feedback wordt als "niet beoordeeld" getoond; testset niet gelezen of gescoord. Hierna is de tool bevroren tot na de testrun.
- Testset gedraaid op 2026-11-11 met commit f6d64fa7a2e14e55e8f458a675ed3224f2fae7a5; metrics pas na review van de labels. Twee verzegelde runs in `backend/evaluation/results/test_sealed_2026-11-11/`: run1 is primair, run2 alleen voor stabiliteit. SHA-256 van predictions.json: run1 `d7eec372cb4d084bf4e8a7e18c44f2a69ceff17a7302fdaded4bd0e2ebde0f51`, run2 `e81c8cddbbb7f7f0b1c57e5b8dbad80a6e4d32a86c55b875d09c4b9d2216f869`.
