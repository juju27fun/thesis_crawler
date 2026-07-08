# Statut d'implémentation ANRT/CIFRE

Date : 2026-07-07

## Statut court

ANRT/CIFRE est maintenant intégré comme source authentifiée préparatoire dans le pipeline
multi-source. Le projet peut :

- lancer CNRS seul ;
- lancer ANRT seul avec garde d'authentification ;
- lancer `--source all`, qui continue CNRS même si ANRT est déconnecté ;
- parser et classifier des fixtures ANRT entreprise/laboratoire ;
- crawler un dossier fixture ANRT anonymisé avec le même pipeline que le réseau ;
- suivre les liens de pagination HTML des listes ANRT avec une limite de sécurité ;
- marquer les offres d'une source comme `missing` quand elles disparaissent d'un crawl complet ;
- évaluer un dataset ANRT synthétique de 21 cas ;
- exporter une provenance lisible et des champs CIFRE spécifiques.

Le crawl ANRT réel complet n'est pas encore prouvé, car il manque une session ANRT connectée et des
fixtures anonymisées issues du HTML réel.

## Implémenté

- `cnrs-jobs crawl --source cnrs`
- `cnrs-jobs crawl --source anrt --anrt-kind entreprise|laboratoire|both`
- `cnrs-jobs crawl --source all`
- `cnrs-jobs export --source all`
- `cnrs-jobs digest --source all`
- `cnrs-jobs audit --source all`
- `cnrs-jobs changes --source all`
- `cnrs-jobs anrt-session-check`
- `cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt`
- `cnrs-jobs anrt-anonymize-fixtures`
- `cnrs-jobs eval --source anrt`
- Module `cnrs_job_watcher.anrt.fetch`
- Module `cnrs_job_watcher.anrt.parse`
- `AnrtSourceAdapter`
- découverte paginée via liens `rel=next`, `Suivant`, `page=` ou `offre-list` ;
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
- Dataset `tests/fixtures/evaluation/anrt_offers.json` avec 21 cas synthétiques couvrant IA forte,
  génératif, ARN/protéines, bioinformatique, data adjacente et exclusions "IA" vagues ;
- Fixtures HTML anonymisées `tests/fixtures/anrt`
- Commande `cnrs-jobs anrt-fixture-audit` pour vérifier structure, détails manquants et contacts
  non anonymisés évidents dans un dossier fixture ANRT.

## Garde-fous validés

- Un run ANRT sans session sort en code `2` avec `ANRT auth requise`.
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
- Les crawls ANRT stockent dans `runs.pages_fetched` le nombre réel de pages liste parcourues.

## Validations lancées

```bash
uv run ruff check .
uv run pytest -q
uv run cnrs-jobs eval
uv run cnrs-jobs eval --source anrt
uv run cnrs-jobs eval --dataset tests/fixtures/evaluation/observed_offers.json
uv run cnrs-jobs anrt-session-check --raw-dir /tmp/anrt_session_check_raw --no-cache
uv run cnrs-jobs crawl --source all --limit-offers 2 --db /tmp/source_all.sqlite --raw-dir /tmp/source_all_raw --no-cache
uv run cnrs-jobs audit --db /tmp/source_all.sqlite --json
uv run cnrs-jobs audit --db /tmp/anrt_scope.sqlite --source all --json
uv run cnrs-jobs export --db /tmp/anrt_scope_export.sqlite --source all --format markdown --output /tmp/anrt_scope_all.md --min-score 0.1
uv run cnrs-jobs digest --db /tmp/anrt_scope_export.sqlite --source all --output /tmp/anrt_scope_digest.md --min-score 0.1 --no-only-new
uv run cnrs-jobs anrt-session-check --anrt-fixture-dir tests/fixtures/anrt --no-cache
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt --db /tmp/anrt_fixture.sqlite --raw-dir /tmp/anrt_fixture_raw --no-cache
uv run cnrs-jobs export --db /tmp/anrt_fixture.sqlite --source anrt --format markdown --output /tmp/anrt_fixture.md --min-score 0.1
uv run cnrs-jobs anrt-anonymize-fixtures tests/fixtures/anrt /tmp/anrt_anonymized_fixture_check
```

Résultats observés :

- `ruff` vert ;
- `pytest` vert, 49 tests ;
- évaluation CNRS annotée : métriques 1.000 ;
- évaluation ANRT synthétique 21 cas : métriques 1.000 ;
- évaluation CNRS observée : métriques 1.000 ;
- `anrt-session-check` sans session : code `2`, attendu ;
- `--source all` sans session ANRT : CNRS traité, ANRT signalé `auth_required`.
- mode fixture ANRT : 2 offres traitées, 0 erreur, buckets `primary_target` et `adjacent_review`.
- mode fixture ANRT : `pages_fetched=2`, `offers_discovered=2`, `offers_fetched=2`.
- export fixture ANRT : provenance entreprise/laboratoire et date limite affichées.
- tests de pagination fixture : une deuxième page liste est suivie et dédupliquée.
- `audit/export/digest --source all` : pas de filtre source, sorties multi-source prêtes.
- `last_seen_status`: les offres non revues après un crawl complet sont marquées `missing`.
- `changes`: les offres avec plusieurs hashes de snapshot distincts sont listées.

## Reste à faire pour compléter le plan

- Se connecter localement à ANRT et lancer `anrt-session-check` avec un vrai fichier cookies.
- Auditer les pages connectées :
  - HTML serveur ou endpoint JSON ;
  - pagination ;
  - filtres ;
  - liens détail ;
  - champs entreprise/laboratoire réels.
- Remplacer les fixtures synthétiques par fixtures anonymisées issues du HTML réel.
- Adapter les sélecteurs ANRT aux pages réelles si nécessaire.
- Prouver un crawl ANRT réel :
  - `--anrt-kind entreprise` ;
  - `--anrt-kind laboratoire` ;
  - `--anrt-kind both`.
- Ajouter un dataset d'évaluation ANRT réel anonymisé avec au moins 20 offres observées.
- Valider un digest réel ANRT + CNRS.
- Décider ensuite si Playwright devient nécessaire pour la session ou si `httpx` + cookies suffit.

## Prochaine action recommandée

Obtenir une session ANRT connectée locale et exécuter :

```bash
uv run cnrs-jobs anrt-session-check \
  --anrt-session-file data/auth/anrt-cookies.json \
  --raw-dir data/raw \
  --no-cache
```

Si cette commande découvre des URLs, lancer ensuite un crawl très limité :

```bash
uv run cnrs-jobs crawl \
  --source anrt \
  --anrt-kind both \
  --anrt-session-file data/auth/anrt-cookies.json \
  --limit-offers 5 \
  --db /tmp/anrt_real_smoke.sqlite \
  --raw-dir /tmp/anrt_real_smoke_raw \
  --no-cache
```
