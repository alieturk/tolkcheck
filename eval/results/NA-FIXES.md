# T9 en T10 na de fixes — vergelijking voor/na

**Wat is vergeleken:** dezelfde controles op twee versies van de code.

| | Commit | Branch |
|---|---|---|
| Voor | `2decb30` | `main` op het moment van de eerste meting |
| Na (T9) | `6d689ea` | `fix/eis-2-eis-5` (10 commits: EIS-2/EIS-5-fixes, retentie, beveiliging, productie-deployment) |
| Na (T10) | `e7c1ff0` | `fix/eis-2-eis-5` + productteksten herschreven (1 commit, alleen tekst) |

**Reproduceren** (vanuit een checkout van `eval/dv4`, met de te inspecteren code in een tweede checkout of worktree):

```bash
uv run --project backend python eval/t9_security.py --repo <checkout> --out eval/results/t9/v2-<voor|na>
uv run --project backend python eval/t10_scope.py   --repo <checkout> --out eval/results/t10/after-<commit>
```

Bewijs: [`t9/v2-before/evidence.json`](t9/v2-before/evidence.json), [`t9/v2-after/evidence.json`](t9/v2-after/evidence.json), [`t10/after-e7c1ff0/evidence.json`](t10/after-e7c1ff0/evidence.json) en [`t10/after-e7c1ff0/schema.sql`](t10/after-e7c1ff0/schema.sql). De eerste T10-meting staat in [`t10/`](t10/); de tussenmeting op `6d689ea` in [`t10/after/`](t10/after/).

## Instrument aangepast (T9 v2) — en daarom beide kanten opnieuw gemeten

Het T9-script is voor deze vergelijking op vier punten verbeterd, omdat de oude versie de nieuwe code verkeerd zou meten. Beide versies van de code zijn met **dezelfde** v2 gemeten; de getallen hieronder zijn dus onderling vergelijkbaar, niet met de v1-uitkomst in [`t9/T9.md`](t9/T9.md).

1. Ontwikkel- en productieconfiguratie worden apart gerapporteerd (`docker-compose.yml` tegenover `docker-compose.prod.yml` + `deploy/`).
2. Beveiligingslogging telt ook de nieuwe `audit()`-aanroepen, niet alleen `log.`-aanroepen.
3. Transcripttekst in logs wordt gevonden door elke logaanroep te parsen (AST), op elk niveau. De v1-regex keek per regel en miste meerregelige aanroepen: **v1 vond er 8, v2 vindt er 15 in dezelfde oude code** (5 op INFO, 5 op WARNING, 5 op DEBUG). Het getal in T9.md was dus een onderschatting.
4. Regels die beginnen met `#` of `//` tellen niet mee: in de eerste na-meting telden "Let's Encrypt" en een opsomming van eisen in commentaar als versleuteling.

## T9 — Beveiliging (EIS-6)

| Controle | Voor | Na |
|---|---:|---:|
| TLS in productieconfiguratie | 0 | 2 (Caddy: poort 443, HSTS) |
| Versleuteling in rust in code/config | 0 | 0 |
| MFA | 0 | 0 |
| Lockout / rate limiting | 0 | 14 |
| Wachtwoordbeleid | 0 | 3 |
| Intrekken van tokens | 0 | 15 |
| Accountbeheer via CLI (aanmaken, lijst, (de)activeren) | 3 | 9 |
| Rollen of beheerdersvlag | 0 | 0 |
| Standaardwachtwoorden — ontwikkeling | 4 | 4 |
| Standaardwachtwoorden — productie | 0 | 0 |
| Verplichte geheimen in productieconfiguratie (`${VAR:?}`) | 0 | 13 |
| Redis met wachtwoord | 0 | 2 |
| Database-rol met minimale rechten | 0 | 6 |
| Gepubliceerde poorten — ontwikkeling | 5 | 5 |
| Gepubliceerde poorten — productie | 0 | 2 (alleen Caddy: 443, 80) |
| Adminer — productie | 0 | 0 |
| Containers als niet-root — productie | 1 (frontend) | 2 (frontend, backend) |
| Logging van beveiligingsgebeurtenissen | 0 | 22 |
| Logaanroepen met transcripttekst | 15 | 0 |
| Uitingen uit `story-of-ali-3` volledig in de standaardlog (n = 61) | 32 | 0 |
| Ruwe foutmelding via de API | 1 | 0 |

Voor productie stond er "0" bij poorten, wachtwoorden en Adminer omdat er nog geen productieconfiguratie was, niet omdat die goed was.

### Oordeel per maatregel

