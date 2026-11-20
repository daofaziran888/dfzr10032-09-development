# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 | 报告编号、采集源、统计周期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 解析与转换计算

格式解析配置表（`parser`）只描述字段映射、类型转换和空值处理，本身不含事件明细。
事件解析与转换计算在这之上补了两条链路：

```text
_raw_events ──按解析配置逐字段转换──> 标准化事件明细 ──按表达式字段依赖──> 转换结果 / 阻断记录
                        （保留原始行号）                    （都关联原始事件）
```

- 原始事件：`GET /api/parser/events/raw?config=PARS-0004`，按解析配置读取，
  保留文件行号（表头第 1 行，数据从第 2 行起）与源字段原文。
- 标准化明细：`GET /api/parser/events?config=PARS-0004`，每个字段单独记录
  `ok` / `missing` / `invalid`：
  - `missing`：源数据原本就没有提供值（空串、`-`、`NULL` 等空值标记）；
  - `invalid`：提供了值但无法按目标类型转换（例如重量写成「复秤中」）。
  两者分开计数，不做合并。
- 转换计算：`GET /api/transform/calculate?config=PARS-0004[&expression=EXPR-0002]`，
  每条计算记录归属为：

  | 归属 | 含义 |
  | --- | --- |
  | `未纳入` | 不满足表达式的纳入条件，本来就不参与统计 |
  | `被阻断` | 参与统计需要的字段转换失败，生成阻断记录 |
  | `正常产出` | 依赖字段全部可用，按分组计入聚合结果 |

  可选依赖字段失败同样阻断：这类字段通常用于限定统计范围，取不到值时继续计算
  会悄悄改变下游收到的数据范围。

样例数据（`backend/app/seed_events.py`）是一条地磅称重明细：第 3 行时间合法但重量是
「复秤中」。`EXPR-0001`（按小时汇总到货次数）只依赖 `event_time`，该行正常产出；
`EXPR-0002`（按重量算运量）必填 `weight_kg`、`EXPR-0003`（按站点汇总入库车次）
把 `weight_kg` 列为可选依赖，两者都会把该行标为被阻断，并指回原始行号 3。

前端页面：

- `/parser/events` 标准化事件明细：逐字段展示转换结果、查看原始事件、重新标准化。
- `/transform/calculate` 转换计算结果：按表达式展示正常产出/被阻断/未纳入，
  计算记录可展开查看原文与阻断原因。

内部表 `_parse_config`、`_raw_events`、`_normalized_events`、`_transform_expressions`
以下划线开头，不计入运营概览的模块统计。
