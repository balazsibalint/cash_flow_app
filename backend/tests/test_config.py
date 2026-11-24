from app.config import Settings


def test_defaults_without_key_disable_llm():
    s = Settings(llm_provider="openrouter", openrouter_api_key="")
    assert s.llm is None
    assert s.llm_enabled is False
    assert s.openrouter_model == "google/gemini-2.5-flash"


def test_openrouter_selected():
    s = Settings(llm_provider="openrouter", openrouter_api_key="k-or", gemini_api_key="k-gem")
    assert s.llm is not None
    assert s.llm.provider == "openrouter"
    assert s.llm.base_url == "https://openrouter.ai/api/v1"
    assert s.llm.api_key == "k-or"
    assert s.llm.model == "google/gemini-2.5-flash"


def test_gemini_selected_uses_same_client_shape():
    s = Settings(llm_provider="gemini", openrouter_api_key="k-or", gemini_api_key="k-gem")
    assert s.llm is not None
    assert s.llm.provider == "gemini"
    assert s.llm.api_key == "k-gem"
    assert "generativelanguage.googleapis.com" in s.llm.base_url
    assert s.llm.model == "gemini-2.5-flash"


def test_provider_none_disables_llm_even_with_key():
    s = Settings(llm_provider="none", openrouter_api_key="k-or")
    assert s.llm is None


def test_empty_env_value_falls_back_to_default(monkeypatch):
    # A kiértékelők a .env.example-t másolják: az üres sor ne írja felül az alapértéket.
    monkeypatch.setenv("OPENROUTER_MODEL", "")
    monkeypatch.setenv("MAX_UPLOAD_MB", "")
    s = Settings()
    assert s.openrouter_model == "google/gemini-2.5-flash"
    assert s.max_upload_mb == 20
    assert s.max_upload_bytes == 20 * 1024 * 1024


def test_unknown_env_vars_are_ignored(monkeypatch):
    # Régi .env-ekben maradhat pl. LLM_MAX_CALLS_PER_BATCH – ettől az app ne álljon le.
    monkeypatch.setenv("LLM_MAX_CALLS_PER_BATCH", "30")
    Settings()
