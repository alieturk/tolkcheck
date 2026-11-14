# VOORLOPIG, LABELS NIET GEREVIEWD — DV4 dev S20–S29 (2026-11-11)

> Voorlopig: de labels zijn nog niet gereviewd door de moedertaalspreker. Geen resultaat; de testset is niet gelezen.


## C_f1_vervallen — drempel 0.942 (vervallen criterium f1)

> Drempel: metrics.choose_threshold(criterion='f1') op de LaBSE-scores (cross_lingual) van alle dev-paren; dezelfde paren worden daarna met die drempel gerapporteerd (in-sample, dus optimistisch).

> **DEMO — niet geldig als resultaat.** Gedraaid met --dry-run: alleen ontwikkelsessies zijn doorgerekend, met een drempel die op dezelfde dev-sessies is gekozen (f1). Er zijn geen testsessies bekeken. Niet-gecontroleerde sessies tellen mee.

**Scoringsroute:** `cross_lingual`. **Drempel:** 0.942, gekozen op deze dev-sessies met choose_threshold (f1), in-sample gerapporteerd. Een paar wordt gesignaleerd als de score onder de drempel ligt. **Ontwikkelset:** 80 paren uit 10 sessie(s).

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.86 | 0.49–0.97 | 0.56–1.00 | 7 |
| Toevoeging | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Betekenisverschuiving | 0.57 | 0.25–0.84 | 0.20–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| **Alle afwijkingen** | 0.89 | 0.74–0.95 | 0.79–0.97 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.64 | 0.50–0.77 | 0.53–0.77 | 45 |
| Precision in deze set (44% afwijkend) | 0.52 | 0.39–0.64 | 0.45–0.58 | 60 |
| Precision bij 5% afwijkende paren | 0.07 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.13 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.26 | – | – | berekend |

Recall per categorie; valse alarmen en precision alleen voor de hele set, omdat de detector geen categorie geeft. De bootstrap trekt hele sessies (2000×); bij weinig sessies is dat interval breed of ontbreekt het.


**Hoeveel beweegt de score?** Score van de referentievertaling min de score van de vertolking, per categorie (alleen analyse; de tool gebruikt geen referentie). Rond 0 betekent dat de afwijking de score niet verandert.

| Categorie | n | gem. verschil | min | max |
|---|---|---|---|---|
| Omissie | 7 | 0.029 | 0.001 | 0.098 |
| Toevoeging | 7 | 0.069 | 0.013 | 0.214 |
| Betekenisverschuiving | 7 | 0.023 | 0.003 | 0.058 |
| Entiteitsfout | 7 | 0.071 | 0.015 | 0.162 |
| Register en nadruk | 7 | 0.014 | -0.010 | 0.049 |

**Per paar (ontwikkelset)**

