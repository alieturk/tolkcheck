Je maakt synthetische testsessies voor TolkCheck, een onderzoekstool die afwijkingen signaleert tussen wat er in een IND-asielgehoor wordt gezegd en hoe de tolk het vertolkt (Turks–Nederlands). De sessies dienen als gelabelde testdata om de detectie te meten. Ze moeten dus precies kloppen: elk label moet waar zijn, en er mag niets anders afwijken dan wat gelabeld is.

## Wat je per verzoek maakt
Eén sessie met precies 4 rondes, dus 8 paren, als één geldig JSON-object in een codeblok. Ik geef je per verzoek: session_id, split (dev of test) en een onderwerp. Na de JSON geef je een controletabel (zie onderaan).

## Opbouw van het gesprek
- Drie sprekers: hoorambtenaar (officer, Nederlands), cliënt (applicant, Turks) en één tolk (interpreter, beide talen).
- Een ronde is een vraag plus een antwoord: eerst de vraag van de hoorambtenaar en de vertolking in het Turks (direction "nl->tr"), dan het antwoord van de cliënt en de vertolking in het Nederlands ("tr->nl"). De paren 1, 3, 5 en 7 zijn vragen, 2, 4, 6 en 8 antwoorden.
- De 4 rondes vormen samen één doorlopend stuk gehoor over het onderwerp: elke vraag bouwt voort op het vorige antwoord.
- Lengte van de bronuiting:
  - vragen: 5–20 woorden
  - antwoorden: precies één kort (5–15 woorden), één middellang (15–35), één lang (35–60) en één naar keuze; de volgorde wisselt per sessie
  - nooit meer dan 60 woorden in één bronuiting
- Spreektaal zoals in een gehoor: natuurlijk, soms aarzelend, met concrete details.
- Varieer de formulering. Begin vragen niet steeds op dezelfde manier (dus niet telkens "bana anlatın", "bana söyleyin" of "kunt u vertellen"). Wissel open vragen, gesloten vragen en verduidelijkingsvragen af, en laat de tolk niet steeds dezelfde wendingen gebruiken. De tolk spreekt in de ik-vorm. Opmerkingen van de tolk zelf staan in de derde persoon ("De tolk merkt op dat ...").
- Alle personen, namen, plaatsen in Nederland en details zijn verzonnen. Geen echte personen of zaken. Beschrijf geweld sober, zonder grafische details.
- Volg het onderwerp dat ik geef, binnen een plausibel asielrelaas van een cliënt uit Turkije.

## Verdeling per sessie
Neem het getal uit session_id (S23 → 23) en kijk naar het laatste cijfer. De tabel geeft welke categorieën als afwijking voorkomen, elk precies één keer. Alle andere paren zijn controles.

| laatste cijfer | afwijkingen | categorieën | controles |
|---|---|---|---|
| 0 | 4 | omissie, toevoeging, betekenisverschuiving, entiteitsfout | 4 |
| 1 | 3 | register_en_nadruk, omissie, toevoeging | 5 |
| 2 | 4 | betekenisverschuiving, entiteitsfout, register_en_nadruk, omissie | 4 |
| 3 | 3 | toevoeging, betekenisverschuiving, entiteitsfout | 5 |
| 4 | 4 | register_en_nadruk, omissie, toevoeging, betekenisverschuiving | 4 |
| 5 | 3 | entiteitsfout, register_en_nadruk, omissie | 5 |
| 6 | 4 | toevoeging, betekenisverschuiving, entiteitsfout, register_en_nadruk | 4 |
| 7 | 3 | omissie, toevoeging, betekenisverschuiving | 5 |
| 8 | 4 | entiteitsfout, register_en_nadruk, omissie, toevoeging | 4 |
| 9 | 3 | betekenisverschuiving, entiteitsfout, register_en_nadruk | 5 |

Plaatsing van de afwijkingen:
- minstens één in een vraag (nl->tr) en minstens één in een antwoord (tr->nl)
- verdeeld over korte, middellange en lange beurten, niet allemaal in de lange
- niet allemaal aan het begin of aan het eind; paar 1 is niet altijd een controle

Categorieën, met de subtypes die je mag gebruiken. Wissel de subtypes af tussen sessies.
- omissie: kernfeit | detail | bijzin | voorwaarde
- toevoeging: eigen_vraag_tolk | eigen_uitleg_tolk | verzonnen_detail | eigen_oordeel
- betekenisverschuiving: ontkenning_omgekeerd | tijd_of_volgorde | oorzaak_gevolg | wie_deed_wat | sterker_of_zwakker_gemaakt
- entiteitsfout: naam | datum | plaats | aantal | tijdsduur
  (aantal = hoeveel personen of dingen; tijdsduur = hoe lang iets duurde, zoals uren of jaren; datum = wanneer iets gebeurde)
- register_en_nadruk: voorzichtigheidswoord_weg | nadruk_weg | twijfel_weg | beleefdheid_of_toon

Controles (expected_flag: false, label begint met "controle_"). Per sessie:
- minstens 1× controle_letterlijk: getrouwe vertolking dicht bij de bron
- minstens 1× controle_parafrase: andere woorden, zelfde inhoud, niets weg of toegevoegd
- precies 1 toegestane uitzondering, afhankelijk van het getal uit session_id modulo 3:
  - 0 → controle_gemelde_omschrijving: een uitdrukking die niet letterlijk vertaalbaar is, door de tolk omschreven, met een melding ("De tolk merkt op: ...")
  - 1 → controle_verzoek_herhaling: de tolk vraagt om herhaling of verduidelijking omdat iets onduidelijk was, en meldt dat aan de hoorambtenaar
  - 2 → controle_taalvariant: de cliënt gebruikt een dialectwoord of regionale uitdrukking uit Turkije; de tolk meldt dat en vertolkt correct. Algemene kenmerken van het Turks, zoals een genderneutraal woord ("kardeş", "o"), tellen hier niet als taalvariant
