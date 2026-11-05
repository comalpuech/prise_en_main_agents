# Analyste boursier / crypto multi-agents

Système multi-agents LangChain / LangGraph (LLM : Gemini via Google AI Studio) qui produit une note d'analyse
hebdomadaire sur une action ou une crypto à partir de vraies données.

- **Agent 1** : veille d'actualités sur l'entreprise
- **Agent 2** : analyse des cours (moyennes mobiles, volatilité)
- **Agent 3** : rédaction de la note d'analyse

Tâche cible : « Fais-moi un point sur Nvidia cette semaine ».

> État : agents 1 et 2 implémentés ; agent 3 et câblage du graphe à faire.

## Installation

```bash
uv sync
cp .env.example .env   # renseigner GOOGLE_API_KEY (https://aistudio.google.com/apikey)
```

## Utilisation

```bash
uv run market-analyst "Fais-moi un point sur Nvidia cette semaine"
uv run pytest
uv run ruff check .
```

## Structure

```
src/market_analyst/
├── main.py          # CLI
├── config.py        # settings (.env)
├── llm.py           # fabrique du ChatModel
├── state.py         # état partagé du graphe
├── graph.py         # câblage LangGraph
├── agents/          # news_agent, market_data_agent, writer_agent
└── prompts/         # prompts système des agents
tests/
docs/architecture.md
```

Voir [docs/architecture.md](docs/architecture.md).

## Agent 2 seul

Après `uv sync`, renseigner `GOOGLE_API_KEY` dans `.env`, puis lancer depuis
la racine du dépôt (aucun câblage du graphe nécessaire) :

```bash
uv run python -m market_analyst.agents.market_data_agent NVDA 7
uv run pytest tests/test_market_data_agent.py
uv run ruff check .
uv run ruff format --check src/market_analyst/agents/market_data_agent.py src/market_analyst/tools/market.py tests/test_market_data_agent.py
```

Comme l'Agent 1, l'Agent 2 utilise `get_llm()` et la configuration commune
(`google_genai:gemini-2.5-flash` par défaut). Son agent LangChain appelle
`get_market_metrics`, puis le nœud retourne uniquement `{"metrics": ...}`,
extrait de l'artefact Python de l'outil, sans reprendre les chiffres du LLM.
Les artefacts d'un autre ticker ou d'une autre période sont écartés.

Les clôtures Yahoo Finance sont ajustées des dividendes et opérations sur titres.
La séance du jour UTC est exclue pour éviter un cours encore provisoire.
`weekly_return_pct` conserve le nom de l'interface commune mais mesure la période
demandée en jours calendaires : dernière clôture disponible / clôture à ou avant
le début de la période, moins 1, multiplié par 100. Les SMA utilisent les 5 et
20 dernières séances ; l'outil télécharge au moins 60 jours pour les calculer.
La volatilité utilise les rendements journaliers de la période, l'écart-type
échantillonnal (`ddof=1`) annualisé par racine de 252 (365 pour les symboles
`-USD`, convention adaptée ici aux cryptos). Elle est exprimée en fraction,
par exemple `0.3` pour 30 %.

Un historique insuffisant laisse les indicateurs concernés absents. Un ticker
inexistant, des données vides ou une erreur Yahoo produisent des métriques vides
avec un avertissement dans les logs. Un ticker vide ou une période non positive
lève `ValueError`. Les erreurs de configuration ou d'accès au LLM restent visibles.
Les tests remplacent Yahoo et le LLM et ne nécessitent aucune clé ni réseau.
