# Architecture

```
            ┌──────────────┐
  request → │ parse_request│
            └──────┬───────┘
          ┌────────┴────────┐
   ┌──────▼─────┐    ┌──────▼──────────┐
   │ news_agent │    │market_data_agent│   (parallèle)
   └──────┬─────┘    └──────┬──────────┘
          └────────┬────────┘
            ┌──────▼──────┐
            │ writer_agent│ → report (Markdown)
            └─────────────┘
```

| Nœud | Rôle | Écrit dans l'état |
|---|---|---|
| `parse_request` | ticker, entreprise, période | `ticker`, `company`, `lookback_days` |
| `news_agent` (Agent 1) | veille d'actualités | `news` |
| `market_data_agent` (Agent 2) | cours + indicateurs | `metrics` |
| `writer_agent` (Agent 3) | note d'analyse | `report` |

`build_graph()` utilise une arête de jonction explicite depuis la liste
`[news_agent, market_data_agent]` : le rédacteur s'exécute une fois, après les deux.
Les états renvoyés sont des mises à jour partielles, pas des copies de l'état entier.

## Interprétation et erreurs

`parse_request` confie l'interprétation au LLM (`with_structured_output(ParsedRequest)`,
prompt `prompts/parse_request.md`) : symbole Yahoo, nom usuel, durée en jours ou
champ `error`. Python valide le résultat (format du symbole, durée entière de 1 à
3650 jours) ; `error` ou une valeur invalide lèvent `RequestError`. Le ticker et la
durée explicites (CLI) priment ; sans demande textuelle, le LLM n'est pas appelé.
« Cette semaine » signifie 7 jours glissants. Sans durée, le défaut vient de la
configuration commune.

Les trois agents passent par `get_llm` : `LLM_MODEL` explicite prime sur
`GOOGLE_MODEL`, puis vient le défaut `google_genai:gemini-2.5-flash`.
Les appels LLM sont bornés à 30 secondes par requête, avec jusqu'à 4 tentatives au total
(`LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`, appliqués par `get_llm` à tous les agents) ; un agent
ReAct peut faire plusieurs requêtes. Une panne LLM arrête le pipeline. Les causes
Python sont conservées ; la CLI affiche un message générique sans texte brut du SDK.

Les outils de collecte dégradent leurs résultats en liste/dictionnaire vide avec
logs en cas de source indisponible. Le rédacteur doit traiter ces absences comme
des données manquantes, jamais comme une absence de risque ou une valeur nulle.

## Agent 2 — indicateurs déterministes

L'agent LangChain appelle `get_market_metrics` (retour direct), dont l'artefact
contient ticker, période et `MarketMetrics`. Le nœud vérifie l'identité de la
demande avant d'en extraire exclusivement `metrics` ; la prose LLM est ignorée.
Les calculs de la contribution Roman sont conservés : clôtures ajustées, période
calendaire hors journée UTC courante, rendement première/dernière clôture de la
période, SMA 5/20 séances et volatilité échantillonnale annualisée sur 252 séances.
Rendement et volatilité sont en pourcentage ; les trois autres valeurs sont dans
la devise de cotation, non déduite automatiquement. Les champs sont optionnels.

## Agent 3 — rédaction contrôlée

`build_writer` construit l'agent LangChain avec le prompt `prompts/writer.md`.
Le nœud transmet au LLM un JSON de données : actualités (titre, source, date,
synthèse), indicateurs formatés par Python à 2 décimales et liste des indicateurs
indisponibles. Le LLM rédige la note Markdown en adaptant sa longueur aux données.

Garde-fou : les nombres de la note sont comparés (après normalisation : « 04 » = « 4 »,
« 5,13 » = « 5.13 ») à ceux des données fournies. Un nombre inconnu déclenche une
seconde rédaction avec la liste des nombres en cause ; s'il en reste, la note est
publiée suivie d'un avertissement « Contrôle automatique ». Ce contrôle ne vérifie
que les chiffres, pas les affirmations qualitatives. Sans actualités ni indicateurs,
une note minimale est produite sans appel LLM. Les synthèses de l'Agent 1 restent
soumises à la fiabilité des sources : le pipeline n'est pas un système de
vérification indépendante des faits.