| paar | categorie | subtype | score | gesignaleerd | woorden bron |
|---|---|---|---|---|---|
| S20-P01 | controle |  | 0.97 | nee | 7 |
| S20-P02 | controle |  | 0.87 | ja | 18 |
| S20-P03 | Toevoeging | eigen_vraag_tolk | 0.85 | ja | 10 |
| S20-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.88 | ja | 9 |
| S20-P05 | controle |  | 0.79 | ja | 15 |
| S20-P06 | Omissie | kernfeit | 0.89 | ja | 37 |
| S20-P07 | controle |  | 0.95 | nee | 8 |
| S20-P08 | Entiteitsfout | naam | 0.85 | ja | 18 |
| S21-P01 | controle |  | 0.92 | ja | 13 |
| S21-P02 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | ja | 9 |
| S21-P03 | controle |  | 0.80 | ja | 8 |
| S21-P04 | Omissie | detail | 0.90 | ja | 44 |
| S21-P05 | Toevoeging | eigen_uitleg_tolk | 0.85 | ja | 13 |
| S21-P06 | controle |  | 0.86 | ja | 17 |
| S21-P07 | controle |  | 0.90 | ja | 16 |
| S21-P08 | controle |  | 0.91 | ja | 13 |
| S22-P01 | controle |  | 0.96 | nee | 10 |
| S22-P02 | Entiteitsfout | datum | 0.92 | ja | 10 |
| S22-P03 | Register en nadruk | nadruk_weg | 0.90 | ja | 10 |
| S22-P04 | Omissie | bijzin | 0.85 | ja | 19 |
| S22-P05 | controle |  | 0.37 | ja | 12 |
| S22-P06 | Betekenisverschuiving | tijd_of_volgorde | 0.95 | nee | 42 |
| S22-P07 | controle |  | 0.93 | ja | 15 |
| S22-P08 | controle |  | 0.93 | ja | 12 |
| S23-P01 | controle |  | 0.97 | nee | 8 |
| S23-P02 | controle |  | 0.98 | nee | 7 |
| S23-P03 | Entiteitsfout | plaats | 0.75 | ja | 13 |
| S23-P04 | Betekenisverschuiving | oorzaak_gevolg | 0.91 | ja | 18 |
| S23-P05 | controle |  | 0.79 | ja | 13 |
| S23-P06 | Toevoeging | verzonnen_detail | 0.93 | ja | 38 |
| S23-P07 | controle |  | 0.79 | ja | 15 |
| S23-P08 | controle |  | 0.97 | nee | 18 |
| S24-P01 | controle |  | 0.95 | nee | 15 |
| S24-P02 | controle |  | 0.76 | ja | 18 |
| S24-P03 | Register en nadruk | twijfel_weg | 0.91 | ja | 14 |
| S24-P04 | Omissie | voorwaarde | 0.90 | ja | 39 |
| S24-P05 | controle |  | 0.98 | nee | 12 |
| S24-P06 | Toevoeging | eigen_oordeel | 0.92 | ja | 18 |
| S24-P07 | controle |  | 0.86 | ja | 16 |
| S24-P08 | Betekenisverschuiving | wie_deed_wat | 0.91 | ja | 8 |
| S25-P01 | controle |  | 0.95 | nee | 17 |
| S25-P02 | controle |  | 0.97 | nee | 8 |
| S25-P03 | controle |  | 0.91 | ja | 13 |
| S25-P04 | Omissie | kernfeit | 0.95 | nee | 43 |
| S25-P05 | Register en nadruk | beleefdheid_of_toon | 0.94 | ja | 11 |
| S25-P06 | Entiteitsfout | aantal | 0.85 | ja | 16 |
| S25-P07 | controle |  | 0.93 | ja | 14 |
| S25-P08 | controle |  | 0.81 | ja | 24 |
| S26-P01 | controle |  | 0.96 | nee | 10 |
| S26-P02 | controle |  | 0.95 | nee | 14 |
| S26-P03 | Toevoeging | eigen_vraag_tolk | 0.86 | ja | 10 |
| S26-P04 | Betekenisverschuiving | sterker_of_zwakker_gemaakt | 0.96 | nee | 24 |
| S26-P05 | controle |  | 0.70 | ja | 10 |
| S26-P06 | Entiteitsfout | tijdsduur | 0.78 | ja | 7 |
| S26-P07 | controle |  | 0.91 | ja | 10 |
| S26-P08 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | ja | 47 |
| S27-P01 | controle |  | 0.96 | nee | 14 |
| S27-P02 | controle |  | 0.91 | ja | 8 |
| S27-P03 | controle |  | 0.91 | ja | 11 |
| S27-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.89 | ja | 18 |
| S27-P05 | controle |  | 0.95 | nee | 11 |
| S27-P06 | Omissie | detail | 0.93 | ja | 41 |
| S27-P07 | Toevoeging | eigen_uitleg_tolk | 0.93 | ja | 9 |
| S27-P08 | controle |  | 0.74 | ja | 16 |
| S28-P01 | controle |  | 0.92 | ja | 15 |
| S28-P02 | Entiteitsfout | naam | 0.79 | ja | 6 |
| S28-P03 | Toevoeging | verzonnen_detail | 0.70 | ja | 8 |
| S28-P04 | Omissie | bijzin | 0.91 | ja | 39 |
| S28-P05 | controle |  | 0.90 | ja | 16 |
| S28-P06 | controle |  | 0.73 | ja | 19 |
| S28-P07 | controle |  | 0.93 | ja | 12 |
| S28-P08 | Register en nadruk | nadruk_weg | 0.92 | ja | 19 |
| S29-P01 | controle |  | 0.91 | ja | 13 |
| S29-P02 | controle |  | 0.95 | nee | 6 |
| S29-P03 | controle |  | 0.86 | ja | 10 |
| S29-P04 | Betekenisverschuiving | tijd_of_volgorde | 0.96 | nee | 20 |
| S29-P05 | Entiteitsfout | datum | 0.93 | ja | 15 |
| S29-P06 | Register en nadruk | twijfel_weg | 0.94 | ja | 41 |
| S29-P07 | controle |  | 0.75 | ja | 18 |
| S29-P08 | controle |  | 0.94 | nee | 17 |