| Maatregel | Voor | Na | Wat ontbreekt nog |
|---|---|---|---|
| 8.24 Cryptografie | Deels voldaan | **Deels voldaan** | TLS zit nu in de productieconfiguratie. Versleuteling in rust is bewust aan de hostingomgeving gelaten en als eis vastgelegd in `DEPLOYMENT-SECURITY.md`; in de code staat er niets van. |
| 5.17 Authenticatie | Niet voldaan | **Deels voldaan** | Lockout, intrekken van tokens en wachtwoordbeleid zijn er. MFA is bewust aan de SSO van de IND gelaten (eis in `DEPLOYMENT-SECURITY.md`), net als rate limiting per IP-adres. Zonder die SSO is 5.17 niet voldaan. |
| 5.18 Accounts en rechten | Deels voldaan | **Voldaan voor de productieconfiguratie** | De app werkt met een databaserol die alleen rijen kan lezen en schrijven (getest op PostgreSQL 16: CREATE/DROP/ALTER TABLE en CREATE EXTENSION geweigerd). Geen rollen binnen de app; verdedigbaar zolang alle gebruikers dezelfde taak hebben. De ontwikkelconfiguratie is ongewijzigd en niet bedoeld voor een netwerk. |
| 8.15 Logging | Niet voldaan | **Voldaan in de code** | Beveiligingsgebeurtenissen worden gelogd, gehoorinhoud niet meer. Centrale opslag, beveiliging en bewaartermijn van de logs zijn eisen aan de uitrol. |

**EIS-6 na de fixes:** in de code en de productieconfiguratie voldaan voor 5.18 en 8.15; voor 5.17 (MFA) en 8.24 (versleuteling in rust) afhankelijk van de uitrolomgeving. Dat is een expliciete ontwerpkeuze en moet in het rapport zo worden benoemd.

## T10 — Scope (EIS-2)

| Deelcontrole | Voor | Na | Bewijs na |
|---|---|---|---|
| Geen tolkscore | Niet voldaan | **Voldaan** | Enige scorekolom: `evaluations.semantic_similarity_scores` (per paar). Geen score of oordeel meer in de UI (0 vondsten) en geen "beoordelaar"-rol of "Samenvattende beoordeling" in de Claude-prompt (0 vondsten). |
| Geen koppeling tussen sessies | Voldaan, met kanttekening | **Voldaan, met kanttekening** | Ongewijzigd: geen tabel verwijst naar meer dan één sessie; `ind_case_id` blijft een vrij tekstveld. Nieuw: na 90 dagen wordt alles verwijderd, wat de periode waarover gekoppeld zou kunnen worden begrenst. |
| Geen koppeling aan identiteit van de tolk | Voldaan in schema, niet afgedwongen | **Ongewijzigd** | Het transcript kan de naam van de tolk bevatten ("Naast mij zit Derya, zij is de tolk"); dat wordt niet gefilterd. Wel worden transcripten nu na 90 dagen verwijderd. |

T10 is twee keer na de fixes gemeten:

| Controle (`product_framing`: teksten die de tool als kwaliteitsbeoordeling omschrijven) | `6d689ea` | `e7c1ff0` |
|---|---:|---:|
| Vondsten | 2 | 0 |

Op `6d689ea` stonden er nog twee: `frontend/app/page.tsx:58` "AI-kwaliteitsevaluatie voor IND-tolkgesprekken" en `frontend/app/upload/page.tsx:89` "om de kwaliteit te evalueren". In `e7c1ff0` zijn die herschreven, samen met drie teksten die de T10-controle niet doorzocht maar dezelfde strekking hadden (paginametadata in `frontend/app/layout.tsx`, de API-beschrijving in `backend/app/main.py` en de statusmelding "Kwaliteit wordt berekend..."). Alle andere T10-uitkomsten en het schema zijn tussen beide metingen gelijk gebleven (zelfde migratierevisie `i2f8b6d3e5a7`; de schemadumps verschillen alleen in regeleinden en de willekeurige `\restrict`-sleutel die pg_dump elke keer genereert).

**EIS-2 na de fixes: voldaan, op één punt na.** Open: de naam van de tolk kan via het transcript worden opgeslagen ("Naast mij zit Derya, zij is de tolk") en wordt niet gefilterd; transcripten worden wel na 90 dagen verwijderd.

## Afwijkingen en beperkingen

- Alleen statische inspectie en een test van de databaserechten. De productie-stack (`docker-compose.prod.yml`) is nooit gestart: er is geen Docker op de ontwikkelmachine. De YAML is gevalideerd.
- De frontendwijzigingen zijn niet gecompileerd of getypecheckt (geen Node beschikbaar).
- T8 (privacy in een echte run, inclusief het verwijderen van audio en de retentietaak) is nog niet uitgevoerd; het verwijdergedrag is alleen met unittests aangetoond (213/213 tests slagen op `6d689ea` en op `e7c1ff0`).
- Het T9-instrument is aangepast (zie boven). Vergelijk alleen v2 met v2.
- Telling 32 van 61 gaat uit van één uiting per regel in het aangeleverde script; in een echte run bepalen ASR-segmentgrenzen het opknippen.
- De BIO2-nummering (5.17/5.18 tegenover ISO 27002:2022 8.5/8.2) is nog niet tegen de BIO2-tekst gecontroleerd [CONTROLEREN].
