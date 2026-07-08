# Roadmap large - Veilleur ANRT/CIFRE IA/ML

Date : 2026-07-08
Statut : cadrage produit et plan d'itérations futures

## Intention

Etendre le veilleur CNRS vers un veilleur multi-source de thèses IA/ML capable de surveiller les
offres CIFRE ANRT côté entreprise et laboratoire :

- `https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/entreprise`
- `https://offres-et-candidatures-cifre.anrt.asso.fr/espace-membre/offre-list/laboratoire`

L'objectif n'est pas de copier le crawler CNRS avec deux URLs différentes. ANRT doit être traité
comme une source de thèses authentifiée, potentiellement dynamique, avec ses propres risques
légaux, de session, de pagination, de champs incomplets et de faux négatifs sémantiques.

## Décision produit

La bonne direction est de faire évoluer le projet de `CNRS Job Watcher` vers un `Thesis Watcher`
multi-source, où CNRS et ANRT deviennent deux sources normalisées qui alimentent le même pipeline :

```txt
source adapter -> raw snapshots -> parser -> JobOffer -> classification -> SQLite -> export/digest
```

ANRT justifie presque un nouveau projet, mais il vaut mieux ne pas repartir de zéro maintenant :
le repo contient déjà les abstractions utiles (`JobOffer.source`, `source_specific`, storage,
exports, evaluation, `SourceAdapter`). Le vrai chantier est donc une généralisation contrôlée.

## Principes non négociables

- Le crawler/parser reste la source de vérité sur les offres existantes.
- Le LLM ne navigue pas sur ANRT et n'invente jamais une offre.
- ANRT est une source authentifiée : aucun cookie, session, identifiant ou snapshot sensible ne doit
  être commité.
- Le mode CNRS public doit continuer à fonctionner même si ANRT est déconnecté.
- Les captures ANRT réelles doivent être anonymisées avant d'entrer dans les fixtures Git.
- La classification doit lire le détail complet des offres, pas seulement le titre ou les cartes.
- Le produit doit optimiser le rappel sur les thèses IA/ML cachées dans le détail, puis contrôler le
  bruit par scoring et bucket.
- Toute automatisation planifiée ANRT dépend d'une validation des conditions d'utilisation.

## Pourquoi ANRT change l'architecture

CNRS est une source publique relativement stable. ANRT est une source membre :

- accès connecté ;
- session possiblement expirée ;
- pages ou API possiblement protégées par cookies/CSRF ;
- listes entreprise et laboratoire séparées ;
- champs probablement différents du CNRS ;
- potentiel doublon entre offre entreprise et offre laboratoire ;
- contenu plus hétérogène, parfois rédigé par des entreprises ;
- thèmes IA/ML souvent absents de la navigation et présents uniquement dans le descriptif.

Conséquence : il faut mesurer la qualité du crawler en faux négatifs, pas seulement en absence
d'erreur technique.

## Périmètre cible

### Inclus

- Offres CIFRE côté entreprise.
- Offres CIFRE côté laboratoire.
- Sujets thèse utilisant machine learning, deep learning, IA générative, NLP, vision, modèles
  prédictifs, bioinformatique ML, protéines/ARN avec deep learning, graph learning, MLOps,
  optimisation par apprentissage, séries temporelles apprenantes.
- Offres data science adjacentes à relire manuellement.
- Détection de nouvelles offres, disparitions et modifications.
- Exports Markdown/CSV et digest multi-source.

### Exclus au départ

- Candidature automatique.
- Scraping de messagerie privée ou données de candidats.
- Téléchargement massif de pièces jointes non nécessaires.
- Contournement technique de protection d'accès.
- Dashboard web complet avant preuve du pipeline réel.
- Classement personnalisé par CV avant stabilité de l'extraction.

## Architecture cible

