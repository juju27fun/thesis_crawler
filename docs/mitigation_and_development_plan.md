# Plan large de mitigation et développement itératif

Date : 2026-07-06
Source principale : `docs/prototype_evaluation_2026-07-06.md`

## Objectif du document

Ce document transforme l'évaluation du prototype en plan d'implémentation progressif.
Il sert de feuille de route pour des itérations futures : chaque lot doit pouvoir être pris par
un agent, implémenté, vérifié, puis livré sans devoir redécouvrir tout le contexte.

Le cap produit reste le même : construire un veilleur intelligent d'offres CNRS qui récupère les
offres publiques, identifie les thèses et CDD réellement liés à l'IA/ML, puis produit une shortlist
fiable avec justification exploitable.

## Principes directeurs

- Le crawler/parser reste la source de vérité sur l'existence et les champs d'une offre.
- L'IA ne doit jamais naviguer librement sur le site CNRS ni décider seule qu'une offre existe.
- La classification doit combiner règles déterministes, signaux lexicaux, puis LLM structuré
  uniquement pour les cas sémantiques.
- La qualité de la shortlist prime sur l'ajout d'interface ou d'automatisation.
- Toute correction de scoring doit ajouter un test de non-régression avec une offre observée.
- Les exports doivent distinguer cible principale, cible secondaire, revue manuelle et exclusion.

## Vue d'ensemble des phases

| Phase | But | Résultat attendu |
| --- | --- | --- |
| 0 | Stabiliser les invariants de projet | Tests et commandes de base fiables |
| 1 | Corriger les faux positifs critiques | Shortlist qui n'inclut plus postdocs et `not_relevant` |
| 2 | Formaliser la taxonomie produit | Buckets `primary`, `secondary`, `review`, `exclude` |
| 3 | Construire un jeu d'évaluation annoté | Mesure rappel/précision reproductible |
| 4 | Améliorer discovery et filtres CNRS | Crawl plus complet et moins bruyant |
| 5 | Brancher un classifieur LLM JSON | Résumés et décisions sémantiques robustes |
| 6 | Enrichir stockage et historique | Détection nouvelles offres/changements |
| 7 | Améliorer exports et UX CLI | Digest réellement actionnable |
| 8 | Automatiser la veille | Runs planifiés et notifications |
| 9 | Étendre les sources | CNRS + autres portails compatibles |

## Phase 0 - Contrat de stabilité du prototype

### Problème

Le prototype fonctionne, mais chaque future itération touchera des zones sensibles : parsing,
classification, export et stockage. Il faut éviter que des changements utiles localement cassent
le pipeline global.

### Actions

- Ajouter une section `Development contract` au README.
- Documenter les commandes de validation minimales :
  - `uv run ruff check .`
  - `uv run pytest`
  - `uv run cnrs-jobs crawl --limit-pages 1 --limit-offers 5 --db /tmp/cnrs_smoke.sqlite --raw-dir /tmp/cnrs_smoke_raw --no-cache`
  - `uv run cnrs-jobs export --db /tmp/cnrs_smoke.sqlite`
- Ajouter une commande future `cnrs-jobs audit` ou un script court pour produire les compteurs :
  offres crawlées, indisponibles, target, review, excluded, score moyen.
- Décider que les bases SQLite et snapshots restent hors Git.

### Critères d'acceptation

- Un agent futur sait quelles commandes lancer avant de livrer.
- Les artefacts générés restent ignorés par Git.
- La smoke test réelle CNRS est documentée.

### Priorité

P1, parce que ce contrat protège toutes les phases suivantes.

## Phase 1 - Mitigation critique du hard filter et de l'export

### Problème

Deux bugs de conception faussent la shortlist :

- `post-doctorant` est capté comme `doctorant`;
- `Classification.is_target` est calculé mais non persisté, puis l'export filtre sur
  `hard_filter_passed`.

### Actions

1. Corriger la détection postdoc avant la détection thèse.
2. Limiter `_is_thesis` aux champs structurés les plus sûrs :
   - `contract_type`;
   - `title`;
   - éventuellement `reference/url` si le chemin contient `/Doctorant/`.
