# CNRS Job Watcher

Veilleur local d'offres publiques CNRS orienté IA/ML. Le pipeline récupère les pages publiques
`emploi.cnrs.fr`, extrait les champs utiles, applique un filtrage dur, score la pertinence IA/ML
et exporte une shortlist exploitable en Markdown et CSV.

## Stack

- Python 3.12+
- `httpx` pour le fetch HTTP
- `BeautifulSoup` pour le parsing HTML
- `pydantic` pour les modèles validés
- SQLite pour l'historique local
- `typer` + `rich` pour le CLI
- `pytest` + fixtures HTML pour protéger les parseurs

## Usage

```bash
uv sync
uv run cnrs-jobs crawl --limit-pages 2 --limit-offers 25
uv run cnrs-jobs export
```

Sorties par défaut :

- `data/cnrs_jobs.sqlite`
- `data/raw/*.html`
- `data/digests/YYYY-MM-DD.md`
- `cnrs_ia_jobs.md`
- `cnrs_ia_jobs.csv`

## Commandes

```bash
uv run cnrs-jobs crawl --limit-pages 13
uv run cnrs-jobs export --format markdown --output cnrs_ia_jobs.md
uv run cnrs-jobs export --format csv --output cnrs_ia_jobs.csv
uv run cnrs-jobs audit
uv run cnrs-jobs digest
uv run cnrs-jobs eval
```

Le crawler respecte les zones publiques du site et limite volontairement le rythme des requêtes.
L'IA générative n'est pas utilisée comme crawler : elle doit rester une étape de classification
sémantique optionnelle après extraction.

## Development contract

Avant de livrer une modification du pipeline, lancer au minimum :

```bash
uv run ruff check .
uv run pytest
```

Pour valider le comportement réel CNRS sur un petit échantillon :

```bash
uv run cnrs-jobs crawl --limit-pages 1 --limit-offers 5 \
  --db /tmp/cnrs_smoke.sqlite \
  --raw-dir /tmp/cnrs_smoke_raw \
  --no-cache
uv run cnrs-jobs export --db /tmp/cnrs_smoke.sqlite --min-score 0.25
uv run cnrs-jobs audit --db /tmp/cnrs_smoke.sqlite
uv run cnrs-jobs digest --db /tmp/cnrs_smoke.sqlite --output /tmp/cnrs_digest.md
uv run cnrs-jobs eval
```

Les bases SQLite, snapshots HTML et exports générés restent hors Git.

`cnrs-jobs eval` utilise actuellement un petit dataset annoté de démarrage. Son rôle est de
bloquer les régressions critiques déjà observées ; il doit encore être enrichi vers au moins 30
offres réelles pour mesurer sérieusement précision et rappel.