## LaBSE_0.70 — drempel 0.700

> LaBSE met vaste drempel 0,70: de afkapgrens uit de drempelregels van variant A. Dit is NIET variant A (Claude met drempelregels); detection_check.py meet die niet.

> **DEMO — niet geldig als resultaat.** Gedraaid met --dry-run: alleen ontwikkelsessies zijn doorgerekend, met een vooraf opgegeven drempel. Er is geen drempel gekozen en er zijn geen testsessies bekeken. Niet-gecontroleerde sessies tellen mee.

**Scoringsroute:** `cross_lingual`. **Drempel:** 0.700, vooraf opgegeven, niet afgesteld. Een paar wordt gesignaleerd als de score onder de drempel ligt. **Ontwikkelset:** 80 paren uit 10 sessie(s).

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Toevoeging | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Betekenisverschuiving | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Entiteitsfout | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Register en nadruk | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| **Alle afwijkingen** | 0.00 | 0.00–0.10 | 0.00–0.00 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (44% afwijkend) | 0.00 | 0.00–0.79 | 0.00–0.00 | 1 |
| Precision bij 5% afwijkende paren | 0.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.00 | – | – | berekend |

Recall per categorie; valse alarmen en precision alleen voor de hele set, omdat de detector geen categorie geeft. De bootstrap trekt hele sessies (2000×); bij weinig sessies is dat interval breed of ontbreekt het.


**Hoeveel beweegt de score?** Score van de referentievertaling min de score van de vertolking, per categorie (alleen analyse; de tool gebruikt geen referentie). Rond 0 betekent dat de afwijking de score niet verandert.

| Categorie | n | gem. verschil | min | max |
|---|---|---|---|---|
| Omissie | 7 | 0.029 | 0.001 | 0.098 |
| Toevoeging | 7 | 0.069 | 0.013 | 0.214 |
| Betekenisverschuiving | 7 | 0.023 | 0.003 | 0.058 |
| Entiteitsfout | 7 | 0.071 | 0.015 | 0.162 |
| Register en nadruk | 7 | 0.014 | -0.010 | 0.049 |

**Per paar (ontwikkelset)**

