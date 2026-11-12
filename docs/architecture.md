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

`parse_request` accepte le nom Nvidia (association explicite NVDA) ou un ticker
fourni par l'utilisateur ; il ne demande pas au LLM d'inventer un symbole.
Les demandes ambiguës ou contradictoires lèvent `RequestError`. La durée est
un entier positif de 1 à 3650 jours ; « cette semaine » signifie 7 jours glissants.
Sans autre durée, le défaut vient de la configuration commune.

Les trois agents passent par `get_llm` : `LLM_MODEL` explicite prime sur
`GOOGLE_MODEL`, puis vient le défaut `google_genai:gemini-2.5-flash`.
Les appels LLM sont bornés à 30 secondes par requête et une tentative ; un agent
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

## Agent 3 — sélection et assemblage sourcé

`build_writer` conserve l'agent LangChain et le prompt de Côme. Dans le pipeline,
le mode sélection demande uniquement des indices d'actualités (au plus trois).
Python valide ces indices puis construit la note avec des extraits de `news`
et le formatage des chiffres de `metrics`. Aucun fait ni chiffre de la prose
libre du rédacteur n'est publié. Une sélection invalide reprend les premières
actualités fournies et l'indique dans les limites. Sans actualités, aucun appel
LLM de sélection n'est nécessaire. Les synthèses de l'Agent 1 restent soumises
à la fiabilité des sources et de sa synthèse LLM : le pipeline n'est pas un
système de vérification indépendante des faits.

## MCP — exécution séparée

`mcp_server.py` conserve le serveur stdio de la branche MCP, avec les outils
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
