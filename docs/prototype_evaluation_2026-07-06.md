# Évaluation du prototype CNRS Job Watcher

Date : 2026-07-06

## Verdict court

Le prototype valide fortement la faisabilité : le site CNRS se scrape proprement en HTTP,
les pages détail donnent les champs utiles, SQLite fonctionne, les exports Markdown/CSV sont
exploitables et le socle de tests/lint est sain.

Il n'est pas encore prêt comme veilleur quotidien fiable. Le principal risque est la qualité de
classification : le hard filter confond certains postdocs avec des thèses, et l'export peut inclure
des offres non pertinentes si le seuil est abaissé. Le prochain incrément doit donc porter sur
l'évaluation et le scoring, plus que sur l'infrastructure.

## Périmètre vérifié

Commandes exécutées :

```bash
uv run pytest
uv run ruff check .
uv run cnrs-jobs crawl --limit-pages 4 --limit-offers 80 --db /tmp/cnrs_eval.sqlite --raw-dir /tmp/cnrs_eval_raw --no-cache
uv run cnrs-jobs export --db /tmp/cnrs_eval.sqlite --min-score 0.25 --format both
```

Résultats :

- 3 tests passés.
- Ruff vert.
- 80 pages détail CNRS crawlées.
- 0 offre indisponible dans cet échantillon.
- 48 offres marquées hard-filter OK.
- 17 offres exportables au seuil par défaut `0.35`.
- 48 offres exportables au seuil permissif `0.25`, ce qui est trop large.
- Scan liste : 253 cartes uniques visibles sur 13 pages paginées.

## Comparaison manuelle sur offres CNRS

### Très bon match : IA bio-inspirée

Offre CNRS : `UMR5549-LESMAR-016`
Lien : https://emploi.cnrs.fr/Offres/CDD/UMR5549-LESMAR-016/Default.aspx

Verdict manuel : très pertinente. CDD IT, BAC+5, IA bio-inspirée, deep learning, réseaux
neuronaux, PyTorch/TensorFlow/Keras/JAX.

Verdict algo : score `1.00`, catégorie `ml_deep_learning`.

Conclusion : bon comportement.

### Bon match mais niveau secondaire : calcul scientifique Huma-Num

Offre CNRS : `UAR3598-ARIALL-048`
Lien : https://emploi.cnrs.fr/Offres/CDD/UAR3598-ARIALL-048/Default.aspx

Verdict manuel : pertinente mais secondaire. Le poste est BAC+3/4, pas BAC+5, mais il touche
serveurs LLM, Ollama, bases vectorielles, Transformers, LangChain, Python et environnements de
calcul. À garder si la cible accepte les postes techniques IA non strictement BAC+5.

Verdict algo sur détail : score `0.81`, catégorie `generative_ai`.

Conclusion : pertinent pour une veille IA large, discutable pour une veille strictement BAC+5.

### Pertinent mais profil inférieur à la cible : Smart-Microscopy

Offre CNRS : `UMR7288-AUDBAR-083`
Lien : https://emploi.cnrs.fr/Offres/CDD/UMR7288-AUDBAR-083/Default.aspx

Verdict manuel : techniquement pertinente, car elle mentionne apprentissages profonds,
deep learning, Python et fine-tuning de modèles. Mais la carte indique BAC+3/4.

Verdict algo : score `0.75`, catégorie `ml_deep_learning`.

Conclusion : bon signal sémantique, mais le niveau doit être mieux exposé dans la shortlist
pour éviter de mélanger cible principale et secondaire.

### Faux positif cible : postdoctorant astrophysique

Offre CNRS : `UMR8023-ERWALL-002`
Lien : https://emploi.cnrs.fr/Offres/CDD/UMR8023-ERWALL-002/Default.aspx

Verdict manuel : hors cible si l'objectif est thèse ou CDD accessible BAC+5. Le poste est
postdoctoral, contrat chercheur, Doctorat requis. Le sujet est data/ML-adjacent, mais pas
accessible BAC+5.

Verdict algo : score `0.67`, catégorie `ml_deep_learning`, hard-filter OK.

Conclusion : bug important. Le hard filter classe `post-doctorant` comme thèse/doctorant.

### Cas ambigu produit : création artistique par IA

Offre CNRS : `UMR7039-RICBOR-002`
Lien : https://emploi.cnrs.fr/Offres/CDD/UMR7039-RICBOR-002/Default.aspx

Verdict manuel : pertinente pour IA générative appliquée, mais moins pertinente pour un profil
ML/recherche technique classique. Le secteur est culture/communication/production de savoirs,
avec LoRA/iLoRA, Stable Diffusion, prompting, Python.

Verdict algo : score `0.47`, catégorie `generative_ai`.

Conclusion : bon candidat à une catégorie `creative_genai_adjacent` ou `needs_review`.

## Code Review

### P1 - Le hard filter laisse passer les postdocs comme thèses

Fichier : `src/cnrs_job_watcher/classify.py`, lignes 135-158.

Le test `_is_thesis()` cherche `doctorant` dans tout le texte. Une offre `post-doctorant`
contient ce signal et passe avant le contrôle `doctorate_required`. Résultat observé :
`UMR8023-ERWALL-002` est classé hard-filter OK alors que le niveau affiché est Doctorat.

Impact : faux positifs sérieux dans la shortlist par défaut.

Correction recommandée :

