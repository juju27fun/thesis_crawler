# Statut d'implémentation ANRT/CIFRE

Date : 2026-07-07, mis à jour le 2026-07-08

## Statut court

ANRT/CIFRE est maintenant intégré comme source authentifiée réelle dans le pipeline multi-source.
Le projet peut :

- lancer CNRS seul ;
- lancer ANRT seul avec garde d'authentification ;
- lancer `--source all`, qui continue CNRS même si ANRT est déconnecté ;
- parser et classifier des fixtures ANRT entreprise/laboratoire ;
- crawler un dossier fixture ANRT anonymisé avec le même pipeline que le réseau ;
- suivre les liens de pagination HTML des listes ANRT avec une limite de sécurité ;
- découvrir les offres réelles via l'endpoint DataTables authentifié
  `/espace-membre/offre/dtList`, car les pages HTML connectées ne contiennent pas les cartes
  d'offres ;
- marquer les offres d'une source comme `missing` quand elles disparaissent d'un crawl complet ;
- évaluer un dataset ANRT synthétique de 21 cas ;
- exporter une provenance lisible et des champs CIFRE spécifiques.

Le crawl ANRT réel a été prouvé le 2026-07-08 avec une session locale hors Git : 288 offres
exploitables découvertes, 288 offres traitées, 0 erreur détail, 62 offres dans le digest IA/ML.

## Implémenté

- `cnrs-jobs crawl --source cnrs`
- `cnrs-jobs crawl --source anrt --anrt-kind entreprise|laboratoire|both`
- `cnrs-jobs crawl --source all`
- `cnrs-jobs anrt-login`
- `cnrs-jobs export --source all`
- `cnrs-jobs digest --source all`
- `cnrs-jobs audit --source all`
- `cnrs-jobs changes --source all`
- `cnrs-jobs anrt-session-check`
- `cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt`
- `cnrs-jobs anrt-real-smoke`
- `cnrs-jobs anrt-real-smoke --anrt-fixture-dir tests/fixtures/anrt`
- `cnrs-jobs anrt-mvp-audit`
- `cnrs-jobs anrt-export-eval-seed`
- `cnrs-jobs anrt-anonymize-fixtures`
- `cnrs-jobs eval --source anrt`
- Module `cnrs_job_watcher.anrt.fetch`
- Module `cnrs_job_watcher.anrt.parse`
- `AnrtSourceAdapter`
- découverte paginée via liens `rel=next`, `Suivant`, `page=` ou `offre-list` ;
- fallback DataTables ANRT quand le HTML connecté ne contient aucun lien détail ;
- parsing des lignes JSON DataTables en `JobOffer` sans chargement navigateur par offre ;
- construction des liens détail via le champ ANRT `crypt` ;
- `SourceDefinition` / `SOURCE_REGISTRY`
- Migration SQLite non destructive des runs :
  - `source`
  - `source_kind`
  - `status_message`
- Migration SQLite non destructive des offres :
  - `last_seen_status`
- Audit par source via `audit_counts`
- Scope `--source all` cohérent pour crawl, export, digest et audit ;
- Historique des disparitions via `last_seen_status=missing` ;
- Historique des modifications via `changed_offers()` et `cnrs-jobs changes` ;
- Exports Markdown/CSV avec :
  - origine lisible ;
  - entreprise ;
  - laboratoire source ;
  - secteur ;
  - discipline ;
  - école doctorale ;
  - partenaire attendu ;
  - statut financement / CIFRE ;
  - télétravail/hybride ;
  - présence de contact visible ;
  - date limite.
- Parsing ANRT enrichi dans `source_specific` :
  - discipline ;
  - école doctorale ;
  - partenaire attendu ;
  - télétravail/hybride ;
  - statut financement ;
  - statut convention CIFRE ;
  - présence de contact visible.
- Prompt LLM hybride multi-source : contexte ANRT/CIFRE, champs source spécifiques filtrés et
  consigne explicite de distinguer IA/ML réelle, IA outil secondaire, data adjacente et mention IA
  vague.
- Dataset `tests/fixtures/evaluation/anrt_offers.json` avec 21 cas synthétiques couvrant IA forte,
  génératif, ARN/protéines, bioinformatique, data adjacente et exclusions "IA" vagues ;
- Fixtures HTML anonymisées `tests/fixtures/anrt`
- Commande `cnrs-jobs anrt-fixture-audit` pour vérifier structure, détails manquants et contacts
  non anonymisés évidents dans un dossier fixture ANRT.

## Garde-fous validés

