# Loan Example Assets

This directory contains sample assets for local demos and regression tests.

- `semantic-domain.json` is an example semantic-domain export. It is not loaded by migrations, startup code, runtime code, or the default UI.
- `seed_loan_indicators.py` creates local demo tables and fake data for the loan example only.
- `seed_loan_indicators.py --append` adds a small, current-date fixture with reserved IDs and
  idempotent UPSERT semantics; it never drops the existing tables.
- `ontology-bundle.json` is a runnable Ontology MVP bundle for the loan agent.
- All six object types in `ontology-bundle.json` enable read-only datasource synchronization
  with a page size of 200 and a stable, unbounded top-level `SELECT`.
- `ONTOLOGY_DEMO.md` explains the workbench workflow, object/action model, and REST replay.
- `scripts/verify_loan_ontology_demo.py` replays import -> validate -> publish -> approve -> collect -> close -> audit.
- To use the question-answering assets, import `semantic-domain.json` with `scripts/import_semantic_bundle.py`; to use the operational Ontology, import `ontology-bundle.json` from the `/ontology` workbench. See `ONTOLOGY_DEMO.md` for the complete sequence.

Ontology definitions and local action overlays are stored in the management database. Synchronized
source properties come from the domain's bound business datasource and remain read-only.

## Ontology datasource synchronization

Entering the object-instances tab, or refreshing it, synchronizes the selected object type's
current page from the domain's default datasource. Switching types or pages continues through all
source rows using server-side `LIMIT/OFFSET`; configured queries contain no top-level `LIMIT`.

| Object type | Base table | Derived or renamed fields |
|---|---|---|
| `Customer` | `customer_risk_monthly_indicator` | latest row per customer, `name`, `monthly_income`, `debt_income_ratio` |
| `LoanApplication` | `loan_application_indicator` | `approved_amount`, `is_blacklist_hit`, `decision_note`, `decided_at` |
| `LoanAccount` | `loan_account_indicator` | `overdue_bucket`, base collection fields, `updated_at` |
| `RepaymentPeriod` | `loan_repayment_period_indicator` | `period_label` from the linked loan number |
| `CustomerRiskSnapshot` | `customer_risk_monthly_indicator` | `snapshot_label` |
| `CollectionCase` | `collection_case_indicator` | `closed_at` from `case_end_date` |

Datasource access is read-only. Synced values are stored as source properties; fields changed by
Ontology actions are stored as local overlays and take precedence on subsequent synchronizations.
This is page-triggered synchronization, not database CDC or a background scheduler. The bound
agent must have read permission for every table referenced by a source query.

## Non-destructive local demo seed

The repository already contains a larger historical fixture. To make questions such as
“本月申请量/逾期情况” useful on the local clock (August 31, 2026), preview the extra rows first:

```bash
uv run python examples/loan/seed_loan_indicators.py --append
```

The preview creates 240 applications, 160 accounts, 960 repayment periods, 480 customer-risk
snapshots, and 120 collection cases. If the preview is correct, write them with an explicit
confirmation:

```bash
uv run python examples/loan/seed_loan_indicators.py --append --write --yes-append
```

The append mode uses stable IDs in the `9x, 19x, 29x, 39x, 49x, 90x` million ranges and
`INSERT ... ON DUPLICATE KEY UPDATE`, so repeating the command updates the same synthetic rows
instead of duplicating them. Existing rows and the historical full-rebuild mode are unchanged.

## Persistent risk-delivery demo

`seed_loan_risk_delivery.py` creates two persistent risk issues in the existing active
`loan_risk` domain. It reads the current values from these already imported Ontology objects:

- `LoanAccount/700001`
- `CustomerRiskSnapshot/600001`

The management database must already contain a published `loan_risk` Ontology release and the
active administrator `wenqu_demo_admin`. The script reports a clear error when a prerequisite is
missing and never creates an account.

Preview the derived issue, evidence, and review plan without writing any records:

```bash
uv run python examples/loan/seed_loan_risk_delivery.py --preview
```

Run without flags to write the two issues, three evidence records per issue, and their initial
review actions:

```bash
uv run python examples/loan/seed_loan_risk_delivery.py
```

The stable issue keys are `demo_m1_collection_700001` and `demo_high_dti_600001`. Repeating the
write command skips an existing issue as a whole, so it does not duplicate evidence or reviews.
The JSON output includes the domain ID, created/skipped counts, issue IDs, final statuses, and
evidence counts.

After seeding, open `http://127.0.0.1:4399/risk-delivery`, select the `loan_risk` domain, and view
the records under **风险事项**. Their evidence and review history are available from the issue
detail view; generated audit events are visible under **决策审计**.

The thresholds, severity levels, descriptions, and review actions are technical demo fixtures
only. They do not represent real lending, collection, compliance, or credit policy.
