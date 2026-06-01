"""
从 VynFi AML 数据集构建银行数据仓库模型

输出:
  demo/bank_dw.sqlite       — SQLite 数据库（9 表）
  demo/bank_data_dict.csv   — DataPilot 格式数据字典
"""
import sqlite3
import csv
from pathlib import Path
from collections import defaultdict
import random

random.seed(42)

DEMO_DIR = Path(__file__).resolve().parent

# ============================================================================
# Step 1: Load source data
# ============================================================================
print("Loading vynfi-aml-100k...")
from datasets import load_dataset
ds = load_dataset("VynFi/vynfi-aml-100k", split="train")

SAMPLE_SIZE = 200_000
print(f"Sampling {SAMPLE_SIZE} rows...")
indices = random.sample(range(len(ds)), SAMPLE_SIZE)
rows = [ds[int(i)] for i in indices]

# ============================================================================
# Step 2: Normalize to star schema
# ============================================================================
print("Normalizing to star schema...")

# --- dim_counterparty ---
counterparties = {}
for r in rows:
    cid = r["counterparty.counterparty_id"]
    if cid and cid not in counterparties:
        counterparties[cid] = {
            "counterparty_id": cid,
            "name": r["counterparty.name"] or "",
            "type": r["counterparty.counterparty_type"] or "unknown",
            "country": r["counterparty.country"] or None,
        }

# --- dim_account ---
accounts = {}
account_countries = defaultdict(set)
account_channels = defaultdict(set)
for r in rows:
    aid = r["account_id"]
    if aid not in accounts:
        accounts[aid] = {
            "account_id": aid, "country": r["location_country"] or "UNKNOWN",
            "city": r["location_city"] or "",
        }
    if r["location_country"]:
        account_countries[aid].add(r["location_country"])
    if r["channel"]:
        account_channels[aid].add(r["channel"])

for aid in accounts:
    countries = account_countries.get(aid, set())
    channels = account_channels.get(aid, set())
    accounts[aid]["primary_country"] = max(countries, key=lambda c: sum(1 for x in account_countries[aid] if x == c)) if countries else accounts[aid]["country"]
    accounts[aid]["country_count"] = len(countries)
    accounts[aid]["preferred_channel"] = max(channels, key=lambda c: sum(1 for x in account_channels[aid] if x == c)) if channels else "unknown"

# --- dim_channel ---
CHANNELS = [
    ("card_present", "POS刷卡", "线下"), ("card_not_present", "线上无卡", "线上"),
    ("atm", "ATM", "线下"), ("wire", "电汇", "线下"), ("ach", "ACH转账", "线上"),
    ("internal", "行内转账", "线上"), ("mobile", "手机银行", "线上"), ("branch", "柜面", "线下"),
]

# --- dim_transaction_type ---
TXN_TYPES = [
    ("CARD_PRESENT_GROCERIES", "POS-商超", "消费"),
    ("CARD_PRESENT_RESTAURANT", "POS-餐饮", "消费"),
    ("CARD_PRESENT_RETAIL", "POS-零售", "消费"),
    ("CARD_NOT_PRESENT_ECOMMERCE", "线上-电商", "消费"),
    ("ATM_WITHDRAWAL", "ATM取现", "取现"),
    ("WIRE_TRANSFER_OUT", "电汇转出", "转账"),
    ("WIRE_TRANSFER_IN", "电汇转入", "转账"),
    ("ACH_CREDIT", "ACH贷记", "转账"),
    ("ACH_DEBIT", "ACH借记", "转账"),
    ("INTERNAL_TRANSFER", "行内转账", "转账"),
    ("MOBILE_PAYMENT", "手机支付", "消费"),
    ("BRANCH_DEPOSIT", "柜面存款", "存款"),
    ("BRANCH_WITHDRAWAL", "柜面取款", "取现"),
    ("FEE_CHARGE", "手续费", "费用"),
]

# --- dim_date ---
dates = set()
for r in rows:
    ts = r["timestamp_initiated"]
    if ts:
        dates.add(ts[:10])

# --- dim_currency ---
currencies = {
    "USD": "美元", "EUR": "欧元", "GBP": "英镑", "JPY": "日元",
    "CNY": "人民币", "CAD": "加元", "AUD": "澳元",
}

