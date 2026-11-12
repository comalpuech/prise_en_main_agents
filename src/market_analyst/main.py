"""Point d'entrée CLI : `uv run market-analyst "Fais-moi un point sur Nvidia cette semaine"`."""

import argparse
import logging

from market_analyst.graph import RequestError, build_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Note multi-agents sur un actif")
    parser.add_argument("request", nargs="*", help="Demande en français")
    parser.add_argument(
        "--ticker", help="Symbole Yahoo explicite, non validé à l'avance"
    )
    parser.add_argument("--days", type=int, help="Période en jours calendaires")
    args = parser.parse_args()
    state = {"request": " ".join(args.request)}
    if args.ticker:
        state["ticker"] = args.ticker
    if args.days is not None:
        state["lookback_days"] = args.days
    if not state["request"] and not args.ticker:
        state["request"] = "Fais-moi un point sur Nvidia cette semaine"
    logging.basicConfig(level=logging.WARNING)
    try:
        result = build_graph().invoke(state, config={"max_concurrency": 2})
    except Exception as exc:  # noqa: BLE001 -- frontière CLI, détails SDK masqués
        # Les SDK peuvent contenir des informations sensibles dans leurs messages.
        # Ne pas afficher de traceback ou le texte brut d'une erreur fournisseur.
        message = (
            str(exc)
            if isinstance(exc, RequestError)
            else (
                "Échec du pipeline : vérifiez le réseau, les quotas et la configuration "
                "GOOGLE_API_KEY / GOOGLE_MODEL / LLM_MODEL."
            )
        )
        parser.exit(1, f"Erreur : {message}\n")
    print(result["report"])


if __name__ == "__main__":
    main()