3. Ajouter des patterns d'exclusion :
   - `post-doctorant`;
   - `postdoctorant`;
   - `postdoctoral`;
   - `postdoc`;
   - `doctorat requis`;
   - `PhD required`.
4. Ajouter `is_target` à `JobOffer`.
5. Ajouter `target_bucket` ou au minimum un champ persistant équivalent.
6. Migrer SQLite sans casser les bases existantes :
   - `ALTER TABLE offers ADD COLUMN is_target INTEGER DEFAULT 0`;
   - `ALTER TABLE offers ADD COLUMN target_bucket TEXT`;
   - gérer le cas où les colonnes existent déjà.
7. Modifier `shortlist()` :
   - exclure `unavailable = 1`;
   - exiger `is_target = 1`;
   - exclure `ai_category = 'not_relevant'`;
   - garder `min_score` comme filtre secondaire.
8. Ajouter les tests :
   - postdoc Doctorat requis exclu;
   - CDD BAC+5 sans IA exclu même si hard-filter compatible;
   - thèse IA générative incluse;
   - IT CDD BAC+5 IA incluse.

### Critères d'acceptation

- L'offre `UMR8023-ERWALL-002` est exclue.
- Une offre `not_relevant` ne sort jamais dans `cnrs_ia_jobs.md`, même avec `--min-score 0.25`.
- Les tests couvrent les faux positifs observés dans l'évaluation.
- `uv run pytest` et `uv run ruff check .` sont verts.

### Risques

- Des offres de thèse mal libellées peuvent être sous-captées si on durcit trop.
- Mitigation : créer un bucket `review` plutôt que supprimer silencieusement les cas ambigus.

### Priorité

P1, premier chantier à implémenter.

## Phase 2 - Taxonomie produit et modèle de décision

### Problème

Le prototype mélange implicitement trois choses différentes :

- cible principale;
- cible secondaire;
- offre intéressante mais à relire.

Cette confusion rend le score difficile à interpréter.

### Taxonomie recommandée

`primary_target`

- CDD Doctorant;
- Contrat doctoral;
- titre thèse/doctorant fiable;
- niveau BAC+5 ou équivalent;
- sujet IA/ML fort.

`secondary_target`

- IT en contrat CDD;
- ingénieur IA/ML/data/MLOps/vision/NLP/génératif;
- niveau BAC+5 ou niveau à vérifier;
- pas de doctorat requis.

`adjacent_review`

- BAC+3/4 mais très pertinent techniquement;
- IA créative ou usage applicatif très spécifique;
- data science/bioinformatique/calcul scientifique sans preuve ML forte;
- offre pertinente mais niveau ambigu.

`exclude`

- postdoc ou chercheur Doctorat requis;
- CDI, mobilité interne, stage, apprentissage si hors cible;
- administratif/communication/gestion sans travail IA technique;
- offre indisponible;
- absence de signal IA/ML.

### Actions

- Créer un type `TargetBucket`.
- Créer un type `Accessibility`.
- Remplacer `hard_filter_passed` comme signal produit par :
  - `eligibility_passed`;
  - `is_target`;
  - `target_bucket`;
  - `exclusion_reason`.
- Garder `hard_filter_passed` uniquement si utile pour rétrocompatibilité, mais ne plus l'utiliser
  comme critère final d'export.
- Adapter Markdown/CSV pour afficher le bucket.

### Critères d'acceptation

- Le Markdown groupe les offres par bucket.
- Les offres BAC+3/4 pertinentes ne disparaissent pas : elles vont dans `adjacent_review` ou
  `secondary_target` selon la règle choisie.
- Les postdocs vont dans `exclude` avec raison explicite.

### Priorité

P1/P2. À faire juste après la mitigation critique.

## Phase 3 - Jeu d'évaluation annoté

### Problème

Le projet ne peut pas progresser sérieusement sans vérité de référence. Les tests actuels valident
un cas positif, mais pas la qualité globale.