# --- dim_suspicion ---
suspicion_reasons = {
    "structuring": ("拆分交易规避报告", "placement"),
    "rapid_movement": ("资金快速进出", "layering"),
    "high_risk_jurisdiction": ("高风险国家/地区", "placement"),
    "unusual_pattern": ("交易模式异常", "layering"),
    "round_amount": ("整数金额频繁交易", "placement"),
    "shell_company": ("壳公司交易", "integration"),
    "trade_based": ("贸易洗钱特征", "integration"),
    "velocity_spike": ("交易频率异常激增", "layering"),
}

print(f"  Accounts: {len(accounts)}, Counterparties: {len(counterparties)}, Dates: {len(dates)}")

# ============================================================================
# Step 3: Create SQLite DB (no COMMENT syntax — SQLite doesn't support it)
# ============================================================================
db_path = DEMO_DIR / "bank_dw.sqlite"
if db_path.exists():
    db_path.unlink()
conn = sqlite3.connect(str(db_path))
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA cache_size=-64000")
# FK 校验推迟到加载完成后（合成数据中少量引用可能跨批次缺失）
conn.execute("PRAGMA foreign_keys=OFF")

print(f"Creating tables in {db_path}...")

DDL = {
    "dim_counterparty": """
        CREATE TABLE dim_counterparty (
            counterparty_id TEXT PRIMARY KEY,
            counterparty_name TEXT NOT NULL,
            counterparty_type TEXT NOT NULL,
            country TEXT
        )
    """,
    "dim_account": """
        CREATE TABLE dim_account (
            account_id TEXT PRIMARY KEY,
            primary_country TEXT NOT NULL,
            city TEXT,
            country_count INTEGER DEFAULT 1,
            preferred_channel TEXT
        )
    """,
    "dim_channel": """
        CREATE TABLE dim_channel (
            channel_code TEXT PRIMARY KEY,
            channel_name TEXT NOT NULL,
            channel_category TEXT NOT NULL
        )
    """,
    "dim_date": """
        CREATE TABLE dim_date (
            date_id TEXT PRIMARY KEY,
            year INTEGER,
            month INTEGER,
            day INTEGER,
            quarter INTEGER
        )
    """,
    "dim_transaction_type": """
        CREATE TABLE dim_transaction_type (
            type_code TEXT PRIMARY KEY,
            type_name TEXT NOT NULL,
            type_category TEXT NOT NULL
        )
    """,
    "dim_currency": """
        CREATE TABLE dim_currency (
            currency_code TEXT PRIMARY KEY,
            currency_name TEXT
        )
    """,
    "dim_suspicion": """
        CREATE TABLE dim_suspicion (
            reason_code TEXT PRIMARY KEY,
            reason_desc TEXT,
            laundering_stage TEXT
        )
    """,
    "fact_transaction": """
        CREATE TABLE fact_transaction (
            transaction_id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            counterparty_id TEXT,
            date_id TEXT NOT NULL,
            channel_code TEXT,
            type_code TEXT,
            currency_code TEXT DEFAULT 'USD',
            amount REAL NOT NULL,
            direction TEXT NOT NULL,
            balance_before REAL,
            balance_after REAL,
            status TEXT DEFAULT 'completed',
            is_authorized INTEGER DEFAULT 1,
            is_suspicious INTEGER DEFAULT 0,
            suspicion_reason TEXT,
            laundering_stage TEXT,
            is_spoofed INTEGER DEFAULT 0,
            location_country TEXT,
            location_city TEXT,
            mcc TEXT,
            gl_cash_account TEXT,
            FOREIGN KEY (account_id) REFERENCES dim_account(account_id),
            FOREIGN KEY (counterparty_id) REFERENCES dim_counterparty(counterparty_id),
            FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
            FOREIGN KEY (channel_code) REFERENCES dim_channel(channel_code),
            FOREIGN KEY (type_code) REFERENCES dim_transaction_type(type_code),
            FOREIGN KEY (currency_code) REFERENCES dim_currency(currency_code)
        )
    """,
    "fact_velocity": """
        CREATE TABLE fact_velocity (
            account_id TEXT PRIMARY KEY,
            txn_count_1h INTEGER,
            txn_count_24h INTEGER,
            txn_count_7d INTEGER,
            txn_count_30d INTEGER,
            amount_sum_24h REAL,
            amount_sum_7d REAL,
            amount_sum_30d REAL,
            amount_max_24h REAL,
            unique_counterparties_24h INTEGER,
            unique_counterparties_7d INTEGER,
            unique_countries_7d INTEGER,
            FOREIGN KEY (account_id) REFERENCES dim_account(account_id)
        )
    """,
}

