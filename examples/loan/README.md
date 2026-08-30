# Loan Example Assets

This directory contains sample assets for local demos and regression tests.

- `semantic-domain.json` is an example semantic-domain export. It is not loaded by migrations, startup code, runtime code, or the default UI.
- `seed_loan_indicators.py` creates local demo tables and fake data for the loan example only.
- `ontology-bundle.json` is a runnable Ontology MVP bundle for the loan agent.
- `ONTOLOGY_DEMO.md` explains the workbench workflow, object/action model, and REST replay.
- `scripts/verify_loan_ontology_demo.py` replays import -> validate -> publish -> approve -> collect -> close -> audit.
- To use the question-answering assets, import `semantic-domain.json` with `scripts/import_semantic_bundle.py`; to use the operational Ontology, import `ontology-bundle.json` from the `/ontology` workbench. See `ONTOLOGY_DEMO.md` for the complete sequence.

The production source of truth is always the management database and the visible UI configuration.
