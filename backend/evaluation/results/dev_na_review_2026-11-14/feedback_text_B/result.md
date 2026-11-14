# Variant B op tekst — Claude zonder drempelregels (LLM_SCORE_RULES=false) (2026-11-14)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.67 | 0.30–0.90 | 0.25–1.00 | 6 |
| Toevoeging | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.65 | 0.48–0.79 | 0.48–0.77 | 34 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.00 | 0.00–0.08 | 0.00–0.00 | 45 |
| Precision in deze set (43% afwijkend) | 1.00 | 0.85–1.00 | 1.00–1.00 | 22 |
| Precision bij 5% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 1.00 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.83 | 0.44–0.97 | 0.50–1.00 | 6 |
| Toevoeging | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 0.29 | 0.08–0.64 | 0.00–0.67 | 7 |
| **Alle afwijkingen** | 0.79 | 0.63–0.90 | 0.66–0.94 | 34 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (43% afwijkend) | 0.96 | 0.82–0.99 | 0.90–1.00 | 28 |
| Precision bij 5% afwijkende paren | 0.65 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.80 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.90 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 13052, 'cache_creation_input_tokens': 1845, 'cache_read_input_tokens': 16605} · kosten ≈ $0.2391

