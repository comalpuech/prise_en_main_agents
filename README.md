# Analyste multi-agents et serveur MCP

Mini-projet LangChain / LangGraph : une demande produit une note Markdown à partir
d'actualités Google News / Yahoo Finance et de cours Yahoo Finance réels.

`START → parse_request → [news_agent, market_data_agent] → writer_agent → END`

Le rédacteur attend les deux branches. Chaque agent ne retourne que sa sortie :
`news`, `metrics` ou `report`. Le serveur MCP fonctionne séparément du pipeline.

## Installation et configuration

Python 3.12+ et uv sont nécessaires. Depuis la racine du dépôt :

```powershell
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Renseigner localement `GOOGLE_API_KEY` dans `.env` avec une clé Google AI Studio.
Ne jamais versionner ce fichier. `.env.example` ne contient aucune clé réelle.

La priorité de configuration commune aux trois agents est :

1. `LLM_MODEL` explicite, au format `google_genai:<modele>` (ou un autre fournisseur installé).
2. `GOOGLE_MODEL`, nom simple ou déjà préfixé par `google_genai:`.
3. Défaut conservé : `google_genai:gemini-2.5-flash`.

Choisir dans `.env` un modèle accessible à votre compte si le défaut renvoie 404.
Les variables déjà exportées dans le processus priment sur `.env`. Redémarrer le
processus après changement : les paramètres et certains agents sont mis en cache.
Les appels LLM sont limités à 30 secondes avec jusqu'à 4 tentatives au total en cas d'erreur
fournisseur passagère (503, 429) ; réglable via `LLM_TIMEOUT_S` et `LLM_MAX_RETRIES`.

## Lancer le pipeline

```powershell
uv run --locked market-analyst "Fais-moi un point sur Nvidia cette semaine"
uv run --locked market-analyst --ticker AAPL --days 14
uv run --locked market-analyst "Point sur BTC-USD sur 7 jours"
```

Avec le venv Windows existant :

```powershell
.\.venv\Scripts\python.exe -m market_analyst.main "Fais-moi un point sur Nvidia cette semaine"
.\.venv\Scripts\python.exe -m market_analyst.agents.market_data_agent NVDA 7
```

La demande est interprétée par le LLM (sortie structurée `ParsedRequest`) :
n'importe quelle entreprise, crypto ou indice (« point sur Apple ce mois-ci »,
« et LVMH ? », « le Bitcoin sur 2 semaines ») est traduite en symbole Yahoo
(`AAPL`, `MC.PA`, `BTC-USD`) et en durée en jours (« ce mois » = 30). Python
valide ensuite le format du symbole et la durée (1 à 3650 jours). `--ticker` et
`--days` sont prioritaires sur l'interprétation ; avec `--ticker` seul, aucun
appel LLM n'est fait. Une demande multi-actifs, sans actif ou ambiguë est refusée.
Le symbole n'est pas vérifié auprès de Yahoo avant la collecte : un symbole
inexistant donne des indicateurs vides, signalés dans la note.

« Cette semaine » signifie les 7 derniers jours calendaires, pas la semaine civile.
Sans durée : 7 jours par défaut configurable.

## Données et garanties du rapport

- Agent 1 : collecte, filtre et déduplique les sources ; Gemini sélectionne et
  synthétise les actualités. Les URL absentes des résultats d'outil sont écartées.
- Agent 2 : LangChain appelle `get_market_metrics`. Les calculs viennent uniquement
  de Python/pandas ; le texte du LLM ne fournit jamais les métriques finales.
- Agent 3 : Gemini rédige la note à partir des actualités et des indicateurs mis
  en forme par Python (2 décimales), en adaptant sa longueur et ses points aux
  données. Contrôle automatique : chaque nombre de la note doit figurer dans les
  données ; sinon une seconde rédaction est demandée, puis la note est publiée avec
  un avertissement listant les nombres non vérifiés. Sans aucune donnée, une note
  minimale est produite sans LLM. La qualité factuelle des synthèses de l'Agent 1
  reste dépendante des sources et du LLM.

Les clôtures sont ajustées des dividendes et opérations sur titres. Le jour UTC
courant est exclu. Le rendement `weekly_return_pct` vaut
`(dernière / première clôture disponible dans la période - 1) * 100`.
Les SMA utilisent 5 et 20 séances complètes ; au moins 60 jours sont téléchargés.
La volatilité vaut `std(rendements journaliers, ddof=1) * sqrt(252) * 100`, en
pourcentage, y compris pour les cryptos. La devise n'est pas déduite du ticker.

Les métriques impossibles à calculer sont absentes, jamais remplacées par zéro.
Yahoo indisponible ou historique vide : `metrics={}` et avertissement dans les logs.
Une source d'actualités indisponible est ignorée ; sans actualités, le rapport le
signale. Une erreur LLM interrompt le pipeline sans publier de rapport partiel :
la CLI termine avec le code 1 et un message sans détails sensibles du fournisseur.
L'API Python conserve la cause de l'exception pour le diagnostic local.

## Mémoire de l'agent de news

L'Agent 1 garde d'une exécution à l'autre les articles riches (résumé Yahoo, texte
lu) et les synthèses déjà écrites, dans un `LangGraph Store` (`SqliteStore`) passé
au graphe à la compilation. Relancé chaque jour, il dispose d'articles avec texte
sur toute la période et ne re-synthétise pas un article déjà traité.

Le fichier est `data/memory.db`, relatif au dossier courant et ignoré par git.
On le règle avec `MEMORY_STORE_PATH` (`:memory:` pour une mémoire jetable) et
`MEMORY_TTL_DAYS` (30 par défaut). Les tests utilisent toujours une mémoire jetable.
Détails : section « Mémoire de l'agent de news » de
[docs/architecture.md](docs/architecture.md).

## Serveur MCP indépendant

```powershell
uv run --locked market-mcp
uv run --locked mcp dev src/market_mcp/server.py
```

Le serveur est un package distinct, `src/market_mcp`, et non un outil du
workflow agentique : il n'importe ni le graphe ni les agents de `market_analyst`.
Il réutilise seulement la collecte d'actualités (`market_analyst.tools.news`) et
le prompt du rédacteur. `uv run --locked python -m market_mcp` fonctionne aussi.

Le serveur utilise stdio : il attend un client MCP ; stdout est réservé au
protocole et les logs sont envoyés sur stderr. Le deuxième lancement ouvre
l'inspecteur de développement (nécessite l'environnement Node de l'inspecteur).

Outils conservés : `ping`, `get_news`, `get_price_summary`. Ressource :
`prompt://writer`. Prompt : `weekly_note`.
`get_price_summary` reste un résumé de cours simple ; il ne remplace pas les
SMA et la volatilité de l'Agent 2. Aucun routage des agents par MCP n'est requis.

## Tests et contrôles

```powershell
uv run --locked pytest -q
uv run --locked pytest tests/test_graph.py tests/test_writer_agent.py tests/test_main.py -q
uv run --locked pytest tests/test_market_mcp.py -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
uv pip check
```

Les tests sont hors ligne : Yahoo et les modèles sont mockés. Ils couvrent les
calculs, le tool calling LangChain, les erreurs, le contrat d'état, le fan-out/fan-in,
la CLI et un vrai sous-processus MCP stdio. Ce dernier exige l'autorisation système
de créer un processus et des pipes ; un bac à sable restrictif peut le bloquer.
Les tests réels Gemini/Yahoo sont manuels et dépendent du réseau et des quotas.

Voir [docs/architecture.md](docs/architecture.md) pour les contrats et les limites.
