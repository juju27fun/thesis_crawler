# Plan large - Extension ANRT/CIFRE

Date : 2026-07-07
Statut : plan d'architecture et d'implémentation future

## Objectif

Transformer le veilleur CNRS actuel en veilleur multi-source de thèses IA/ML, avec une nouvelle
source ANRT/CIFRE couvrant les offres proposées par :

- les entreprises ;
- les laboratoires.

Le résultat attendu n'est pas un scraper opportuniste, mais un pipeline robuste capable de produire
une shortlist exploitable de sujets CIFRE liés à l'IA, machine learning, deep learning, IA
générative, NLP, vision, MLOps et data science.

## Contexte produit

Le site ANRT/CIFRE est pertinent parce qu'il concentre des offres de thèse appliquées et
partenariales. La page publique indique explicitement que les entreprises et les laboratoires
proposent leurs offres de thèse sur la plateforme, et que les étudiants peuvent y mettre en ligne
leur candidature.

Différence majeure avec CNRS : les pages d'offres ciblées sont sous `/espace-membre/` et redirigent
vers une page de déconnexion lorsque l'on n'est pas authentifié. Cette source doit donc être traitée
comme une source authentifiée, pas comme une source publique équivalente au sitemap CNRS.

## Décision d'architecture

Recommandation : ajouter ANRT comme source de premier niveau dans le même produit, tout en
généralisant le coeur du projet.

Ne pas créer un second projet séparé au départ. Le repo contient déjà :

- un modèle `JobOffer` avec `source` et `source_specific` ;
- une interface `SourceAdapter` ;
- un stockage SQLite ;
- une classification IA/ML centralisée ;
- des exports Markdown/CSV ;
- des jeux d'évaluation.

Ces briques sont réutilisables. En revanche, le CLI, les chemins par défaut, certains noms et les
smokes restent encore très CNRS. L'extension ANRT doit donc servir de déclencheur pour faire évoluer
le projet vers un vrai `thesis-job-watcher` multi-source.

## Principes directeurs

- Le crawler/parser reste source de vérité sur l'existence et le contenu d'une offre.
- L'IA ne navigue pas sur ANRT et ne décide jamais qu'une offre existe.
- L'accès authentifié doit être explicite, local et non commité.
- Aucun secret, cookie, identifiant ou snapshot privé sensible ne doit entrer dans Git.
- Le pipeline doit pouvoir fonctionner en mode CNRS public sans dépendre d'ANRT.
- ANRT doit avoir ses propres fixtures, tests de parsing et limites de taux.
- Les offres CNRS et ANRT doivent converger vers le même modèle normalisé.
- Les champs propres à ANRT restent dans `source_specific` tant qu'ils ne sont pas communs.
- Les exports doivent afficher la provenance et le type d'origine : CNRS, ANRT entreprise, ANRT laboratoire.
- Toute automatisation ANRT doit être précédée d'un contrôle des conditions d'utilisation.

## Risques structurants

| Risque | Impact | Mitigation |
| --- | --- | --- |
| Accès authentifié obligatoire | Crawl impossible en HTTP simple | Session navigateur Playwright ou session exportée localement |
| Conditions d'utilisation restrictives | Automatisation non conforme | Lire les règles ANRT avant mode planifié |
| HTML dynamique | Parser HTTP insuffisant | Découverte endpoint JSON, sinon Playwright contrôlé |
| Données personnelles dans offres/messages | Risque de stockage sensible | Ne stocker que les offres, filtrer contacts si nécessaire |
| Expiration de session | Runs instables | Détection `logged_out`, erreur claire, renouvellement manuel |
| Pagination masquée | Faux négatifs | Audit volumétrique et comparaison compteurs UI |
| Search keyword insuffisant | Offres IA ratées | Classifieur sémantique après extraction complète |
| Modèle CNRS trop spécifique | Dette produit | Introduire couche `SourceRegistry` et commandes génériques |

## Phase 0 - Cadrage légal, accès et observation

### But

Savoir ce qu'il est acceptable et techniquement possible d'automatiser avant d'écrire le crawler.

### Actions

- Lire les mentions légales, politique de confidentialité et conditions d'utilisation de la
  plateforme ANRT/CIFRE.
