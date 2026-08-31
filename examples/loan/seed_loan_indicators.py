"""Seed synthetic loan indicator tables for financial Text-to-SQL scenarios."""

from __future__ import annotations

import argparse
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is optional for direct script use.
    load_dotenv = None


MONEY = Decimal("0.01")
RATIO4 = Decimal("0.0001")
RATIO6 = Decimal("0.000001")
DEFAULT_START_DATE = date(2024, 1, 1)
DEFAULT_SNAPSHOT_DATE = date(2026, 6, 14)
# ``--append`` is deliberately separate from the historical full rebuild.  The
# append fixture uses a reserved ID range and a recent, fixed snapshot so that
# it can be run repeatedly during a local demo without colliding with the
# original 2024-01-01 .. 2026-06-14 dataset.
DEFAULT_APPEND_START_DATE = date(2026, 7, 1)
DEFAULT_APPEND_SNAPSHOT_DATE = date(2026, 8, 31)
DEFAULT_APPEND_APPLICATIONS = 240
MAX_APPEND_APPLICATIONS = 10_000

# IDs in the original generator start at 1_000_001/2_000_001/... .  Keep the
# new fixture far away from those ranges, and keep all foreign-key references
# inside the same namespace.  The values are intentionally stable: an UPSERT
# on a second run updates the same demo rows instead of creating duplicates.
APPEND_ID_BASES = {
    "customer": 90_000_000,
    "application": 9_000_000,
    "loan": 19_000_000,
    "repayment": 29_000_000,
    "risk_snapshot": 39_000_000,
    "collection": 49_000_000,
}


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    definition: str


@dataclass(frozen=True)
class TableSpec:
    name: str
    comment: str
    target_rows: int
    columns: tuple[ColumnSpec, ...]
    primary_key: str
    indexes: tuple[str, ...] = ()
    foreign_keys: tuple[str, ...] = ()