```txt
src/cnrs_job_watcher/
  sources.py                 # registry multi-source
  schemas.py                 # modèle commun JobOffer
  classify.py                # règles + buckets
  llm_classifier.py          # classification JSON stricte optionnelle
  storage.py                 # SQLite, snapshots, historique
  export.py                  # Markdown/CSV/digest
  anrt/
    fetch.py                 # client authentifié ou fixture client
    parse.py                 # liste, pagination, détail, logout detection
    fixtures.py              # anonymisation snapshots réels
    audit.py                 # futur audit de couverture réel
  cnrs/                      # futur déplacement possible du code CNRS
```

Le déplacement de CNRS dans `cnrs/` n'est pas prioritaire. Il devient intéressant seulement quand
ANRT est suffisamment réel pour que le package principal soit trop mélangé.

## Données normalisées

Chaque offre ANRT doit converger vers `JobOffer` :

- `source = "anrt"`
- `source_specific.anrt_kind = "entreprise" | "laboratoire"`
- `url`
- `reference`
- `title`
- `contract_type = "CIFRE"` si confirmé
- `duration`
- `education_level`
- `location`
- `lab`
- `published_at_text`
- `description`
- `skills`
- `raw_text`
- `target_bucket`
- `ai_category`
- `ai_relevance_score`
- `ai_reason`

Champs ANRT spécifiques à garder dans `source_specific` :

- `company_name`
- `laboratory_name`
- `doctoral_school`
- `discipline`
- `sector`
- `region`
- `application_deadline`
- `contact_visible`
- `partner_status`
- `funding_status`
- `detail_sections`

Règle : ne pas créer un champ commun tant qu'au moins deux sources ne le justifient pas.

## Taxonomie de décision

### `primary_target`

Offre CIFRE ou thèse explicitement IA/ML forte :

- deep learning ;
- machine learning ;
- modèle génératif ;
- LLM/NLP ;
- vision par ordinateur ;
- graph neural network ;
- protéines/ARN avec modèle profond ;
- bioinformatique avec apprentissage ;
- reinforcement learning ;
- MLOps thèse ou système ML central.

### `secondary_target`

Offre probablement intéressante mais pas pure thèse ML :

- ingénierie IA appliquée ;
- plateforme MLOps ou data science fortement connectée à modèles ;
- sujet industriel où le ML est une brique importante mais pas toute la thèse.

### `adjacent_review`

Cas à relire, pour éviter les faux négatifs :

- data science sans preuve d'apprentissage ;
- bioinformatique sans modèle ML clair ;
- jumeau numérique ;
- simulation + optimisation ;
- séries temporelles sans méthode explicitement apprenante ;
- statistiques avancées mais pas deep learning.

### `exclude`

- transformation numérique sans contenu IA technique ;
- data engineering sans apprentissage ;
- logiciel métier sans composant IA ;
- communication, coordination, gestion de programme IA ;
- statistiques descriptives uniquement ;
- offre expirée, inaccessible ou hors thèse.

## Plan d'implémentation

### Phase 0 - Audit accès, conformité et surface réelle

But : savoir précisément ce que le compte ANRT autorise et expose.

Actions :

- Lire les conditions d'utilisation ANRT applicables au compte.
- Vérifier si les deux listes sont accessibles après login.
- Inspecter les pages connectées :
  - HTML serveur ou application JS ;
  - endpoints JSON ;
  - paramètres de pagination ;
  - filtres ;
  - compteur total ;
  - liens détail ;
  - redirections login/logout ;
  - tokens CSRF.
- Capturer un petit jeu de pages réelles en local hors Git.
- Produire un audit écrit avec conclusion :
  - `httpx_session_possible` ;
  - `playwright_required` ;
  - `manual_export_only` ;
  - `blocked_by_terms`.

Critères d'acceptation :

- On sait si l'automatisation est acceptable.
- On sait quel client utiliser.
- On connaît le volume visible par liste.
- Les snapshots bruts réels restent hors Git.

### Phase 1 - Authentification locale robuste

But : éviter les faux succès à zéro offre quand la session ANRT est expirée.

Actions :