### Actions

- Créer `tests/fixtures/evaluation/offers.yaml` ou `tests/fixtures/evaluation/offers.json`.
- Inclure au minimum 30 offres réelles observées, avec :
  - `reference`;
  - `url`;
  - `title`;
  - `expected_bucket`;
  - `expected_ai_domain`;
  - `expected_accessibility`;
  - `notes`;
  - éventuellement `snapshot_file`.
- Démarrer avec les offres du rapport :
  - `UMR5549-LESMAR-016` : `secondary_target` ou `primary` selon décision BAC+5 IT;
  - `UAR3598-ARIALL-048` : `adjacent_review` ou `secondary_target`, niveau BAC+3/4;
  - `UMR7288-AUDBAR-083` : `adjacent_review`, BAC+3/4 mais deep learning;
  - `UMR8023-ERWALL-002` : `exclude`, postdoc Doctorat requis;
  - `UMR7039-RICBOR-002` : `adjacent_review`, IA créative;
  - `UMR6074-NICKER-008` : `primary_target`;
  - `UMR6074-NICKER-009` : `primary_target`.
- Ajouter une commande de test ou un test Pytest :
  - charge les snapshots;
  - parse;
  - classifie;
  - compare aux labels attendus.
- Ajouter des métriques simples :
  - précision `primary + secondary`;
  - rappel sur offres annotées cibles;
  - nombre de `exclude` mal classés target.

### Critères d'acceptation

- Un changement de scoring qui réintroduit le faux positif postdoc casse un test.
- Le jeu annoté est facile à enrichir par copier-coller d'une offre observée.
- Les métriques sont affichées dans les tests ou une commande `eval`.

### Priorité

P1/P2. C'est l'investissement qui rend les futurs réglages sérieux.

## Phase 4 - Discovery CNRS et filtres serveur

### Problème

Le prototype parcourt la recherche générale et découvre moins de cartes que le compteur global
annoncé. Il n'exploite pas encore les filtres CNRS, alors que le portail expose les types de contrat,
niveaux, durées, et possiblement domaines.

### Actions

- Étudier précisément le formulaire `Recherche.aspx` :
  - `ContractType`;
  - `Page`;
  - `FiltersDegree`;
  - `FiltersDuration`;
  - autres champs cachés.
- Ajouter un objet `SearchProfile` :
  - `all_public`;
  - `doctorant`;
  - `cdd_bac5`;
  - `ai_audit`.
- Ajouter `cnrs-jobs crawl --profile doctorant`.
- Ajouter `cnrs-jobs crawl --profile cdd-bac5`.
- Comparer les volumes :
  - pages générales;
  - pages filtrées;
  - sitemap;
  - doublons par référence.
- Dédupliquer par référence quand disponible, URL sinon.

### Critères d'acceptation

- Le crawler peut récupérer les CDD Doctorant sans parcourir toutes les offres.
- Le comportement de pagination est documenté avec chiffres.
- Une commande d'audit indique le nombre d'offres découvertes par profil.

### Risques

- Le formulaire ASP.NET peut changer ou dépendre de champs cachés.
- Si la simulation POST devient fragile, conserver le crawl général comme fallback.

### Priorité

P2. Important pour efficacité et complétude, mais après la shortlist.

## Phase 5 - Classification LLM JSON stricte

### Problème

Les règles lexicales seules ne suffiront pas pour distinguer :

- IA technique vs communication autour de l'IA;
- data science réelle vs simple traitement de données;
- niveau accessible vs doctorat implicite;
- pertinence forte vs contexte de labo seulement.

### Architecture recommandée

Flux :

```txt
parse detail
  -> eligibility rules
  -> keyword/domain signals
  -> LLM classifier for ambiguous or candidate offers
  -> persisted decision
  -> export
```

Le LLM doit recevoir uniquement les champs extraits :

- titre;
- contrat;
- niveau;
- durée;
- labo;
- lieu;
- description;
- compétences;
- raw snippets pertinents si nécessaire.

