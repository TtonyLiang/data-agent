from datetime import date

from examples.loan import seed_loan_indicators as seed

TABLE_NAMES = [
    "loan_application_indicator",
    "loan_account_indicator",
    "loan_repayment_period_indicator",
    "customer_risk_monthly_indicator",
    "collection_case_indicator",
]


def test_table_specs_define_confirmed_loan_indicator_er():
    specs = seed.build_table_specs()

    assert list(specs) == TABLE_NAMES
    assert all(spec.target_rows > 10_000 for spec in specs.values())

    account_sql = seed.build_create_table_sql(specs["loan_account_indicator"])
    repayment_sql = seed.build_create_table_sql(specs["loan_repayment_period_indicator"])
    collection_sql = seed.build_create_table_sql(specs["collection_case_indicator"])

    assert "COMMENT='贷款账户当前指标表'" in account_sql
    assert "FOREIGN KEY (application_id)" in account_sql
    assert "REFERENCES loan_application_indicator(application_id)" in account_sql
    assert "FOREIGN KEY (loan_id)" in repayment_sql
    assert "REFERENCES loan_account_indicator(loan_id)" in repayment_sql
    assert "FOREIGN KEY (loan_id)" in collection_sql
    assert "REFERENCES loan_account_indicator(loan_id)" in collection_sql


def test_generate_dataset_keeps_references_and_financial_ranges_consistent():
    row_counts = {
        "loan_application_indicator": 120,
        "loan_account_indicator": 90,
        "loan_repayment_period_indicator": 360,
        "customer_risk_monthly_indicator": 240,
        "collection_case_indicator": 80,
    }

    data = seed.generate_dataset(
        row_counts=row_counts,
        start_date=date(2024, 1, 1),
        snapshot_date=date(2026, 6, 14),
        random_seed=20260614,
    )
    specs = seed.build_table_specs()

    assert {name: len(rows) for name, rows in data.items()} == row_counts
    assert seed.validate_dataset(data, specs, date(2024, 1, 1), date(2026, 6, 14)) == []

    applications = {row["application_id"]: row for row in data["loan_application_indicator"]}
    loans = {row["loan_id"]: row for row in data["loan_account_indicator"]}

    assert {row["application_id"] for row in data["loan_account_indicator"]} <= set(applications)
    assert {row["loan_id"] for row in data["loan_repayment_period_indicator"]} <= set(loans)
    assert {row["loan_id"] for row in data["collection_case_indicator"]} <= set(loans)

    for row in data["loan_application_indicator"]:
        assert row["approval_amount"] <= row["requested_amount"]
        assert 0 <= row["model_pd"] <= 1
        assert 0 <= row["debt_income_ratio"] <= 2.5
        assert date(2024, 1, 1) <= row["apply_date"] <= date(2026, 6, 14)

    for row in data["loan_account_indicator"]:
        assert row["remaining_principal"] <= row["loan_amount"]
        assert row["current_overdue_days"] <= row["max_overdue_days"]
        assert row["snapshot_date"] == date(2026, 6, 14)

    for row in data["collection_case_indicator"]:
        assert 0 <= row["recovery_rate"] <= 1
        assert row["recovered_principal"] <= row["entry_overdue_principal"]


def test_generated_schema_does_not_include_sensitive_personal_columns():
    specs = seed.build_table_specs()

    forbidden_fragments = {"name", "phone", "mobile", "id_card", "email", "address"}
    column_names = {column.name for spec in specs.values() for column in spec.columns}

    assert not any(
        fragment in column for fragment in forbidden_fragments for column in column_names
    )


def test_seed_script_defaults_to_dry_run(monkeypatch):
    monkeypatch.setattr("sys.argv", ["seed_loan_indicators.py"])

    args = seed.parse_args()

    assert args.dry_run is True


def test_append_fixture_is_small_current_and_namespace_safe():
    data = seed.generate_append_dataset(application_count=12)

    assert {
        name: len(rows) for name, rows in data.items()
    } == seed.append_row_counts(12)
    assert seed.validate_append_dataset(data) == []

    application_ids = {row["application_id"] for row in data["loan_application_indicator"]}
    loan_ids = {row["loan_id"] for row in data["loan_account_indicator"]}
    customer_ids = {row["customer_id"] for row in data["loan_application_indicator"]}

    assert min(application_ids) > seed.APPEND_ID_BASES["application"]
    assert min(loan_ids) > seed.APPEND_ID_BASES["loan"]
    assert min(customer_ids) > seed.APPEND_ID_BASES["customer"]
    assert {
        row["application_id"] for row in data["loan_account_indicator"]
    } <= application_ids
    assert {row["loan_id"] for row in data["loan_repayment_period_indicator"]} <= loan_ids
    assert {row["loan_id"] for row in data["collection_case_indicator"]} <= loan_ids
    assert all(
        row["application_no"].startswith("DEMO-")
        for row in data["loan_application_indicator"]
    )


def test_append_fixture_is_deterministic_and_uses_august_snapshot():
    first = seed.generate_append_dataset(application_count=8)
    second = seed.generate_append_dataset(application_count=8)

    assert first == second
    assert {
        row["snapshot_date"] for row in first["loan_account_indicator"]
    } == {date(2026, 8, 31)}
    assert {
        row["snapshot_date"] for row in first["collection_case_indicator"]
    } == {date(2026, 8, 31)}


def test_append_cli_defaults_to_safe_dry_run_and_current_date(monkeypatch):
    monkeypatch.setattr("sys.argv", ["seed_loan_indicators.py", "--append"])

    args = seed.parse_args()

    assert args.append is True
    assert args.dry_run is True
    assert args.append_count == seed.DEFAULT_APPEND_APPLICATIONS
    assert args.append_snapshot_date == date(2026, 8, 31)


def test_append_database_uses_create_if_missing_and_upsert_only():
    class FakeCursor:
        def __init__(self):
            self.executed = []
            self.batch_sql = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, sql, *args):
            self.executed.append(sql)

        def executemany(self, sql, values):
            self.batch_sql.append((sql, list(values)))

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.commits = 0

        def cursor(self):
            return self.cursor_instance

        def commit(self):
            self.commits += 1

    connection = FakeConnection()
    data = seed.generate_append_dataset(application_count=2)

    seed.append_database(connection, data, batch_size=10)

    assert len(connection.cursor_instance.executed) == len(TABLE_NAMES)
    assert len(connection.cursor_instance.batch_sql) == len(TABLE_NAMES)
    assert all(
        "ON DUPLICATE KEY UPDATE" in sql
        for sql, _ in connection.cursor_instance.batch_sql
    )
    assert connection.commits == 1
