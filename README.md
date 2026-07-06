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
- `cnrs_ia_jobs.md`
- `cnrs_ia_jobs.csv`

## Commandes

```bash
uv run cnrs-jobs crawl --limit-pages 13
uv run cnrs-jobs export --format markdown --output cnrs_ia_jobs.md
uv run cnrs-jobs export --format csv --output cnrs_ia_jobs.csv
```

Le crawler respecte les zones publiques du site et limite volontairement le rythme des requêtes.
L'IA générative n'est pas utilisée comme crawler : elle doit rester une étape de classification
sémantique optionnelle après extraction.