### Schéma de sortie

```json
{
  "is_target": true,
  "target_bucket": "primary_target",
  "ai_domain": "generative_ai",
  "accessibility": "bac5_accessible",
  "relevance_score": 0.92,
  "short_summary": "Thèse sur la transférabilité des modèles génératifs structurés.",
  "reason": "CDD Doctorant BAC+5 avec sujet explicitement centré sur modèles génératifs et GNN.",
  "risk_flags": []
}
```

### Actions

- Créer `src/cnrs_job_watcher/llm_classifier.py`.
- Définir un protocole/interface pour pouvoir mocker le LLM en tests.
- Ajouter un mode `--classifier rules|llm|hybrid`.
- Utiliser règles seules par défaut tant que les credentials ne sont pas configurés.
- Appeler le LLM uniquement pour :
  - offres hard-filter compatibles;
  - offres avec signaux IA adjacents;
  - cas ambigus.
- Garder un cache par hash des champs d'offre.
- Ne jamais envoyer de secrets.

### Critères d'acceptation

- Le projet fonctionne sans clé API.
- Les tests mockent la réponse LLM.
- Le JSON LLM est validé par Pydantic.
- Une réponse invalide ne casse pas tout le run : elle marque l'offre `needs_review`.

### Priorité

P2. Très utile pour qualité sémantique, mais seulement après correction de la logique produit.

## Phase 6 - Résumés et exports actionnables

### Problème

Le Markdown actuel explique surtout les mots-clés détectés. Il ne donne pas encore un résumé
utilisable pour décider si Louis doit ouvrir l'offre.

### Actions

- Ajouter `short_summary`.
- Ajouter `fit_summary` ou `why_interesting`.
- Ajouter `risk_flags` :
  - `bac3_4`;
  - `doctorate_required`;
  - `postdoc`;
  - `creative_ai`;
  - `administrative_context`;
  - `expired_or_unavailable`;
  - `level_unclear`.
- Réorganiser le Markdown :
  - `Très pertinentes`;
  - `Pertinentes mais à vérifier`;
  - `Adjacentes / revue manuelle`;
  - optionnel : `Exclusions notables`.
- Ajouter un CSV avec colonnes stables :
  - `reference`;
  - `bucket`;
  - `score`;
  - `title`;
  - `contract`;
  - `level`;
  - `lab`;
  - `location`;
  - `summary`;
  - `reason`;
  - `flags`;
  - `url`.

### Critères d'acceptation

- Une offre peut être évaluée en moins de 20 secondes en lisant le digest.
- Les offres secondaires ne polluent pas le haut de la shortlist.
- Le CSV reste exploitable dans tableur/Notion/Airtable.

### Priorité

P2/P3. À faire après les buckets.

## Phase 7 - Stockage, historique et migrations

### Problème

SQLite est adapté au MVP, mais le schéma doit évoluer vers une mémoire de veille :
nouvelles offres, changements, dates de première/dernière vue, décisions de classification.

### Actions

- Ajouter une table `runs` :
  - id;
  - started_at;
  - finished_at;
  - profile;
  - pages_fetched;
  - offers_discovered;
  - offers_fetched;
  - errors_count.
- Ajouter une table `offer_snapshots` ou conserver HTML hash :
  - `offer_url`;
  - `reference`;
  - `content_hash`;
  - `fetched_at`;
  - `raw_path`.
- Ajouter les colonnes :
  - `is_target`;
  - `target_bucket`;
  - `accessibility`;
  - `short_summary`;
  - `risk_flags`;
  - `classifier_version`;
  - `content_hash`;
  - `last_classified_at`.
- Créer une petite gestion de migrations idempotente.

### Critères d'acceptation

- Relancer le crawler ne perd pas `first_seen_at`.
- On peut lister les nouvelles offres depuis le dernier run.
- On peut savoir si une offre a changé.
- Les migrations passent sur une base existante.

### Priorité

P2. Nécessaire avant l'automatisation quotidienne.

