"""Configuration locale sans lecture d'une vraie clé ou d'un .env personnel."""

import pytest
from pydantic import ValidationError

from market_analyst import config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("GOOGLE_MODEL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_default_model_unchanged():
    assert config.Settings(_env_file=None).llm_model == "google_genai:gemini-2.5-flash"


@pytest.mark.parametrize(
    "value", ["gemini-3.8-flash", " google_genai:gemini-3.8-flash "]
)
def test_google_model_environment(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_MODEL", value)
    assert config.Settings(_env_file=None).llm_model == "google_genai:gemini-3.8-flash"


def test_explicit_llm_model_has_priority(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "google_genai:another-model")
    monkeypatch.setenv("GOOGLE_MODEL", "gemini-3.8-flash")
    assert config.Settings(_env_file=None).llm_model == "google_genai:another-model"


def test_google_model_in_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GOOGLE_MODEL=gemini-3.8-flash\n", encoding="utf-8")
    assert config.Settings(_env_file=env).llm_model == "google_genai:gemini-3.8-flash"


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_google_model_uses_default(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_MODEL", value)
    assert config.Settings(_env_file=None).llm_model == "google_genai:gemini-2.5-flash"


@pytest.mark.parametrize("value", ["openai:other", "google_genai:"])
def test_invalid_google_model(monkeypatch, value):
    monkeypatch.setenv("GOOGLE_MODEL", value)
    with pytest.raises(ValidationError, match="GOOGLE_MODEL"):
        config.Settings(_env_file=None)