- Un run ANRT sans session sort en code `2` avec `ANRT auth requise`.
- `anrt-login` crée un `storage_state` Playwright local hors Git et échoue clairement si Playwright
  n'est pas installé.
- Un fichier session ANRT absent, non JSON, sans liste `cookies` ou sans cookie utilisable est
  rejeté avant crawl avec une erreur d'authentification explicite.
- Un run `--source all` continue CNRS si ANRT est déconnecté.
- Les cookies/session restent hors Git :
  - `data/auth/`
  - `data/anrt_session/`
  - `playwright/.auth/`
- Une page ANRT logout/déconnexion n'est pas parsée comme une offre.
- Une page détail ANRT indisponible, une page erreur serveur et une page authentifiée non-offre
  produisent des erreurs parser explicites.
- Un dossier fixture ANRT peut être audité avant commit pour repérer listes manquantes, détails
  absents et emails/téléphones restants.
- La date limite ANRT reste un champ spécifique et ne pollue pas `published_at_text`.
- Les champs CIFRE propres à ANRT restent dans `source_specific` et ne polluent pas le modèle commun.
- Les offres disparues restent en historique mais ne sortent plus en shortlist/digest.
- Les offres CIFRE sans signal IA/ML restent exclues.
- Les offres CIFRE data adjacentes vont en `adjacent_review`, pas automatiquement en cible primaire.
- `anrt-session-check` affiche les pages liste explorées, les URLs dédupliquées, les doublons
  entreprise/laboratoire et les compteurs UI visibles.
- `anrt-real-smoke` produit un rapport Markdown local avec statut, compteur découverte, offres
  fetchées, erreurs, buckets, dernier run, chemin SQLite, snapshots et digest.
- Les crawls/smokes ANRT réels exigent une confirmation explicite de revue des conditions
  applicables (`--anrt-terms-reviewed` ou `--terms-reviewed`) ; les fixtures restent exemptées.
- `anrt-mvp-audit` vérifie les preuves locales du MVP : run ANRT fini, erreurs nulles, minimum
  d'offres, origines entreprise/laboratoire, cible primaire, digest, snapshots, fixtures anonymisées
  et dataset d'évaluation.
- `anrt-export-eval-seed` génère depuis SQLite un dataset ANRT local annotable, compatible avec
  `cnrs-jobs eval`, en masquant emails/téléphones évidents.
- Les crawls ANRT stockent dans `runs.pages_fetched` le nombre réel de pages liste parcourues.
- Les lignes DataTables sans titre ni sujet sont ignorées comme lignes non exploitables.

## Validations lancées

```bash
uv run ruff check .
uv run pytest -q
uv run cnrs-jobs eval
uv run cnrs-jobs eval --source anrt
uv run cnrs-jobs eval --dataset tests/fixtures/evaluation/observed_offers.json
uv run cnrs-jobs anrt-login --help
uv run cnrs-jobs anrt-session-check --raw-dir /tmp/anrt_session_check_raw --no-cache
uv run cnrs-jobs anrt-real-smoke --anrt-fixture-dir tests/fixtures/anrt --db /tmp/anrt_smoke.sqlite --raw-dir /tmp/anrt_smoke_raw --report /tmp/anrt_smoke.md --digest-output /tmp/anrt_smoke_digest.md --no-cache
uv run cnrs-jobs anrt-export-eval-seed --db /tmp/anrt_smoke.sqlite --output /tmp/anrt_eval_seed.json --limit 2
uv run cnrs-jobs anrt-mvp-audit --db /tmp/anrt_smoke.sqlite --raw-dir /tmp/anrt_smoke_raw --digest /tmp/anrt_smoke_digest.md --fixture-dir tests/fixtures/anrt --eval-dataset tests/fixtures/evaluation/anrt_offers.json --output /tmp/anrt_mvp.md --min-offers 2 --min-raw-list-files 0 --min-raw-detail-files 0
uv run cnrs-jobs crawl --source all --limit-offers 2 --db /tmp/source_all.sqlite --raw-dir /tmp/source_all_raw --no-cache
uv run cnrs-jobs audit --db /tmp/source_all.sqlite --json
uv run cnrs-jobs audit --db /tmp/anrt_scope.sqlite --source all --json
uv run cnrs-jobs export --db /tmp/anrt_scope_export.sqlite --source all --format markdown --output /tmp/anrt_scope_all.md --min-score 0.1
uv run cnrs-jobs digest --db /tmp/anrt_scope_export.sqlite --source all --output /tmp/anrt_scope_digest.md --min-score 0.1 --no-only-new
uv run cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt --no-cache
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt --db /tmp/anrt_fixture.sqlite --raw-dir /tmp/anrt_fixture_raw --no-cache
uv run cnrs-jobs export --db /tmp/anrt_fixture.sqlite --source anrt --format markdown --output /tmp/anrt_fixture.md --min-score 0.1
uv run cnrs-jobs anrt-anonymize-fixtures tests/fixtures/anrt /tmp/anrt_anonymized_fixture_check
uv run cnrs-jobs anrt-session-check --anrt-session-file data/auth/anrt-cookies.json --raw-dir data/raw --no-cache
uv run cnrs-jobs anrt-real-smoke --anrt-session-file data/auth/anrt-cookies.json --terms-reviewed --limit-offers 290 --db data/anrt_real.sqlite --raw-dir data/raw --report data/validation/anrt_real_smoke_2026-07-08.md --digest-output data/digests/anrt_real_digest_2026-07-08.md
```