| paar | categorie | subtype | score | gesignaleerd | woorden bron |
|---|---|---|---|---|---|
| S20-P01 | controle |  | 0.97 | nee | 7 |
| S20-P02 | controle |  | 0.87 | nee | 18 |
| S20-P03 | Toevoeging | eigen_vraag_tolk | 0.85 | nee | 10 |
| S20-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.88 | nee | 9 |
| S20-P05 | controle |  | 0.79 | nee | 15 |
| S20-P06 | Omissie | kernfeit | 0.89 | nee | 37 |
| S20-P07 | controle |  | 0.95 | nee | 8 |
| S20-P08 | Entiteitsfout | naam | 0.85 | nee | 18 |
| S21-P01 | controle |  | 0.92 | nee | 13 |
| S21-P02 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | nee | 9 |
| S21-P03 | controle |  | 0.80 | nee | 8 |
| S21-P04 | Omissie | detail | 0.90 | nee | 44 |
| S21-P05 | Toevoeging | eigen_uitleg_tolk | 0.85 | nee | 13 |
| S21-P06 | controle |  | 0.86 | nee | 17 |
| S21-P07 | controle |  | 0.90 | nee | 16 |
| S21-P08 | controle |  | 0.91 | nee | 13 |
| S22-P01 | controle |  | 0.96 | nee | 10 |
| S22-P02 | Entiteitsfout | datum | 0.92 | nee | 10 |
| S22-P03 | Register en nadruk | nadruk_weg | 0.90 | nee | 10 |
| S22-P04 | Omissie | bijzin | 0.85 | nee | 19 |
| S22-P05 | controle |  | 0.37 | ja | 12 |
| S22-P06 | Betekenisverschuiving | tijd_of_volgorde | 0.95 | nee | 42 |
| S22-P07 | controle |  | 0.93 | nee | 15 |
| S22-P08 | controle |  | 0.93 | nee | 12 |
| S23-P01 | controle |  | 0.97 | nee | 8 |
| S23-P02 | controle |  | 0.98 | nee | 7 |
| S23-P03 | Entiteitsfout | plaats | 0.75 | nee | 13 |
| S23-P04 | Betekenisverschuiving | oorzaak_gevolg | 0.91 | nee | 18 |
| S23-P05 | controle |  | 0.79 | nee | 13 |
| S23-P06 | Toevoeging | verzonnen_detail | 0.93 | nee | 38 |
| S23-P07 | controle |  | 0.79 | nee | 15 |
| S23-P08 | controle |  | 0.97 | nee | 18 |
| S24-P01 | controle |  | 0.95 | nee | 15 |
| S24-P02 | controle |  | 0.76 | nee | 18 |
| S24-P03 | Register en nadruk | twijfel_weg | 0.91 | nee | 14 |
| S24-P04 | Omissie | voorwaarde | 0.90 | nee | 39 |
| S24-P05 | controle |  | 0.98 | nee | 12 |
| S24-P06 | Toevoeging | eigen_oordeel | 0.92 | nee | 18 |
| S24-P07 | controle |  | 0.86 | nee | 16 |
| S24-P08 | Betekenisverschuiving | wie_deed_wat | 0.91 | nee | 8 |
| S25-P01 | controle |  | 0.95 | nee | 17 |
| S25-P02 | controle |  | 0.97 | nee | 8 |
| S25-P03 | controle |  | 0.91 | nee | 13 |
| S25-P04 | Omissie | kernfeit | 0.95 | nee | 43 |
| S25-P05 | Register en nadruk | beleefdheid_of_toon | 0.94 | nee | 11 |
| S25-P06 | Entiteitsfout | aantal | 0.85 | nee | 16 |
| S25-P07 | controle |  | 0.93 | nee | 14 |
| S25-P08 | controle |  | 0.81 | nee | 24 |
| S26-P01 | controle |  | 0.96 | nee | 10 |
| S26-P02 | controle |  | 0.95 | nee | 14 |
| S26-P03 | Toevoeging | eigen_vraag_tolk | 0.86 | nee | 10 |
| S26-P04 | Betekenisverschuiving | sterker_of_zwakker_gemaakt | 0.96 | nee | 24 |
| S26-P05 | controle |  | 0.70 | nee | 10 |
| S26-P06 | Entiteitsfout | tijdsduur | 0.78 | nee | 7 |
| S26-P07 | controle |  | 0.91 | nee | 10 |
| S26-P08 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | nee | 47 |
| S27-P01 | controle |  | 0.96 | nee | 14 |
| S27-P02 | controle |  | 0.91 | nee | 8 |
| S27-P03 | controle |  | 0.91 | nee | 11 |
| S27-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.89 | nee | 18 |
| S27-P05 | controle |  | 0.95 | nee | 11 |
| S27-P06 | Omissie | detail | 0.93 | nee | 41 |
| S27-P07 | Toevoeging | eigen_uitleg_tolk | 0.93 | nee | 9 |
| S27-P08 | controle |  | 0.74 | nee | 16 |
| S28-P01 | controle |  | 0.92 | nee | 15 |
| S28-P02 | Entiteitsfout | naam | 0.79 | nee | 6 |
| S28-P03 | Toevoeging | verzonnen_detail | 0.70 | nee | 8 |
| S28-P04 | Omissie | bijzin | 0.91 | nee | 39 |
| S28-P05 | controle |  | 0.90 | nee | 16 |
| S28-P06 | controle |  | 0.73 | nee | 19 |
| S28-P07 | controle |  | 0.93 | nee | 12 |
| S28-P08 | Register en nadruk | nadruk_weg | 0.92 | nee | 19 |
| S29-P01 | controle |  | 0.91 | nee | 13 |
| S29-P02 | controle |  | 0.95 | nee | 6 |
| S29-P03 | controle |  | 0.86 | nee | 10 |
| S29-P04 | Betekenisverschuiving | tijd_of_volgorde | 0.96 | nee | 20 |
| S29-P05 | Entiteitsfout | datum | 0.93 | nee | 15 |
| S29-P06 | Register en nadruk | twijfel_weg | 0.94 | nee | 41 |
| S29-P07 | controle |  | 0.75 | nee | 18 |
| S29-P08 | controle |  | 0.94 | nee | 17 |

