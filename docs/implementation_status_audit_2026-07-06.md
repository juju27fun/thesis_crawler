# Audit de statut d'implémentation

Date : 2026-07-06

Source auditée : `docs/mitigation_and_development_plan.md`

## Synthèse

Le projet dispose maintenant d'une V1 CNRS locale robuste :

- crawler déterministe CNRS public ;
- profils de découverte ;
- parsing détail enrichi ;
- classification règles + LLM JSON optionnel ;
- stockage SQLite historisé ;
- exports Markdown/CSV actionnables ;
- digest quotidien local ;
- audit machine-readable ;
- dataset annoté de 31 cas ;
- interface multi-source prête, CNRS restant la seule source active.

Le plan est très largement implémenté, mais je ne le considère pas encore comme prouvé à 100 %
au sens strict : le dataset de 31 cas couvre les branches produit, mais il mélange offres observées
et cas réalistes/synthétiques. Pour satisfaire littéralement l'exigence "30 offres réelles observées",
il faudra remplacer ou compléter ce corpus par 30 snapshots réels annotés manuellement.

## Preuves de vérification

Commandes exécutées avec succès :

```bash
uv run pytest
uv run ruff check .
uv run cnrs-jobs eval
uv run cnrs-jobs crawl --profile ai_audit --limit-pages 1 --limit-offers 2 --max-error-rate 0.2
uv run cnrs-jobs audit --json
```

Résultat `eval` :

```txt
Cas évalués 31
Bucket accuracy 1.000
Domain accuracy 1.000
Accessibility accuracy 1.000
Target precision 1.000
Target recall 1.000
False targets 0
Missed targets 0
```

## Couverture par phase

| Phase | Statut | Preuve principale |
| --- | --- | --- |
| 0 - Contrat stabilité | Fait | README `Development contract`, `.gitignore`, smoke CNRS documenté |
| 1 - Hard filter/export | Fait | `is_target`, `target_bucket`, exclusion postdoc/doctorat, tests |
| 2 - Taxonomie produit | Fait | `TargetBucket`, `Accessibility`, exports groupés |
| 3 - Dataset annoté | Partiel strict / utile en pratique | 31 cas, mais pas encore 30 snapshots réels annotés |
| 4 - Discovery CNRS | Fait | `SearchProfile`, `profile-audit`, audit discovery documenté |
| 5 - LLM JSON | Fait | `llm_classifier.py`, JSON Schema strict, cache, tests mockés |
| 6 - Exports actionnables | Fait | `why_interesting`, flags, sections Markdown, CSV stable |
| 7 - Historique/migrations | Fait | tables `runs`, `offer_snapshots`, `llm_cache`, migrations idempotentes |
| 8 - Observabilité | Fait | `audit`, `audit --json`, top scores, exit codes crawl/eval |
| 9 - Automatisation locale | Fait | `digest --only-new`, `docs/local_automation.md`, logs locaux |
| 10 - Multi-source | Fait pour l'architecture | `SourceAdapter`, `source`, `source_specific`, filtre `--source` |

## Décisions critiques

- Les filtres CNRS serveur ne sont pas forcés : un POST minimal ne reproduisait pas fiablement
  l'interface ASP.NET. Le crawler garde donc le parcours public général et applique des profils
  locaux avant fetch détail.
- Les notifications externes ne sont pas activées par défaut. La V1 produit un digest Markdown local,
  conformément à l'option la plus sûre du plan.
- Aucune deuxième source n'est activée : l'interface multi-source est prête, mais le plan recommande
  d'ajouter une source seulement après stabilisation CNRS.

## Prochaine itération nécessaire

Créer un corpus `tests/fixtures/evaluation/observed_offers.json` avec au moins 30 offres CNRS
réellement crawlées, idéalement annotées à la main après lecture du digest. Ce sera la dernière
preuve forte manquante pour déclarer le plan complet au sens strict.
