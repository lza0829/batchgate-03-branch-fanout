# 02-batchgate（闸序）

Batchgate — 离线作业依赖编排：作业定义 → 依赖就绪检查 → 条件分支选路 → 执行/失败 → 产出水位与对账。

与 Feedstitch（多源 Feed 归并）主链路不同，禁止做成 Feed 解析/冲突/回看换皮。

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:5200 |
| API | http://localhost:10200 |

## 主链

配置作业、依赖与分支条件 → 触发一次编排 Run → 先过依赖就绪闸，再按上游产出评估分支条件 →
选中的作业执行夹具、写尝试记录与产出水位 → 报告与尝试列表逐项对账

## 条件分支

分支条件与依赖边是两层概念，互不替代：

- **依赖边 `depends_on`**：回答“能不能跑”——上游必须在本趟成功产出，未就绪记 `skipped_dep`。
- **分支条件 `branch_conditions`**：回答“该不该跑”——基于上游实际产出求值，不满足记
  `skipped_branch` 旁路，**夹具不会被执行**。
- **互斥组 `mutex_group`**：同一编排内同组只允许一个下游执行，先被选中者占位，其余记
  `skipped_mutex`（详情里记录占用者）。

支持的条件（多条 AND 组合，条件引用的上游必须出现在 `depends_on` 中）：

| type | 形态 | 说明 |
| --- | --- | --- |
| `rows` | `{type:"rows", upstream, op, value}` | 比较上游 `artifact_rows` 与整数阈值，op：`gte/lte/gt/lt/eq/ne` |
| `flag` | `{type:"flag", upstream, flag, op, value}` | 比较上游夹具摘要 `flags` 里的约定布尔标志，op：`eq/ne` |

配置入口：`PUT /api/jobs/{id}/branch-config`，或前端「作业」页的分支配置编辑器。

## 尝试状态与对账

| 状态 | 含义 | 是否跑夹具 | 是否推进水位 |
| --- | --- | --- | --- |
| `success` | 执行成功 | 是 | 是 |
| `failed` | 执行失败 | 是 | 否 |
| `skipped_branch` | 分支条件未命中，旁路 | 否 | 否 |
| `skipped_mutex` | 互斥组已被同趟其他作业占用 | 否 | 否 |
| `skipped_dep` | 依赖未就绪（上游失败/被跳过） | 否 | 否 |

编排报告的 `succeeded / failed / skipped_branch / skipped_mutex / skipped_dep` 全部由落库的
尝试记录反推，五个桶之和恒等于尝试数，保证报告与尝试列表对得上。

## 种子拓扑（8 个作业，一趟覆盖全部状态）

- **ingest_orders**（3 行，`flags.needs_retry=true`）、**dim_customer**：无依赖源作业。
- **retry_orders**：标志 `needs_retry eq true` 命中 → 执行；
  **skip_retry_clean**：`needs_retry eq false` 未命中 → `skipped_branch`。
- **fact_bulk / fact_recent**：行数阈值均命中，同属互斥组 `fact_volume`，一趟只跑一个，另一个 `skipped_mutex`。
- **fact_full**：行数阈值 `gte 5`，实际 3 行 → `skipped_branch`；阈值可在作业页改成命中后执行。
- **fact_order_daily**：无分支条件，两路上游成功即执行。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。

## 0-1 切口（未实现）

`retry_budget` / `watermark_reconcile` / `sla_breach`；`dep_gate` 的严格水位闸仍为占位。