- détecter et exclure `post-doctorant`, `postdoctorant`, `postdoc`, `doctorat` avant `_is_thesis`;
- limiter `_is_thesis` au titre/contrat, pas au texte complet;
- considérer `CDD Doctorant` et `Contrat doctoral` comme signaux forts, mais pas `doctorant` seul
  dans un texte libre.

### P1 - L'export utilise `hard_filter_passed`, pas `Classification.is_target`

Fichier : `src/cnrs_job_watcher/classify.py`, lignes 103 et 116-124.
Fichier : `src/cnrs_job_watcher/storage.py`, lignes 98-105.

`classify_offer()` calcule `is_target`, mais `apply_classification()` ne le persiste pas.
`hard_filter_passed` est mis à `target_type != "not_target"`, puis `shortlist()` filtre seulement
sur hard filter + score. Au seuil `0.25`, toutes les offres BAC+5 CDD sans signal IA fort peuvent
sortir avec le bonus de base.

Impact : si Louis baisse le seuil pour augmenter le rappel, le bruit explose.

Correction recommandée :

- ajouter un champ `is_target` au modèle et à SQLite;
- filtrer l'export sur `is_target = 1`;
- ou au minimum exclure `ai_category = 'not_relevant'` dans `shortlist()`.

### P2 - Les filtres CNRS ne sont pas exploités

Fichier : `src/cnrs_job_watcher/fetch.py`, lignes 38-47.

Le crawler parcourt les pages générales et télécharge ensuite les détails. Il ne poste pas les
filtres `ContractType`, niveau, durée ou type de poste déjà disponibles dans le formulaire CNRS.

Impact : beaucoup de pages inutiles, coût runtime plus haut, bruit plus élevé.

Recommandation : ajouter une commande `crawl --profile ai-bac5-cdd` qui poste les filtres CNRS
quand ils sont fiables, tout en gardant le crawl général pour audit.

### P2 - La couverture de tests ne protège pas les erreurs de classification observées

Fichier : `tests/test_parse.py`.

Les tests valident un cas positif de thèse IA, mais pas :

- postdoc Doctorat requis;
- BAC+3/4 pertinent mais secondaire;
- CDD BAC+5 sans IA;
- offre IA créative/communication;
- export qui doit exclure `not_relevant`.

Impact : les erreurs actuelles peuvent réapparaître sans casser la CI.

### P2 - La pagination totale reste partiellement comprise

Fichier : `src/cnrs_job_watcher/parse.py`, lignes 52-71.

Le site annonce un compteur global élevé, mais la pagination visible testée donne 13 pages et
253 cartes uniques dans le scan liste. Ce n'est pas forcément un bug : le portail peut segmenter
ou filtrer côté formulaire. Mais le prototype ne prouve pas encore qu'il découvre toutes les offres
publiques disponibles.

Recommandation : documenter ce comportement et comparer avec le sitemap CNRS ou les filtres
de contrat.

### P3 - Les résumés ne sont pas encore des résumés

Fichier : `src/cnrs_job_watcher/export.py`.

La sortie donne une justification courte basée sur mots-clés. Elle ne résume pas réellement
la mission, les compétences et pourquoi l'offre est intéressante pour Louis.

Recommandation : ajouter une étape `llm_classifier` ou `llm_summarizer` en JSON strict, avec
fallback règles.

## Évaluation produit

### Ce qui est déjà solide

- Le découpage crawler / parser / classify / storage / export est sain.
- HTTP + BeautifulSoup suffit pour le portail actuel.
- Les snapshots HTML sont utiles pour déboguer les parsers.
- SQLite est adapté au MVP.
- Les exports Markdown/CSV donnent une première valeur immédiate.
- La stack est légère et maintenable.

### Ce qui manque pour une vraie V1

- Une vérité de classification testée sur un échantillon annoté.
- Une séparation nette entre cible principale, cible secondaire et hors cible.
- Un champ `is_target` persistant.
- Un export qui n'inclut jamais `not_relevant`.
- Un classifieur LLM JSON strict pour les cas ambigus.
- Des tests de non-régression sur les faux positifs/faux négatifs observés.
- Une commande de rapport d'audit : nombre crawlés, nouveaux, pertinents, exclus, erreurs.

## Recommandation de priorisation

### Étape 1 : fiabiliser la shortlist

Corriger le hard filter postdoc, persister `is_target`, exclure `not_relevant` de l'export et
ajouter les tests associés. C'est le plus fort gain qualité.

### Étape 2 : ajouter des classes produit

Remplacer la sortie binaire implicite par :

- `primary_target` : thèse / contrat doctoral / CDD Doctorant IA/ML BAC+5;
- `secondary_target` : IT CDD IA/ML compatible, même BAC+3/4 ou niveau à vérifier;
- `adjacent_review` : IA créative, data science, bioinformatique, calcul scientifique;
- `exclude` : postdoc Doctorat requis, administratif, stage, apprentissage, mobilité interne.

### Étape 3 : brancher le LLM

Le LLM doit produire :

- `is_target`;
- `target_bucket`;
- `ai_domain`;
- `accessibility`;
- `relevance_score`;
- `short_summary`;
- `reason`;
- `risk_flags`.

Le crawler/parser reste la source de vérité.

## Conclusion

Le prototype a atteint le bon stade : il prouve que le site est exploitable et que le pipeline
local marche. Le prochain travail ne doit pas être plus de scraping ou une interface. Il doit être
une phase d'évaluation/classification : corriger les faux positifs structurels, créer un petit jeu
d'offres annotées, et verrouiller les règles par tests.