- Vérifier si un étudiant peut consulter librement toutes les offres après création de compte.
- Vérifier si le site interdit explicitement l'extraction automatisée.
- Documenter la nature des pages :
  - liste entreprise ;
  - liste laboratoire ;
  - page détail offre ;
  - filtres ;
  - pagination ;
  - recherche texte éventuelle.
- Observer une session connectée localement :
  - HTML serveur ou app JS ;
  - endpoints JSON ;
  - paramètres de pagination ;
  - identifiants stables d'offres ;
  - présence de token CSRF.
- Capturer deux ou trois snapshots HTML anonymisés pour fixture, uniquement si le contenu ne contient
  pas d'information sensible non nécessaire.

### Livrables

- `docs/anrt_access_audit_YYYY-MM-DD.md`
- conclusion claire : `http_session_possible`, `playwright_required`, `manual_export_only`, ou `blocked`.

### Critères d'acceptation

- On sait si l'automatisation est conforme.
- On sait si le crawler peut utiliser `httpx` ou doit utiliser Playwright/Botasaurus.
- Le mode d'authentification choisi ne met aucun secret dans le repo.

## Phase 1 - Généralisation du produit multi-source

### But

Éviter d'ajouter ANRT par duplication de logique CNRS.

### Actions

- Renommer mentalement le produit vers `thesis watcher`, sans forcément renommer le package tout de
  suite.
- Introduire une option CLI :
  - `--source cnrs`
  - `--source anrt`
  - `--source all`
- Ajouter une option ANRT :
  - `--anrt-kind entreprise`
  - `--anrt-kind laboratoire`
  - `--anrt-kind both`
- Préparer des chemins par défaut non CNRS-spécifiques :
  - `data/thesis_jobs.sqlite` à terme ;
  - garder `data/cnrs_jobs.sqlite` compatible pendant la transition.
- Ajouter une `SourceRegistry` :
  - résout la source demandée ;
  - instancie l'adapter ;
  - fournit les valeurs de `source`, `source_kind`, `display_name`.
- Faire évoluer `SourceAdapter` si besoin :
  - `discover_urls()`;
  - `fetch_detail()`;
  - `parse_detail()`;
  - éventuellement `login_status()` pour sources authentifiées.

### Livrables

- CLI capable de sélectionner une source, même si ANRT n'est au départ qu'un stub.
- Tests unitaires du registry.

### Critères d'acceptation

- `cnrs-jobs crawl --source cnrs` conserve le comportement actuel.
- Une source inconnue donne une erreur claire.
- Aucun test CNRS ne régresse.

## Phase 2 - Modèle de données ANRT

### But

Faire converger ANRT vers `JobOffer` sans perdre les détails CIFRE utiles.

### Champs normalisés

- `source`: `anrt`
- `url`
- `reference`
- `title`
- `contract_type`: `CIFRE` ou équivalent
- `duration`: souvent 36 mois si explicitement indiqué
- `education_level`: master/BAC+5 si mentionné
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

### Champs spécifiques ANRT

À placer dans `source_specific` :

- `anrt_kind`: `entreprise` ou `laboratoire`
- `company_name`
- `laboratory_name`
- `sector`
- `discipline`
- `doctoral_school`
- `partner_expected`
- `application_deadline`
- `contact_visible`
- `remote_or_hybrid`
- `funding_status`
- `cifre_status`

### Actions

- Identifier les champs réellement présents dans l'UI ANRT.
- Mapper seulement les champs fiables.
- Ne pas inventer de données absentes.
- Ajouter des tests Pydantic sur les cas incomplets.

### Critères d'acceptation

- Une offre ANRT partiellement remplie peut être stockée sans échec.
- Les champs propres ANRT ne polluent pas le modèle commun.
- L'export affiche les champs utiles quand ils existent.

## Phase 3 - Authentification et gestion de session

### But

Permettre un crawl local sans stocker de secrets dans le repo.

### Options

Option A - Session navigateur Playwright persistante

- L'utilisateur se connecte une fois dans un profil local.
- Le crawler réutilise le `storage_state`.
- Avantage : robuste pour site dynamique.
- Risque : dépendance navigateur, session expirée.

Option B - Cookies exportés localement

- Le crawler `httpx` reçoit un cookie jar hors repo.
- Avantage : rapide et testable.
- Risque : fragile si JS/CSRF/pagination dynamique.

Option C - Export manuel assisté

