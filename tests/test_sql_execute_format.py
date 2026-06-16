from app.agent.nodes.sql_execute import format_result


def test_format_result_does_not_embed_sql_or_markdown_table():
    answer = format_result(
        [{"product_type": "现金贷", "m1_plus_rate": 0.14261}],
        "SELECT * FROM loan_repayment_period_indicator",
    )

    assert answer == "现金贷的 M1+逾期率为 14.26%。"
    assert "SQL:" not in answer
    assert "|" not in answer


def test_format_result_summarizes_multi_row_result():
    answer = format_result(
        [
            {"product_type": "现金贷", "m1_plus_rate": 0.14261},
            {"product_type": "消费贷", "m1_plus_rate": 0.0821},
        ],
        "SELECT * FROM loan_repayment_period_indicator",
    )

    assert answer == "查询完成，共 2 条结果。详细数据已在结果表中展示。"