## Phase 8 - Observabilité et audit qualité

### Problème

Un veilleur doit expliquer ce qu'il a fait : combien d'offres, combien exclues, pourquoi, et où
les erreurs éventuelles se sont produites.

### Actions

- Ajouter `cnrs-jobs audit`.
- Ajouter `cnrs-jobs eval`.
- Ajouter un rapport console Rich :
  - découvertes;
  - fetch réussis;
  - erreurs HTTP;
  - indisponibles;
  - par bucket;
  - top scores;
  - exclusions par raison.
- Ajouter logs structurés simples.
- Ajouter un exit code non nul si :
  - aucune offre découverte;
  - trop d'erreurs HTTP;
  - parser extrait zéro titre;
  - eval descend sous un seuil défini.

### Critères d'acceptation

- Après un run, Louis peut savoir si le résultat est fiable sans ouvrir SQLite.
- Un futur cron/GitHub Action peut détecter un run cassé.

### Priorité

P2/P3.

## Phase 9 - Automatisation locale et notifications

### Problème

Le prototype est manuel. La valeur produit augmente fortement quand il détecte les nouvelles offres
et notifie sans bruit.

### Actions

- Ajouter `cnrs-jobs digest --since last-run`.
- Ajouter `--only-new`.
- Ajouter export dans `data/digests/YYYY-MM-DD.md`.
- Ajouter option notification :
  - email local;
  - Discord/Slack webhook;
  - Telegram;
  - simple fichier Markdown au départ.
- Ajouter un exemple cron :
  - quotidien matin;
  - logs dans `data/logs`.
- Ajouter GitHub Actions schedule seulement si le repo reçoit les secrets nécessaires.

### Critères d'acceptation

- Un run quotidien produit seulement les nouvelles offres ou changements importants.
- Aucune notification n'est envoyée sans configuration explicite.
- Les erreurs de run sont visibles.

### Priorité

P3. À faire quand la classification est suffisamment fiable.

## Phase 10 - Extension multi-sources

### Problème

CNRS seul est utile, mais la valeur augmente avec Inria, CEA, universités, Euraxess, Academic
Positions, etc. Il ne faut pas dupliquer toute la logique pour chaque source.

### Actions

- Introduire un modèle `SourceAdapter`.
- Extraire les interfaces :
  - `discover()`;
  - `fetch_detail()`;
  - `parse_detail()`;
  - `normalize_offer()`.
- Garder le modèle `JobOffer` commun.
- Ajouter `source_specific` JSON pour champs propres à chaque portail.
- Ajouter une source seulement après stabilisation CNRS.

### Critères d'acceptation

- CNRS continue de passer tous les tests.
- Une nouvelle source peut être ajoutée sans modifier la classification centrale.
- Les exports groupent ou filtrent par source.

### Priorité

P4. À éviter avant une V1 CNRS solide.

## Backlog détaillé par fichier

### `src/cnrs_job_watcher/schemas.py`

- Ajouter `TargetBucket`.
- Ajouter `Accessibility`.
- Ajouter `is_target`.
- Ajouter `target_bucket`.
- Ajouter `exclusion_reason`.
- Ajouter `short_summary`.
- Ajouter `risk_flags`.
- Ajouter `classifier_version`.

### `src/cnrs_job_watcher/classify.py`

- Séparer eligibility, domain detection et final decision.
- Corriger postdoc.
- Ne plus utiliser le texte complet pour décider qu'une offre est une thèse.
- Introduire `TargetDecision`.
- Ajouter des raisons d'exclusion structurées.
- Ajouter tests unitaires purs sans HTML.

### `src/cnrs_job_watcher/storage.py`

- Ajouter migrations idempotentes.
- Persister les nouveaux champs.
- Filtrer shortlist sur `is_target` ou `target_bucket`.
- Ajouter requêtes `new_since_last_run`.

### `src/cnrs_job_watcher/parse.py`

