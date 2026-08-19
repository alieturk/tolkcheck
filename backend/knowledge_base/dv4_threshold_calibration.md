---
source_id: davis-goadrich-2006-pr-roc
category: taxonomy
title: Davis, J., & Goadrich, M. (2006). The Relationship Between Precision-Recall and ROC Curves. Proceedings of the 23rd International Conference on Machine Learning (ICML), 233-240.
language: nl
status: geverifieerd (PDF geopend, titel/auteurs/jaar bevestigd)
---

Davis en Goadrich (2006) laten zien dat een classifier die dominant is in ROC-ruimte dat ook is in precision-recall(PR)-ruimte, en omgekeerd — maar dat PR-curves veel gevoeliger zijn voor klasse-onbalans dan ROC-curves. Bij een sterk scheve klasseverdeling (veel meer "correcte" dan "afwijkende" tolkfragmenten, zoals bij TolkCheck) kan een classifier er in ROC-ruimte goed uitzien terwijl de precision in PR-ruimte laag is.

Dit is direct relevant voor TolkCheck's DV4: de huidige 0.70/0.50-drempels in app/services/feedback.py zijn met de hand gekozen en niet gekalibreerd (zie de TODO(DV4)-notitie in dat bestand). Davis en Goadrich onderbouwen waarom drempelkeuze op basis van alleen een enkele score-cutoff, zonder precision/recall-analyse op de daadwerkelijke (scheve) klasseverdeling van gelabelde paren, een vertekend beeld van de kwaliteit van de detector kan geven. Een kalibratie die alleen naar ROC-achtige totaalscores kijkt, kan een drempel opleveren die er goed uitziet maar in de praktijk (weinig afwijkingen, veel correcte vertalingen) een lage precision heeft — precies het scenario waarin de hoorambtenaar veel valse waarschuwingen te zien krijgt.
