from sentinel_project.settings import Settings


def test_settings_loads_expected_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("TARGET_MODEL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CHROMA_PATH", raising=False)

    settings = Settings()

    assert settings.openai_api_key == "test-key"
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.target_model == "gpt-4.1-mini"
    assert settings.database_url.endswith("sentinel.db")
    assert settings.chroma_path.endswith("data/chroma")


def test_settings_accepts_open_api_key_alias(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_API_KEY", "alias-test-key")

    settings = Settings(_env_file=None)

    assert settings.openai_api_key == "alias-test-key"