# Create tables in dependency order
TABLE_ORDER = [
    "dim_currency", "dim_channel", "dim_transaction_type", "dim_suspicion",
    "dim_date", "dim_counterparty", "dim_account",
    "fact_transaction", "fact_velocity",
]
for t in TABLE_ORDER:
    conn.execute(DDL[t])
    print(f"  Created {t}")

# ============================================================================
# Step 4: Load dimension data
# ============================================================================
print("Loading dimension tables...")

for c in counterparties.values():
    conn.execute("INSERT INTO dim_counterparty VALUES (?,?,?,?)",
        (c["counterparty_id"], c["name"], c["type"], c["country"]))
print(f"  dim_counterparty: {len(counterparties)} rows")

for a in accounts.values():
    conn.execute("INSERT INTO dim_account VALUES (?,?,?,?,?)",
        (a["account_id"], a["primary_country"], a["city"] or None,
         a["country_count"], a["preferred_channel"]))
print(f"  dim_account: {len(accounts)} rows")

for code, name, cat in CHANNELS:
    conn.execute("INSERT INTO dim_channel VALUES (?,?,?)", (code, name, cat))
print(f"  dim_channel: {len(CHANNELS)} rows")

for d in sorted(dates):
    parts = d.split("-")
    y, m, day = int(parts[0]), int(parts[1]), int(parts[2])
    q = (m - 1) // 3 + 1
    conn.execute("INSERT INTO dim_date VALUES (?,?,?,?,?)", (d, y, m, day, q))
print(f"  dim_date: {len(dates)} rows")

for code, name, cat in TXN_TYPES:
    conn.execute("INSERT INTO dim_transaction_type VALUES (?,?,?)", (code, name, cat))
print(f"  dim_transaction_type: {len(TXN_TYPES)} rows")

for code, name in currencies.items():
    conn.execute("INSERT INTO dim_currency VALUES (?,?)", (code, name))
print(f"  dim_currency: {len(currencies)} rows")

for code, (desc, stage) in suspicion_reasons.items():
    conn.execute("INSERT INTO dim_suspicion VALUES (?,?,?)", (code, desc, stage))
print(f"  dim_suspicion: {len(suspicion_reasons)} rows")

# ============================================================================
# Step 5: Ensure all FK references exist (backfill from transactions)
# ============================================================================
print("Backfilling missing dimension keys...")
txn_accounts = set()
txn_counterparties = set()
for r in rows:
    txn_accounts.add(r["account_id"])
    cid = r["counterparty.counterparty_id"]
    if cid:
        txn_counterparties.add(cid)

missing_accounts = txn_accounts - set(a["account_id"] for a in accounts.values())
for aid in missing_accounts:
    conn.execute("INSERT INTO dim_account VALUES (?,?,?,?,?)",
        (aid, "UNKNOWN", None, 0, "unknown"))
print(f"  Backfilled {len(missing_accounts)} accounts")

missing_cps = txn_counterparties - set(c["counterparty_id"] for c in counterparties.values())
for cid in missing_cps:
    conn.execute("INSERT INTO dim_counterparty VALUES (?,?,?,?)",
        (cid, f"Unknown-{cid[:8]}", "unknown", None))
print(f"  Backfilled {len(missing_cps)} counterparties")

# ============================================================================
# Step 6: Load fact_transaction (200K rows)
# ============================================================================
print("Loading fact_transaction (200K rows, this takes ~30s)...")
txn_sql = """INSERT OR IGNORE INTO fact_transaction VALUES (
    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
)"""
count = 0
for r in rows:
    ts = r["timestamp_initiated"] or "2024-01-01T00:00:00Z"
    date_id = ts[:10]
    amount = float(r["amount"]) if r["amount"] else 0

    def safe_float(v):
        return float(v) if v else None

    conn.execute(txn_sql, (
        r["transaction_id"], r["account_id"],
        r["counterparty.counterparty_id"] or None,
        date_id, r["channel"] or None, r["transaction_type"] or None,
        r["currency"] or "USD", amount, r["direction"] or "outbound",
        safe_float(r["balance_before"]), safe_float(r["balance_after"]),
        r["status"] or "completed", int(bool(r["is_authorized"])),
        int(bool(r["is_suspicious"])), r["suspicion_reason"] or None,
        r["laundering_stage"] or None, int(bool(r["is_spoofed"])),
        r["location_country"] or None, r["location_city"] or None,
        str(int(r["mcc"])) if r["mcc"] else None,
        r["gl_cash_account"] or None,
    ))
    count += 1
    if count % 50000 == 0:
        print(f"  {count}...")
