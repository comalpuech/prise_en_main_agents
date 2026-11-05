"""Point d'entrée CLI : `uv run market-analyst "Fais-moi un point sur Nvidia cette semaine"`."""

import sys


def main() -> None:
    request = " ".join(sys.argv[1:]) or "Fais-moi un point sur Nvidia cette semaine"
    # TODO: build_graph().invoke({"request": request}) puis afficher state["report"]
    raise NotImplementedError(request)


if __name__ == "__main__":
    main()
