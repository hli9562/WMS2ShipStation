from wms2ship.config import Settings


def test_native_startup_loads_dotenv_and_environment_overrides_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ("SHIPSTATION_API_KEY", "SHIPSTATION_API_SECRET", "WMS_ENABLE_LIVE_PURCHASE"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text(
        "SHIPSTATION_API_KEY=synthetic-key\nSHIPSTATION_API_SECRET=synthetic-secret\n"
        "WMS_ENABLE_LIVE_PURCHASE=false\nPORT=8080\n"
    )
    settings = Settings()
    assert settings.shipstation_api_key.get_secret_value() == "synthetic-key"
    assert settings.shipstation_api_secret.get_secret_value() == "synthetic-secret"
    assert settings.enable_live_purchase is False
    assert "synthetic-secret" not in repr(settings)
    monkeypatch.setenv("SHIPSTATION_API_KEY", "environment-key")
    assert Settings().shipstation_api_key.get_secret_value() == "environment-key"