## C — drempel 0.719 (recall_at_fpr, max FPR 0.1)

> Drempel: metrics.choose_threshold(criterion='recall_at_fpr', max_fpr=0.1) op de LaBSE-scores (cross_lingual) van alle dev-paren; dezelfde paren worden daarna met die drempel gerapporteerd (in-sample, dus optimistisch).

> **DEMO — niet geldig als resultaat.** Gedraaid met --dry-run: alleen ontwikkelsessies zijn doorgerekend, met een drempel die op dezelfde dev-sessies is gekozen (recall_at_fpr). Er zijn geen testsessies bekeken. Niet-gecontroleerde sessies tellen mee.

**Scoringsroute:** `cross_lingual`. **Drempel:** 0.719, gekozen op deze dev-sessies met choose_threshold (recall_at_fpr, max FPR 0.1), in-sample gerapporteerd. Een paar wordt gesignaleerd als de score onder de drempel ligt. **Ontwikkelset:** 80 paren uit 10 sessie(s).

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Toevoeging | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| Betekenisverschuiving | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Entiteitsfout | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| Register en nadruk | 0.00 | 0.00–0.35 | 0.00–0.00 | 7 |
| **Alle afwijkingen** | 0.03 | 0.01–0.15 | 0.00–0.09 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.04 | 0.01–0.15 | 0.00–0.12 | 45 |
| Precision in deze set (44% afwijkend) | 0.33 | 0.06–0.79 | 0.00–1.00 | 3 |
| Precision bij 5% afwijkende paren | 0.03 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.07 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.14 | – | – | berekend |

Recall per categorie; valse alarmen en precision alleen voor de hele set, omdat de detector geen categorie geeft. De bootstrap trekt hele sessies (2000×); bij weinig sessies is dat interval breed of ontbreekt het.


**Hoeveel beweegt de score?** Score van de referentievertaling min de score van de vertolking, per categorie (alleen analyse; de tool gebruikt geen referentie). Rond 0 betekent dat de afwijking de score niet verandert.