def money(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def ratio4(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(RATIO4, rounding=ROUND_HALF_UP)


def ratio6(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(RATIO6, rounding=ROUND_HALF_UP)


def month_key(value: date) -> str:
    return value.strftime("%Y-%m")


def month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, days_in_month(year, month))
    return date(year, month, day)


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


def months_between(start: date, end: date) -> int:
    return max(0, (end.year - start.year) * 12 + end.month - start.month)


def random_date(rng: random.Random, start: date, end: date) -> date:
    if end <= start:
        return start
    return start + timedelta(days=rng.randint(0, (end - start).days))


def weighted_choice(rng: random.Random, choices: tuple[tuple[str, float], ...]) -> str:
    total = sum(weight for _, weight in choices)
    pick = rng.random() * total
    cumulative = 0.0
    for value, weight in choices:
        cumulative += weight
        if pick <= cumulative:
            return value
    return choices[-1][0]


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def build_table_specs() -> dict[str, TableSpec]:
    return {
        "loan_application_indicator": TableSpec(
            name="loan_application_indicator",
            comment="贷款申请审批指标表",
            target_rows=30_000,
            primary_key="application_id",
            columns=(
                ColumnSpec("application_id", "BIGINT NOT NULL COMMENT '申请ID'"),
                ColumnSpec("customer_id", "BIGINT NOT NULL COMMENT '客户ID'"),
                ColumnSpec("application_no", "VARCHAR(64) NOT NULL COMMENT '申请编号'"),
                ColumnSpec("apply_date", "DATE NOT NULL COMMENT '申请日期'"),
                ColumnSpec("apply_month", "CHAR(7) NOT NULL COMMENT '申请月份'"),
                ColumnSpec("product_type", "VARCHAR(32) NOT NULL COMMENT '产品类型'"),
                ColumnSpec("loan_purpose", "VARCHAR(64) NOT NULL COMMENT '贷款用途'"),
                ColumnSpec("channel", "VARCHAR(64) NOT NULL COMMENT '申请渠道'"),
                ColumnSpec("region", "VARCHAR(64) NOT NULL COMMENT '区域'"),
                ColumnSpec("city_tier", "VARCHAR(32) NOT NULL COMMENT '城市等级'"),
                ColumnSpec("customer_age", "INT NOT NULL COMMENT '客户年龄'"),
                ColumnSpec("gender", "VARCHAR(16) NOT NULL COMMENT '性别'"),
                ColumnSpec("occupation_type", "VARCHAR(64) NOT NULL COMMENT '职业类型'"),
                ColumnSpec("monthly_income", "DECIMAL(12,2) NOT NULL COMMENT '月收入'"),
                ColumnSpec("existing_debt_amt", "DECIMAL(14,2) NOT NULL COMMENT '存量负债'"),
                ColumnSpec(
                    "credit_card_utilization_rate",
                    "DECIMAL(6,4) NOT NULL COMMENT '信用卡使用率'",
                ),
                ColumnSpec("debt_income_ratio", "DECIMAL(6,4) NOT NULL COMMENT '负债收入比'"),
                ColumnSpec("requested_amount", "DECIMAL(14,2) NOT NULL COMMENT '申请金额'"),
                ColumnSpec("requested_term_months", "INT NOT NULL COMMENT '申请期限(月)'"),
                ColumnSpec("bureau_credit_score", "INT NOT NULL COMMENT '征信分'"),
                ColumnSpec("internal_score", "DECIMAL(8,2) NOT NULL COMMENT '内部评分'"),
                ColumnSpec("risk_grade", "VARCHAR(8) NOT NULL COMMENT '风险等级'"),
                ColumnSpec("model_pd", "DECIMAL(8,6) NOT NULL COMMENT '预测违约概率'"),
                ColumnSpec("fraud_score", "DECIMAL(8,2) NOT NULL COMMENT '欺诈分'"),
                ColumnSpec("approval_status", "VARCHAR(32) NOT NULL COMMENT '审批状态'"),
                ColumnSpec("approval_amount", "DECIMAL(14,2) NOT NULL COMMENT '审批金额'"),
                ColumnSpec("reject_reason", "VARCHAR(128) DEFAULT NULL COMMENT '拒绝原因'"),
                ColumnSpec("decision_time_minutes", "INT NOT NULL COMMENT '审批耗时(分钟)'"),
                ColumnSpec("created_at", "DATETIME NOT NULL COMMENT '创建时间'"),
            ),
            indexes=(
                "KEY idx_apply_month_product (apply_month, product_type)",
                "KEY idx_apply_date_channel (apply_date, channel)",
                "KEY idx_customer_id (customer_id)",
                "KEY idx_region_risk (region, risk_grade)",
                "KEY idx_approval_status (approval_status)",
            ),
        ),
        "loan_account_indicator": TableSpec(
            name="loan_account_indicator",
            comment="贷款账户当前指标表",
            target_rows=22_000,
            primary_key="loan_id",
            columns=(
                ColumnSpec("loan_id", "BIGINT NOT NULL COMMENT '贷款ID'"),
                ColumnSpec("application_id", "BIGINT NOT NULL COMMENT '申请ID'"),
                ColumnSpec("customer_id", "BIGINT NOT NULL COMMENT '客户ID'"),
                ColumnSpec("loan_no", "VARCHAR(64) NOT NULL COMMENT '借据号'"),
                ColumnSpec("disburse_date", "DATE NOT NULL COMMENT '放款日期'"),
                ColumnSpec("disburse_month", "CHAR(7) NOT NULL COMMENT '放款月份'"),
                ColumnSpec("product_type", "VARCHAR(32) NOT NULL COMMENT '产品类型'"),
                ColumnSpec("channel", "VARCHAR(64) NOT NULL COMMENT '渠道'"),
                ColumnSpec("region", "VARCHAR(64) NOT NULL COMMENT '区域'"),
                ColumnSpec("loan_amount", "DECIMAL(14,2) NOT NULL COMMENT '放款金额'"),
                ColumnSpec("term_months", "INT NOT NULL COMMENT '贷款期限(月)'"),
                ColumnSpec("annual_interest_rate", "DECIMAL(7,4) NOT NULL COMMENT '年化利率'"),
                ColumnSpec("repayment_method", "VARCHAR(32) NOT NULL COMMENT '还款方式'"),
                ColumnSpec("guarantee_type", "VARCHAR(32) NOT NULL COMMENT '担保方式'"),
                ColumnSpec(
                    "risk_grade_at_origination",
                    "VARCHAR(8) NOT NULL COMMENT '放款时风险等级'",
                ),
                ColumnSpec(
                    "model_pd_at_origination",
                    "DECIMAL(8,6) NOT NULL COMMENT '放款时预测违约概率'",
                ),
                ColumnSpec("current_status", "VARCHAR(32) NOT NULL COMMENT '当前状态'"),
                ColumnSpec("mob", "INT NOT NULL COMMENT '账龄月数'"),
                ColumnSpec("remaining_principal", "DECIMAL(14,2) NOT NULL COMMENT '剩余本金'"),
                ColumnSpec("repaid_principal", "DECIMAL(14,2) NOT NULL COMMENT '已还本金'"),
                ColumnSpec("repaid_interest", "DECIMAL(14,2) NOT NULL COMMENT '已还利息'"),
                ColumnSpec("current_overdue_days", "INT NOT NULL COMMENT '当前逾期天数'"),
                ColumnSpec("max_overdue_days", "INT NOT NULL COMMENT '历史最大逾期天数'"),
                ColumnSpec("overdue_principal", "DECIMAL(14,2) NOT NULL COMMENT '逾期本金'"),
                ColumnSpec("next_due_date", "DATE DEFAULT NULL COMMENT '下一应还日'"),
                ColumnSpec("is_restructured", "TINYINT(1) NOT NULL COMMENT '是否展期或重组'"),
                ColumnSpec("is_written_off", "TINYINT(1) NOT NULL COMMENT '是否核销'"),
                ColumnSpec("writeoff_amount", "DECIMAL(14,2) NOT NULL COMMENT '核销金额'"),
                ColumnSpec("snapshot_date", "DATE NOT NULL COMMENT '快照日期'"),
            ),
            indexes=(
                "KEY idx_application_id (application_id)",
                "KEY idx_customer_id (customer_id)",
                "KEY idx_disburse_month_product (disburse_month, product_type)",
                "KEY idx_status_overdue (current_status, current_overdue_days)",
                "KEY idx_region_risk (region, risk_grade_at_origination)",
                "KEY idx_snapshot_date (snapshot_date)",
            ),
            foreign_keys=(
                "CONSTRAINT fk_loan_account_application "
                "FOREIGN KEY (application_id) "
                "REFERENCES loan_application_indicator(application_id)",
            ),
        ),
        "loan_repayment_period_indicator": TableSpec(
            name="loan_repayment_period_indicator",
            comment="分期还款表现指标表",
            target_rows=120_000,
            primary_key="repay_period_id",
            columns=(
                ColumnSpec("repay_period_id", "BIGINT NOT NULL COMMENT '分期ID'"),
                ColumnSpec("loan_id", "BIGINT NOT NULL COMMENT '贷款ID'"),
                ColumnSpec("customer_id", "BIGINT NOT NULL COMMENT '客户ID'"),
                ColumnSpec("period_no", "INT NOT NULL COMMENT '期数'"),
                ColumnSpec("due_date", "DATE NOT NULL COMMENT '应还日'"),
                ColumnSpec("due_month", "CHAR(7) NOT NULL COMMENT '应还月份'"),
                ColumnSpec("scheduled_principal", "DECIMAL(14,2) NOT NULL COMMENT '应还本金'"),
                ColumnSpec("scheduled_interest", "DECIMAL(14,2) NOT NULL COMMENT '应还利息'"),
                ColumnSpec("scheduled_fee", "DECIMAL(14,2) NOT NULL COMMENT '应还费用'"),
                ColumnSpec("scheduled_total", "DECIMAL(14,2) NOT NULL COMMENT '应还总额'"),
                ColumnSpec("paid_principal", "DECIMAL(14,2) NOT NULL COMMENT '实还本金'"),
                ColumnSpec("paid_interest", "DECIMAL(14,2) NOT NULL COMMENT '实还利息'"),
                ColumnSpec("paid_fee", "DECIMAL(14,2) NOT NULL COMMENT '实还费用'"),
                ColumnSpec("paid_total", "DECIMAL(14,2) NOT NULL COMMENT '实还总额'"),
                ColumnSpec("latest_pay_date", "DATE DEFAULT NULL COMMENT '最近还款日'"),
                ColumnSpec("repay_status", "VARCHAR(32) NOT NULL COMMENT '还款状态'"),
                ColumnSpec("overdue_days", "INT NOT NULL COMMENT '逾期天数'"),
                ColumnSpec("overdue_bucket", "VARCHAR(16) NOT NULL COMMENT '逾期阶段'"),
                ColumnSpec("is_prepayment", "TINYINT(1) NOT NULL COMMENT '是否提前还款'"),
                ColumnSpec("is_extension", "TINYINT(1) NOT NULL COMMENT '是否展期'"),
                ColumnSpec("penalty_interest", "DECIMAL(14,2) NOT NULL COMMENT '罚息'"),
                ColumnSpec(
                    "remaining_principal_after",
                    "DECIMAL(14,2) NOT NULL COMMENT '期后剩余本金'",
                ),
                ColumnSpec("snapshot_date", "DATE NOT NULL COMMENT '快照日期'"),
            ),
            indexes=(
                "KEY idx_loan_period (loan_id, period_no)",
                "KEY idx_customer_id (customer_id)",
                "KEY idx_due_month_bucket (due_month, overdue_bucket)",
                "KEY idx_repay_status (repay_status)",
                "KEY idx_snapshot_date (snapshot_date)",
            ),
            foreign_keys=(
                "CONSTRAINT fk_repayment_loan "
                "FOREIGN KEY (loan_id) "
                "REFERENCES loan_account_indicator(loan_id)",
            ),
        ),
        "customer_risk_monthly_indicator": TableSpec(
            name="customer_risk_monthly_indicator",
            comment="客户月度风险指标表",
            target_rows=60_000,
            primary_key="snapshot_id",
            columns=(
                ColumnSpec("snapshot_id", "BIGINT NOT NULL COMMENT '快照ID'"),
                ColumnSpec("customer_id", "BIGINT NOT NULL COMMENT '客户ID'"),
                ColumnSpec("stat_month", "DATE NOT NULL COMMENT '统计月份'"),
                ColumnSpec("region", "VARCHAR(64) NOT NULL COMMENT '区域'"),
                ColumnSpec("city_tier", "VARCHAR(32) NOT NULL COMMENT '城市等级'"),
                ColumnSpec("age_band", "VARCHAR(16) NOT NULL COMMENT '年龄段'"),
                ColumnSpec("customer_segment", "VARCHAR(32) NOT NULL COMMENT '客群类型'"),
                ColumnSpec("active_loan_count", "INT NOT NULL COMMENT '在贷笔数'"),
                ColumnSpec("open_loan_amount", "DECIMAL(14,2) NOT NULL COMMENT '在贷合同金额'"),
                ColumnSpec(
                    "outstanding_principal",
                    "DECIMAL(14,2) NOT NULL COMMENT '未还本金'",
                ),
                ColumnSpec(
                    "monthly_income_estimate",
                    "DECIMAL(12,2) NOT NULL COMMENT '月收入估计'",
                ),
                ColumnSpec(
                    "bankcard_inflow_amt_3m",
                    "DECIMAL(14,2) NOT NULL COMMENT '近3月入账金额'",
                ),
                ColumnSpec(
                    "bankcard_outflow_amt_3m",
                    "DECIMAL(14,2) NOT NULL COMMENT '近3月出账金额'",
                ),
                ColumnSpec("avg_balance_3m", "DECIMAL(14,2) NOT NULL COMMENT '近3月平均余额'"),
                ColumnSpec("bureau_query_count_1m", "INT NOT NULL COMMENT '近1月征信查询次数'"),
                ColumnSpec("bureau_query_count_3m", "INT NOT NULL COMMENT '近3月征信查询次数'"),
                ColumnSpec("external_loan_org_count", "INT NOT NULL COMMENT '外部贷款机构数'"),
                ColumnSpec(
                    "credit_card_utilization_rate",
                    "DECIMAL(6,4) NOT NULL COMMENT '信用卡使用率'",
                ),
                ColumnSpec("dti", "DECIMAL(6,4) NOT NULL COMMENT '负债收入比'"),
                ColumnSpec("max_dpd_12m", "INT NOT NULL COMMENT '近12月最大逾期天数'"),
                ColumnSpec("overdue_count_12m", "INT NOT NULL COMMENT '近12月逾期次数'"),
                ColumnSpec("settled_loan_count", "INT NOT NULL COMMENT '已结清笔数'"),
                ColumnSpec("application_count_3m", "INT NOT NULL COMMENT '近3月申请次数'"),
                ColumnSpec(
                    "rejected_application_count_3m",
                    "INT NOT NULL COMMENT '近3月拒绝次数'",
                ),
                ColumnSpec("behavior_score", "DECIMAL(8,2) NOT NULL COMMENT '行为评分'"),
                ColumnSpec("risk_grade", "VARCHAR(8) NOT NULL COMMENT '风险等级'"),
                ColumnSpec("model_pd", "DECIMAL(8,6) NOT NULL COMMENT '预测违约概率'"),
                ColumnSpec("fraud_risk_level", "VARCHAR(16) NOT NULL COMMENT '欺诈风险等级'"),
                ColumnSpec("is_blacklist_hit", "TINYINT(1) NOT NULL COMMENT '是否命中黑名单'"),
            ),
            indexes=(
                "KEY idx_customer_month (customer_id, stat_month)",
                "KEY idx_stat_month_region (stat_month, region)",
                "KEY idx_risk_grade (risk_grade)",
                "KEY idx_dpd (max_dpd_12m)",
            ),
        ),
        "collection_case_indicator": TableSpec(
            name="collection_case_indicator",
            comment="贷后催收处置指标表",
            target_rows=20_000,
            primary_key="case_id",
            columns=(
                ColumnSpec("case_id", "BIGINT NOT NULL COMMENT '案件ID'"),
                ColumnSpec("loan_id", "BIGINT NOT NULL COMMENT '贷款ID'"),
                ColumnSpec("customer_id", "BIGINT NOT NULL COMMENT '客户ID'"),
                ColumnSpec("case_no", "VARCHAR(64) NOT NULL COMMENT '案件编号'"),
                ColumnSpec("case_start_date", "DATE NOT NULL COMMENT '入催日期'"),
                ColumnSpec("case_end_date", "DATE DEFAULT NULL COMMENT '结案日期'"),
                ColumnSpec("case_month", "CHAR(7) NOT NULL COMMENT '入催月份'"),
                ColumnSpec("case_status", "VARCHAR(32) NOT NULL COMMENT '案件状态'"),
                ColumnSpec(
                    "overdue_bucket_at_entry",
                    "VARCHAR(16) NOT NULL COMMENT '入催逾期阶段'",
                ),
                ColumnSpec("entry_overdue_days", "INT NOT NULL COMMENT '入催逾期天数'"),
                ColumnSpec(
                    "entry_overdue_principal",
                    "DECIMAL(14,2) NOT NULL COMMENT '入催逾期本金'",
                ),
                ColumnSpec("assigned_team", "VARCHAR(64) NOT NULL COMMENT '分配团队'"),
                ColumnSpec("collector_id", "BIGINT NOT NULL COMMENT '催收员ID'"),
                ColumnSpec("collection_strategy", "VARCHAR(32) NOT NULL COMMENT '催收策略'"),
                ColumnSpec("contact_attempt_count", "INT NOT NULL COMMENT '联系尝试次数'"),
                ColumnSpec("connected_count", "INT NOT NULL COMMENT '接通次数'"),
                ColumnSpec("promise_to_pay_count", "INT NOT NULL COMMENT '承诺还款次数'"),
                ColumnSpec("promise_amount", "DECIMAL(14,2) NOT NULL COMMENT '承诺还款金额'"),
                ColumnSpec("promise_broken_count", "INT NOT NULL COMMENT '爽约次数'"),
                ColumnSpec("recovered_principal", "DECIMAL(14,2) NOT NULL COMMENT '回收本金'"),
                ColumnSpec("recovered_interest", "DECIMAL(14,2) NOT NULL COMMENT '回收利息'"),
                ColumnSpec("recovered_penalty", "DECIMAL(14,2) NOT NULL COMMENT '回收罚息'"),
                ColumnSpec("recovery_rate", "DECIMAL(6,4) NOT NULL COMMENT '回收率'"),
                ColumnSpec("close_reason", "VARCHAR(64) DEFAULT NULL COMMENT '结案原因'"),
                ColumnSpec("days_to_cure", "INT DEFAULT NULL COMMENT '化解天数'"),
                ColumnSpec("is_escalated", "TINYINT(1) NOT NULL COMMENT '是否升级处置'"),
                ColumnSpec("snapshot_date", "DATE NOT NULL COMMENT '快照日期'"),
            ),
            indexes=(
                "KEY idx_loan_id (loan_id)",
                "KEY idx_customer_id (customer_id)",
                "KEY idx_case_month_bucket (case_month, overdue_bucket_at_entry)",
                "KEY idx_case_status (case_status)",
                "KEY idx_strategy (collection_strategy)",
                "KEY idx_snapshot_date (snapshot_date)",
            ),
            foreign_keys=(
                "CONSTRAINT fk_collection_loan "
                "FOREIGN KEY (loan_id) "
                "REFERENCES loan_account_indicator(loan_id)",
            ),
        ),
    }


def build_create_table_sql(spec: TableSpec) -> str:
    parts = [f"    `{column.name}` {column.definition}" for column in spec.columns]
    parts.append(f"    PRIMARY KEY (`{spec.primary_key}`)")
    parts.extend(f"    {index}" for index in spec.indexes)
    parts.extend(f"    {foreign_key}" for foreign_key in spec.foreign_keys)
    return (
        f"CREATE TABLE IF NOT EXISTS `{spec.name}` (\n"
        + ",\n".join(parts)
        + f"\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='{spec.comment}'"
    )


def build_drop_table_sqls(specs: dict[str, TableSpec]) -> list[str]:
    return [f"DROP TABLE IF EXISTS `{name}`" for name in reversed(specs)]


def default_row_counts(specs: dict[str, TableSpec] | None = None) -> dict[str, int]:
    table_specs = specs or build_table_specs()
    return {name: spec.target_rows for name, spec in table_specs.items()}


def append_row_counts(application_count: int = DEFAULT_APPEND_APPLICATIONS) -> dict[str, int]:
    """Return a small, relationally consistent append fixture.

    The full seed intentionally creates a large analytical corpus.  A local
    demo normally only needs enough recent rows to exercise the current-month
    and risk/collection questions.  Derived table sizes are deterministic and
    preserve the foreign-key ordering constraints used by ``generate_dataset``.
    """
    count = int(application_count)
    if count < 1 or count > MAX_APPEND_APPLICATIONS:
        raise ValueError(
            f"append application count must be between 1 and {MAX_APPEND_APPLICATIONS}"
        )
    account_count = max(1, round(count * 2 / 3))
    return {
        "loan_application_indicator": count,
        "loan_account_indicator": account_count,
        # Six periods per account gives useful repayment status/bucket variety
        # without creating the 120k-row corpus used by the full rebuild.
        "loan_repayment_period_indicator": account_count * 6,
        "customer_risk_monthly_indicator": count * 2,
        "collection_case_indicator": max(1, round(account_count * 0.75)),
    }


def risk_grade_from_pd(pd: Decimal) -> str:
    value = float(pd)
    if value < 0.025:
        return "A"
    if value < 0.055:
        return "B"
    if value < 0.10:
        return "C"
    if value < 0.18:
        return "D"
    return "E"


def overdue_bucket(days: int) -> str:
    if days <= 0:
        return "C"
    if days <= 30:
        return "M1"
    if days <= 60:
        return "M2"
    if days <= 90:
        return "M3"
    return "M4+"


def age_band(age: int) -> str:
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    return "55+"


def random_amount_by_product(rng: random.Random, product_type: str) -> Decimal:
    ranges = {
        "消费贷": (3_000, 80_000),
        "经营贷": (50_000, 800_000),
        "现金贷": (1_000, 30_000),
        "车贷": (30_000, 300_000),
        "装修贷": (20_000, 250_000),
    }
    low, high = ranges[product_type]
    return money(rng.triangular(low, high, low + (high - low) * 0.35))


def generate_applications(
    rng: random.Random,
    count: int,
    account_count: int,
    start_date: date,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    products = ("消费贷", "经营贷", "现金贷", "车贷", "装修贷")
    purposes = ("日常消费", "经营周转", "装修", "购车", "教育培训", "医疗支出")
    channels = ("手机银行", "直营网点", "三方平台", "客户经理", "互联网广告")
    regions = ("华东", "华南", "华北", "华中", "西南", "西北", "东北")
    city_tiers = ("一线", "新一线", "二线", "三线", "四线及以下")
    occupations = ("企业职员", "个体工商户", "小微企业主", "自由职业", "公务事业单位")
    customer_pool = max(1, int(max(count * 0.55, account_count * 0.7)))
    rows: list[dict[str, Any]] = []

    for index in range(1, count + 1):
        product_type = rng.choice(products)
        monthly_income = money(rng.lognormvariate(8.75, 0.45))
        monthly_income = money(clamp(float(monthly_income), 3_000, 120_000))
        existing_debt = money(float(monthly_income) * rng.uniform(1.5, 24.0))
        dti = ratio4(clamp(float(existing_debt) / max(float(monthly_income) * 12, 1), 0, 2.5))
        credit_util = ratio4(clamp(rng.betavariate(2.2, 3.8), 0, 0.98))
        bureau_score = int(clamp(rng.gauss(680 - float(dti) * 70, 70), 350, 850))
        requested_amount = random_amount_by_product(rng, product_type)
        requested_term = rng.choice((6, 9, 12, 18, 24, 36))
        fraud_score = Decimal(str(clamp(rng.gauss(38 + float(dti) * 12, 18), 1, 99))).quantize(
            MONEY
        )
        pd_value = clamp(
            0.015
            + (720 - bureau_score) / 4_000
            + float(dti) * 0.035
            + float(credit_util) * 0.035
            + float(fraud_score) / 1_400
            + rng.uniform(-0.015, 0.02),
            0.003,
            0.45,
        )
        model_pd = ratio6(pd_value)
        risk_grade = risk_grade_from_pd(model_pd)
        internal_score = money(clamp(760 - float(model_pd) * 850 + rng.gauss(0, 24), 300, 900))
        apply_date = random_date(rng, start_date, snapshot_date)
        is_account_source = index <= account_count

        if is_account_source:
            approval_status = "approved"
        else:
            approval_status = weighted_choice(
                rng,
                (
                    ("approved", 0.18),
                    ("rejected", 0.58),
                    ("cancelled", 0.08),
                    ("manual_review", 0.16),
                ),
            )
        approved = approval_status == "approved"
        approval_rate_factor = clamp(
            1.05 - float(model_pd) * 1.8 - float(dti) * 0.06,
            0.45,
            1.0,
        )
        approval_amount = (
            money(float(requested_amount) * approval_rate_factor) if approved else money(0)
        )
        reject_reason = None
        if approval_status == "rejected":
            reject_reason = weighted_choice(
                rng,
                (
                    ("征信评分不足", 0.35),
                    ("负债收入比过高", 0.25),
                    ("多头借贷风险", 0.2),
                    ("欺诈风险较高", 0.1),
                    ("资料完整性不足", 0.1),
                ),
            )
        elif approval_status == "manual_review":
            reject_reason = "人工复核中"

        rows.append(
            {
                "application_id": 1_000_000 + index,
                "customer_id": 200_000 + rng.randint(1, customer_pool),
                "application_no": f"APP{index:010d}",
                "apply_date": apply_date,
                "apply_month": month_key(apply_date),
                "product_type": product_type,
                "loan_purpose": rng.choice(purposes),
                "channel": rng.choice(channels),
                "region": rng.choice(regions),
                "city_tier": rng.choice(city_tiers),
                "customer_age": rng.randint(21, 62),
                "gender": rng.choice(("男", "女")),
                "occupation_type": rng.choice(occupations),
                "monthly_income": monthly_income,
                "existing_debt_amt": existing_debt,
                "credit_card_utilization_rate": credit_util,
                "debt_income_ratio": dti,
                "requested_amount": requested_amount,
                "requested_term_months": requested_term,
                "bureau_credit_score": bureau_score,
                "internal_score": internal_score,
                "risk_grade": risk_grade,
                "model_pd": model_pd,
                "fraud_score": fraud_score,
                "approval_status": approval_status,
                "approval_amount": approval_amount,
                "reject_reason": reject_reason,
                "decision_time_minutes": int(clamp(rng.lognormvariate(3.5, 0.9), 2, 1440)),
                "created_at": datetime.combine(apply_date, datetime.min.time())
                + timedelta(minutes=rng.randint(0, 1439)),
            }
        )
    return rows


def generate_accounts(
    rng: random.Random,
    applications: list[dict[str, Any]],
    count: int,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    repayment_methods = ("等额本息", "等额本金", "先息后本", "随借随还")
    guarantee_types = ("信用", "保证", "抵押", "质押")
    rows: list[dict[str, Any]] = []

    for index, application in enumerate(applications[:count], start=1):
        disburse_date = min(
            application["apply_date"] + timedelta(days=rng.randint(1, 12)),
            snapshot_date,
        )
        term_months = application["requested_term_months"]
        loan_amount = max(application["approval_amount"], money(1_000))
        mob = min(term_months, months_between(disburse_date, snapshot_date))
        risk_grade = application["risk_grade"]
        pd_value = float(application["model_pd"])
        overdue_roll = rng.random()
        current_overdue_days = 0
        if overdue_roll < pd_value * 1.8:
            current_overdue_days = rng.choice((7, 15, 25, 45, 75, 105, 150))
        historical_extra = (
            rng.choice((0, 0, 0, 5, 15, 30, 60, 90)) if pd_value > 0.06 else 0
        )
        max_overdue_days = max(current_overdue_days, historical_extra)
        paid_ratio = clamp(mob / max(term_months, 1), 0, 1)
        delinquency_drag = 0.0 if current_overdue_days == 0 else rng.uniform(0.02, 0.18)
        remaining_principal = money(
            float(loan_amount) * clamp(1 - paid_ratio + delinquency_drag, 0, 1)
        )
        repaid_principal = money(float(loan_amount) - float(remaining_principal))
        annual_interest_rate = ratio4(
            clamp(0.045 + pd_value * 0.75 + rng.uniform(-0.006, 0.012), 0.035, 0.26)
        )
        repaid_interest = money(float(repaid_principal) * float(annual_interest_rate) * 0.55)
        overdue_principal = (
            money(float(remaining_principal) * rng.uniform(0.08, 0.65))
            if current_overdue_days > 0
            else money(0)
        )
        settled = mob >= term_months and current_overdue_days == 0 and rng.random() < 0.55
        written_off = max_overdue_days >= 120 and rng.random() < 0.18
        if written_off:
            current_status = "written_off"
        elif current_overdue_days > 0:
            current_status = "overdue"
        elif settled:
            current_status = "settled"
            remaining_principal = money(0)
            repaid_principal = loan_amount
        else:
            current_status = "active"
        writeoff_amount = (
            money(float(overdue_principal) * rng.uniform(0.45, 1.0))
            if written_off
            else money(0)
        )
        next_due_date = (
            None
            if current_status in {"settled", "written_off"}
            else add_months(disburse_date, mob + 1)
        )

        rows.append(
            {
                "loan_id": 2_000_000 + index,
                "application_id": application["application_id"],
                "customer_id": application["customer_id"],
                "loan_no": f"LN{index:010d}",
                "disburse_date": disburse_date,
                "disburse_month": month_key(disburse_date),
                "product_type": application["product_type"],
                "channel": application["channel"],
                "region": application["region"],
                "loan_amount": loan_amount,
                "term_months": term_months,
                "annual_interest_rate": annual_interest_rate,
                "repayment_method": rng.choice(repayment_methods),
                "guarantee_type": rng.choice(guarantee_types),
                "risk_grade_at_origination": risk_grade,
                "model_pd_at_origination": application["model_pd"],
                "current_status": current_status,
                "mob": mob,
                "remaining_principal": remaining_principal,
                "repaid_principal": repaid_principal,
                "repaid_interest": repaid_interest,
                "current_overdue_days": current_overdue_days,
                "max_overdue_days": max_overdue_days,
                "overdue_principal": overdue_principal,
                "next_due_date": next_due_date,
                "is_restructured": 1 if max_overdue_days >= 60 and rng.random() < 0.22 else 0,
                "is_written_off": 1 if written_off else 0,
                "writeoff_amount": writeoff_amount,
                "snapshot_date": snapshot_date,
            }
        )
    return rows


def generate_repayments(
    rng: random.Random,
    loans: list[dict[str, Any]],
    count: int,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not loans:
        return rows

    for index in range(1, count + 1):
        loan = loans[(index - 1) % len(loans)]
        cycle = (index - 1) // len(loans)
        period_no = cycle % max(loan["term_months"], 1) + 1
        due_date = add_months(loan["disburse_date"], period_no)
        principal = money(float(loan["loan_amount"]) / loan["term_months"])
        interest = money(float(loan["loan_amount"]) * float(loan["annual_interest_rate"]) / 12)
        fee = money(float(loan["loan_amount"]) * rng.uniform(0.0001, 0.0012))
        scheduled_total = money(principal + interest + fee)
        not_due = due_date > snapshot_date

        if not_due:
            overdue_days = 0
            repay_status = "not_due"
            paid_ratio = 0.0
            latest_pay_date = None
        else:
            if period_no >= max(1, loan["mob"]) and loan["current_overdue_days"] > 0:
                overdue_days = loan["current_overdue_days"]
            elif rng.random() < float(loan["model_pd_at_origination"]) * 0.9:
                overdue_days = rng.choice((3, 8, 18, 35, 65, 95))
            else:
                overdue_days = 0
            if overdue_days == 0:
                repay_status = "paid"
                paid_ratio = 1.0
                latest_pay_date = due_date - timedelta(days=rng.randint(0, 5))
            else:
                repay_status = "overdue" if rng.random() < 0.65 else "partial_paid"
                paid_ratio = rng.uniform(0.0, 0.75)
                latest_pay_date = min(
                    snapshot_date,
                    due_date + timedelta(days=rng.randint(1, overdue_days)),
                )

        paid_principal = money(float(principal) * paid_ratio)
        paid_interest = money(float(interest) * paid_ratio)
        paid_fee = money(float(fee) * paid_ratio)
        paid_total = money(paid_principal + paid_interest + paid_fee)
        penalty_interest = (
            money(float(scheduled_total) * overdue_days * 0.0005) if overdue_days > 0 else money(0)
        )
        remaining_after = money(max(float(loan["loan_amount"]) - float(principal) * period_no, 0))

        rows.append(
            {
                "repay_period_id": 3_000_000 + index,
                "loan_id": loan["loan_id"],
                "customer_id": loan["customer_id"],
                "period_no": period_no,
                "due_date": due_date,
                "due_month": month_key(due_date),
                "scheduled_principal": principal,
                "scheduled_interest": interest,
                "scheduled_fee": fee,
                "scheduled_total": scheduled_total,
                "paid_principal": paid_principal,
                "paid_interest": paid_interest,
                "paid_fee": paid_fee,
                "paid_total": paid_total,
                "latest_pay_date": latest_pay_date,
                "repay_status": repay_status,
                "overdue_days": overdue_days,
                "overdue_bucket": overdue_bucket(overdue_days),
                "is_prepayment": 1 if repay_status == "paid" and rng.random() < 0.035 else 0,
                "is_extension": 1 if overdue_days >= 30 and rng.random() < 0.08 else 0,
                "penalty_interest": penalty_interest,
                "remaining_principal_after": remaining_after,
                "snapshot_date": snapshot_date,
            }
        )
    return rows


def build_customer_profiles(applications: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    profiles: dict[int, dict[str, Any]] = {}
    for row in applications:
        profiles.setdefault(
            row["customer_id"],
            {
                "region": row["region"],
                "city_tier": row["city_tier"],
                "age_band": age_band(row["customer_age"]),
                "monthly_income": row["monthly_income"],
                "credit_util": row["credit_card_utilization_rate"],
            },
        )
    return profiles


def build_customer_loan_summary(loans: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    summary: dict[int, dict[str, Any]] = {}
    for loan in loans:
        item = summary.setdefault(
            loan["customer_id"],
            {
                "active_count": 0,
                "open_amount": money(0),
                "outstanding": money(0),
                "max_dpd": 0,
                "overdue_count": 0,
                "settled_count": 0,
            },
        )
        if loan["current_status"] in {"active", "overdue"}:
            item["active_count"] += 1
        if loan["current_status"] == "settled":
            item["settled_count"] += 1
        item["open_amount"] = money(item["open_amount"] + loan["loan_amount"])
        item["outstanding"] = money(item["outstanding"] + loan["remaining_principal"])
        item["max_dpd"] = max(item["max_dpd"], loan["max_overdue_days"])
        if loan["max_overdue_days"] > 0:
            item["overdue_count"] += 1
    return summary


def generate_customer_risk(
    rng: random.Random,
    applications: list[dict[str, Any]],
    loans: list[dict[str, Any]],
    count: int,
    start_date: date,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    profiles = build_customer_profiles(applications)
    loan_summary = build_customer_loan_summary(loans)
    customer_ids = sorted(profiles) or [200_001]
    months = []
    cursor = month_start(start_date)
    while cursor <= month_start(snapshot_date):
        months.append(cursor)
        cursor = add_months(cursor, 1)

    for index in range(1, count + 1):
        customer_id = customer_ids[(index - 1) % len(customer_ids)]
        profile = profiles.get(customer_id, {})
        summary = loan_summary.get(
            customer_id,
            {
                "active_count": 0,
                "open_amount": money(0),
                "outstanding": money(0),
                "max_dpd": 0,
                "overdue_count": 0,
                "settled_count": 0,
            },
        )
        monthly_income = money(
            float(profile.get("monthly_income", money(8_000))) * rng.uniform(0.85, 1.25)
        )
        dti = ratio4(
            clamp(
                float(summary["outstanding"]) / max(float(monthly_income) * 12, 1),
                0,
                2.5,
            )
        )
        credit_util = ratio4(
            clamp(
                float(profile.get("credit_util", ratio4(0.35))) + rng.uniform(-0.08, 0.12),
                0,
                0.98,
            )
        )
        max_dpd = int(summary["max_dpd"])
        overdue_count = int(summary["overdue_count"] + rng.choice((0, 0, 1)))
        pd_value = clamp(
            0.012 + float(dti) * 0.05 + max_dpd / 500 + overdue_count * 0.012,
            0.003,
            0.55,
        )
        model_pd = ratio6(pd_value)
        behavior_score = money(clamp(780 - pd_value * 900 + rng.gauss(0, 20), 300, 900))
        inflow = money(float(monthly_income) * rng.uniform(2.2, 4.2))
        outflow = money(float(inflow) * rng.uniform(0.55, 1.12))

        rows.append(
            {
                "snapshot_id": 4_000_000 + index,
                "customer_id": customer_id,
                "stat_month": months[(index - 1) % len(months)],
                "region": profile.get("region", "华东"),
                "city_tier": profile.get("city_tier", "二线"),
                "age_band": profile.get("age_band", "35-44"),
                "customer_segment": weighted_choice(
                    rng,
                    (
                        ("优质客群", 0.18),
                        ("普通客群", 0.52),
                        ("高风险客群", 0.18),
                        ("沉默客群", 0.12),
                    ),
                ),
                "active_loan_count": int(summary["active_count"]),
                "open_loan_amount": summary["open_amount"],
                "outstanding_principal": summary["outstanding"],
                "monthly_income_estimate": monthly_income,
                "bankcard_inflow_amt_3m": inflow,
                "bankcard_outflow_amt_3m": outflow,
                "avg_balance_3m": money(
                    max(float(inflow) - float(outflow), 0) * rng.uniform(0.25, 1.2)
                ),
                "bureau_query_count_1m": rng.randint(0, 8),
                "bureau_query_count_3m": rng.randint(0, 18),
                "external_loan_org_count": rng.randint(0, 12),
                "credit_card_utilization_rate": credit_util,
                "dti": dti,
                "max_dpd_12m": max_dpd,
                "overdue_count_12m": overdue_count,
                "settled_loan_count": int(summary["settled_count"]),
                "application_count_3m": rng.randint(0, 8),
                "rejected_application_count_3m": rng.randint(0, 5),
                "behavior_score": behavior_score,
                "risk_grade": risk_grade_from_pd(model_pd),
                "model_pd": model_pd,
                "fraud_risk_level": weighted_choice(
                    rng,
                    (("低", 0.68), ("中", 0.22), ("高", 0.08), ("极高", 0.02)),
                ),
                "is_blacklist_hit": 1 if rng.random() < max(0.004, pd_value * 0.025) else 0,
            }
        )
    return rows


def generate_collections(
    rng: random.Random,
    loans: list[dict[str, Any]],
    count: int,
    snapshot_date: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not loans:
        return rows
    candidates = [loan for loan in loans if loan["max_overdue_days"] > 0] or loans
    teams = ("自营一组", "自营二组", "委外A组", "委外B组", "法催组")
    strategies = ("短信提醒", "电话催收", "委外催收", "法务催收", "协商还款")

    for index in range(1, count + 1):
        loan = candidates[(index - 1) % len(candidates)]
        max_start = max(loan["disburse_date"], snapshot_date - timedelta(days=360))
        case_start = random_date(rng, max_start, snapshot_date)
        entry_days = max(1, loan["max_overdue_days"], rng.choice((7, 15, 31, 61, 91)))
        entry_principal = loan["overdue_principal"]
        if entry_principal <= 0:
            entry_principal = money(float(loan["remaining_principal"]) * rng.uniform(0.08, 0.45))
        if entry_principal <= 0:
            entry_principal = money(float(loan["loan_amount"]) * rng.uniform(0.02, 0.18))
        recovery_rate_value = clamp(rng.betavariate(1.4, 3.2), 0, 1)
        if entry_days >= 90:
            recovery_rate_value *= 0.65
        recovered_principal = money(float(entry_principal) * recovery_rate_value)
        recovery_rate = ratio4(float(recovered_principal) / max(float(entry_principal), 1))
        contact_attempts = rng.randint(1, 28)
        connected = rng.randint(0, contact_attempts)
        promised = rng.randint(0, max(connected, 1))
        closed = rng.random() < 0.58
        days_to_cure = rng.randint(3, 120) if closed and recovered_principal > 0 else None
        case_end = (
            min(case_start + timedelta(days=days_to_cure), snapshot_date)
            if days_to_cure
            else None
        )
        case_status = (
            "closed"
            if closed
            else weighted_choice(
                rng,
                (("open", 0.62), ("outsourced", 0.25), ("legal", 0.13)),
            )
        )

        rows.append(
            {
                "case_id": 5_000_000 + index,
                "loan_id": loan["loan_id"],
                "customer_id": loan["customer_id"],
                "case_no": f"COL{index:010d}",
                "case_start_date": case_start,
                "case_end_date": case_end,
                "case_month": month_key(case_start),
                "case_status": case_status,
                "overdue_bucket_at_entry": overdue_bucket(entry_days),
                "entry_overdue_days": entry_days,
                "entry_overdue_principal": entry_principal,
                "assigned_team": rng.choice(teams),
                "collector_id": 900_000 + rng.randint(1, 260),
                "collection_strategy": rng.choice(strategies),
                "contact_attempt_count": contact_attempts,
                "connected_count": connected,
                "promise_to_pay_count": promised,
                "promise_amount": money(float(entry_principal) * rng.uniform(0.05, 0.85)),
                "promise_broken_count": rng.randint(0, promised),
                "recovered_principal": recovered_principal,
                "recovered_interest": money(float(recovered_principal) * rng.uniform(0.01, 0.12)),
                "recovered_penalty": money(float(recovered_principal) * rng.uniform(0, 0.05)),
                "recovery_rate": recovery_rate,
                "close_reason": (
                    rng.choice(("已还清", "部分回收", "转委外", "转法诉", "失联"))
                    if closed
                    else None
                ),
                "days_to_cure": days_to_cure,
                "is_escalated": (
                    1 if entry_days >= 60 or case_status in {"outsourced", "legal"} else 0
                ),
                "snapshot_date": snapshot_date,
            }
        )
    return rows


def generate_dataset(
    row_counts: dict[str, int] | None = None,
    start_date: date = DEFAULT_START_DATE,
    snapshot_date: date = DEFAULT_SNAPSHOT_DATE,
    random_seed: int = 20260614,
) -> dict[str, list[dict[str, Any]]]:
    specs = build_table_specs()
    counts = default_row_counts(specs)
    if row_counts:
        counts.update(row_counts)
    if counts["loan_account_indicator"] > counts["loan_application_indicator"]:
        raise ValueError("loan_account_indicator count cannot exceed application count")

    rng = random.Random(random_seed)
    applications = generate_applications(
        rng,
        counts["loan_application_indicator"],
        counts["loan_account_indicator"],
        start_date,
        snapshot_date,
    )
    accounts = generate_accounts(rng, applications, counts["loan_account_indicator"], snapshot_date)
    repayments = generate_repayments(
        rng,
        accounts,
        counts["loan_repayment_period_indicator"],
        snapshot_date,
    )
    customer_risk = generate_customer_risk(
        rng,
        applications,
        accounts,
        counts["customer_risk_monthly_indicator"],
        start_date,
        snapshot_date,
    )
    collections = generate_collections(
        rng,
        accounts,
        counts["collection_case_indicator"],
        snapshot_date,
    )
    return {
        "loan_application_indicator": applications,
        "loan_account_indicator": accounts,
        "loan_repayment_period_indicator": repayments,
        "customer_risk_monthly_indicator": customer_risk,
        "collection_case_indicator": collections,
    }


def namespace_append_dataset(
    data: dict[str, list[dict[str, Any]]],
    id_bases: dict[str, int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Move a generated dataset into the reserved append ID namespace.

    ``generate_dataset`` uses compact IDs for the destructive full rebuild.
    Reusing those IDs for an append would overwrite existing rows, and merely
    adding an offset to each table would leave customer/foreign-key references
    inconsistent.  This helper remaps every primary/foreign key together and
    returns copied rows, leaving the generated input untouched.
    """
    bases = {**APPEND_ID_BASES, **(id_bases or {})}
    result = {
        table_name: [dict(row) for row in rows]
        for table_name, rows in data.items()
    }

    applications = result.get("loan_application_indicator", [])
    accounts = result.get("loan_account_indicator", [])
    repayments = result.get("loan_repayment_period_indicator", [])
    customer_risk = result.get("customer_risk_monthly_indicator", [])
    collections = result.get("collection_case_indicator", [])

    def stable_map(values: list[Any], base: int) -> dict[Any, int]:
        unique_values = sorted({value for value in values})
        return {value: base + index for index, value in enumerate(unique_values, start=1)}

    customer_map = stable_map(
        [row["customer_id"] for row in applications if row.get("customer_id") is not None],
        bases["customer"],
    )
    application_map = stable_map(
        [row["application_id"] for row in applications if row.get("application_id") is not None],
        bases["application"],
    )
    loan_map = stable_map(
        [row["loan_id"] for row in accounts if row.get("loan_id") is not None],
        bases["loan"],
    )
    repayment_map = stable_map(
        [row["repay_period_id"] for row in repayments if row.get("repay_period_id") is not None],
        bases["repayment"],
    )
    risk_map = stable_map(
        [row["snapshot_id"] for row in customer_risk if row.get("snapshot_id") is not None],
        bases["risk_snapshot"],
    )
    collection_map = stable_map(
        [row["case_id"] for row in collections if row.get("case_id") is not None],
        bases["collection"],
    )

    for row in applications:
        old_id = row["application_id"]
        row["application_id"] = application_map[old_id]
        row["customer_id"] = customer_map[row["customer_id"]]
        # A visible prefix makes it clear in the UI/query result that these
        # are synthetic append rows, while retaining the source row's index.
        row["application_no"] = f"DEMO-{row['application_no']}"

    for row in accounts:
        old_loan_id = row["loan_id"]
        row["loan_id"] = loan_map[old_loan_id]
        row["application_id"] = application_map[row["application_id"]]
        row["customer_id"] = customer_map[row["customer_id"]]
        row["loan_no"] = f"DEMO-{row['loan_no']}"

    for row in repayments:
        old_period_id = row["repay_period_id"]
        row["repay_period_id"] = repayment_map[old_period_id]
        row["loan_id"] = loan_map[row["loan_id"]]
        row["customer_id"] = customer_map[row["customer_id"]]

    for row in customer_risk:
        old_snapshot_id = row["snapshot_id"]
        row["snapshot_id"] = risk_map[old_snapshot_id]
        row["customer_id"] = customer_map[row["customer_id"]]

    for row in collections:
        old_case_id = row["case_id"]
        row["case_id"] = collection_map[old_case_id]
        row["loan_id"] = loan_map[row["loan_id"]]
        row["customer_id"] = customer_map[row["customer_id"]]
        row["case_no"] = f"DEMO-{row['case_no']}"

    return result


def generate_append_dataset(
    application_count: int = DEFAULT_APPEND_APPLICATIONS,
    start_date: date = DEFAULT_APPEND_START_DATE,
    snapshot_date: date = DEFAULT_APPEND_SNAPSHOT_DATE,
    random_seed: int = 20260831,
) -> dict[str, list[dict[str, Any]]]:
    """Generate a current, non-colliding demo fixture for ``--append``."""
    data = generate_dataset(
        row_counts=append_row_counts(application_count),
        start_date=start_date,
        snapshot_date=snapshot_date,
        random_seed=random_seed,
    )
    return namespace_append_dataset(data)


def validate_append_dataset(
    data: dict[str, list[dict[str, Any]]],
    start_date: date = DEFAULT_APPEND_START_DATE,
    snapshot_date: date = DEFAULT_APPEND_SNAPSHOT_DATE,
) -> list[str]:
    """Validate the extra invariants required by the non-destructive fixture."""
    errors = validate_dataset(
        data,
        build_table_specs(),
        start_date=start_date,
        snapshot_date=snapshot_date,
    )
    ranges = {
        "loan_application_indicator": ("application_id", "application"),
        "loan_account_indicator": ("loan_id", "loan"),
        "loan_repayment_period_indicator": ("repay_period_id", "repayment"),
        "customer_risk_monthly_indicator": ("snapshot_id", "risk_snapshot"),
        "collection_case_indicator": ("case_id", "collection"),
    }
    for table_name, (key, base_key) in ranges.items():
        base = int(APPEND_ID_BASES[base_key])
        for row in data.get(table_name, []):
            value = int(row[key])
            if value <= base or value > base + MAX_APPEND_APPLICATIONS * 10:
                errors.append(f"{table_name} {key} is outside append namespace")
                break

    customer_base = int(APPEND_ID_BASES["customer"])
    customer_ids = {
        int(row["customer_id"])
        for table_name in (
            "loan_application_indicator",
            "loan_account_indicator",
            "loan_repayment_period_indicator",
            "customer_risk_monthly_indicator",
            "collection_case_indicator",
        )
        for row in data.get(table_name, [])
        if row.get("customer_id") is not None
    }
    customer_upper_bound = customer_base + MAX_APPEND_APPLICATIONS * 10
    if any(value <= customer_base or value > customer_upper_bound for value in customer_ids):
        errors.append("customer_id is outside append namespace")

    for table_name in (
        "loan_account_indicator",
        "loan_repayment_period_indicator",
        "collection_case_indicator",
    ):
        for row in data.get(table_name, []):
            if row.get("snapshot_date") != snapshot_date:
                errors.append(f"{table_name} snapshot_date mismatch")
                break
    return errors


def validate_dataset(
    data: dict[str, list[dict[str, Any]]],
    specs: dict[str, TableSpec] | None = None,
    start_date: date = DEFAULT_START_DATE,
    snapshot_date: date = DEFAULT_SNAPSHOT_DATE,
) -> list[str]:
    table_specs = specs or build_table_specs()
    errors: list[str] = []
    for name, spec in table_specs.items():
        rows = data.get(name)
        if rows is None:
            errors.append(f"missing table data: {name}")
            continue
        required_columns = {column.name for column in spec.columns}
        for index, row in enumerate(rows[:1000], start=1):
            missing = required_columns - set(row)
            if missing:
                errors.append(f"{name} row {index} missing columns: {sorted(missing)}")

    application_ids = {
        row["application_id"] for row in data.get("loan_application_indicator", [])
    }
    loan_ids = {row["loan_id"] for row in data.get("loan_account_indicator", [])}
    account_application_ids = {
        row["application_id"] for row in data.get("loan_account_indicator", [])
    }
    repayment_loan_ids = {
        row["loan_id"] for row in data.get("loan_repayment_period_indicator", [])
    }
    collection_loan_ids = {row["loan_id"] for row in data.get("collection_case_indicator", [])}
    if not account_application_ids <= application_ids:
        errors.append("loan_account_indicator has orphan application_id values")
    if not repayment_loan_ids <= loan_ids:
        errors.append("loan_repayment_period_indicator has orphan loan_id values")
    if not collection_loan_ids <= loan_ids:
        errors.append("collection_case_indicator has orphan loan_id values")

    for row in data.get("loan_application_indicator", []):
        if row["approval_amount"] > row["requested_amount"]:
            errors.append("application approval_amount exceeds requested_amount")
            break
        if not Decimal("0") <= row["model_pd"] <= Decimal("1"):
            errors.append("application model_pd out of range")
            break
        if not Decimal("0") <= row["debt_income_ratio"] <= Decimal("2.5"):
            errors.append("application debt_income_ratio out of range")
            break
        if not start_date <= row["apply_date"] <= snapshot_date:
            errors.append("application apply_date out of range")
            break

    for row in data.get("loan_account_indicator", []):
        if row["remaining_principal"] > row["loan_amount"]:
            errors.append("account remaining_principal exceeds loan_amount")
            break
        if row["current_overdue_days"] > row["max_overdue_days"]:
            errors.append("account current_overdue_days exceeds max_overdue_days")
            break
        if row["snapshot_date"] != snapshot_date:
            errors.append("account snapshot_date mismatch")
            break

    for row in data.get("customer_risk_monthly_indicator", []):
        if not Decimal("0") <= row["model_pd"] <= Decimal("1"):
            errors.append("customer risk model_pd out of range")
            break
        if not Decimal("0") <= row["dti"] <= Decimal("2.5"):
            errors.append("customer risk dti out of range")
            break

    for row in data.get("collection_case_indicator", []):
        if not Decimal("0") <= row["recovery_rate"] <= Decimal("1"):
            errors.append("collection recovery_rate out of range")
            break
        if row["recovered_principal"] > row["entry_overdue_principal"]:
            errors.append("collection recovered_principal exceeds entry_overdue_principal")
            break
    return errors


def insert_rows(
    cursor: Any,
    spec: TableSpec,
    rows: list[dict[str, Any]],
    batch_size: int,
    *,
    upsert: bool = False,
) -> None:
    column_names = [column.name for column in spec.columns]
    placeholders = ", ".join(["%s"] * len(column_names))
    columns_sql = ", ".join(f"`{name}`" for name in column_names)
    sql = f"INSERT INTO `{spec.name}` ({columns_sql}) VALUES ({placeholders})"
    if upsert:
        update_columns = [name for name in column_names if name != spec.primary_key]
        if update_columns:
            # ``VALUES(col)`` is supported by the MySQL versions used by the
            # local app (8.0/8.4).  Keeping this expression explicit also
            # avoids interpolating any caller-provided column names.
            updates = ", ".join(
                f"`{name}` = VALUES(`{name}`)" for name in update_columns
            )
            sql += f" ON DUPLICATE KEY UPDATE {updates}"
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        values = [tuple(row[name] for name in column_names) for row in batch]
        cursor.executemany(sql, values)


def seed_database(
    connection: Any,
    data: dict[str, list[dict[str, Any]]],
    specs: dict[str, TableSpec] | None = None,
    batch_size: int = 2_000,
) -> None:
    table_specs = specs or build_table_specs()
    with connection.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        for sql in build_drop_table_sqls(table_specs):
            cursor.execute(sql)
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
        for spec in table_specs.values():
            cursor.execute(build_create_table_sql(spec))
        for name, spec in table_specs.items():
            insert_rows(cursor, spec, data[name], batch_size)
    connection.commit()


def append_database(
    connection: Any,
    data: dict[str, list[dict[str, Any]]],
    specs: dict[str, TableSpec] | None = None,
    batch_size: int = 2_000,
) -> None:
    """Create missing tables and append demo rows without dropping anything.

    Parent/child tables are processed in declaration order.  Every row uses a
    deterministic reserved ID namespace and ``ON DUPLICATE KEY UPDATE`` so a
    rerun is idempotent.  Existing rows outside that namespace are untouched.
    """
    table_specs = specs or build_table_specs()
    with connection.cursor() as cursor:
        for spec in table_specs.values():
            cursor.execute(build_create_table_sql(spec))
        for name, spec in table_specs.items():
            insert_rows(cursor, spec, data[name], batch_size, upsert=True)
    connection.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create and seed synthetic loan indicator tables in MySQL."
    )
    parser.add_argument("--host", default=os.getenv("MYSQL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MYSQL_PORT", "3306")))
    parser.add_argument("--user", default=os.getenv("MYSQL_USER", "root"))
    parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "business_db"))
    parser.add_argument("--seed", type=int, default=20260614)
    parser.add_argument("--start-date", type=date.fromisoformat, default=DEFAULT_START_DATE)
    parser.add_argument("--snapshot-date", type=date.fromisoformat, default=DEFAULT_SNAPSHOT_DATE)
    parser.add_argument("--batch-size", type=int, default=2_000)
    parser.add_argument(
        "--append",
        action="store_true",
        help=(
            "append a small current-date fixture with reserved IDs; "
            "never drops existing loan tables"
        ),
    )
    parser.add_argument(
        "--append-count",
        type=int,
        default=DEFAULT_APPEND_APPLICATIONS,
        help=f"number of synthetic applications for --append (1-{MAX_APPEND_APPLICATIONS})",
    )
    parser.add_argument(
        "--append-start-date",
        type=date.fromisoformat,
        default=DEFAULT_APPEND_START_DATE,
        help="start date for --append (default: 2026-07-01)",
    )
    parser.add_argument(
        "--append-snapshot-date",
        type=date.fromisoformat,
        default=DEFAULT_APPEND_SNAPSHOT_DATE,
        help="snapshot date for --append (default: 2026-08-31)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="generate and validate without MySQL writes",
    )
    parser.add_argument(
        "--write",
        dest="dry_run",
        action="store_false",
        help="write generated data to MySQL; this drops and recreates loan indicator tables",
    )
    parser.add_argument(
        "--yes-drop-existing",
        action="store_true",
        help="confirm destructive table rebuild when used with --write",
    )
    parser.add_argument(
        "--yes-append",
        action="store_true",
        help="confirm non-destructive UPSERT when used with --append --write",
    )
    return parser.parse_args()


def connect_mysql(args: argparse.Namespace) -> Any:
    import pymysql

    connection = pymysql.connect(
        host=args.host,
        port=args.port,
        user=args.user,
        password=args.password,
        charset="utf8mb4",
        autocommit=False,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{args.database}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cursor.execute(f"USE `{args.database}`")
    return connection


def main() -> int:
    if load_dotenv:
        load_dotenv()
    args = parse_args()
    specs = build_table_specs()
    if args.append and args.yes_drop_existing:
        print("refusing conflicting flags: --append cannot be combined with --yes-drop-existing")
        return 2

    if args.append:
        data = generate_append_dataset(
            application_count=args.append_count,
            start_date=args.append_start_date,
            snapshot_date=args.append_snapshot_date,
            random_seed=args.seed,
        )
        validation_errors = validate_append_dataset(
            data,
            start_date=args.append_start_date,
            snapshot_date=args.append_snapshot_date,
        )
    else:
        data = generate_dataset(
            row_counts=default_row_counts(specs),
            start_date=args.start_date,
            snapshot_date=args.snapshot_date,
            random_seed=args.seed,
        )
        validation_errors = validate_dataset(data, specs, args.start_date, args.snapshot_date)
    if validation_errors:
        for error in validation_errors:
            print(f"validation error: {error}")
        return 1

    counts = {name: len(rows) for name, rows in data.items()}
    if args.dry_run:
        mode = "append fixture" if args.append else "full rebuild fixture"
        print(f"dry run ok ({mode})")
        for name, count in counts.items():
            print(f"{name}: {count}")
        return 0

    if args.append:
        if not args.yes_append:
            print("refusing to write append fixture without --yes-append")
            return 2
        connection = connect_mysql(args)
        try:
            append_database(connection, data, specs, args.batch_size)
        finally:
            connection.close()
        print(f"appended demo fixture to database `{args.database}`")
        for name, count in counts.items():
            print(f"{name}: {count}")
        return 0

    if not args.yes_drop_existing:
        print("refusing to write without --yes-drop-existing")
        return 2

    connection = connect_mysql(args)
    try:
        seed_database(connection, data, specs, args.batch_size)
    finally:
        connection.close()

    print(f"seeded database `{args.database}`")
    for name, count in counts.items():
        print(f"{name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
