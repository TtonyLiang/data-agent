import pytest

from app.db import migrations


class MigrationDB:
    def __init__(self, completed=False, scopes=None):
        self.completed = completed
        self.scopes = scopes or []
        self.transactions = []

    async def execute_query(self, sql, params=None):
        if sql.startswith("SELECT param_key FROM system_parameter"):
            return [{"param_key": params["param_key"]}] if self.completed else []
        if sql.startswith("SELECT sd.id AS domain_id"):
            return self.scopes
        raise AssertionError(sql)

    async def execute_transaction(self, statements):
        self.transactions.append(statements)


@pytest.mark.asyncio
async def test_legacy_agent_permissions_backfill_one_domain_owner_without_union(monkeypatch):
    db = MigrationDB(
        scopes=[{"domain_id": 1, "datasource_id": 2, "agent_id": 3}]
    )
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.backfill_domain_permissions_from_legacy_agents()

    assert len(db.transactions) == 1
    table_sql, table_params = db.transactions[0][0]
    column_sql, column_params = db.transactions[0][1]
    marker_sql, marker_params = db.transactions[0][2]
    assert "FROM agent_table_permission atp" in table_sql
    assert "FROM agent_column_permission acp JOIN agent_table_permission atp" in column_sql
    assert table_params == {"domain_id": 1, "datasource_id": 2, "agent_id": 3}
    assert column_params == table_params
    assert marker_sql.startswith("INSERT INTO system_parameter")
    assert marker_params["param_key"] == "migration.domain_permission_backfill_v1"


@pytest.mark.asyncio
async def test_legacy_permission_backfill_does_not_restore_rules_after_marker(monkeypatch):
    db = MigrationDB(completed=True)
    monkeypatch.setattr(migrations, "get_management_db", lambda: db)

    await migrations.backfill_domain_permissions_from_legacy_agents()

    assert db.transactions == []
