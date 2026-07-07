# Audit accès ANRT/CIFRE

Date : 2026-07-07
Statut : audit initial non connecté

## Résumé

Les pages d'offres ANRT ciblées sont dans l'espace membre :

- `https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/entreprise`
- `https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/laboratoire`

Sans session authentifiée, elles ne se comportent pas comme des pages publiques. Les essais directs
redirigent vers une page de déconnexion ou `/logout`, puis peuvent produire un statut HTTP `401`.

Conclusion actuelle : `playwright_required_or_session_cookie_required`.

## Observations

- La page d'accueil publique explique que les entreprises et laboratoires proposent leurs offres de
  thèse sur la plateforme.
- Les listes d'offres sont sous `/espace-membre/`.
- Un accès non connecté ne donne pas une liste vide exploitable ; il signale une déconnexion.
- Un test réel non connecté via CLI redirige vers `/logout` et peut produire `401 Unauthorized`.
- Il n'y a pas de `robots.txt` exploitable à l'URL standard : la route renvoie une page 404 HTML.

## Décision d'implémentation

Le crawler ANRT ne doit pas considérer une page de déconnexion comme un succès. Il doit échouer
explicitement avec une erreur d'authentification, afin d'éviter un faux run "0 offre".

La première version implémentée accepte donc :

- une source `--source anrt` ;
- un type `--anrt-kind entreprise|laboratoire|both` ;
- un fichier de session cookies local via `--anrt-session-file` ;
- des snapshots runtime hors Git ;
- des parsers testés sur fixtures anonymisées.
- une commande `cnrs-jobs anrt-session-check` pour vérifier une session avant crawl.

## Prochain audit nécessaire

À faire depuis une session ANRT connectée locale :

- observer si les listes sont rendues en HTML serveur ou via endpoint JSON ;
- identifier les paramètres de pagination ;
- confirmer le format des liens détail ;
- vérifier les champs disponibles côté entreprise et laboratoire ;
- vérifier les conditions d'utilisation de l'espace membre ;
- produire deux fixtures anonymisées : une entreprise, une laboratoire.

## Garde-fous

- Aucun identifiant, cookie ou session ne doit être commité.
- Les dossiers `data/auth/`, `data/anrt_session/` et `playwright/.auth/` restent ignorés.
- CNRS doit continuer à fonctionner sans dépendre d'ANRT.
- Un run ANRT sans session doit sortir avec un message clair `ANRT auth requise`.
- Un run `--source all` doit continuer CNRS si ANRT est déconnecté.