## MCP — exécution séparée

Le package `market_mcp` (`src/market_mcp/server.py`) est séparé de
`market_analyst` : c'est un serveur stdio autonome, pas un outil du graphe. Il ne
dépend que de la collecte d'actualités et du prompt du rédacteur. Il expose les outils
`ping`, `get_news`, `get_price_summary`, la ressource `prompt://writer` et le prompt
`weekly_note`. Le pipeline n'utilise pas MCP pour cette version. En particulier,
le résumé de cours MCP ne remplace pas l'outil financier plus complet de l'Agent 2.
Un test lance un client et un serveur réels en sous-processus stdio, sans réseau.


## Agent 1 — veille d'actualités

`agents/news_agent.py` est un agent ReAct (`langchain.agents.create_agent`) qui appelle l'outil
`search_news` (`tools/news.py`) puis renvoie une sortie structurée (`NewsDigest`) convertie en
`list[NewsItem]`. Prompt : `prompts/news.md`.

Sources, sans clé d'API :

| Source | Couverture | Contenu |
|---|---|---|
| Google News RSS | toute la période (`when:<n>d`) | titre, média, lien |
| Yahoo Finance (`yfinance`) | quelques heures seulement | titre, média, lien, résumé ; filtré sur les articles taggés avec le ticker **et** dont le titre ou le résumé cite le nom ou le symbole |

Le filtrage par date, la déduplication (URL ou titre) et le plafond de 30 articles sont faits en
Python avant que le LLM ne voie quoi que ce soit. Jusqu'à la moitié du plafond est réservée à
Yahoo (seule source avec résumé) ; le reste est réparti jour par jour sur la période.

Les articles Yahoo retenus sont ensuite **lus** : leur copie hébergée sur finance.yahoo.com est
récupérée en parallèle et le texte extrait avec `trafilatura`, tronqué à ~6 000 caractères (≈ l'article entier)
(champ `content`, visible par l'agent mais absent de l'état du graphe). On cite toujours l'URL du
média d'origine. Une page en échec ou trop courte (vidéo) garde simplement le résumé Yahoo.
Les liens Google News ne sont pas lisibles (redirection en JavaScript) : ces articles restent
résumés à partir du titre.

Le champ `summary` est une **synthèse**, pas un résumé : elle garde tous les chiffres, acteurs,
dates, causes et conclusions de l'article, sans formules du type « l'article évalue… ». Sa
longueur suit la densité d'information de l'article (cf. `prompts/news.md`). L'agent en
retient 5 à 10 et les résume en français. Toute URL absente des résultats de l'outil est écartée.

Le nœud ne renvoie que la clé `news` : il tourne en parallèle de `market_data_agent`, et deux
écritures concurrentes d'une même clé sans reducer feraient échouer le fan-in.

## Mémoire de l'agent de news

La mémoire est construite par étapes, en s'appuyant sur les briques de LangChain / LangGraph
plutôt que sur un mécanisme maison :

| Étape | Mémoire | Brique du framework | État |
|---|---|---|---|
| 1 | Articles sources gardés d'une exécution à l'autre | `LangGraph Store` (`SqliteStore`) | fait |
| 2a | Synthèses déjà écrites, réutilisées | Store + middleware `after_agent` | fait |
| 2b | Fiche du dernier point (« depuis le dernier point… ») | Store, middleware ou LangMem | reportée à l'agent rédacteur |
| 3 | Recherche sémantique | Store + embeddings | à faire |
| 4 | Mémoire court terme (`thread_id`) | checkpointer LangGraph | à faire |

### Le Store et son injection (`memory/store.py`)

Le `LangGraph Store` est une base clé-valeur partagée entre toutes les exécutions, rangée par
namespaces (tuples). `build_store()` crée un `SqliteStore` sur `MEMORY_STORE_PATH`
(`data/memory.db` par défaut, relatif au dossier courant, ignoré par git). On passe
explicitement `":memory:"` pour une mémoire jetable, comme dans les tests. Il n'y a pas de repli
silencieux : la valeur ne peut pas être vide.

Le Store est créé **une seule fois, à la racine** : `build_graph()` compile le graphe avec
`compile(store=build_store())` (on peut lui passer un autre Store, `build_graph(store=...)`).
LangGraph l'injecte ensuite partout, y compris dans l'agent `create_agent` lancé depuis le nœud
`news_agent` : `runtime.store` dans les nœuds et les middlewares, `ToolRuntime.store` dans les
outils. Sans Store, l'outil et le middleware échouent avec un message clair au lieu de tourner
sans mémoire.

Le ticker arrive de la même façon, par le **contexte d'exécution** :
`agent.invoke(..., context=NewsContext(ticker=...))`. C'est le code qui le fixe, pas le LLM :
l'outil `search_news` ne prend plus de paramètre `ticker`.

- **Durée de vie** : chaque élément expire `MEMORY_TTL_DAYS` jours (30 par défaut) après sa
  dernière écriture, et non après sa date de publication. Un article revu est donc prolongé.
  La purge (`sweep_ttl()`) a lieu à chaque `build_store()`. La fenêtre de dates des articles,
  elle, vient du filtre de recherche.
- **Pièges rencontrés** :
  - `store.search` renvoie 10 éléments par défaut, il faut passer un `limit` explicite.
  - `InMemoryStore` ne sait pas filtrer une plage de dates écrites en texte (il convertit en
    float), d'où un `SqliteStore` même pour la mémoire jetable.
  - `put` remplace toute la valeur, d'où la séquence get → fusion → put pour ne rien perdre.

### Étape 1 — articles sources (`memory/news_memory.py`)

Yahoo Finance ne remonte que les dernières heures. `search_news` garde donc les articles riches
(résumé Yahoo ou texte lu) dans le namespace `("news", <TICKER>, "articles")`, avec l'URL comme
clé, et les ressort aux appels suivants tant qu'ils sont dans la fenêtre demandée
(`filter={"published_at": {"$gte": ...}}`).

- **Pas de relecture** : un article qui a déjà un `content` n'est pas relu. Une page en échec est
  retentée au passage suivant.
- **Mise à jour sans perte** : un article revu ne perd jamais un résumé ou un texte déjà connu.
- **Priorité à la mémoire** : les articles connus partagent le quota de Yahoo et passent avant
  les articles frais en cas de doublon.
- **Pas d'articles Google News** (titre seul) : le flux RSS redonne toute la période à chaque
  appel.
- **Données sources uniquement** : les synthèses du LLM vivent dans un namespace à part.
- Sans ticker, il n'y a pas de mémoire (Yahoo n'est pas interrogé).

