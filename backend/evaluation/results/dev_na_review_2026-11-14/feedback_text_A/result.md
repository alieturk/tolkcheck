# Variant A op tekst — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-14)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.33 | 0.10–0.70 | 0.00–0.75 | 6 |
| Toevoeging | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.53 | 0.37–0.69 | 0.38–0.65 | 34 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.00 | 0.00–0.08 | 0.00–0.00 | 45 |
| Precision in deze set (43% afwijkend) | 1.00 | 0.82–1.00 | 1.00–1.00 | 18 |
| Precision bij 5% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 1.00 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.83 | 0.44–0.97 | 0.50–1.00 | 6 |
| Toevoeging | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.71 | 0.54–0.83 | 0.59–0.82 | 34 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (43% afwijkend) | 0.96 | 0.80–0.99 | 0.88–1.00 | 25 |
| Precision bij 5% afwijkende paren | 0.63 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.78 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.89 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 12736, 'cache_creation_input_tokens': 1916, 'cache_read_input_tokens': 17244} · kosten ≈ $0.2348

