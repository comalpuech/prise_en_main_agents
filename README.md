# Analyste boursier / crypto multi-agents

Système multi-agents LangChain / LangGraph (LLM : Gemini via Google AI Studio) qui produit une note d'analyse
hebdomadaire sur une action ou une crypto à partir de vraies données.

- **Agent 1** : veille d'actualités sur l'entreprise
- **Agent 2** : analyse des cours (moyennes mobiles, volatilité)
- **Agent 3** : rédaction de la note d'analyse

Tâche cible : « Fais-moi un point sur Nvidia cette semaine ».

> État : scaffolding uniquement, pas encore d'implémentation.

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
