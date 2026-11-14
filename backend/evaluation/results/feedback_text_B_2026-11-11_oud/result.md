# Variant B op tekst — Claude zonder drempelregels (LLM_SCORE_RULES=false) (2026-11-11)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Toevoeging | 0.86 | 0.49–0.97 | 0.56–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.86 | 0.49–0.97 | 0.50–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.66 | 0.49–0.79 | 0.53–0.77 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.00 | 0.00–0.08 | 0.00–0.00 | 45 |
| Precision in deze set (44% afwijkend) | 1.00 | 0.86–1.00 | 1.00–1.00 | 23 |
| Precision bij 5% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 1.00 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.86 | 0.49–0.97 | 0.56–1.00 | 7 |
| Toevoeging | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 0.29 | 0.08–0.64 | 0.00–0.67 | 7 |
| **Alle afwijkingen** | 0.80 | 0.64–0.90 | 0.66–0.94 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.04 | 0.01–0.15 | 0.00–0.11 | 45 |
| Precision in deze set (44% afwijkend) | 0.93 | 0.79–0.98 | 0.84–1.00 | 30 |
| Precision bij 5% afwijkende paren | 0.49 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.67 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.82 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 13293, 'cache_creation_input_tokens': 1800, 'cache_read_input_tokens': 16200} · kosten ≈ $0.2424