- Stabiliser `anrt-session-check`.
- Supporter un fichier de session local hors Git.
- Ajouter éventuellement un login Playwright assisté :
  - l'utilisateur se connecte manuellement ;
  - le storage state est sauvegardé localement ;
  - le crawler le réutilise.
- Détecter toutes les formes de déconnexion :
  - page login ;
  - page logout ;
  - redirection ;
  - contenu "connectez-vous".
- Journaliser clairement le statut :
  - `auth_valid` ;
  - `auth_missing` ;
  - `auth_expired` ;
  - `auth_blocked`.

Critères d'acceptation :

- `--source anrt` sans session échoue clairement.
- `--source all` continue CNRS mais signale ANRT indisponible.
- Aucune session n'apparaît dans `git status`.

### Phase 2 - Discovery exhaustive des listes

But : récupérer toutes les URLs visibles, pas seulement la première page.

Actions :

- Implémenter discovery `entreprise`.
- Implémenter discovery `laboratoire`.
- Dédupliquer `both`.
- Suivre pagination HTML et/ou API.
- Ajouter limite de sécurité configurée.
- Comparer le nombre d'URLs découvertes au compteur UI si disponible.
- Sauvegarder les pages liste en snapshots.

Critères d'acceptation :

- Les deux listes donnent un nombre d'offres cohérent.
- Une pagination incomplète est détectée comme risque, pas ignorée.
- Les URLs détail sont stables et dédupliquées.

### Phase 3 - Parsing détail ANRT réel

But : extraire assez de contenu pour que la classification ne rate pas les offres IA/ML cachées.

Actions :

- Parser titre, résumé, description longue, compétences, contexte, entreprise, labo, lieu, deadline.
- Garder `raw_text` complet et sections structurées quand elles existent.
- Ne pas dépendre uniquement de labels exacts si l'UI varie.
- Ajouter snapshots anonymisés réels dans `tests/fixtures/anrt_real_anonymized`.
- Tester les cas incomplets.
- Tester les pages expirées ou interdites.

Critères d'acceptation :

- Une offre réelle entreprise devient un `JobOffer` complet.
- Une offre réelle laboratoire devient un `JobOffer` complet.
- Le parser échoue explicitement sur une page non-offre.

### Phase 4 - Classification ANRT orientée rappel

But : ne pas répéter l'erreur CNRS des thèses pertinentes ratées parce que le signal est dans le
détail, pas dans la navigation.

Actions :

- Elargir le lexique fort :
  - protéines ;
  - ARN ;
  - RNA ;
  - protein design ;
  - structure prediction ;
  - foundation model ;
  - graph neural network ;
  - geometric deep learning ;
  - multimodal ;
  - embedding ;
  - représentation latente ;
  - modèle auto-supervisé.
- Distinguer les signaux forts des signaux adjacents.
- Ajouter des signaux négatifs :
  - transformation numérique ;
  - data engineering sans apprentissage ;
  - logiciel sans IA ;
  - communication IA ;
  - statistiques descriptives uniquement.
- Construire un dataset ANRT de référence avec au moins 20 cas synthétiques puis 20 cas réels
  anonymisés.
- Mesurer précision/rappel par bucket.

Critères d'acceptation :

- Les offres bio/ARN/protéines avec deep learning sont `primary_target`.
- Les offres "IA" institutionnelles sont exclues.
- Les cas data ambigus vont en `adjacent_review`, pas en silence.

### Phase 5 - LLM classifier optionnel mais structuré

But : améliorer le jugement sémantique sur les cas ambigus, sans rendre le pipeline opaque.

Actions :

- Adapter le prompt à ANRT/CIFRE.
- Envoyer seulement les champs utiles :
  - titre ;
  - contrat ;
  - source kind ;
  - description ;
  - compétences ;
  - contexte labo/entreprise.
- Exiger JSON Schema strict :
  - `is_target`;
  - `target_bucket`;
  - `ai_domain`;
  - `relevance_score`;
  - `accessibility`;
  - `reason`;
  - `evidence_terms`.