Résultats observés :

- `ruff` vert ;
- `pytest` vert, 56 tests ;
- évaluation CNRS annotée : métriques 1.000 ;
- évaluation ANRT synthétique 21 cas : métriques 1.000 ;
- évaluation CNRS observée : métriques 1.000 ;
- `anrt-login --help` expose la commande de création de session locale ;
- `anrt-session-check` sans session : code `2`, attendu ;
- `anrt-real-smoke` fixture : rapport `ok`, 2 URLs découvertes, 2 offres fetchées, digest produit ;
- `anrt-export-eval-seed` fixture : dataset JSON compatible avec `load_evaluation_cases` ;
- `anrt-mvp-audit` fixture : gates OK avec seuil `--min-offers 2` et dataset ANRT synthétique ;
- `--source all` sans session ANRT : CNRS traité, ANRT signalé `auth_required`.
- mode fixture ANRT : 2 offres traitées, 0 erreur, buckets `primary_target` et `adjacent_review`.
- mode fixture ANRT : `pages_fetched=2`, `offers_discovered=2`, `offers_fetched=2`.
- export fixture ANRT : provenance entreprise/laboratoire et date limite affichées.
- tests de pagination fixture : une deuxième page liste est suivie et dédupliquée.
- `audit/export/digest --source all` : pas de filtre source, sorties multi-source prêtes.
- `last_seen_status`: les offres non revues après un crawl complet sont marquées `missing`.
- `changes`: les offres avec plusieurs hashes de snapshot distincts sont listées.
- `anrt-session-check` réel : 18 pages liste/DataTables, 288 URLs exploitables, 0 doublon ;
  compteurs UI bruts observés : 171 entreprise, 119 laboratoire, dont 2 lignes laboratoire vides
  ignorées.
- `anrt-real-smoke` réel complet : 288 offres traitées, 0 erreur détail, buckets
  `primary_target=58`, `adjacent_review=4`, `exclude=226`, digest de 62 offres.

## Reste à faire pour compléter le plan

- Remplacer ou compléter les fixtures synthétiques par fixtures anonymisées issues des payloads
  DataTables réels.
- Ajouter un dataset d'évaluation ANRT réel anonymisé avec au moins 20 offres observées.
- Valider un digest réel ANRT + CNRS.
- Ajouter une option dédiée de crawl complet ANRT qui exprime mieux l'intention qu'un
  `anrt-real-smoke --limit-offers 290`.
- Améliorer le ranking : certaines offres institutionnelles contenant "IA" sont encore classées
  trop haut et devront être revues avec un classifieur LLM ou des règles négatives plus fines.

## Prochaine action recommandée

Pour rejouer la validation réelle avec une session locale déjà créée :

```bash
uv run cnrs-jobs anrt-session-check \
  --anrt-session-file data/auth/anrt-cookies.json \
  --raw-dir data/raw \
  --no-cache
uv run cnrs-jobs anrt-real-smoke \
  --anrt-session-file data/auth/anrt-cookies.json \
  --terms-reviewed \
  --limit-offers 290 \
  --db data/anrt_real.sqlite \
  --raw-dir data/raw \
  --report data/validation/anrt_real_smoke_2026-07-08.md \
  --digest-output data/digests/anrt_real_digest_2026-07-08.md
uv run cnrs-jobs anrt-export-eval-seed \
  --db data/anrt_real.sqlite \
  --output data/validation/anrt_eval_seed.json \
  --limit 20
```

Pour lancer le pipeline de crawl ANRT classique :

```bash
uv run cnrs-jobs crawl \
  --source anrt \
  --anrt-kind both \
  --anrt-session-file data/auth/anrt-cookies.json \
  --anrt-terms-reviewed \
  --limit-offers 290 \
  --db data/cnrs_jobs.sqlite \
  --raw-dir data/raw
```
