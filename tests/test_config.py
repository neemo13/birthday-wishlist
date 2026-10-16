import pytest

from wishlist import config
from wishlist.config import ConfigError, validate

URL, KEY = "https://abcd1234.supabase.co", "eyJhbGciOi.real.key"


def test_dev_and_prod_accept_good_values():
    assert validate(URL, KEY, None) == "dev" and validate(URL, KEY, "PROD ") == "prod"


@pytest.mark.parametrize("url,key", [(None, KEY), (URL, None), ("", ""), (URL, "")])
def test_missing_values_are_named_but_never_echoed(url, key):
    with pytest.raises(ConfigError) as err:
        validate(url, key, "dev")
    assert "Missing configuration" in str(err.value) and KEY not in str(err.value)


@pytest.mark.parametrize("url,key", [("https://YOUR-PROJECT-REF.supabase.co", KEY), (URL, "YOUR-SERVICE-ROLE-KEY"), (URL, "<paste>")])
def test_placeholders_are_rejected_in_every_environment(url, key):
    for env in ("dev", "prod"):
        with pytest.raises(ConfigError, match="placeholder"):
            validate(url, key, env)


@pytest.mark.parametrize("url", ["http://abcd.supabase.co", "http://localhost:54321", "https://localhost", "https://127.0.0.1:8000"])
def test_production_requires_a_real_https_url(url):
    with pytest.raises(ConfigError, match="https"):
        validate(url, KEY, "prod")
    assert validate(url, KEY, "dev") == "dev"           # fine on your own computer


def test_unknown_environment_is_rejected():
    with pytest.raises(ConfigError, match="APP_ENV"):
        validate(URL, KEY, "staging")


def test_load_config_reads_environment_variables(monkeypatch):
    for k, v in (("SUPABASE_URL", URL), ("SUPABASE_SERVICE_KEY", KEY), ("APP_ENV", "prod"), ("SUPABASE_BUCKET", "b2")):
        monkeypatch.setenv(k, v)
    cfg = config.load_config()
    assert cfg.is_prod and cfg.bucket == "b2" and cfg.supabase_url == URL
    monkeypatch.setenv("SUPABASE_URL", "http://insecure.example")
    with pytest.raises(ConfigError):
        config.load_config()


def test_log_level_falls_back_safely(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug"); assert config.log_level() == "DEBUG"
    monkeypatch.setenv("LOG_LEVEL", "verbose-nonsense"); assert config.log_level() == "INFO"
    monkeypatch.delenv("LOG_LEVEL"); assert config.log_level() == "INFO"


def test_dev_harness_refuses_to_run_in_production():
    import runpy, os
    os.environ["APP_ENV"] = "prod"
    try:
        with pytest.raises(SystemExit, match="never run with APP_ENV=prod"):
            runpy.run_path("scripts/dev_harness.py")
    finally:
        os.environ.pop("APP_ENV")
