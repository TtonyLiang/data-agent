# Project Harness

This file applies to the whole repository. It defines stable project boundaries and execution rules for future development. It is not a product roadmap.

## Product North Star

- WenQu is an internal, Ontology-driven enterprise operational digital-twin and intelligent-decision platform.
- First principle: business semantics are enterprise assets, databases are data sources, and Agents are capability consumers.
- The current priority is to make the enterprise model, data/twin runtime, and capability publishing center solid.
- Built-in Agent/chat features are reference clients for debugging, regression, and acceptance. Do not let Agent configuration own or control enterprise-model assets.
- Finance/tax, lending, risk delivery, and intelligent querying are vertical validation scenarios, not the platform boundary.

## Product Boundaries

- The deployment is company-internal and single-company. Do not introduce multi-tenancy, multi-enterprise spaces, tenant switching, or enterprise isolation unless the user explicitly changes the product direction.
- Product roles are only business personnel and technical personnel (including database engineers).
- `admin/user` remain compatibility account values. Do not treat them as additional product roles or redesign the account model without an explicit request.
- Business domains organize models, mappings, releases, permissions, and capabilities. They are not tenants.
- External Agents and applications must be able to consume published capabilities without first creating an internal Agent.

## Model and Runtime Invariants

- Maintain one enterprise business model: Ontology objects/relationships/states/actions and query-semantic metrics/rules/mappings/templates must share domain ownership, stable keys, and release lifecycle.
- Start from business objects and definitions, then bind tables, columns, joins, SQL, and LogicForm. Do not make physical schema the business model.
- Business personnel edit and confirm business definitions. Technical personnel own data sources, Schema, physical mappings, permissions, synchronization, and publishing. The current developer may perform both through the compatibility `admin` account.
- Keep Query, Decision, and Action capabilities separate. Query is read-only; Decision returns controlled judgments and reasons; Action carries side effects and must enforce permission, approval, version, transaction, and audit checks.
- Keep source data and local overlays distinguishable. Ontology synchronization must not imply that the platform writes back to the production business database.
- Preserve explicit release, datasource, permission, masking, lineage, and trace boundaries.

## Documentation Authority

Read [docs/README.md](docs/README.md) first.

1. [Product roadmap](docs/ontology-product-roadmap.md): the only source for direction, priority, progress, and acceptance status.
2. [Product flow and data lineage](docs/product-business-flow.md): current business facts and cross-module flow.
3. [Project design](docs/project-design.md): current technical implementation and boundaries.
4. [Project structure](docs/project-structure.md): feature, page, API, service, and database map.
5. [Business/data onboarding](docs/business-data-onboarding.md): real-domain onboarding SOP.

Technical references belong in `docs/reference/`, vertical scenarios in `docs/scenarios/`, and completed audits or obsolete research in `docs/archive/`. Do not create a second roadmap in a design or scenario document.

## Task Execution Defaults

- Infer scope and acceptance criteria from the request and current repository state. Ask only when an answer materially changes the result or an irreversible/external action requires approval.
- Prefer a single agent for small or linear work. Delegate only independent, bounded tasks when parallel execution materially improves speed or quality.
- Preserve unrelated working-tree changes. Never reset, overwrite, or reformat unrelated user work.
- Make the smallest coherent change that satisfies the current product direction. Avoid speculative frameworks, duplicate abstractions, and premature production features.
- Reuse existing services and contracts before creating parallel implementations. Keep compatibility adapters explicit and prevent them from becoming the new product model.
- Demo assets must remain explicit examples. Do not load local JSON, seed files, or hard-coded business definitions during normal startup or migration.

## Change Checklist

Before completing a material change, verify as applicable:

- The change belongs to the correct platform layer and does not make Agent/chat the owner of platform assets.
- Business-facing UI leads with business meaning; SQL, fields, keys, and LogicForm remain technical binding or advanced content.
- New data access follows domain datasource authorization, table allowlist, column permission, masking, and read-only constraints.
- New external capabilities use stable business contracts and do not expose physical SQL or database errors.
- Migrations, models, services, APIs, UI, tests, and documentation remain consistent when their shared contract changes.
- Validation is proportional to risk: run focused tests first, then broader checks only when the affected scope justifies them.
- Update the product roadmap only when direction, stage status, acceptance evidence, or priority actually changes.

## Documentation Language

- Chinese product documents use “业务人员” and “技术人员（包含数据库工程师）”. After the first full mention, use “技术人员”.
- Describe `admin/user` as compatibility accounts, not product roles.
- Use “业务确认人（由业务人员承担）” for a confirmation responsibility; security, delivery, review, and Agent integration are responsibilities rather than new platform roles.
- Clearly distinguish “已实现”, “已有基础”, “计划中”, and “明确不包含”.