Un `sqlite3` brut aurait suffi pour ce cache, mais le Store fait la même chose avec moins de
code, et apporte en plus la purge (TTL) et une API commune avec les étapes suivantes.

### Étape 2a — synthèses réutilisées

- **Namespace `("news", <TICKER>, "syntheses")`**, clé = URL : la synthèse française de l'agent,
  son titre et sa date.
- **Lecture par l'outil** : un article déjà synthétisé arrive avec `known_summary` à la place de
  son `content`, ce qui économise des tokens.
- **Recopie et écriture par le code**, dans `SynthesisMemoryMiddleware.after_agent` :
  - l'agent laisse `summary` vide pour ces articles et le middleware y remet la synthèse gardée
    (quand on lui demandait de la recopier lui-même, le LLM la reformulait parfois) ;
  - le middleware retient ensuite toutes les synthèses.
  - Le middleware n'est pas une API de mémoire : c'est le point d'accroche que `create_agent`
    prévoit pour agir avant ou après l'agent, le modèle ou les outils.

Gain mesuré sur NVDA (Gemini 2.5 Flash, deux exécutions de suite à travers un graphe compilé
avec le Store) :

| | Tokens d'entrée | Tokens de sortie | Pages lues |
|---|---|---|---|
| Mémoire vide | ~20 000 | ~13 000 | 15 |
| 10 synthèses connues | ~14 400 | ~7 900 | 0 |

Les tokens de sortie varient beaucoup d'une exécution à l'autre, car ils sont dominés par le
raisonnement du modèle.

LangChain 1.4.9 émet un avertissement `PydanticSerializationUnexpectedValue` à chaque appel
d'agent qui utilise un `context_schema`. Il vient de la bibliothèque, pas du projet, et n'a pas
d'effet sur le résultat.
