# Audit discovery CNRS

Date : 2026-07-06

Commande :

```bash
uv run cnrs-jobs profile-audit --limit-pages 2 --no-cache
uv run cnrs-jobs crawl --profile doctorant --limit-pages 2 --limit-offers 5 --no-cache
```

## Résultat observé

Sur les 2 premières pages publiques CNRS :

| Profil | Offres découvertes |
| --- | ---: |
| `all_public` | 40 |
| `doctorant` | 10 |
| `cdd_bac5` | 13 |
| `ai_audit` | 3 |

Le crawl `doctorant` limité à 5 détails a produit :

| Mesure | Valeur |
| --- | ---: |
| Détails fetchés | 5 |
| Erreurs | 0 |
| `primary_target` | 1 |
| `exclude` | 4 |

## Interprétation

Le formulaire public expose des valeurs de contrat comme `DOCTOR`, `ITCDD` et `CHRCDD`, mais un POST
minimal avec ces valeurs ne reproduit pas de façon fiable le filtrage de l'interface. Le crawler
conserve donc le parcours public général, puis applique les profils localement sur les cartes de
liste avant de télécharger les pages détail.

Ce compromis réduit déjà le bruit et le nombre de pages détail à récupérer, sans faire dépendre le
pipeline d'un état ASP.NET fragile. Le crawl général reste le fallback de complétude.

## Limite

Ces profils ne remplacent pas encore de vrais filtres serveur. Une future itération pourra inspecter
plus finement les champs cachés et les scripts du portail, mais elle devra conserver un fallback
`all_public`.
