# Automatisation locale

Objectif : produire chaque matin un digest Markdown des nouvelles offres CNRS IA/ML, sans envoyer
de notification externe implicite.

## Commande quotidienne

Depuis la racine du dépôt :

```bash
uv run cnrs-jobs crawl \
  --profile ai_audit \
  --classifier hybrid \
  --db data/cnrs_jobs.sqlite \
  --raw-dir data/raw

uv run cnrs-jobs digest \
  --db data/cnrs_jobs.sqlite \
  --min-score 0.35 \
  --only-new \
  --output data/digests/$(date +%F).md

uv run cnrs-jobs audit --db data/cnrs_jobs.sqlite
```

Sans `OPENAI_API_KEY`, `--classifier hybrid` retombe sur les règles locales.

## Commande multi-source locale

ANRT/CIFRE nécessite une session locale. Vérifier la session avant de l'ajouter à une routine :

```bash
uv run --with playwright playwright install chromium
uv run --with playwright cnrs-jobs anrt-login --output data/auth/anrt-cookies.json
```

La commande ouvre un navigateur local, laisse le temps de se connecter à ANRT, vérifie les listes
entreprise/laboratoire, puis écrit un `storage_state` Playwright dans `data/auth/`, hors Git.

```bash
uv run cnrs-jobs anrt-session-check \
  --anrt-session-file data/auth/anrt-cookies.json \
  --raw-dir data/raw
```

Avant de l'ajouter à une routine, lancer un smoke réel borné qui écrit un rapport local :

```bash
uv run cnrs-jobs anrt-real-smoke \
  --anrt-session-file data/auth/anrt-cookies.json \
  --limit-offers 20 \
  --db data/validation/anrt_real_smoke.sqlite \
  --raw-dir data/raw \
  --report data/validation/anrt_real_smoke.md \
  --digest-output data/validation/anrt_real_digest.md
```

Le dossier `data/validation/` reste hors Git. Le rapport doit prouver au minimum : session valide,
pages liste parcourues, URLs découvertes, offres fetchées, erreurs détail, buckets et chemin du
digest produit.

Une fois la session valide, le mode multi-source peut être lancé ainsi :

```bash
uv run cnrs-jobs crawl \
  --source all \
  --classifier hybrid \
  --anrt-session-file data/auth/anrt-cookies.json \
  --db data/cnrs_jobs.sqlite \
  --raw-dir data/raw
```

Si ANRT est déconnecté, CNRS continue en mode `--source all` et le run indique que la session ANRT
est absente ou expirée. Pour diagnostiquer seulement ANRT, utiliser `--source anrt`, qui échoue avec
un code `2` quand l'authentification manque.

## Smoke ANRT hors réseau

Le dossier `tests/fixtures/anrt` permet de valider le pipeline ANRT sans session :

```bash
uv run cnrs-jobs anrt-session-check \
  --anrt-fixture-dir tests/fixtures/anrt \
  --no-cache

uv run cnrs-jobs crawl \
  --source anrt \
  --anrt-fixture-dir tests/fixtures/anrt \
  --db /tmp/anrt_fixture.sqlite \
  --raw-dir /tmp/anrt_fixture_raw \
  --no-cache
```

Pour transformer des snapshots locaux en fixtures committables, utiliser d'abord :

```bash
uv run cnrs-jobs anrt-anonymize-fixtures data/raw/anrt tests/fixtures/anrt_real_anonymized
uv run cnrs-jobs anrt-fixture-audit tests/fixtures/anrt_real_anonymized
```

Relire ensuite les fixtures produites avant commit : l'audit vérifie la structure, les détails
manquants et les emails/téléphones évidents, mais il ne garantit pas l'anonymisation de noms propres
ou de détails confidentiels.

## Exemple cron

Adapter le chemin du dépôt si nécessaire :

```cron
15 8 * * * cd /Users/julienleboulch/Documents/Scraping_Thèse && mkdir -p data/logs data/digests && uv run cnrs-jobs crawl --profile ai_audit --classifier hybrid --db data/cnrs_jobs.sqlite --raw-dir data/raw >> data/logs/cnrs-jobs.log 2>&1 && uv run cnrs-jobs digest --db data/cnrs_jobs.sqlite --min-score 0.35 --only-new --output data/digests/$(date +\%F).md >> data/logs/cnrs-jobs.log 2>&1 && uv run cnrs-jobs audit --db data/cnrs_jobs.sqlite >> data/logs/cnrs-jobs.log 2>&1
```

## Notifications

Aucune notification email, Discord, Slack ou Telegram n'est envoyée par défaut. Une future
intégration devra exiger une configuration explicite du canal et du secret associé.

## Contrôle rapide

```bash
tail -n 80 data/logs/cnrs-jobs.log
ls -lh data/digests/
```