- L'utilisateur exporte ou sauvegarde les pages.
- Le pipeline parse/classifie localement.
- Avantage : conformité maximale.
- Risque : moins automatisé.

### Recommandation

Commencer par une exploration Playwright locale pour comprendre le site. Si un endpoint JSON propre
apparaît, basculer le runtime vers `httpx` avec session. Sinon, garder Playwright pour ANRT.

### Actions

- Ajouter `.gitignore` pour :
  - `data/auth/`
  - `data/anrt_session/`
  - `playwright/.auth/`
- Ajouter une commande future :
  - `cnrs-jobs anrt-login`
  - ou `cnrs-jobs auth anrt`
- Détecter explicitement les pages logout/login.
- Échouer avec message clair si la session n'est plus valide.

### Critères d'acceptation

- Un run sans session échoue proprement, sans faux succès à zéro offre.
- Un run avec session valide atteint la page liste.
- Les cookies/session ne sont jamais trackés.

## Phase 4 - Discovery ANRT

### But

Découvrir exhaustivement les URLs d'offres entreprise et laboratoire.

### Actions

- Implémenter `AnrtSourceAdapter.discover_urls(kind=...)`.
- Gérer :
  - pagination ;
  - filtres ;
  - tri date ;
  - offres masquées/expirées ;
  - déduplication entreprise/laboratoire.
- Stocker un compteur d'audit :
  - nombre d'offres vues dans l'UI ;
  - nombre d'URLs extraites ;
  - nombre de détails fetchés ;
  - nombre d'erreurs.
- Ajouter une limite volontaire :
  - délai entre requêtes ;
  - retries sobres ;
  - arrêt si taux d'erreur élevé.

### Critères d'acceptation

- `--anrt-kind entreprise` découvre toutes les offres visibles du compte.
- `--anrt-kind laboratoire` découvre toutes les offres visibles du compte.
- `--anrt-kind both` déduplique correctement.
- Le run indique clairement combien d'offres ont été découvertes.

## Phase 5 - Fetch et snapshots

### But

Rendre le debugging possible sans refaire un crawl ANRT à chaque modification.

### Actions

- Stocker les payloads bruts dans :
  - `data/raw/anrt/list/...`
  - `data/raw/anrt/detail/...`
- Hacher chaque payload.
- Si le contenu contient des informations de contact personnelles, prévoir un mode fixture anonymisé.
- Séparer :
  - snapshots runtime locaux ;
  - fixtures de test commitées et anonymisées.

### Critères d'acceptation

- Un bug parser peut être reproduit depuis fixture.
- Les snapshots locaux restent hors Git.
- Les fixtures commitées ne contiennent pas d'identifiants de session ni données sensibles inutiles.

## Phase 6 - Parsing ANRT

### But

Extraire les offres en champs structurés de façon testable.

### Actions

- Créer `src/cnrs_job_watcher/anrt/parse.py`.
- Ajouter des parseurs séparés :
  - `parse_anrt_list_page`
  - `parse_anrt_offer_detail`
  - éventuellement `parse_anrt_json_offer`
- Écrire les tests avant de stabiliser les sélecteurs.
- Extraire au minimum :
  - titre ;
  - organisation ;
  - type entreprise/laboratoire ;
  - localisation ;
  - résumé ;
  - description ;
  - compétences ou profil ;
  - lien détail ;
  - référence/id.
- Détecter les états :
  - session expirée ;
  - offre indisponible ;
  - aucune offre ;
  - erreur serveur.

### Critères d'acceptation

- Le parser passe sur au moins une fixture entreprise et une fixture laboratoire.
- Les champs vides ne provoquent pas d'échec s'ils sont optionnels.
- Une page logout n'est jamais parsée comme une offre.

## Phase 7 - Classification IA/ML adaptée CIFRE

### But

Réutiliser le classifieur commun tout en tenant compte de la nature CIFRE.

### Différences avec CNRS

- Toutes les offres sont a priori des sujets de thèse ou partenariats de thèse.
- Le hard filter contrat/niveau est donc moins discriminant.
- La vraie difficulté est la pertinence technique IA/ML.
- Les offres peuvent être formulées côté entreprise avec jargon métier et peu de mots académiques.

### Actions

- Ajouter des signaux CIFRE :
  - `CIFRE`, `doctorant`, `thèse`, `partenariat`, `laboratoire`, `R&D`.