| Categorie | n | gem. verschil | min | max |
|---|---|---|---|---|
| Omissie | 7 | 0.029 | 0.001 | 0.098 |
| Toevoeging | 7 | 0.069 | 0.013 | 0.214 |
| Betekenisverschuiving | 7 | 0.023 | 0.003 | 0.058 |
| Entiteitsfout | 7 | 0.071 | 0.015 | 0.162 |
| Register en nadruk | 7 | 0.014 | -0.010 | 0.049 |

**Per paar (ontwikkelset)**

| paar | categorie | subtype | score | gesignaleerd | woorden bron |
|---|---|---|---|---|---|
| S20-P01 | controle |  | 0.97 | nee | 7 |
| S20-P02 | controle |  | 0.87 | nee | 18 |
| S20-P03 | Toevoeging | eigen_vraag_tolk | 0.85 | nee | 10 |
| S20-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.88 | nee | 9 |
| S20-P05 | controle |  | 0.79 | nee | 15 |
| S20-P06 | Omissie | kernfeit | 0.89 | nee | 37 |
| S20-P07 | controle |  | 0.95 | nee | 8 |
| S20-P08 | Entiteitsfout | naam | 0.85 | nee | 18 |
| S21-P01 | controle |  | 0.92 | nee | 13 |
| S21-P02 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | nee | 9 |
| S21-P03 | controle |  | 0.80 | nee | 8 |
| S21-P04 | Omissie | detail | 0.90 | nee | 44 |
| S21-P05 | Toevoeging | eigen_uitleg_tolk | 0.85 | nee | 13 |
| S21-P06 | controle |  | 0.86 | nee | 17 |
| S21-P07 | controle |  | 0.90 | nee | 16 |
| S21-P08 | controle |  | 0.91 | nee | 13 |
| S22-P01 | controle |  | 0.96 | nee | 10 |
| S22-P02 | Entiteitsfout | datum | 0.92 | nee | 10 |
| S22-P03 | Register en nadruk | nadruk_weg | 0.90 | nee | 10 |
| S22-P04 | Omissie | bijzin | 0.85 | nee | 19 |
| S22-P05 | controle |  | 0.37 | ja | 12 |
| S22-P06 | Betekenisverschuiving | tijd_of_volgorde | 0.95 | nee | 42 |
| S22-P07 | controle |  | 0.93 | nee | 15 |
| S22-P08 | controle |  | 0.93 | nee | 12 |
| S23-P01 | controle |  | 0.97 | nee | 8 |
| S23-P02 | controle |  | 0.98 | nee | 7 |
| S23-P03 | Entiteitsfout | plaats | 0.75 | nee | 13 |
| S23-P04 | Betekenisverschuiving | oorzaak_gevolg | 0.91 | nee | 18 |
| S23-P05 | controle |  | 0.79 | nee | 13 |
| S23-P06 | Toevoeging | verzonnen_detail | 0.93 | nee | 38 |
| S23-P07 | controle |  | 0.79 | nee | 15 |
| S23-P08 | controle |  | 0.97 | nee | 18 |
| S24-P01 | controle |  | 0.95 | nee | 15 |
| S24-P02 | controle |  | 0.76 | nee | 18 |
| S24-P03 | Register en nadruk | twijfel_weg | 0.91 | nee | 14 |
| S24-P04 | Omissie | voorwaarde | 0.90 | nee | 39 |
| S24-P05 | controle |  | 0.98 | nee | 12 |
| S24-P06 | Toevoeging | eigen_oordeel | 0.92 | nee | 18 |
| S24-P07 | controle |  | 0.86 | nee | 16 |
| S24-P08 | Betekenisverschuiving | wie_deed_wat | 0.91 | nee | 8 |
| S25-P01 | controle |  | 0.95 | nee | 17 |
| S25-P02 | controle |  | 0.97 | nee | 8 |
| S25-P03 | controle |  | 0.91 | nee | 13 |
| S25-P04 | Omissie | kernfeit | 0.95 | nee | 43 |
| S25-P05 | Register en nadruk | beleefdheid_of_toon | 0.94 | nee | 11 |
| S25-P06 | Entiteitsfout | aantal | 0.85 | nee | 16 |
| S25-P07 | controle |  | 0.93 | nee | 14 |
| S25-P08 | controle |  | 0.81 | nee | 24 |
| S26-P01 | controle |  | 0.96 | nee | 10 |
| S26-P02 | controle |  | 0.95 | nee | 14 |
| S26-P03 | Toevoeging | eigen_vraag_tolk | 0.86 | nee | 10 |
| S26-P04 | Betekenisverschuiving | sterker_of_zwakker_gemaakt | 0.96 | nee | 24 |
| S26-P05 | controle |  | 0.70 | ja | 10 |
| S26-P06 | Entiteitsfout | tijdsduur | 0.78 | nee | 7 |
| S26-P07 | controle |  | 0.91 | nee | 10 |
| S26-P08 | Register en nadruk | voorzichtigheidswoord_weg | 0.92 | nee | 47 |
| S27-P01 | controle |  | 0.96 | nee | 14 |
| S27-P02 | controle |  | 0.91 | nee | 8 |
| S27-P03 | controle |  | 0.91 | nee | 11 |
| S27-P04 | Betekenisverschuiving | ontkenning_omgekeerd | 0.89 | nee | 18 |
| S27-P05 | controle |  | 0.95 | nee | 11 |
| S27-P06 | Omissie | detail | 0.93 | nee | 41 |
| S27-P07 | Toevoeging | eigen_uitleg_tolk | 0.93 | nee | 9 |
| S27-P08 | controle |  | 0.74 | nee | 16 |
| S28-P01 | controle |  | 0.92 | nee | 15 |
| S28-P02 | Entiteitsfout | naam | 0.79 | nee | 6 |
| S28-P03 | Toevoeging | verzonnen_detail | 0.70 | ja | 8 |
| S28-P04 | Omissie | bijzin | 0.91 | nee | 39 |
| S28-P05 | controle |  | 0.90 | nee | 16 |
| S28-P06 | controle |  | 0.73 | nee | 19 |
| S28-P07 | controle |  | 0.93 | nee | 12 |
| S28-P08 | Register en nadruk | nadruk_weg | 0.92 | nee | 19 |
| S29-P01 | controle |  | 0.91 | nee | 13 |
| S29-P02 | controle |  | 0.95 | nee | 6 |
| S29-P03 | controle |  | 0.86 | nee | 10 |
| S29-P04 | Betekenisverschuiving | tijd_of_volgorde | 0.96 | nee | 20 |
| S29-P05 | Entiteitsfout | datum | 0.93 | nee | 15 |
| S29-P06 | Register en nadruk | twijfel_weg | 0.94 | nee | 41 |
| S29-P07 | controle |  | 0.75 | nee | 18 |
| S29-P08 | controle |  | 0.94 | nee | 17 |

