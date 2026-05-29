# ResearchFlow-Agent

## 项目简介

ResearchFlow-Agent 是一个面向科研场景的多 Agent 智能研究助手平台，支持论文检索、文献分析、知识库问答、创新点生成和研究报告生成。

项目基于 FastAPI、LangGraph、LangChain、RAG、Redis、PostgreSQL、Celery 和 Vue 构建，目标是提供一个完整的科研辅助工作流系统。

## 功能特性

- 支持多 Agent 协同研究工作流
- 支持论文检索与文献分析
- 支持基于 RAG 的知识库问答
- 支持文档上传、解析、切分与向量化索引
- 支持研究报告生成
- 支持 Redis 记忆与检查点存储
- 支持 PostgreSQL 数据持久化
- 支持 Celery 异步任务处理
- 支持 Vue 前端交互界面
- 支持 Docker Compose 一键启动

## Agent 工作流

核心研究流程基于 LangGraph 构建。

```text
Planner -> Retriever -> Analyzer -> Critic -> Reporter
```

各 Agent 的职责如下：

```text
Planner    负责研究任务规划
Retriever  负责论文与知识库检索
Analyzer   负责文献分析与信息整合
Critic     负责结果评估与质量检查
Reporter   负责研究报告生成
```

当 Critic 评估分数较低时，系统可以触发重新规划，并继续迭代研究流程。

## 技术栈

| 模块 | 技术 |
|---|---|
| 后端服务 | FastAPI, Python |
| Agent 工作流 | LangGraph |
| Agent 工具调用 | LangChain |
| RAG 检索 | LlamaIndex, ChromaDB, BM25, Rerank |
| 记忆系统 | Redis |
| 数据库 | PostgreSQL, SQLAlchemy Async |
| 异步任务 | Celery, Redis Broker |
| 前端 | Vue 3, Pinia, Vite |
| 部署 | Docker Compose, Nginx |

## 项目结构

```text
backend/
  api/          API 路由与请求响应结构
  core/         核心配置、安全、日志、中间件
  database/     数据库连接、模型与迁移
  memory/       Redis 记忆与检查点逻辑
  models/       SQLAlchemy 数据模型
  rag/          RAG 文档处理、切分、检索与重排序
  tools/        内置科研工具
  worker/       Celery 异步任务
  workflow/     LangGraph 工作流与 Agent

frontend/
  src/          Vue 前端源码
  public/       静态资源
  package.json  前端依赖与脚本

requirements.txt
```

## 环境要求

### 本地开发环境

```text
Python 3.11+
Node.js 18+
PostgreSQL
Redis
```

### Docker 部署环境

```text
Docker
Docker Compose
```

## 环境变量

运行项目之前，需要在本地创建 `.env` 文件。

```env
OPENAI_API_KEY=your_openai_api_key
TAVILY_API_KEY=your_tavily_api_key

POSTGRES_URL=postgresql+asyncpg://researchflow:changeme@localhost:5432/researchflow
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1

CHROMA_PERSIST_DIR=./data/chroma
DEBUG=true
```

请不要提交真实 API Key、密钥或本地配置文件。

## 使用 Docker 启动

### 启动全部服务

```bash
docker compose up -d --build
```

### 查看容器状态

```bash
docker compose ps
```

### 查看全部日志

```bash
docker compose logs -f
```

### 查看后端 API 日志

```bash
docker compose logs -f api
```

### 查看 Celery Worker 日志

```bash
docker compose logs -f worker
```

### 停止服务

```bash
docker compose down
```

### 停止服务并删除数据卷

```bash
docker compose down -v
```

## Docker 启动后的访问地址

```text
前端页面 / Nginx: http://localhost
后端 API:        通过 Nginx 反向代理访问
PostgreSQL:      localhost:5432
Redis:           localhost:6379
```

## 本地启动

### 启动后端

安装 Python 依赖：

```bash
pip install -r requirements.txt
```

启动 FastAPI 服务：

```bash
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

### 启动前端

安装前端依赖：

```bash
cd frontend
npm install
```

启动前端开发服务：

```bash
npm run dev
```

前端开发服务默认访问地址：

```text
http://localhost:5173
```

## 构建前端

```bash
cd frontend
npm run build
```

## 开发说明

- 本地配置文件不要提交到仓库。
- API Key 和密钥应通过本地环境变量或 `.env` 文件管理。
- 测试文件、缓存文件、构建产物和依赖目录不应上传。
- 如果使用 Docker 部署，需要保留 Docker 相关文件。
- 如果仅上传运行源码，需要确保部署环境中具备对应的配置文件和启动脚本。

## 项目状态

```text
项目仍在持续开发中。
部分功能需要配合模型 API Key、PostgreSQL、Redis 和 Celery Worker 才能完整运行。
```
