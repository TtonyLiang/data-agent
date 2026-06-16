from pathlib import Path


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


def test_env_example_exposes_milvus_uri_used_by_vector_store():
    env = parse_env_example()

    assert env["MILVUS_URI"] == "http://127.0.0.1:19530"


def test_docker_compose_initializes_business_sample_database():
    compose = (ROOT / "docker-compose.yml").read_text()

    assert "./app/db/sample_data.sql:/docker-entrypoint-initdb.d/02-sample-data.sql" in compose
