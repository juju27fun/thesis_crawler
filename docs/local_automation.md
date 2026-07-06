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