print(f"  fact_transaction: {count} rows")

# ============================================================================
# Step 6: Load fact_velocity
# ============================================================================
print("Loading fact_velocity...")
vel_by_account = {}
for r in rows:
    aid = r["account_id"]
    if aid not in vel_by_account:
        vel_by_account[aid] = (
            int(r["velocity_features.txn_count_1h"] or 0),
            int(r["velocity_features.txn_count_24h"] or 0),
            int(r["velocity_features.txn_count_7d"] or 0),
            int(r["velocity_features.txn_count_30d"] or 0),
            float(r["velocity_features.amount_sum_24h"] or 0),
            float(r["velocity_features.amount_sum_7d"] or 0),
            float(r["velocity_features.amount_sum_30d"] or 0),
            float(r["velocity_features.amount_max_24h"] or 0),
            int(r["velocity_features.unique_counterparties_24h"] or 0),
            int(r["velocity_features.unique_counterparties_7d"] or 0),
            int(r["velocity_features.unique_countries_7d"] or 0),
        )

for aid, v in vel_by_account.items():
    conn.execute("INSERT INTO fact_velocity VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (aid,) + v)
print(f"  fact_velocity: {len(vel_by_account)} rows")

conn.commit()
conn.execute("PRAGMA foreign_keys=ON")

# ============================================================================
# Step 7: Create views
# ============================================================================
print("Creating DM views...")
conn.execute("""
CREATE VIEW v_customer_summary AS
SELECT
    a.account_id,
    a.primary_country,
    a.city,
    a.preferred_channel,
    a.country_count,
    COUNT(t.transaction_id) AS total_txn_count,
    ROUND(SUM(t.amount), 2) AS total_amount,
    ROUND(AVG(t.amount), 2) AS avg_amount,
    SUM(t.is_suspicious) AS suspicious_count,
    CASE
        WHEN SUM(t.amount) > 1000000 THEN 'VIP'
        WHEN SUM(t.amount) > 100000 THEN 'STANDARD'
        ELSE 'DORMANT'
    END AS customer_level
FROM dim_account a
LEFT JOIN fact_transaction t ON a.account_id = t.account_id
GROUP BY a.account_id
""")

conn.execute("""
CREATE VIEW v_channel_daily_summary AS
SELECT
    t.channel_code,
    t.date_id,
    COUNT(*) AS txn_count,
    ROUND(SUM(t.amount), 2) AS total_amount,
    COUNT(DISTINCT t.account_id) AS unique_customers,
    SUM(t.is_suspicious) AS suspicious_count
FROM fact_transaction t
GROUP BY t.channel_code, t.date_id
""")

conn.execute("""
CREATE VIEW v_suspicious_transactions AS
SELECT
    t.transaction_id,
    t.account_id,
    t.date_id,
    t.amount,
    t.direction,
    t.suspicion_reason,
    t.laundering_stage,
    c.counterparty_name,
    t.location_country
FROM fact_transaction t
LEFT JOIN dim_counterparty c ON t.counterparty_id = c.counterparty_id
WHERE t.is_suspicious = 1
""")

# ============================================================================
# Step 8: Print stats and verify
# ============================================================================
print(f"\n=== Database Stats ===")
for table in TABLE_ORDER:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"  {table}: {cur.fetchone()[0]:,} rows")

# Verify views
for view in ["v_customer_summary", "v_channel_daily_summary", "v_suspicious_transactions"]:
    cur = conn.execute(f"SELECT COUNT(*) FROM {view}")
    print(f"  {view}: {cur.fetchone()[0]:,} rows")

# Show sample query
print("\n=== Sample Query ===")
cur = conn.execute("""
    SELECT customer_level, COUNT(*) as cnt, ROUND(AVG(total_amount),2) as avg_amt
    FROM v_customer_summary
    GROUP BY customer_level
    ORDER BY avg_amt DESC
""")
for row in cur:
    print(f"  {row[0]}: {row[1]} customers, avg amount ${row[2]:,.2f}")

