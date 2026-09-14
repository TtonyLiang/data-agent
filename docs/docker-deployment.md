# Docker 部署说明

> 适用版本：内部 1.0 试点

本部署方式把 WenQu 后端和前端放入 Docker，连接公司已有的 MySQL。Compose **不会启动、初始化或覆盖业务 MySQL**；管理库使用同一 MySQL 实例时，需由数据库管理员预先创建独立的 `dataquery_agent` 数据库并授予应用账号权限。

## 1. 准备配置

复制配置并填写真实值：

```bash
cp .env.example .env
```

容器内不能把业务数据库地址写成 `127.0.0.1`（那是容器自身）。

- 如果 MySQL 在宿主机：Mac/Windows 使用 `host.docker.internal`；Linux 可使用宿主机 IP。
- 如果 MySQL 在公司网络：填写数据库服务器的内网主机名或 IP。
- `MYSQL_DATABASE` 填已有业务库；`MANAGEMENT_MYSQL_DATABASE` 填平台管理库，建议为独立的 `dataquery_agent`。

首次部署由管理员（当前项目开发者）预置：

- `INITIAL_ADMIN_USERNAME`
- `INITIAL_ADMIN_PASSWORD` 或 `INITIAL_ADMIN_PASSWORD_HASH`
- `JWT_SECRET_KEY`（至少 32 字节）
- `SECRET_ENCRYPTION_KEY`

部署包会把 `DEBUG=false` 写入 Compose，覆盖 `.env` 里的开发值。账号由技术人员在系统参数中创建，不开放自助注册。不要把密码、API Key 提交到 Git。

## 2. 启动平台

```bash
docker compose -f docker-compose.deploy.yml up -d --build
```

启动后：

- 前端：`http://<服务器地址>:4399`
- 后端探活：`http://<服务器地址>:4400/health`

查看状态和日志：

```bash
docker compose -f docker-compose.deploy.yml ps
docker compose -f docker-compose.deploy.yml logs -f backend
```

首次启动时，后端会对管理库执行幂等迁移。迁移前请备份管理库；当前迁移机制是前向兼容，没有数据库级回滚。

## 3. 向量服务

默认使用后端容器持久卷中的 Milvus Lite 文件，不需要额外容器，也不会受开发环境 `.env` 中 `MILVUS_URI` 的 `127.0.0.1` 配置影响。若公司已有 Milvus，在 `.env` 中增加 `WENQU_DEPLOY_MILVUS_URI`，填写容器可访问的地址后重启 backend。

现有的 `docker-compose.yml` 仍用于本地演示依赖（MySQL + Milvus），不用于连接公司的现有业务库；交付部署使用 `docker-compose.deploy.yml`。

## 4. 停止与升级

```bash
docker compose -f docker-compose.deploy.yml down
docker compose -f docker-compose.deploy.yml up -d --build
```

不要执行 `down -v`，除非已确认要删除平台的 `wenqu_data` 和 `wenqu_logs` 持久卷。升级前先备份管理库，并在升级后检查 `/health`、登录、业务领域、active release 和孪生运行页面。

## 5. 1.0 交付边界

此部署包面向公司内部试点，包含企业模型、数据绑定、校验发布、手动孪生运行、外部只读 Query 和内置验证 Agent。CDC、后台增量同步、外部 Action/Decision、SDK、配额和生产网关不属于本次 1.0 部署承诺。
