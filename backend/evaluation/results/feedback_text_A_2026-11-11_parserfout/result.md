# Variant A op tekst — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-11)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.29 | 0.08–0.64 | 0.00–0.67 | 7 |
| Toevoeging | 0.43 | 0.16–0.75 | 0.11–0.80 | 7 |
| Betekenisverschuiving | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Entiteitsfout | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.43 | 0.28–0.59 | 0.26–0.57 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.00 | 0.00–0.08 | 0.00–0.00 | 45 |
| Precision in deze set (44% afwijkend) | 1.00 | 0.80–1.00 | 1.00–1.00 | 15 |
| Precision bij 5% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 1.00 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Toevoeging | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.86 | 0.49–0.97 | 0.56–1.00 | 7 |
| Register en nadruk | 0.29 | 0.08–0.64 | 0.00–0.67 | 7 |
| **Alle afwijkingen** | 0.69 | 0.52–0.81 | 0.46–0.86 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (44% afwijkend) | 0.96 | 0.80–0.99 | 0.88–1.00 | 25 |
| Precision bij 5% afwijkende paren | 0.62 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.77 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.89 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 13002, 'cache_creation_input_tokens': 1916, 'cache_read_input_tokens': 17244} · kosten ≈ $0.2388

