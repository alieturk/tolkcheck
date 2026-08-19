---
source_id: mqm-core-typology
category: taxonomy
title: MQM (Multidimensional Quality Metrics). (z.d.). The MQM Core Typology. https://themqm.org/the-mqm-typology/
language: nl
status: geverifieerd (webpagina geopend, typologie en definities gecontroleerd)
---

Binnen de MQM-foutentypologie (Multidimensional Quality Metrics) valt een "mistranslation" onder de categorie Accuracy: de doeltekst geeft de betekenis van de brontekst niet correct weer. TolkCheck gebruikt "mistranslation" in dezelfde betekenis: de tolk zegt iets anders dan wat feitelijk gezegd is, ook al lijkt de vertaling op het eerste gezicht plausibel.

Binnen dezelfde Accuracy-categorie definieert MQM "omission" als: inhoud die in de brontekst aanwezig is maar in de doeltekst ontbreekt. En "addition" als: de doeltekst bevat inhoud die niet in de brontekst voorkomt. Deze twee definities liggen ten grondslag aan de "omission"- en "addition"-issue-types in TolkCheck's feedbackschema (zie app/services/feedback.py).

MQM onderscheidt Accuracy (is de betekenis correct overgebracht) expliciet van Fluency/Language (is de doeltaal grammaticaal correct) en Style (formaliteit, woordkeuze). Voor TolkCheck is alleen de Accuracy-as relevant: het gaat om semantische afwijkingen tussen bron en tolkvertaling, niet om de spreekstijl of grammatica van de tolk. Dat onderbouwt waarom TolkCheck's issue-types beperkt blijven tot omission/addition/mistranslation en niet zijn uitgebreid met stijl- of grammaticacategorieën — die zijn voor dit doel niet relevant en zouden het IND-signaal juist verwateren.