## LaBSE-analyse (dev)

**ROC-AUC per categorie** (afwijkingen tegen alle controles; 0,5 = toeval)

| categorie | AUC | n afwijkingen | n controles |
|---|---|---|---|
| omissie | 0.575 | 7 | 45 |
| toevoeging | 0.632 | 7 | 45 |
| betekenisverschuiving | 0.435 | 7 | 45 |
| entiteitsfout | 0.695 | 7 | 45 |
| register_en_nadruk | 0.463 | 7 | 45 |
| alle_afwijkingen | 0.560 | 35 | 45 |

**Gemiddelde LaBSE-score per soort paar**

| label | n | gemiddeld | min | max |
|---|---|---|---|---|
| afwijking (alle) | 35 | 0.890 | 0.704 | 0.961 |
| controle_gemelde_omschrijving | 3 | 0.785 | 0.737 | 0.858 |
| controle_letterlijk | 21 | 0.931 | 0.864 | 0.980 |
| controle_parafrase | 14 | 0.909 | 0.792 | 0.982 |
| controle_verzoek_herhaling | 3 | 0.636 | 0.369 | 0.805 |
| controle_zelfcorrectie | 4 | 0.775 | 0.701 | 0.865 |

# Variant A_oud op tekst (oude prompt) — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-11)

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


