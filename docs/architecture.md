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

