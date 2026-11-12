"""Entrée CLI et erreurs explicites, sans réseau ni clé réelle."""

import pytest

from market_analyst import main as cli
from market_analyst.graph import RequestError


def test_cli_prints_report(monkeypatch, capsys):
    received = {}

    class Graph:
        def invoke(self, state, config):
            received.update(state)
            assert config["max_concurrency"] == 2
            return {"report": "# Note validée"}

    monkeypatch.setattr(cli, "build_graph", lambda: Graph())
    monkeypatch.setattr(
        "sys.argv", ["market-analyst", "--ticker", "AAPL", "--days", "14"]
    )
    cli.main()
    assert received == {"request": "", "ticker": "AAPL", "lookback_days": 14}
    assert capsys.readouterr().out == "# Note validée\n"


@pytest.mark.parametrize(
    "error,expected",
    [
        (RequestError("Actif ambigu"), "Actif ambigu"),
        (RuntimeError("secret-do-not-print"), "Échec du pipeline"),
        (ValueError("secret-do-not-print"), "Échec du pipeline"),
    ],
)
def test_cli_errors_hide_sdk_details(monkeypatch, capsys, error, expected):
    class Graph:
        def invoke(self, *a, **kw):
            raise error

    monkeypatch.setattr(cli, "build_graph", lambda: Graph())
    monkeypatch.setattr("sys.argv", ["market-analyst", "Nvidia"])
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert expected in captured.err
    assert "secret-do-not-print" not in captured.err
