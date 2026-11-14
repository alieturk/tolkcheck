# Variant A op tekst — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-11)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.43 | 0.16–0.75 | 0.00–0.83 | 7 |
| Toevoeging | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.54 | 0.38–0.70 | 0.39–0.67 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (44% afwijkend) | 0.95 | 0.76–0.99 | 0.85–1.00 | 20 |
| Precision bij 5% afwijkende paren | 0.56 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.73 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.86 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Toevoeging | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.71 | 0.55–0.84 | 0.60–0.82 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.07 | 0.02–0.18 | 0.00–0.13 | 45 |
| Precision in deze set (44% afwijkend) | 0.89 | 0.73–0.96 | 0.81–1.00 | 28 |
| Precision bij 5% afwijkende paren | 0.36 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.54 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.73 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 12627, 'cache_creation_input_tokens': 1871, 'cache_read_input_tokens': 16839} · kosten ≈ $0.2329