- Élargir le vocabulaire IA/ML :
  - apprentissage automatique ;
  - apprentissage profond ;
  - modèle prédictif ;
  - modèles génératifs ;
  - grands modèles de langage ;
  - vision par ordinateur ;
  - traitement automatique du langage ;
  - apprentissage par renforcement ;
  - jumeau numérique avec ML ;
  - optimisation bayésienne ;
  - graph neural networks ;
  - bioinformatique ML ;
  - chemoinformatique ;
  - séries temporelles ;
  - détection d'anomalies.
- Ajouter des exclusions :
  - simple transformation numérique ;
  - logiciel sans composant IA ;
  - statistiques descriptives uniquement ;
  - data engineering sans apprentissage ;
  - usage marketing du mot IA.
- Adapter le prompt LLM pour source ANRT :
  - demander si le sujet implique réellement des méthodes IA/ML ;
  - distinguer recherche IA centrale vs IA outil secondaire ;
  - demander une justification courte orientée candidat.

### Critères d'acceptation

- Le classifieur ne garde pas une offre qui mentionne vaguement "innovation numérique".
- Il garde une offre ML même si le titre ne contient pas "machine learning".
- Les exports peuvent grouper `anrt` avec `primary_target` par défaut si le sujet est IA/ML fort.

## Phase 8 - Export multi-source

### But

Produire un digest vraiment utile pour choisir où candidater.

### Actions

- Ajouter une colonne `Source`.
- Ajouter une colonne `Origine` :
  - `CNRS`
  - `ANRT entreprise`
  - `ANRT laboratoire`
- Ajouter les champs spécifiques quand disponibles :
  - entreprise ;
  - laboratoire ;
  - secteur ;
  - date limite ;
  - localisation.
- Grouper par :
  - très pertinent ;
  - pertinent ;
  - à relire ;
  - exclusions notables si demandé.
- Ajouter un score et une raison orientée décision :
  - "Sujet ML central"
  - "IA appliquée mais niveau technique à vérifier"
  - "Mention IA vague"

### Critères d'acceptation

- Un digest combine CNRS + ANRT sans mélanger les provenances.
- Une offre ANRT a assez de contexte pour décider de cliquer.
- Le CSV reste exploitable dans tableur.

## Phase 9 - Stockage et historique

### But

Suivre les nouvelles offres, les changements et les disparitions.

### Actions

- Vérifier que `offers.source + reference/url` forment une clé fiable.
- Ajouter si nécessaire :
  - `source_kind`
  - `external_id`
  - `last_seen_status`
- Garder l'historique des snapshots par hash.
- Détecter :
  - nouvelle offre ;
  - offre modifiée ;
  - offre disparue ;
  - score modifié après reclassification.

### Critères d'acceptation

- Le digest quotidien peut afficher seulement les nouvelles offres ANRT.
- Une modification de description déclenche une nouvelle classification.
- Les anciennes offres ne disparaissent pas silencieusement de l'historique.

## Phase 10 - Évaluation et QA

### But

Éviter le même type de faux négatif que celui observé sur CNRS avec ARN/protéines.

### Actions

- Créer un dataset annoté ANRT :
  - minimum 20 offres ;
  - positives évidentes ;
  - positives sans mots-clés directs ;
  - IA vague ;
  - data science adjacent ;
  - hors cible.
- Ajouter une commande :
  - `cnrs-jobs eval --source anrt`
  - ou `cnrs-jobs eval --dataset tests/fixtures/evaluation/anrt_offers.json`
- Suivre :
  - rappel sur offres IA/ML ;
  - précision des `primary_target`;
  - nombre de `adjacent_review`;
  - raisons d'exclusion.

### Critères d'acceptation

- Une offre IA biomédicale/protéines/ARN ne peut pas être ratée si ses signaux existent dans le détail.
- Les faux positifs institutionnels restent exclus.
- Chaque bug de classification observé devient un cas d'évaluation.

## Phase 11 - Automatisation locale

### But

Passer d'un run manuel à une veille quotidienne fiable.

### Actions

- Garder CNRS automatisable sans auth.
- Pour ANRT, choisir selon conformité :
  - automatisation locale avec session persistante ;
  - rappel manuel de renouvellement session ;
  - mode semi-automatique.
- Ajouter des sorties :
  - Markdown local ;
  - CSV ;
  - digest quotidien ;
  - option notification plus tard.