- Extraire le niveau d'étude depuis les faits détail si CNRS l'ajoute ailleurs.
- Extraire date limite de candidature.
- Extraire date d'embauche.
- Extraire rémunération si utile.
- Extraire sections `Missions`, `Activités`, `Compétences`, `Sujet de thèse` séparément.

### `src/cnrs_job_watcher/fetch.py`

- Ajouter profils de recherche.
- Gérer retries simples.
- Ajouter timeout configurable.
- Ajouter backoff léger sur erreurs 429/5xx.
- Comparer sitemap vs pagination.

### `src/cnrs_job_watcher/export.py`

- Grouper par bucket.
- Ajouter résumé court.
- Ajouter flags.
- Ajouter section `À vérifier`.
- Ajouter option `--include-excluded`.

### `src/cnrs_job_watcher/cli.py`

- Ajouter `audit`.
- Ajouter `eval`.
- Ajouter `digest`.
- Ajouter `--classifier`.
- Ajouter `--profile`.
- Ajouter `--only-new`.

### `tests/`

- Créer fixtures réalistes par offre.
- Ajouter dataset annoté.
- Ajouter tests de migration SQLite.
- Ajouter tests d'export.
- Ajouter tests de CLI avec base temporaire.

## Séquence recommandée des 6 prochaines itérations

### Itération 1 - Shortlist fiable

Objectif : corriger les deux P1.

Livrables :

- postdocs exclus;
- `is_target` persisté;
- export exclut `not_relevant`;
- tests de régression.

Validation :

```bash
uv run pytest
uv run ruff check .
uv run cnrs-jobs crawl --limit-pages 4 --limit-offers 80 --db /tmp/cnrs_eval.sqlite --raw-dir /tmp/cnrs_eval_raw --no-cache
uv run cnrs-jobs export --db /tmp/cnrs_eval.sqlite --min-score 0.25
```

### Itération 2 - Buckets produit

Objectif : remplacer la décision binaire implicite par une taxonomie stable.

Livrables :

- `primary_target`;
- `secondary_target`;
- `adjacent_review`;
- `exclude`;
- Markdown groupé.

### Itération 3 - Jeu d'évaluation

Objectif : transformer les cas observés en vérité testable.

Livrables :

- dataset annoté;
- tests d'évaluation;
- métriques simples.

### Itération 4 - Meilleur parsing détail

Objectif : extraire plus de champs utiles pour décision et résumé.

Livrables :

- date limite;
- date d'embauche;
- sections séparées;
- niveau depuis détail si disponible;
- tests fixtures.

### Itération 5 - LLM JSON hybride

Objectif : générer vraie justification/résumé pour les cas cibles ou ambigus.

Livrables :

- interface LLM mockable;
- schéma Pydantic strict;
- cache de classification;
- fallback règles.

### Itération 6 - Audit et digest quotidien

Objectif : rendre le veilleur opérable.

Livrables :

- `audit`;
- `digest --only-new`;
- historique de runs;
- exemple cron local.

## Définition de V1

Le projet peut être considéré V1 lorsque :

- le crawl CNRS public fonctionne sur un profil utile;
- les postdocs et offres non pertinentes ne sortent pas en shortlist cible;
- les offres IA/ML observées dans le jeu annoté sont correctement bucketées;
- le Markdown permet de décider rapidement quelles offres ouvrir;
- les tests protègent parsing, classification, export et migrations;
- un run quotidien peut produire un digest de nouvelles offres.

## Définition de non-objectifs pour l'instant

- Pas de dashboard web avant fiabilisation de la classification.
- Pas de Botasaurus/Playwright tant que HTTP suffit.
- Pas de multi-source avant V1 CNRS.
- Pas d'agent autonome qui navigue et décide en production.
- Pas d'envoi de notifications sans configuration explicite.

## Notes de décision

Le meilleur prochain investissement n'est pas d'ajouter plus de scraping. Le prototype sait déjà
extraire des offres. Le meilleur investissement est de rendre la décision fiable, mesurable et
explicable. Une fois cette couche solide, l'automatisation et l'extension multi-source auront une
base beaucoup plus stable.