# ============================================================================
# Step 9: Generate DataPilot data dictionary
# ============================================================================
print(f"\nGenerating bank_data_dict.csv...")

SCHEMA = {
    "DM": [
        {
            "table_name": "v_customer_summary",
            "table_comment": "客户交易汇总视图（DM层-零售银行）",
            "columns": [
                ("account_id", "VARCHAR(36)", "客户账号唯一标识", True, False, "", []),
                ("primary_country", "VARCHAR(2)", "主要交易国家ISO代码", False, False, "", [
                    ("US", "美国"), ("CN", "中国"), ("GB", "英国"), ("JP", "日本"),
                    ("DE", "德国"), ("SG", "新加坡"),
                ]),
                ("city", "VARCHAR(50)", "主要交易城市", False, False, "", []),
                ("preferred_channel", "VARCHAR(20)", "偏好交易渠道", False, False, "", [
                    ("card_present", "POS刷卡"), ("atm", "ATM"), ("mobile", "手机银行"),
                    ("wire", "电汇"), ("branch", "柜面"),
                ]),
                ("country_count", "INTEGER", "涉及国家数量", False, False, "", []),
                ("total_txn_count", "INTEGER", "总交易笔数", False, False, "", []),
                ("total_amount", "DECIMAL(20,4)", "总交易金额", False, False, "", []),
                ("avg_amount", "DECIMAL(20,4)", "平均单笔金额", False, False, "", []),
                ("suspicious_count", "INTEGER", "可疑交易笔数", False, False, "", []),
                ("customer_level", "VARCHAR(10)", "客户等级", False, False, "", [
                    ("VIP", "高净值客户"), ("STANDARD", "普通客户"), ("DORMANT", "休眠客户"),
                ]),
            ],
        },
        {
            "table_name": "v_channel_daily_summary",
            "table_comment": "渠道每日汇总视图（DM层-运营分析）",
            "columns": [
                ("channel_code", "VARCHAR(20)", "渠道代码", True, False, "", [
                    ("card_present", "POS刷卡"), ("card_not_present", "线上无卡"),
                    ("atm", "ATM"), ("wire", "电汇"), ("mobile", "手机银行"), ("branch", "柜面"),
                ]),
                ("date_id", "VARCHAR(10)", "交易日期", True, False, "", []),
                ("txn_count", "INTEGER", "交易笔数", False, False, "", []),
                ("total_amount", "DECIMAL(20,4)", "交易总额", False, False, "", []),
                ("unique_customers", "INTEGER", "交易客户数", False, False, "", []),
                ("suspicious_count", "INTEGER", "可疑交易数", False, False, "", []),
            ],
        },
        {
            "table_name": "v_suspicious_transactions",
            "table_comment": "可疑交易明细视图（DM层-反洗钱AML）",
            "columns": [
                ("transaction_id", "VARCHAR(36)", "交易唯一标识", True, False, "", []),
                ("account_id", "VARCHAR(36)", "客户账号", False, True, "dim_account", []),
                ("date_id", "VARCHAR(10)", "交易日期", False, False, "", []),
                ("amount", "DECIMAL(20,4)", "交易金额", False, False, "", []),
                ("direction", "VARCHAR(10)", "交易方向", False, False, "", [
                    ("inbound", "入账"), ("outbound", "出账"),
                ]),
                ("suspicion_reason", "VARCHAR(30)", "可疑原因代码", False, False, "", [
                    ("structuring", "拆分交易"), ("rapid_movement", "资金快速进出"),
                    ("high_risk_jurisdiction", "高风险国家"), ("velocity_spike", "频率异常激增"),
                    ("shell_company", "壳公司交易"), ("round_amount", "整数金额"),
                ]),
                ("laundering_stage", "VARCHAR(20)", "洗钱阶段", False, False, "", [
                    ("placement", "处置阶段"), ("layering", "离析阶段"), ("integration", "融合阶段"),
                ]),
                ("counterparty_name", "VARCHAR(100)", "交易对手名称", False, False, "", []),
                ("location_country", "VARCHAR(2)", "交易发生国家", False, False, "", []),
            ],
        },
    ],
    "DWS": [
        {
            "table_name": "fact_transaction",
            "table_comment": "交易事实表（DWS层-核心交易流水）",
            "columns": [
                ("transaction_id", "VARCHAR(36)", "交易唯一标识", True, False, "", []),
                ("account_id", "VARCHAR(36)", "客户账号", False, True, "dim_account", []),
                ("counterparty_id", "VARCHAR(36)", "对手方ID", False, True, "dim_counterparty", []),
                ("date_id", "VARCHAR(10)", "交易日期", False, True, "dim_date", []),
                ("channel_code", "VARCHAR(20)", "渠道代码", False, True, "dim_channel", []),
                ("type_code", "VARCHAR(30)", "交易类型代码", False, True, "dim_transaction_type", []),
                ("currency_code", "VARCHAR(3)", "币种代码", False, True, "dim_currency", []),
                ("amount", "DECIMAL(20,4)", "交易金额", False, False, "", []),
                ("direction", "VARCHAR(10)", "交易方向", False, False, "", [
                    ("inbound", "入账"), ("outbound", "出账"),
                ]),
                ("balance_before", "DECIMAL(20,4)", "交易前余额", False, False, "", []),
                ("balance_after", "DECIMAL(20,4)", "交易后余额", False, False, "", []),
                ("status", "VARCHAR(15)", "交易状态", False, False, "", [
                    ("completed", "已完成"), ("pending", "处理中"), ("failed", "失败"),
                ]),
                ("is_authorized", "BOOLEAN", "是否已授权", False, False, "", [
                    ("1", "是"), ("0", "否"),
                ]),
                ("is_suspicious", "BOOLEAN", "是否可疑交易", False, False, "", [
                    ("1", "是"), ("0", "否"),
                ]),
                ("suspicion_reason", "VARCHAR(30)", "可疑原因代码", False, False, "", [
                    ("structuring", "拆分交易"), ("rapid_movement", "资金快速进出"),
                    ("high_risk_jurisdiction", "高风险国家"), ("velocity_spike", "频率异常"),
                ]),
                ("laundering_stage", "VARCHAR(20)", "洗钱阶段", False, False, "", [
                    ("placement", "处置"), ("layering", "离析"), ("integration", "融合"),
                ]),
                ("is_spoofed", "BOOLEAN", "是否伪造交易", False, False, "", [
                    ("1", "是"), ("0", "否"),
                ]),
                ("location_country", "VARCHAR(2)", "交易发生国家ISO代码", False, False, "", []),
                ("location_city", "VARCHAR(50)", "交易发生城市", False, False, "", []),
                ("mcc", "VARCHAR(4)", "商户类别码", False, False, "", [
                    ("5411", "商超"), ("5812", "餐饮"), ("5999", "其他零售"),
                ]),
                ("gl_cash_account", "VARCHAR(20)", "GL现金科目编码", False, False, "", []),
            ],
        },
        {
            "table_name": "fact_velocity",
            "table_comment": "客户交易行为特征表（DWS层-AML特征工程）",
            "columns": [
                ("account_id", "VARCHAR(36)", "客户账号", True, True, "dim_account", []),
                ("txn_count_1h", "INTEGER", "近1小时交易笔数", False, False, "", []),
                ("txn_count_24h", "INTEGER", "近24小时交易笔数", False, False, "", []),
                ("txn_count_7d", "INTEGER", "近7天交易笔数", False, False, "", []),
                ("txn_count_30d", "INTEGER", "近30天交易笔数", False, False, "", []),
                ("amount_sum_24h", "DECIMAL(20,4)", "近24小时交易总额", False, False, "", []),
                ("amount_sum_7d", "DECIMAL(20,4)", "近7天交易总额", False, False, "", []),
                ("amount_sum_30d", "DECIMAL(20,4)", "近30天交易总额", False, False, "", []),
                ("amount_max_24h", "DECIMAL(20,4)", "近24小时最大单笔金额", False, False, "", []),
                ("unique_counterparties_24h", "INTEGER", "近24小时对手方数", False, False, "", []),
                ("unique_counterparties_7d", "INTEGER", "近7天对手方数", False, False, "", []),
                ("unique_countries_7d", "INTEGER", "近7天涉及国家数", False, False, "", []),
            ],
        },
    ],
    "ODS": [
        {
            "table_name": "dim_account",
            "table_comment": "客户账户维表（ODS层-核心）",
            "columns": [
                ("account_id", "VARCHAR(36)", "客户账号唯一标识", True, False, "", []),
                ("primary_country", "VARCHAR(2)", "主要交易国家", False, False, "", [
                    ("US", "美国"), ("CN", "中国"), ("GB", "英国"), ("JP", "日本"),
                ]),
                ("city", "VARCHAR(50)", "主要交易城市", False, False, "", []),
                ("country_count", "INTEGER", "涉及国家数量", False, False, "", []),
                ("preferred_channel", "VARCHAR(20)", "偏好交易渠道", False, False, "", [
                    ("card_present", "POS刷卡"), ("atm", "ATM"), ("mobile", "手机银行"),
                ]),
            ],
        },
        {
            "table_name": "dim_counterparty",
            "table_comment": "交易对手维表（ODS层）",
            "columns": [
                ("counterparty_id", "VARCHAR(36)", "对手方唯一标识", True, False, "", []),
                ("counterparty_name", "VARCHAR(100)", "对手方名称", False, False, "", []),
                ("counterparty_type", "VARCHAR(20)", "对手方类型", False, False, "", [
                    ("merchant", "商户"), ("individual", "个人"),
                    ("bank", "银行"), ("internal", "行内"),
                ]),
                ("country", "VARCHAR(2)", "注册国家", False, False, "", []),
            ],
        },
        {
            "table_name": "dim_channel",
            "table_comment": "交易渠道维表（ODS层）",
            "columns": [
                ("channel_code", "VARCHAR(20)", "渠道代码", True, False, "", []),
                ("channel_name", "VARCHAR(20)", "渠道中文名", False, False, "", []),
                ("channel_category", "VARCHAR(10)", "渠道大类", False, False, "", [
                    ("线上", "线上渠道"), ("线下", "线下渠道"),
                ]),
            ],
        },
        {
            "table_name": "dim_date",
            "table_comment": "日期维表（ODS层）",
            "columns": [
                ("date_id", "VARCHAR(10)", "日期", True, False, "", []),
                ("year", "INTEGER", "年", False, False, "", []),
                ("month", "INTEGER", "月", False, False, "", []),
                ("quarter", "INTEGER", "季度", False, False, "", []),
            ],
        },
        {
            "table_name": "dim_currency",
            "table_comment": "币种维表（ODS层）",
            "columns": [
                ("currency_code", "VARCHAR(3)", "币种ISO代码", True, False, "", [
                    ("USD", "美元"), ("EUR", "欧元"), ("CNY", "人民币"), ("JPY", "日元"),
                ]),
                ("currency_name", "VARCHAR(10)", "币种中文名称", False, False, "", []),
            ],
        },
    ],
}

