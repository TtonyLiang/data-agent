# Ontology 开源项目调研与选型

检索日期：2026-08-29。数据来自各项目 GitHub 仓库公开 API；star、fork 和最近推送时间会随时间变化，不能替代正式的供应链安全审查。

## 结论

V1 保留 WenQu 当前的 FastAPI + MySQL + Vue 运行时。Ontology 的对象、关系、动作、权限和审计是业务产品能力，不能由数据目录或图数据库直接替代。开源项目按边界作为契约、元数据或图查询侧车引入。

## 候选比较

| 项目 | 许可证 | 公开活跃度（检索时） | 能复用什么 | 决策 |
|---|---|---:|---|---|
| [LinkML](https://github.com/linkml/linkml) | Apache-2.0 | 603 stars，2026-08-28 推送 | YAML linked-data schema，生成 JSON Schema、Pydantic、SQL、SHACL、OWL，并可做 CI 校验 | P1 企业模型中心做 schema source-of-truth PoC |
| [OpenMetadata](https://github.com/open-metadata/OpenMetadata) | Apache-2.0 | 15,022 stars，2026-08-28 推送 | Glossary、指标、Ownership、血缘、策略、连接器、MCP context | P2 孪生运行时作为治理侧车候选 |
| [DataHub](https://github.com/datahub-project/datahub) | Apache-2.0 | 12,608 stars，2026-08-28 推送 | 技术元数据、Glossary、Lineage、MetadataChangeEvent、130+ connectors | P2 与 OpenMetadata 二选一 |
| [TerminusDB](https://github.com/TerminusDB/terminusdb) | Apache-2.0 | 3,399 stars，2026-08-10 推送 | JSON-LD、revision、diff、branch、time-travel、REST/GraphQL | 借鉴版本治理；需要强版本化时 sidecar |
| [TypeDB](https://github.com/typedb/typedb) | MPL-2.0 | 4,430 stars，2026-08-28 推送 | 强类型 entity/relation/attribute、继承、事务和多跳 TypeQL | 图查询瓶颈验证后 benchmark，不替换 V1 |
| [Ontop](https://github.com/ontop/ontop) | Apache-2.0 | 930 stars，2026-07-13 推送 | R2RML 虚拟知识图谱、SPARQL 到关系库 SQL | 需要标准 RDF 出口时 sidecar |
| [RMLMapper](https://github.com/RMLio/rmlmapper-java) | MIT | 202 stars，2026-02-17 推送 | CSV/JSON/XML/Excel/RDB/API 到 RDF/JSON-LD 离线映射 | 离线迁移工具，不进在线动作链路 |
| [OpenSPG](https://github.com/OpenSPG/openspg) | Apache-2.0 | 2,221 stars，2025-07-05 推送 | 中文实体对齐、SPG schema、规则推理和知识构建 | 借鉴设计，后续专项 PoC |
| [Baserow](https://github.com/baserow/baserow) | MIT（部分商业模块另行授权） | 5,743 stars，2026-08-28 推送 | 表格、实例编辑和低代码 UX | 仅借鉴交互，不引入 Django/PostgreSQL 核心 |
| [NocoDB](https://github.com/nocodb/nocodb) | Sustainable Use License | 64,774 stars，2026-08-28 推送 | 表格和 API 交互思路 | 不复用代码，许可证不适合商业嵌入 |

## 集成边界

### LinkML

将 `OntologyObjectTypePayload`、`OntologyProperty`、`OntologyActionTypePayload` 等映射为 LinkML classes，生成 JSON Schema/Pydantic/SHACL 作为开发期契约。动作的 `parameters/preconditions/effects` 需要自定义类扩展；LinkML 不提供运行时动作执行器。

### OpenMetadata 或 DataHub

仅异步同步技术元数据、术语、Owner 和 lineage，携带领域与 release 版本。不要把其元数据图模型硬塞进本项目对象运行时，也不要让外部目录承担 Action 写回和审批。

### TypeDB 或 TerminusDB

通过 adapter 维护对象/关系读写 benchmark。只有在多跳查询、图事务或分支合并的真实指标不满足 MySQL 方案时才引入服务依赖。MPL-2.0 和外部数据库运维成本需要纳入 SBOM 与部署评审。

### Ontop / RMLMapper

作为标准 RDF/JSON-LD 交换、一次性迁移或只读虚拟图谱出口；在线 Action 执行继续使用本项目权限、事务和审计链路。

## 引入门槛

任何依赖进入主干前必须完成：许可证核验、SBOM、漏洞扫描、数据迁移回滚方案、接口 benchmark，以及与现有认证/权限/审计的集成测试。
