from datetime import date

from scripts import seed_loan_indicators as seed

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
