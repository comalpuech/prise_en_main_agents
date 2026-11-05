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
