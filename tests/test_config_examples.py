from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def parse_env_example() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_env_example_matches_frontend_proxy_port():
    env = parse_env_example()
    vite_config = (ROOT / "frontend/vite.config.ts").read_text()

    assert env["APP_PORT"] == "4400"
    assert f"http://localhost:{env['APP_PORT']}" in vite_config


def test_env_example_can_be_loaded_by_settings(monkeypatch):
    # Importing app.main in other tests loads the developer .env into the
    # process; isolate this fixture so the checked-in example is authoritative.
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    settings = Settings(_env_file=ROOT / ".env.example")

    assert settings.cors_allowed_origins == [
        "http://localhost:4399",
        "http://127.0.0.1:4399",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_settings_accepts_comma_separated_cors_origins():
    settings = Settings(
        _env_file=None,
        cors_allowed_origins="http://localhost:4399,http://127.0.0.1:4399",
    )

    assert settings.cors_allowed_origins == [
        "http://localhost:4399",
        "http://127.0.0.1:4399",
    ]


def test_production_startup_does_not_depend_on_legacy_admin_api_key():
    settings = Settings(
        _env_file=None,
        debug=False,
        jwt_secret_key="j" * 32,
        secret_encryption_key="test-encryption-key",
        mysql_password="business-password",
        management_mysql_password="management-password",
        admin_api_key="",
    )

    settings.validate_startup_safety()


def test_env_example_exposes_milvus_uri_used_by_vector_store():
    env = parse_env_example()

    assert env["MILVUS_URI"] == "http://127.0.0.1:19530"


def test_docker_compose_initializes_business_sample_database():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "./app/db/sample_data.sql:/docker-entrypoint-initdb.d/02-sample-data.sql" in compose
