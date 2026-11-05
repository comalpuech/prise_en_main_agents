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
Yahoo (seule source avec résumé) ; le reste est réparti jour par jour sur la période. L'agent en
retient 5 à 10 et les résume en français. Toute URL absente des résultats de l'outil est écartée.

Le nœud ne renvoie que la clé `news` : il tourne en parallèle de `market_data_agent`, et deux
écritures concurrentes d'une même clé sans reducer feraient échouer le fan-in.
