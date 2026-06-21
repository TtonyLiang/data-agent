from app.utils.sql_validator import normalize_sql_for_execution, validate_sql


def test_validate_sql_allows_semicolon_inside_string_and_injects_limit():
    result = normalize_sql_for_execution("SELECT ';' AS marker")

    assert result.ok
    assert result.sql == "SELECT ';' AS marker\nLIMIT 1000"


def test_validate_sql_blocks_multiple_statements_outside_strings():
    ok, reason = validate_sql("SELECT 1; DROP TABLE users")

    assert not ok
    assert "单条" in reason


def test_validate_sql_blocks_dangerous_functions():
    result = normalize_sql_for_execution("SELECT SLEEP(10)")

    assert not result.ok
    assert "危险函数" in result.reason


def test_validate_sql_blocks_cross_database_table_references():
    result = normalize_sql_for_execution("SELECT * FROM other_db.loan_application_indicator")

    assert not result.ok
    assert "跨库" in result.reason


def test_validate_sql_blocks_system_schema_access():
    result = normalize_sql_for_execution("SELECT table_name FROM information_schema.tables")

    assert not result.ok
    assert "系统库" in result.reason


def test_validate_sql_clamps_oversized_limit():
    result = normalize_sql_for_execution("SELECT * FROM loan_application_indicator LIMIT 50000")

    assert result.ok
    assert result.sql == "SELECT * FROM loan_application_indicator\nLIMIT 1000"


def test_validate_sql_blocks_mysql_file_keywords():
    for keyword in ("OUTFILE", "INFILE", "DUMPFILE", "HANDLER", "PREPARE", "XA"):
        result = normalize_sql_for_execution(f"SELECT 1 {keyword}")

        assert not result.ok
        assert "禁止操作" in result.reason