# Variant B_oud op tekst (oude prompt) — Claude zonder drempelregels (LLM_SCORE_RULES=false) (2026-11-11)

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


# Variant A_parserfout op tekst (oude parser) — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-11)

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


# Variant B op tekst — Claude zonder drempelregels (LLM_SCORE_RULES=false) (2026-11-11)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Toevoeging | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Betekenisverschuiving | 0.86 | 0.49–0.97 | 0.57–1.00 | 7 |
| Entiteitsfout | 0.86 | 0.49–0.97 | 0.50–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.63 | 0.46–0.77 | 0.42–0.79 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (44% afwijkend) | 0.96 | 0.79–0.99 | 0.88–1.00 | 23 |
| Precision bij 5% afwijkende paren | 0.60 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.76 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.88 | – | – | berekend |

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
| Valse alarmen (FPR) op controleparen | 0.07 | 0.02–0.18 | 0.00–0.13 | 45 |
| Precision in deze set (44% afwijkend) | 0.90 | 0.75–0.97 | 0.83–1.00 | 31 |
| Precision bij 5% afwijkende paren | 0.39 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.57 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.75 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 13339, 'cache_creation_input_tokens': 1845, 'cache_read_input_tokens': 16605} · kosten ≈ $0.2434


# Variant A op tekst — Claude met drempelregels (LLM_SCORE_RULES=true) (2026-11-11)

Model `claude-sonnet-4-6`, temperature 0.0, split dev, 10 sessies. Verschillen met de tool: geen kennisbank (geen database); geen Nederlandse hulpvertaling bij cliënt→ambtenaar.


## Gesignaleerd = high_critical (primair)

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.29 | 0.08–0.64 | 0.00–0.67 | 7 |
| Toevoeging | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Betekenisverschuiving | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Entiteitsfout | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.49 | 0.33–0.64 | 0.34–0.61 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.00 | 0.00–0.08 | 0.00–0.00 | 45 |
| Precision in deze set (44% afwijkend) | 1.00 | 0.82–1.00 | 1.00–1.00 | 17 |
| Precision bij 5% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 10% afwijkende paren | 1.00 | – | – | berekend |
| Precision bij 20% afwijkende paren | 1.00 | – | – | berekend |

## Gesignaleerd = any_issue

| Foutcategorie | Recall | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Omissie | 0.57 | 0.25–0.84 | 0.17–1.00 | 7 |
| Toevoeging | 0.86 | 0.49–0.97 | 0.56–1.00 | 7 |
| Betekenisverschuiving | 0.71 | 0.36–0.92 | 0.33–1.00 | 7 |
| Entiteitsfout | 1.00 | 0.65–1.00 | 1.00–1.00 | 7 |
| Register en nadruk | 0.14 | 0.03–0.51 | 0.00–0.43 | 7 |
| **Alle afwijkingen** | 0.66 | 0.49–0.79 | 0.52–0.79 | 35 |

| Hele set | Waarde | 95% Wilson | 95% sessie-bootstrap | n |
|---|---|---|---|---|
| Valse alarmen (FPR) op controleparen | 0.02 | 0.00–0.12 | 0.00–0.07 | 45 |
| Precision in deze set (44% afwijkend) | 0.96 | 0.80–0.99 | 0.87–1.00 | 24 |
| Precision bij 5% afwijkende paren | 0.61 | – | – | berekend |
| Precision bij 10% afwijkende paren | 0.77 | – | – | berekend |
| Precision bij 20% afwijkende paren | 0.88 | – | – | berekend |

Tokens: {'input_tokens': 10481, 'output_tokens': 12577, 'cache_creation_input_tokens': 1916, 'cache_read_input_tokens': 17244} · kosten ≈ $0.2325