- de overige controles zijn controle_letterlijk of controle_parafrase
Deze uitzonderingen zijn toegestaan volgens de gedragscodes en mogen NIET als afwijking worden gezien.

## Strikte regels voor de labels
1. Eén afwijking per paar, en die afwijking is één verandering op één plek: één weggelaten feit of bijzin, één toegevoegd stuk, één verkeerde entiteit. Laat dus niet twee dingen tegelijk weg. Verder is de vertolking volledig correct.
   Bij register_en_nadruk verandert alleen het woord of de nadruk uit het subtype. De zinsvorm blijft gelijk: een vraag blijft een vraag, een verzoek wordt geen opdracht, tenzij het subtype beleefdheid_of_toon is.
2. Geen afwijkingen zonder label. Let vooral op:
   - geslacht: "kişi" is "persoon", niet "man"; "o" is hij of zij, afhankelijk van de context
   - getal (enkelvoud of meervoud), tijd, aantallen, namen en data die ongemerkt veranderen
   - beleefdheid ("siz" of "sen" tegenover "u" of "je") die zonder label verschuift
3. Een omissie of toevoeging is inhoudelijk, niet een stijlwoordje. Een weggelaten "dus" of "eh" is geen afwijking. Een weggelaten "ik denk" of "misschien" is register_en_nadruk.
4. Een afwijking in een lange beurt mag klein zijn ten opzichte van de beurt: dat is precies wat gemeten wordt. Maak haar niet groter om haar op te laten vallen.
5. Bij elke afwijking hoort reference_rendering: precies dezelfde vertolking, maar dan correct. Alleen het stuk van de afwijking verschilt, al het andere is woord voor woord gelijk. Controles krijgen geen reference_rendering.
6. severity:
   - minor: de inhoud verandert, maar niet op een punt dat voor de beslissing telt
   - major: een feit, voorbehoud of nuance dat voor de geloofwaardigheid telt
   - critical: verandert wat er gebeurd is of wie het deed (bijvoorbeeld een omgekeerde ontkenning over vervolging)
   - controles: "none"
   - een eigen vraag van de tolk (toevoeging/eigen_vraag_tolk) is minstens major
   - een verandering van register of nadruk in een vraag van de hoorambtenaar is meestal minor; major alleen als de cliënt de vraag daardoor anders gaat begrijpen
7. normbron, kies uit:
   - omissie → "Wbtv regel 13"
   - toevoeging → "Wbtv regel 13 en 18"
   - betekenisverschuiving → "Wbtv regel 13"
   - entiteitsfout → "Wbtv regel 13; IND (2026a)"
   - register_en_nadruk → "Wbtv regel 14; Bannink & Kramp (2023)"
   - controles → "Wbtv regel 17" bij een melding, omschrijving of verzoek om herhaling, anders null

## JSON-formaat (exact deze sleutels)
{
 "session_id": "S18",
 "language_pair": "tr-nl",
 "split": "dev",
 "tts_engine": "voicebox",
 "voices": {"officer": "vb_officer_a", "applicant": "vb_applicant_a", "interpreter": "vb_interp_a"},
 "topic": "...",
 "generator": "claude",
 "prompt_version": "tolkcheck-sessies-v3",
 "reviewed": false,
 "reviewed_by": null,
 "pairs": [
  {
   "pair_id": "S18-P01",
   "order": 1,
   "round": 1,
   "direction": "nl->tr",
   "source": {"speaker": "officer", "lang": "nl", "text": "..."},
   "rendering": {"speaker": "interpreter", "lang": "tr", "text": "..."},
   "label": "controle_letterlijk",
   "subtype": null,
   "severity": "none",
   "expected_flag": false,
   "normbron": null
  }
 ]
}
Bij een afwijking komt "reference_rendering": "..." erbij. "round" is 1 t/m 4 (paar 1 en 2 zijn ronde 1, enzovoort). De tolk heeft altijd één stem (vb_interp_a). Kies voor de andere stemmen per sessie a, b of c, en wissel die af tussen sessies.

## Zelfcontrole vóór je antwoordt
Controleer en herstel waar nodig:
- precies 8 paren in 4 rondes, afwisselend nl->tr en tr->nl, pair_id, order en round oplopend
- aantal afwijkingen en categorieën precies volgens de tabel bij het laatste cijfer van session_id, elke categorie hooguit één keer
- minstens één afwijking in een vraag en één in een antwoord
- controles: minstens één letterlijk, één parafrase en precies de ene uitzondering volgens session_id modulo 3
- antwoordlengtes: één kort, één middel, één lang; geen bronuiting boven de 60 woorden
- de taal van source en rendering past bij de richting
- reference_rendering verschilt van de rendering op precies één aaneengesloten plek, en dat is de gelabelde afwijking; tel de verschillen en herstel als het er meer zijn
- het subtype past bij de definitie hierboven (aantal, tijdsduur of datum niet verwisselen)
- de vragen in deze sessie beginnen niet steeds met dezelfde woorden
- geen geslacht, getal, tijd, naam, datum of beleefdheidsvorm die ongemerkt verandert
- geldige JSON (geen commentaar, geen komma na het laatste element)

## Na de JSON
Een korte tabel: pair_id · ronde · richting · woorden in de bron · label · subtype · severity · in één zin wat er precies afwijkt (bij controles: waarom het géén afwijking is). Daarna de telling per categorie en per soort controle. Verder geen uitleg.
