# WenQu DataQuery Agent

English | [中文](./README_CN.md)

> An intelligent data query system built on LangGraph — ask questions in natural language, automatically generate SQL, execute queries, perform statistical analysis, and produce structured reports.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-0.4+-1a1a2e)
![Vue.js](https://img.shields.io/badge/Vue.js-3.5+-4FC08D?logo=vue.js&logoColor=white)
![MySQL](https://img.shields.io/badge/MySQL-8.0+-4479A1?logo=mysql&logoColor=white)
![Milvus](https://img.shields.io/badge/Milvus-2.5+-00A3E0)
![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Detailed Documentation](#detailed-documentation)
  - [Core Workflow](#1-core-workflow)
  - [Semantic Layer](#2-semantic-layer)
  - [Deep Analysis (Phase 3)](#3-deep-analysis-phase-3)
  - [Security](#4-security)
  - [Streaming & Frontend](#5-streaming--frontend)
  - [API Overview](#6-api-overview)
  - [Configuration](#7-configuration)
  - [Database Design](#8-database-design)
  - [Logging & Observability](#9-logging--observability)
  - [Development Guide](#10-development-guide)
- [Examples](#examples)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Natural Language Querying

Ask questions in natural language. The system automatically completes the full pipeline: intent recognition, semantic enhancement, knowledge recall, schema recall, SQL generation, query execution, statistical analysis, and report generation. Supports multi-turn conversation with contextual follow-ups and corrections.

### Semantic Layer Driven

Business logic is expressed through six types of semantic assets (concepts, relations, metrics, rules, mappings, templates). When the semantic layer is matched, SQL is deterministically compiled from a structured LogicForm — controllable metric definitions, traceable field mappings, and locatable errors. Falls back to constrained NL2SQL when unmatched.

### Deep Analysis & Reporting

SQL results are automatically fed into a Python sandbox for statistical analysis (distribution, trend, ranking, anomaly detection), then a structured Markdown report of at least 300 Chinese characters is generated with charts and data interpretation.

### Multi-Agent / Multi-Datasource / Multi-Model

Create multiple agents, each binding different datasources, LLMs, and embedding models. Data isolation and independent permissions between agents.

### Security

- JWT authentication with role-based access (admin / regular user)
- SQL safety validation (single read-only SELECT, dangerous keyword interception, LIMIT injection)
- Three-layer permission control (datasource authorization, table whitelist, column masking)
- Python executor isolation (AST validation, import whitelist, resource limits, containerization)
- Datasource passwords and model API keys encrypted at rest

### Streaming Interaction

Real-time SSE (Server-Sent Events) output lets users observe node execution progress, model reasoning, and intermediate results.

### Configurability

Prompt templates can be overridden per agent, model, and semantic domain. System parameters support runtime tuning of recall thresholds, executor settings, and more.

---

## Architecture

### System Architecture

![System Architecture](docs/images/architecture-en.png)

The system consists of a frontend management console, FastAPI backend, LangGraph query workflow, and external dependencies (LLM, MySQL, Milvus). The frontend communicates with the backend via REST API and SSE, while the backend orchestrates 16 processing nodes through LangGraph.

### Query Execution Flow

![Query Execution Flow](docs/images/workflow-en.png)

Full pipeline: User question → Intent Recognition → Semantic Enhancement → Knowledge Recall → Schema Recall → LogicForm Generation → Semantic Validation → SQL Compilation → Semantic Consistency Check → SQL Execution → Analysis Plan → Python Generation → Python Analysis → Report Generation.

### Semantic Layer Configuration

![Semantic Layer ER Diagram](docs/images/er-diagram-en.png)

An agent is the runtime entry point, binding datasources, models, and a semantic domain. Each semantic domain contains six asset types: concepts, relations, metrics, rules, mappings, and templates.

---

## Quick Start

### Prerequisites

| Dependency | Version | Notes |
|------------|---------|-------|
| Python | >= 3.11 | Backend runtime |
| Node.js | >= 18 | Frontend build |
| MySQL | >= 8.0 | Business + management databases |
| Milvus | >= 2.5 | Vector database (optional, supports local Lite mode) |
| uv | Latest | Python package manager (recommended) |

### 1. Clone the Project

```bash
git clone https://github.com/<your-org>/wenqu-dataquery-agent.git
cd wenqu-dataquery-agent
```

### 2. Start Dependencies

Use Docker Compose to start MySQL and Milvus:

```bash
docker compose up -d
```

This starts:
- **MySQL 8.0** — Port 3306, auto-creates management database `dataquery_agent` with schema and sample data
- **Milvus 2.5** — Port 19530, local storage mode

### 3. Backend Setup

```bash
# Copy environment config
cp .env.example .env

# Edit .env — at minimum configure:
# - LLM_BASE_URL / LLM_API_KEY / LLM_MODEL (LLM)
# - EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL (embedding model)
# - MYSQL_* / MANAGEMENT_MYSQL_* (database connections, defaults work out of the box)

# Install Python dependencies
uv sync

# Start backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 4400 --reload
```

The backend automatically runs database migrations on startup, creating management tables and seeding default configurations.

### 4. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173` by default, backend API at `http://localhost:4400`.

### 5. Import Demo Data (Optional)

**Loan Risk domain:**

```bash
# Create demo tables and data
uv run python examples/loan/seed_loan_indicators.py

# Import semantic layer assets
uv run python scripts/import_semantic_bundle.py --path examples/loan/semantic-domain.json
```

**Douyin E-commerce domain:**

```bash
uv run python examples/douyin_ecommerce/seed_douyin_ecommerce.py
```

### 6. Verify

Open `http://localhost:5173`, register an account, get authorized for an agent in Agent Management, then ask a question in the Chat page:

```
What are the top 3 application regions by loan count, and how many applications did each have?
```

Observe the node execution process, SQL generation, and final analysis report in the analysis pipeline.

---

## Detailed Documentation

### 1. Core Workflow

The query pipeline is orchestrated by a LangGraph StateGraph with 16 processing nodes:

| Node | File | Function | Calls LLM |
|------|------|----------|-----------|
| `intent_recognition` | `nodes/intent.py` | Intent classification: rule-based keywords + LLM fallback. Types: data_query/chat/metadata_query | Not always |
| `semantic_enhance` | `nodes/semantic_enhance.py` | Rewrites the original question into a clearer business query, filling in omitted metrics, dimensions, and TopN | Yes |
| `semantic_runtime_recall` | `nodes/semantic_runtime_recall.py` | Loads semantic assets, vector recall for relevant metrics, dimensions, and rules | Vector recall |
| `schema_recall` | `nodes/schema_recall.py` | Recalls candidate tables, columns, and JOIN hints from collected schema and semantic assets | No |
| `clarification` | `nodes/clarification.py` | Low-confidence clarification: when no candidate tables found, guides user to specify business object, time range, or metric | Yes |
| `nl2lf_generate` | `nodes/nl2lf_generate.py` | LogicForm generation: natural language → structured query intent (metrics/dimensions/filters/sort/limit) | Yes |
| `lf_validate` | `nodes/lf_validate.py` | Semantic validation: checks if metrics, dimensions, filters, and time ranges in the LogicForm are valid | No |
| `lf_repair` | `nodes/lf_repair.py` | LF repair: removes unsupported dimensions, unknown metrics, or unresolvable time ranges | No |
| `lf_to_sql_compile` | `nodes/lf_to_sql_compile.py` | SQL compilation: deterministically compiles LogicForm into MySQL SELECT | No |
| `nl2sql_fallback` | `nodes/nl2sql_fallback.py` | NL2SQL fallback: when semantic layer misses, LLM generates read-only SQL based on candidate schema | Yes |
| `semantic_check` | `nodes/analysis_pipeline.py` | Semantic consistency check: verifies compiled SQL faithfully represents the LogicForm | No |
| `sql_confirmation` | `nodes/human_confirm.py` | Execution confirmation: human-in-the-loop, waits for user to confirm SQL execution | No |
| `sql_execute` | `nodes/sql_execute.py` | SQL execution: safety validation → permission check → execute → mask sensitive columns → format results | No |
| `planner` | `nodes/analysis_pipeline.py` | Analysis plan: profiles result data, infers analysis mode, generates analysis steps | No |
| `python_generate` | `nodes/analysis_pipeline.py` | Python generation: LLM generates pandas analysis script, AST security validation, fallback to safe template | Yes |
| `python_analyze` | `nodes/analysis_pipeline.py` | Python analysis: executes script in restricted subprocess, supports multi-round LLM-based repair | On repair |
| `report_generator` | `nodes/analysis_pipeline.py` | Report generation: LLM streams Markdown report, fallback to template report | Yes |

#### Conditional Routing

```mermaid
flowchart TD
    A[Intent Recognition] -->|data_query| B[Semantic Enhancement]
    A -->|chat/metadata| END[End]
    B --> C[Knowledge Recall]
    C --> D[Schema Recall]
    D -->|has candidates| E[LogicForm Generation]
    D -->|no candidates + clarify enabled| F[Clarification]
    F --> END
    E --> G[Semantic Validation]
    G -->|valid| H[SQL Compilation]
    G -->|invalid| I[NL2SQL Fallback]
    H -->|compiled| J[Semantic Check]
    H -->|failed| I
    J -->|valid| K[SQL Execution]
    J -->|repairable| L[LF Repair]
    J -->|invalid| END
    L --> G
    I -->|compiled| K
    I -->|needs confirmation| M[SQL Confirmation]
    I -->|failed| END
    K -->|success| N[Analysis Plan]
    K -->|retry| L
    K -->|failed| END
    N --> O[Python Generation]
    O --> P[Python Analysis]
    P --> Q[Report Generation]
    Q --> END
```

### 2. Semantic Layer

The semantic layer is the core design of WenQu, expressing business logic through structured assets to prevent unconstrained SQL generation by LLMs.

#### Six Semantic Asset Types

| Asset Type | Description | Example |
|------------|-------------|---------|
| **Concept** | Business term definitions with synonyms | `loan_application` — synonyms: application, intake |
| **Relation** | JOIN paths and business relationships between tables | `loan_to_applicant`: loan_application → customer |
| **Metric** | Computable business measures with formula SQL | `application_count`: COUNT(\*), grouped by region |
| **Rule** | Business rules: rewrite, normalization, logic_form | TopN follow-up completion rule, count correction rule |
| **Mapping** | Maps semantic assets to physical table columns | `application_count` → `loan_application_indicator.id` (COUNT) |
| **Template** | Predefined query intent skeletons | Ranking template: required_slots = [metric, rank_count] |

#### LogicForm Structure

LogicForm is the core intermediate representation connecting natural language and SQL:

```json
{
  "metrics": ["application_count"],
  "dimensions": ["application_region"],
  "filters": [
    {"field": "application_date", "operator": ">=", "value": "2024-01-01"}
  ],
  "time_range": {"period": "last_3_months"},
  "sort": [{"field": "application_count", "direction": "desc"}],
  "limit": 3
}
```

#### Compilation Strategy

**Same-table mode (normal)**: All metrics share one `base_table`. Dimensions and filters are resolved through mappings. Relations are used to auto-derive JOIN conditions:

```sql
SELECT t0.`region` AS `application_region`, COUNT(*) AS `application_count`
FROM `loan_application_indicator` t0
WHERE t0.`created_at` >= '2024-01-01'
GROUP BY t0.`region`
ORDER BY `application_count` DESC
LIMIT 3
```

**Cross-table scalar mode**: When metrics span different fact tables, each metric generates an independent scalar subquery with its own filters, CROSS JOINed into a single row:

```sql
SELECT
  (SELECT COUNT(*) FROM loan_application_indicator) AS application_count,
  (SELECT SUM(amount) FROM loan_disbursement) AS total_disbursement
```

### 3. Deep Analysis (Phase 3)

After SQL execution, results are automatically fed into the deep analysis pipeline:

```mermaid
flowchart LR
    SQL[SQL Result Set] --> PLAN[Planner<br/>Analysis Plan]
    PLAN --> PYGEN[PythonGenerate<br/>Script Generation]
    PYGEN --> CHECK[Safety Validation<br/>AST/Import/Output]
    CHECK --> EXEC[Safe Executor]
    EXEC --> PYANA[PythonAnalyze<br/>Result Structuring]
    PYANA --> REPORT[ReportGenerator<br/>Markdown Report]
```

#### Analysis Modes

The Planner automatically infers analysis mode based on result data characteristics:

| Mode | Trigger | Analysis Content |
|------|---------|-----------------|
| Ranking | Dimension column + sorting | TopN bar chart, proportion pie chart |
| Trend | Time column + numeric column | Line chart, period-over-period change, trend detection |
| Distribution | Category column + numeric column | Histogram, box plot, concentration analysis |
| Anomaly | Numeric values deviate significantly from mean | Anomaly marking, root cause analysis |
| Profile | General scenario | Basic statistics, dimension samples, null analysis |

#### Python Executor Safety Mechanisms

| Layer | Measures |
|-------|----------|
| Code Validation | AST parsing: module whitelist (json/math/pandas etc.), banned open/exec/eval/import |
| Process Isolation | `python -I` (isolated mode), temp working directory, no user site-packages |
| Resource Limits | Timeout (default 15s), memory (default 512MB), CPU limits |
| Containerization | Docker/containerd: `--network none`, `--pids-limit 128`, read-only mount |
| High Security | Firecracker microVM via external runner |

#### Report Structure

```json
{
  "markdown": {"body": "Streamed Markdown body (>= 300 chars)"},
  "summary": "Extracted summary from body",
  "charts": [{"type": "bar", "data": {...}, "echarts_option": {...}}],
  "tables": [{"title": "Derived table", "columns": [...], "rows": [...]}],
  "python_result": {"insights": [...], "charts": [...], "tables": [...], "metrics": {...}},
  "generation_source": "llm_report_generator | fallback_template"
}
```

### 4. Security

#### Authentication & Authorization

- **JWT-based auth**: Register/login to obtain access_token, all API requests carry Bearer Token
- **Roles**: Admin (full access), Regular User (per-agent authorization)
- **Session isolation**: Chat history is user-scoped, regular users only see authorized agents

#### SQL Safety

Pre-execution validation via `normalize_sql_for_execution`:

| Check | Description |
|-------|-------------|
| Single SELECT | Only single read-only SELECT statements allowed |
| Dangerous keywords | DROP/INSERT/UPDATE/DELETE/UNION/ALTER/CREATE/TRUNCATE blocked |
| Dangerous functions | SLEEP/LOAD_FILE/BENCHMARK/INTO OUTFILE/DUMPFILE blocked |
| System databases | mysql/information_schema/performance_schema/sys blocked |
| Cross-database | Refuses tables outside current datasource |
| LIMIT injection | Auto-injects LIMIT 1000 when missing, truncates when exceeding |
| MySQL keywords | PREPARE/EXECUTE/DEALLOCATE/LOAD DATA etc. blocked |

#### Three-Layer Permission Control

```mermaid
flowchart LR
    subgraph Layer1[Layer 1: Datasource Authorization]
        A1[Agent A] -->|binds| D1[Datasource 1]
        A1 -->|binds| D2[Datasource 2]
        A2[Agent B] -->|binds| D3[Datasource 3]
    end

    subgraph Layer2[Layer 2: Table Permissions]
        T1[Table Whitelist/Blacklist]
    end

    subgraph Layer3[Layer 3: Column Permissions & Masking]
        C1[Column Allow/Deny]
        M1[Masking Policies]
    end

    Layer1 --> Layer2 --> Layer3
```

| Layer | Granularity | Storage Table |
|-------|-------------|---------------|
| Datasource Authorization | Agent ↔ Datasource | `agent_datasource` |
| Table Permissions | Allow/deny specific tables | `agent_table_permission` |
| Column Permissions | Allow/deny + masking policy | `agent_column_permission` |

**Masking Policies**:

| Policy | Effect | Example |
|--------|--------|---------|
| `none` | No masking (default) | `13812345678` → `13812345678` |
| `redact` | Full redaction | `13812345678` → `***` |
| `partial` | Keep first 2 and last 2 chars | `13812345678` → `13****78` |
| `hash` | SHA-256 hash, first 12 hex chars | `13812345678` → `a1b2c3d4e5f6` |

#### API Key Encryption

Datasource passwords and model API keys are stored as `enc:v1:` prefixed ciphertext. Legacy plaintext data is compatible on read and automatically encrypted on next save.

### 5. Streaming & Frontend

#### SSE Event Flow

```mermaid
sequenceDiagram
    participant FE as Frontend ChatView
    participant API as /api/chat/stream
    participant G as LangGraph
    participant LLM as LLM
    participant DB as Business DB

    FE->>API: Submit question
    API->>G: Start workflow
    G-->>API: node_start (Intent Recognition)
    API-->>FE: node_start
    G->>LLM: Semantic Enhancement
    LLM-->>G: Enhanced question
    G->>LLM: LogicForm Generation
    LLM-->>G: token / reasoning
    G-->>API: token / reasoning
    API-->>FE: token / reasoning (streaming)
    G-->>API: node_complete
    API-->>FE: node_complete
    G->>DB: SQL Execution
    DB-->>G: rows
    G->>LLM: Report Generation
    LLM-->>G: Markdown streaming body
    G-->>API: report_payload
    API-->>FE: answer_delta / result / done
```

#### SSE Event Types

| Event | Description | Data Fields |
|-------|-------------|-------------|
| `node_start` | Node starts executing | `node`, `label` |
| `node_progress` | Node execution progress | `node`, `label`, `message` |
| `node_complete` | Node execution complete | `node`, `label`, `output` |
| `reasoning` | Model reasoning process | `node`, `label`, `delta` |
| `token` | Streaming output content | `node`, `delta` |
| `answer_start` | Final answer begins | `session_id` |
| `answer_delta` | Final answer increment | `session_id`, `delta` |
| `answer_complete` | Final answer complete | `session_id`, `answer` |
| `result` | Full result (JSON) | All fields |
| `error` | Exception | `error_type`, `error_category`, `message` |
| `done` | End | `{}` |

#### Frontend Pages

| Page | Route | Function |
|------|-------|----------|
| Chat | `/` | Main query interface with analysis pipeline, SQL, result table, and report display |
| Agent Management | `/agent` | Create/edit/delete agents, bind datasources, models, and semantic domains |
| Model Config | `/model-config` | Manage LLM and embedding model configurations, test connectivity |
| Datasource | `/datasource` | Datasource connection management, table schema collection, field details |
| Knowledge | `/knowledge` | Semantic layer configuration: concepts, relations, metrics, rules, mappings, templates |
| System Parameters | `/system-parameter` | System parameters, Prompt templates, user management |
| Login | `/login` | User login |
| Register | `/register` | User registration |

**Tech Stack**: Vue 3 + TypeScript + Element Plus + Vite + ECharts

### 6. API Overview

The backend provides REST APIs in the following categories:

| Category | Prefix | Description |
|----------|--------|-------------|
| Health | `/health` | Service health check |
| Chat | `/api/chat` | Sync/streaming queries, SQL confirmation, session management |
| Auth | `/api/auth` | Register, login, current user |
| Agent | `/api/agent` | Agent CRUD, datasource binding |
| Datasource | `/api/datasource` | Datasource CRUD, connectivity test, schema collection |
| Semantic | `/api/semantic` | Domain/asset management, snapshot versioning, import/export, vector sync |
| Model Config | `/api/model-config` | Model CRUD, connectivity test |
| Prompt | `/api/prompt` | Prompt template management, catalog |
| System | `/api/system` | Runtime parameter configuration |
| User Management | `/api/users` | User CRUD, permission management |
| Feedback | `/api/feedback` | User feedback collection |

All `/api/*` endpoints (except `/api/auth/login` and `/api/auth/register`) require Bearer Token authentication. `/health` is publicly accessible.

### 7. Configuration

Configured via `.env` file or environment variables. All configurations have sensible defaults:

#### LLM

> **Note**: These are fallback defaults used when an agent has no model configuration bound via the management UI. Once you bind a dedicated model to an agent through "Model Config", that binding takes priority. For quick local development, these env vars are the only model source.

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | Provider: ollama/deepseek/mimo/minimax |
| `LLM_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible Base URL |
| `LLM_API_KEY` | `ollama` | API Key |
| `LLM_MODEL` | `qwen3:14b` | Model name |

#### Embedding Model

> **Note**: Same as above — fallback defaults. Agent-bound embedding model config takes priority.

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible Base URL |
| `EMBEDDING_API_KEY` | - | API Key |
| `EMBEDDING_MODEL` | `embedding-3` | Model name |

#### MySQL

| Variable | Default | Description |
|----------|---------|-------------|
| `MYSQL_HOST` | `127.0.0.1` | Business DB host |
| `MYSQL_PORT` | `3306` | Business DB port |
| `MYSQL_USER` | `root` | Business DB user |
| `MYSQL_PASSWORD` | `root` | Business DB password |
| `MYSQL_DATABASE` | `business_db` | Business DB name |
| `MANAGEMENT_MYSQL_HOST` | `127.0.0.1` | Management DB host |
| `MANAGEMENT_MYSQL_DATABASE` | `dataquery_agent` | Management DB name |

#### Milvus

| Variable | Default | Description |
|----------|---------|-------------|
| `MILVUS_URI` | `./data/milvus.db` | Milvus address or local file path |
| `MILVUS_COLLECTION` | `dataquery_knowledge` | Collection name |

#### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `APP_HOST` | `0.0.0.0` | Listen address |
| `APP_PORT` | `4400` | Listen port |
| `DEBUG` | `true` | Debug mode |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:4399,...` | CORS allowed origins (comma-separated) |

#### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_API_KEY` | - | API auth key (required in production) |
| `JWT_SECRET_KEY` | - | JWT signing key (production >= 32 bytes) |
| `SECRET_ENCRYPTION_KEY` | - | Encryption key for secrets (required in production) |
| `INITIAL_ADMIN_USERNAME` | - | Initial admin username |
| `INITIAL_ADMIN_PASSWORD` | - | Initial admin password |
| `API_RATE_LIMIT_PER_MINUTE` | `120` | Requests per minute limit |
| `CHAT_STREAM_MAX_CONCURRENT` | `8` | Max concurrent streaming sessions |

#### Schema Recall

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEMA_RECALL_MAX_TABLES` | `6` | Max candidate tables |
| `SCHEMA_RECALL_REQUIRED_SCORE_RATIO` | `0.35` | Required recall score ratio |
| `SCHEMA_RECALL_OPTIONAL_SCORE_RATIO` | `0.15` | Optional recall score ratio |

#### Python Executor

| Variable | Default | Description |
|----------|---------|-------------|
| `PYTHON_EXECUTOR_BACKEND` | `local` | Backend: local/worker/docker/containerd/firecracker |
| `PYTHON_EXECUTOR_TIMEOUT_SECONDS` | `15` | Execution timeout |
| `PYTHON_EXECUTOR_MEMORY_MB` | `512` | Memory limit |

#### Production Safety Checks

When `DEBUG=false`, the following conditions must be met or startup is refused:
- `JWT_SECRET_KEY` length >= 32 bytes
- `SECRET_ENCRYPTION_KEY` is configured
- MySQL passwords are not the default `root`

### 8. Database Design

#### Management Database (`dataquery_agent`)

Stores system configuration, metadata, and session history:

| Category | Tables | Description |
|----------|--------|-------------|
| Agent | `agent` | Agent configuration, model and semantic domain bindings |
| Model | `model_config` | LLM and embedding model configurations |
| Datasource | `datasource` | Database connection info |
| Association | `agent_datasource` | Agent ↔ Datasource many-to-many |
| Permissions | `agent_table_permission`, `agent_column_permission` | Table/column access control |
| Metadata | `meta_table`, `meta_column` | Collected table schemas |
| Semantic Layer | `semantic_domain`, `semantic_domain_snapshot` | Domains and version snapshots |
| Semantic Layer | `semantic_concept`, `semantic_relation`, `semantic_metric` | Concepts, relations, metrics |
| Semantic Layer | `semantic_rule`, `semantic_mapping`, `logic_form_template` | Rules, mappings, templates |
| Prompt | `prompt_template` | Prompt templates |
| Chat | `chat_history` | Chat history (includes reasoning_trace, report_payload) |
| Feedback | `user_feedback` | User feedback |
| System | `system_parameter` | Runtime parameters |
| User | `app_user`, `user_agent_permission` | Users and agent permissions |

#### Migration Strategy

Uses **idempotent auto-migration** at application startup:

- `CREATE TABLE IF NOT EXISTS` for table creation
- Query `INFORMATION_SCHEMA` then `ALTER TABLE ADD COLUMN` as needed
- Query `INFORMATION_SCHEMA` then `CREATE INDEX` as needed
- Default data seeding (model configs, system parameters, prompt templates, initial admin)
- Historical data backfill (model bindings, semantic domain associations, example questions)

All migration operations are idempotent and reentrant, with no version tracking or rollback mechanism (forward-compatible only).

### 9. Logging & Observability

#### Logging Configuration

| Item | Configuration |
|------|---------------|
| Log file | `logs/backend.log` |
| Rotation | 10MB per file, 5 backup files |
| Format | `%(asctime)s %(levelname)s [%(name)s] %(message)s` |
| Encoding | UTF-8 |

#### Observability

| Dimension | Description |
|-----------|-------------|
| `trace_id` | Spans SSE events, execution traces, history results, and error responses |
| Node timing | Start/end time recorded per node |
| SQL execution | Duration, slow query flag (>2s), row count |
| LLM call log | Model name, message count, char count, cache hit |
| Error classification | permission/sql/timeout/llm/runtime categories |
| Streaming event log | SSE events logged in compacted form |

### 10. Development Guide

#### Project Structure

```
wenqu-dataquery-agent/
├── app/                          # Backend application
│   ├── main.py                   # FastAPI entry, SSE streaming
│   ├── config.py                 # Pydantic Settings
│   ├── security.py               # Auth middleware & rate limiting
│   ├── logging_config.py         # Logging configuration
│   ├── agent/                    # LangGraph query pipeline
│   │   ├── graph.py              # Workflow definition & routing
│   │   ├── nodes/                # 16 processing nodes
│   │   ├── prompts/              # Default prompt templates
│   │   ├── python_templates/     # Python fallback analysis scripts
│   │   └── domain_rules.py       # Domain rewrite rules
│   ├── api/                      # REST API routes
│   ├── services/                 # Business logic services
│   ├── models/                   # Pydantic data models
│   ├── db/                       # Database schema, migrations, SQL
│   └── utils/                    # Utility functions
├── frontend/                     # Frontend application
│   ├── src/
│   │   ├── views/                # Page components
│   │   ├── components/           # Shared components
│   │   ├── stores/               # Pinia state management
│   │   ├── api/                  # API client
│   │   └── router/               # Route configuration
│   └── package.json
├── docs/                         # Documentation
│   ├── project-design.md         # Project design document
│   ├── TODO.md                   # Development progress
│   ├── design-qa.md              # Design QA records
│   └── images/                   # Architecture diagrams
├── examples/                     # Demo data
│   ├── loan/                     # Loan risk domain
│   └── douyin_ecommerce/         # Douyin e-commerce domain
├── scripts/                      # Utility scripts
├── tests/                        # Test cases
├── docker-compose.yml            # Dependency orchestration
├── pyproject.toml                # Python project config
├── .env.example                  # Environment variable template
└── uv.lock                       # Python dependency lock
```

#### Testing

```bash
# Backend tests
uv run pytest -q

# Frontend tests
npm --prefix frontend test

# Frontend build
npm --prefix frontend run build
```

#### Code Quality

```bash
# Python lint
uv run ruff check .

# Python format
uv run ruff format .
```

#### Adding a New Node

1. Create node file in `app/agent/nodes/`
2. Implement `async def xxx_node(state: AgentState) -> dict`
3. Register node and edges in `app/agent/graph.py`
4. Add Chinese label in `app/main.py` `NODE_LABELS`
5. Add prompt template in `app/agent/prompts/` (if calling LLM)
6. Register in `app/agent/prompts/__init__.py` `PROMPT_CATALOG`

---

## Examples

### Loan Risk

```bash
uv run python examples/loan/seed_loan_indicators.py
uv run python scripts/import_semantic_bundle.py --path examples/loan/semantic-domain.json
```

Example queries:
- What are the top 3 application regions by loan count, and how many applications did each have?
- Monthly application count trend for the last 3 months
- Average disbursement amount by loan product
- Collection recovery rate for high-PD customers

### Douyin E-commerce

```bash
uv run python examples/douyin_ecommerce/seed_douyin_ecommerce.py
```

Example queries:
- GMV trend by category for the last 3 months
- Top 10 creators by GMV and their transaction amounts
- Order count and GMV by transaction channel
- Ad spend, attributed GMV, and ROI by campaign type

---

## Roadmap

- [ ] SQL AST safety validation enhancement (dedicated parsing library)
- [ ] Prompt template versioning and hit statistics
- [ ] Multi-datasource type support (PostgreSQL, ClickHouse)
- [ ] Fine-grained permission audit logging
- [ ] One-click Docker deployment
- [ ] CI/CD pipeline (GitHub Actions)

---

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork this repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m 'Add your feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Create a Pull Request

Please ensure:
- Backend tests pass: `uv run pytest -q`
- Frontend tests pass: `npm --prefix frontend test`
- Code passes lint: `uv run ruff check .`

---

## License

This project is licensed under the [Apache License 2.0](./LICENSE).

Copyright 2026 WenQu DataQuery Agent Contributors
