# DV4 testset — definitief (2026-11-14)

Verzegeld op 2026-11-11 met commit `f6d64fa7a2e14e55e8f458a675ed3224f2fae7a5`; gescoord met commit `a6e4fb495c137459994e222a70fe76fdcd6e71d8`. 160 testparen.


## C — LaBSE, drempel 0.719 (recall_at_fpr, max FPR 0.1, gekozen op 79 gereviewde dev-paren)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.00 | 0.00–0.22 | 0.00–0.00 | 14 |
| Toevoeging | 0.00 | 0.00–0.22 | 0.00–0.00 | 14 |
| Betekenisverschuiving | 0.00 | 0.00–0.22 | 0.00–0.00 | 14 |
| Entiteitsfout | 0.07 | 0.01–0.31 | 0.00–0.23 | 14 |
| Register en nadruk | 0.00 | 0.00–0.22 | 0.00–0.00 | 14 |
| **Alle afwijkingen** | 0.01 | 0.00–0.08 | 0.00–0.04 | 70 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.07 | 0.03–0.14 | 0.02–0.11 | 90 |
| Precision in deze set (44% afwijkend) | 0.14 | 0.03–0.51 | 0.00–0.44 | 7 |
| Precision bij 5% afwijkende paren | 0.01 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.02 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.05 | – | – | berekend |

## A — gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.64 | 0.39–0.84 | 0.36–0.91 | 14 |
| Toevoeging | 0.57 | 0.33–0.79 | 0.31–0.82 | 14 |
| Betekenisverschuiving | 0.79 | 0.52–0.92 | 0.55–1.00 | 14 |
| Entiteitsfout | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Register en nadruk | 0.07 | 0.01–0.31 | 0.00–0.23 | 14 |
| **Alle afwijkingen** | 0.61 | 0.50–0.72 | 0.51–0.71 | 70 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.01–0.08 | 0.00–0.06 | 90 |
| Precision in deze set (44% afwijkend) | 0.96 | 0.85–0.99 | 0.90–1.00 | 45 |
| Precision bij 5% afwijkende paren | 0.59 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.75 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.87 | – | – | berekend |

## A — gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.64 | 0.39–0.84 | 0.36–0.91 | 14 |
| Toevoeging | 0.79 | 0.52–0.92 | 0.55–1.00 | 14 |
| Betekenisverschuiving | 0.93 | 0.69–0.99 | 0.77–1.00 | 14 |
| Entiteitsfout | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Register en nadruk | 0.36 | 0.16–0.61 | 0.11–0.60 | 14 |
| **Alle afwijkingen** | 0.74 | 0.63–0.83 | 0.62–0.85 | 70 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.03 | 0.01–0.09 | 0.00–0.07 | 90 |
| Precision in deze set (44% afwijkend) | 0.95 | 0.85–0.98 | 0.89–1.00 | 55 |
| Precision bij 5% afwijkende paren | 0.54 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.71 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.85 | – | – | berekend |

## B — gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.57 | 0.33–0.79 | 0.31–0.83 | 14 |
| Toevoeging | 0.64 | 0.39–0.84 | 0.38–0.88 | 14 |
| Betekenisverschuiving | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Entiteitsfout | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Register en nadruk | 0.14 | 0.04–0.40 | 0.00–0.36 | 14 |
| **Alle afwijkingen** | 0.67 | 0.56–0.77 | 0.58–0.76 | 70 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.03 | 0.01–0.09 | 0.00–0.07 | 90 |
| Precision in deze set (44% afwijkend) | 0.94 | 0.84–0.98 | 0.88–1.00 | 50 |
| Precision bij 5% afwijkende paren | 0.51 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.69 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.83 | – | – | berekend |

## B — gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.71 | 0.45–0.88 | 0.46–0.93 | 14 |
| Toevoeging | 0.86 | 0.60–0.96 | 0.64–1.00 | 14 |
| Betekenisverschuiving | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Entiteitsfout | 1.00 | 0.78–1.00 | 1.00–1.00 | 14 |
| Register en nadruk | 0.50 | 0.27–0.73 | 0.22–0.76 | 14 |
| **Alle afwijkingen** | 0.81 | 0.71–0.89 | 0.72–0.90 | 70 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.04 | 0.02–0.11 | 0.01–0.09 | 90 |
| Precision in deze set (44% afwijkend) | 0.93 | 0.84–0.97 | 0.88–0.98 | 61 |
| Precision bij 5% afwijkende paren | 0.49 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.67 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.82 | – | – | berekend |

## Stabiliteit (run2 tegen run1)

run2 alleen voor stabiliteit; alle metrics komen uit run1.

| variant | paren | zelfde beslissing | aandeel |
|---|---|---|---|
| C | 160 | 160 | 1.000 |
| A:high_critical | 160 | 154 | 0.963 |
| A:any_issue | 160 | 159 | 0.994 |
| B:high_critical | 160 | 156 | 0.975 |
| B:any_issue | 160 | 157 | 0.981 |

**Weggelaten door de reviewer:** 0 testpaar/-paren, 1 dev-paar/-paren (tellen nergens mee; maken de run niet ongeldig)

- dev S20-P06: Er is een stad in Turkije genoemd, Mardin. Maar die staat niet in de text van applicant. Er kan twee dingen tegelijk zijn. Omissie en toevoeging.
