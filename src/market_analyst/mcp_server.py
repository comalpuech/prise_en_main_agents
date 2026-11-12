"""Serveur MCP exposant les outils de l'analyste."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market-analyst")


@mcp.tool()
def ping(name: str) -> str:
    """Outil de test : renvoie un bonjour."""
    return f"Bonjour {name}"


# TODO : tes vrais outils ici


def main() -> None:
    mcp.run()  # transport stdio par défaut


if __name__ == "__main__":
    main()