# Write data_dict.csv (matches dictionary/loader.py expected format)
dict_path = DEMO_DIR / "bank_data_dict.csv"
total_tables = 0
with open(dict_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.writer(f)
    writer.writerow(["分层", "表名", "表注释", "字段名", "字段类型", "字段注释",
                      "码值", "关联表", "主键"])
    for layer, tables in SCHEMA.items():
        for t in tables:
            total_tables += 1
            for col in t["columns"]:
                name, dtype, comment, is_pk, is_fk, ref, code_values = col
                # code_values → "01=活跃; 02=休眠" 格式
                code_str = "; ".join(f"{cv}={cv_meaning}" for cv, cv_meaning in code_values)
                # relations → 外键引用表
                rel_str = ref if is_fk and ref else ""
                writer.writerow([layer, t["table_name"], t["table_comment"],
                    name, dtype, comment, code_str, rel_str,
                    "true" if is_pk else ""])

print(f"  Data dict: {dict_path} ({total_tables} tables)")

# ============================================================================
# Step 10: Build ChromaDB index
# ============================================================================
print(f"\nBuilding ChromaDB index...")
from dictionary.loader import load_dictionary
from dictionary.indexer import build_index

data_dict = load_dictionary(str(dict_path))
collection = build_index(data_dict, reset=True)
print(f"  Index: {collection.count()} vectors")

conn.close()
print(f"\n=== Done ===")
print(f"Database:    {db_path} ({db_path.stat().st_size / 1024 / 1024:.1f} MB)")
print(f"Data Dict:   {dict_path}")
print(f"ChromaDB:    data/chroma_db/")
print(f"\nTry it:")
print(f"  python cli.py search --req demo/bank_req_aml.txt --dict demo/bank_data_dict.csv -v")
print(f"  python cli.py analyze --req demo/bank_req_aml.txt --dict demo/bank_data_dict.csv --sql --db demo/bank_dw.sqlite")
