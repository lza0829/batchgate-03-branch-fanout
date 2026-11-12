import json

from app.db import connect

# name, fixture, depends_on, note, branch_conditions, mutex_group
_SEED_JOBS = [
    (
        "ingest_orders",
        "ingest_orders.json",
        [],
        "无依赖：写出订单水位（fixture 约定标志 needs_retry=true）",
        [],
        None,
    ),
    (
        "dim_customer",
        "dim_customer.json",
        [],
        "无依赖：写出客户维表水位",
        [],
        None,
    ),
    (
        "fact_order_daily",
        "fact_order_daily.json",
        ["ingest_orders", "dim_customer"],
        "依赖两路上游成功后才执行（无条件分支）",
        [],
        None,
    ),
    (
        "retry_orders",
        "retry_orders.json",
        ["ingest_orders"],
        "标志命中：needs_retry=true 时执行重试旁路",
        [
            {
                "type": "flag",
                "upstream": "ingest_orders",
                "flag": "needs_retry",
                "op": "eq",
                "value": True,
            }
        ],
        None,
    ),
    (
        "skip_retry_clean",
        "skip_retry_clean.json",
        ["ingest_orders"],
        "标志未命中：needs_retry=false 才执行，种子趟里旁路跳过",
        [
            {
                "type": "flag",
                "upstream": "ingest_orders",
                "flag": "needs_retry",
                "op": "eq",
                "value": False,
            }
        ],
        None,
    ),
    (
        "fact_bulk",
        "fact_bulk.json",
        ["ingest_orders", "dim_customer"],
        "行数阈值命中（>=3），互斥组 fact_volume 中按名先占先得",
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 3,
            }
        ],
        "fact_volume",
    ),
    (
        "fact_recent",
        "fact_recent.json",
        ["ingest_orders", "dim_customer"],
        "行数阈值命中（>=2）但与 fact_bulk 互斥，同趟只能跑一个",
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 2,
            }
        ],
        "fact_volume",
    ),
    (
        "fact_full",
        "fact_full.json",
        ["ingest_orders"],
        "行数阈值未命中（要求 >=5，实际 3 行），旁路跳过不跑夹具",
        [
            {
                "type": "rows",
                "upstream": "ingest_orders",
                "op": "gte",
                "value": 5,
            }
        ],
        None,
    ),
]


def _columns(conn) -> set[str]:
    return {r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()}


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings(
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs(
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            fixture_path TEXT NOT NULL,
            depends_on_json TEXT NOT NULL,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            branch_conditions_json TEXT NOT NULL DEFAULT '[]',
            mutex_group TEXT
        );
        CREATE TABLE IF NOT EXISTS orchestrations(
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            report_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_attempts(
            id INTEGER PRIMARY KEY,
            orchestration_id INTEGER NOT NULL,
            job_id INTEGER NOT NULL,
            attempt_no INTEGER NOT NULL,
            status TEXT NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS watermarks(
            job_id INTEGER PRIMARY KEY,
            watermark_ts TEXT,
            artifact_rows INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT
        );
        """
    )
    # Migrate databases created before conditional branching existed.
    existing = _columns(conn)
    if "branch_conditions_json" not in existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN branch_conditions_json TEXT NOT NULL DEFAULT '[]'")
    if "mutex_group" not in existing:
        conn.execute("ALTER TABLE jobs ADD COLUMN mutex_group TEXT")

    conn.executemany(
        """
        INSERT OR IGNORE INTO jobs(
            name, fixture_path, depends_on_json, max_attempts, enabled, note,
            branch_conditions_json, mutex_group
        )
        VALUES (?,?,?,1,1,?,?,?)
        """,
        [
            (
                name,
                fixture,
                json.dumps(depends_on, ensure_ascii=False),
                note,
                json.dumps(conditions, ensure_ascii=False),
                mutex_group,
            )
            for name, fixture, depends_on, note, conditions, mutex_group in _SEED_JOBS
        ],
    )
    for row in conn.execute("SELECT id FROM jobs").fetchall():
        conn.execute(
            "INSERT OR IGNORE INTO watermarks(job_id, watermark_ts, artifact_rows, updated_at) VALUES (?,?,?,?)",
            (row["id"], None, 0, None),
        )
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
        ("default_max_attempts", "1"),
    )
    conn.commit()
    conn.close()