- Mettre en cache par hash de snapshot.
- Router LLM uniquement sur :
  - cas adjacent ;
  - score proche du seuil ;
  - offres longues avec signaux faibles.

Critères d'acceptation :

- Sans clé API, les règles restent fonctionnelles.
- Avec clé API, le LLM n'écrase pas les exclusions évidentes.
- Les raisons sont courtes et utiles dans le digest.

### Phase 6 - Stockage et historique multi-source

But : faire de la veille, pas seulement un export ponctuel.

Actions :

- Vérifier la clé unique `source + reference` puis fallback URL.
- Stocker snapshots par source.
- Marquer `missing` après crawl complet par source.
- Détecter changements par hash.
- Garder `source_kind` pour ANRT entreprise/laboratoire.
- Ajouter compteurs d'audit par source :
  - découvertes ;
  - parsées ;
  - indisponibles ;
  - nouvelles ;
  - modifiées ;
  - disparues ;
  - primary/secondary/adjacent/exclude.

Critères d'acceptation :

- Une disparition ANRT ne supprime pas l'historique.
- Une modification de texte ressort dans `changes`.
- `audit --source all` donne une vision multi-source lisible.

### Phase 7 - Exports orientés décision de candidature

But : produire une shortlist réellement actionnable.

Actions :

- Grouper par bucket et par source.
- Afficher clairement :
  - titre ;
  - source ;
  - entreprise/labo ;
  - lieu ;
  - deadline ;
  - score ;
  - justification ;
  - lien ;
  - signaux extraits.
- Ajouter une section `A relire` pour `adjacent_review`.
- Ajouter une section `Nouveautés depuis le dernier run`.
- Ajouter CSV avec colonnes stables pour tri manuel.

Critères d'acceptation :

- Louis peut décider quoi ouvrir en moins de quelques minutes.
- Les offres ANRT ne sont pas mélangées indistinctement avec CNRS.
- Le digest n'inclut pas les offres `missing`.

### Phase 8 - Validation réelle et boucle qualité

But : rendre les erreurs visibles et corrigeables.

Actions :

- Faire un premier crawl réel limité :
  - `--anrt-kind entreprise --limit-offers 10` ;
  - `--anrt-kind laboratoire --limit-offers 10`.
- Produire un digest.
- Annoter manuellement les faux positifs/faux négatifs observés.
- Ajouter chaque erreur intéressante au dataset d'évaluation.
- Rejouer :
  - `ruff` ;
  - `pytest` ;
  - `eval` CNRS ;
  - `eval --source anrt` ;
  - crawl fixture ANRT.

Critères d'acceptation :

- Les erreurs découvertes deviennent des tests.
- Le rappel ANRT sur les offres IA/ML observées est prioritaire.
- Les changements de classification ne dégradent pas CNRS.

### Phase 9 - Automatisation prudente

But : transformer le pipeline en veille régulière.

Préconditions :

- conformité ANRT validée ;
- session stable ;
- parsing réel testé ;
- digest utile ;
- taux d'erreur faible ;
- limites de fréquence définies.

Actions :

- Ajouter commande cron locale séparée pour ANRT.
- Ne pas lancer ANRT si la session est expirée.
- Générer digest quotidien ou hebdomadaire.
- Ajouter notification optionnelle seulement après stabilité :
  - email local ;
  - Slack/Discord/Telegram si demandé.

Critères d'acceptation :

- Un run planifié ne spamme pas le site.
- Un échec auth produit une alerte claire.
- Les nouvelles offres sont distinguées des anciennes.

### Phase 10 - Evolution produit

Seulement après preuve ANRT réelle :

- renommer le produit vers `thesis-watcher` ;
- ajouter un dashboard local ;
- ajouter favoris et statut de candidature ;
- comparer offres avec un profil/CV ;
- générer brouillon de mail ou lettre ;
- ajouter Inria, CEA, Academic Positions ou autres sources.

