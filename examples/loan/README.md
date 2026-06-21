# Loan Example Assets

This directory contains sample assets for local demos and regression tests.

- `semantic-domain.json` is an example semantic-domain export. It is not loaded by migrations, startup code, runtime code, or the default UI.
- `seed_loan_indicators.py` creates local demo tables and fake data for the loan example only.
- To use this example, import the bundle explicitly through the semantic-layer UI or with `scripts/import_semantic_bundle.py --path examples/loan/semantic-domain.json`.

The production source of truth is always the management database and the visible UI configuration.