- Ne pas automatiser en cloud une session personnelle ANRT sans décision explicite.

### Critères d'acceptation

- Le run quotidien ne casse pas si ANRT est déconnecté : CNRS continue.
- Le digest signale clairement "ANRT non exécuté : session expirée".
- Les erreurs ANRT ne polluent pas les résultats CNRS.

## Phase 12 - Renommage et packaging éventuel

### But

Aligner le nom du produit avec sa réalité multi-source.

### Options

- Garder `cnrs_job_watcher` en interne jusqu'à stabilisation ANRT.
- Renommer plus tard vers `thesis_job_watcher`.
- Exposer une commande alias :
  - `cnrs-jobs` pour compatibilité ;
  - `thesis-jobs` comme nouveau nom.

### Recommandation

Ne pas renommer maintenant. Ajouter ANRT d'abord, puis renommer quand deux sources fonctionnent et
que les tests protègent le comportement.

## Découpage recommandé en tickets

### Lot A - Audit ANRT

- Inspecter accès connecté.
- Identifier endpoints/pagination.
- Documenter conformité.
- Produire deux fixtures anonymisées.

### Lot B - Multi-source CLI

- Ajouter `--source`.
- Ajouter registry.
- Préserver CNRS.
- Tests registry.

### Lot C - Stub ANRT

- Créer package `anrt`.
- Adapter vide ou fixture-based.
- Tests de parse sur fixtures.

### Lot D - Session ANRT

- Choisir Playwright ou HTTP session.
- Ajouter stockage session hors Git.
- Détection session expirée.

### Lot E - Discovery entreprise/laboratoire

- Extraire URLs.
- Gérer pagination.
- Dédoublonner.
- Audit volumes.

### Lot F - Detail parser

- Parser pages détail.
- Mapper `JobOffer`.
- Tests entreprise/laboratoire.

### Lot G - Classification CIFRE

- Étendre signaux IA/ML.
- Ajouter dataset ANRT.
- Adapter prompt LLM.

### Lot H - Export multi-source

- Ajouter provenance.
- Afficher champs ANRT.
- Digest combiné.

### Lot I - Automatisation contrôlée

- Daily run local.
- Gestion session expirée.
- Alertes/digest.

## Commandes cibles

```bash
uv run cnrs-jobs crawl --source cnrs
uv run cnrs-jobs crawl --source anrt --anrt-kind entreprise
uv run cnrs-jobs crawl --source anrt --anrt-kind laboratoire
uv run cnrs-jobs crawl --source all --classifier hybrid

uv run cnrs-jobs export --source all --format markdown --output thesis_ia_jobs.md
uv run cnrs-jobs audit --source all
uv run cnrs-jobs eval --source anrt
```

## Définition du MVP ANRT

Le MVP ANRT est atteint quand :

- une session locale valide permet de découvrir les offres entreprise et laboratoire ;
- au moins 20 offres réelles peuvent être fetchées, parsées, stockées et exportées ;
- les offres IA/ML fortes apparaissent dans le digest ;
- les offres hors IA évidentes sont exclues ou envoyées en `adjacent_review` ;
- les tests couvrent au moins une offre entreprise, une offre laboratoire, une offre IA forte et une
  offre hors cible ;
- CNRS continue de fonctionner exactement comme avant.

## Ce qu'il ne faut pas faire

- Ne pas mettre login/mot de passe/cookies dans `.env` commité ou dans Git.
- Ne pas contourner de protection d'accès.
- Ne pas laisser un agent navigateur cliquer librement sans bornes.
- Ne pas mélanger parsing ANRT et parsing CNRS dans les mêmes fonctions.
- Ne pas créer une deuxième base incompatible si le modèle commun suffit.
- Ne pas faire dépendre CNRS d'une session ANRT.
- Ne pas lancer une automatisation cloud avec compte personnel sans décision explicite.

## Conclusion

L'extension ANRT/CIFRE est assez proche d'un nouveau projet parce qu'elle introduit l'authentification,
une nouvelle structure de données et une UX multi-source. Mais le bon choix est de l'intégrer comme
source majeure dans le watcher existant, car la classification, le stockage, l'évaluation et les
exports sont déjà des actifs réutilisables.

La première décision concrète n'est pas "Playwright ou httpx" : c'est l'audit d'accès. Une fois la
session observée, le reste peut être découpé en lots courts et testables.
