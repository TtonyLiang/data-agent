"""Import a semantic-domain bundle into the management DB."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional for direct script use.
    load_dotenv = None

from app.db.mysql import get_management_db
from app.services.semantic_runtime import get_semantic_runtime_service


ASSET_GROUPS: tuple[tuple[str, str], ...] = (
    ("concepts", "concept"),
    ("relations", "relation"),
    ("metrics", "metric"),
    ("rules", "rule"),
    ("mappings", "mapping"),
    ("templates", "template"),
)


def load_semantic_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def import_semantic_bundle(
    path: Path,
    agent_id: int = 1,
    datasource_id: int | None = None,
) -> dict[str, int]:
    """Upsert a semantic runtime bundle exported from the management UI."""
    svc = get_semantic_runtime_service()
    payload = load_semantic_file(path)

    domain_data = dict(payload["domain"])
    domain_data["agent_id"] = agent_id
    if datasource_id is not None:
        domain_data["datasource_id"] = datasource_id
    domain_id = await svc.upsert_domain(domain_data)

    counts = {"semantic_domain": 1}
    for group_key, asset_type in ASSET_GROUPS:
        items = payload.get(group_key, [])
        for item in items:
            await svc.upsert_asset(domain_id, asset_type, item)
        counts[
            f"semantic_{asset_type}" if asset_type != "template" else "logic_form_template"
        ] = len(items)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import semantic runtime assets from an explicit exported bundle."
    )
    parser.add_argument("--agent-id", type=int, default=1)
    parser.add_argument("--datasource-id", type=int, default=None)
    parser.add_argument("--path", type=Path, required=True)
    return parser.parse_args()


async def async_main() -> None:
    if load_dotenv:
        load_dotenv()
    args = parse_args()
    result = await import_semantic_bundle(
        path=args.path,
        agent_id=args.agent_id,
        datasource_id=args.datasource_id,
    )
    await get_management_db().close()
    summary = ", ".join(f"{key}={value}" for key, value in result.items())
    print(f"Imported semantic runtime: {summary}")


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