## Risques et mitigations

| Risque | Impact | Mitigation |
| --- | --- | --- |
| Conditions ANRT incompatibles avec scraping | Blocage produit | Mode manuel : snapshots/export utilisateur puis parsing local |
| Session expirée | Faux crawl vide | `anrt-session-check`, code erreur clair, statut run |
| Pagination incomplète | Faux négatifs | Comparaison compteur UI, tests pagination, limite de sécurité |
| HTML dynamique | Parser incomplet | Audit endpoint JSON, fallback Playwright |
| Données sensibles dans fixtures | Fuite Git | Anonymisation obligatoire, review `git diff` avant commit |
| Mot "IA" marketing | Faux positifs | Signaux négatifs + bucket `exclude` |
| Sujet ML caché dans description | Faux négatif | Parsing détail complet + lexique bio/ARN/protéines + LLM cas ambigus |
| Dédup entreprise/labo difficile | Doublons digest | Clé source/référence + similarité titre/labo si besoin |
| Régression CNRS | Perte du produit existant | Tests/evals CNRS lancés à chaque changement classifier |
| Coût LLM inutile | Pipeline lent/cher | Règles d'abord, LLM seulement sur cas ambigus, cache hash |

## Ordre recommandé des prochaines itérations

1. Audit réel ANRT connecté et conformité.
2. Stabilisation session réelle.
3. Capture locale de 10 à 20 pages réelles hors Git.
4. Anonymisation de 4 à 6 fixtures réelles représentatives.
5. Adaptation parser détail.
6. Expansion dataset ANRT à 20+ cas synthétiques.
7. Ajout de cas réels anonymisés au dataset.
8. Crawl réel limité entreprise/laboratoire.
9. Digest réel ANRT + CNRS.
10. Automatisation locale uniquement si tout ce qui précède est stable.

## Commandes de validation attendues

```bash
uv run ruff check .
uv run pytest -q
uv run cnrs-jobs eval
uv run cnrs-jobs eval --source anrt
uv run cnrs-jobs crawl --source anrt --anrt-fixture-dir tests/fixtures/anrt \
  --db /tmp/anrt_fixture.sqlite \
  --raw-dir /tmp/anrt_fixture_raw \
  --no-cache
uv run cnrs-jobs audit --db /tmp/anrt_fixture.sqlite --source anrt
```

Avec session réelle disponible :

```bash
uv run cnrs-jobs anrt-session-check \
  --anrt-session-file data/auth/anrt-cookies.json \
  --raw-dir data/raw \
  --no-cache

uv run cnrs-jobs crawl \
  --source anrt \
  --anrt-kind both \
  --anrt-session-file data/auth/anrt-cookies.json \
  --limit-offers 20 \
  --db /tmp/anrt_real_smoke.sqlite \
  --raw-dir /tmp/anrt_real_smoke_raw \
  --no-cache
```

## Définition de "prêt pour usage réel"

ANRT est considéré utilisable au quotidien seulement si :

- l'accès est conforme ;
- le crawler découvre les deux listes ;
- la pagination est vérifiée ;
- au moins 20 offres réelles ont été parsées sans adaptation manuelle ;
- les offres IA/ML évidentes sont captées ;
- les cas bio/ARN/protéines avec deep learning sont captés ;
- les faux positifs institutionnels sont exclus ou mis en revue ;
- le digest final est actionnable ;
- les tests et évaluations passent ;
- les secrets et snapshots sensibles restent hors Git.

## Recommandation finale

Faire ANRT, oui, mais comme une extension structurante du produit. Le premier succès ne doit pas être
"le scraper ne plante pas", mais :

```txt
Je peux lancer un crawl ANRT limité, obtenir une shortlist CIFRE IA/ML lisible,
voir les offres ambiguës en revue, et transformer chaque erreur en test de non-régression.
```

C'est cette boucle qui fera du projet un veilleur de thèses fiable, pas seulement une collection de
scrapers.
