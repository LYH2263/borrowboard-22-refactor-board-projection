"""看板投影层：可借栏、在借栏、顶细条计数的唯一数据源。

刷新策略（STRATEGY = "refresh-within-write-transaction"）：随写事务刷新。

- items / loans 是唯一真源；proj_available_items / proj_on_loan 是由真源
  全量重建出来的投影，不持有独立事实，任何时候都可以从真源重建。
- 写路径（app.board_service）在同一个 SQLite 事务里先写真源、再调
  refresh() 重建投影，然后才 commit：投影重建一旦失败，整个事务回滚，
  真源写入同样失败 —— 投影里不会留下半截行，顶细条也不会读到与真源
  不一致的旧拼装。
- 启动时 seed.init_db 也会全量重建一次，覆盖投影表缺失或漂移的情况。

可借栏、在借栏、顶细条三处读方共用本层、共用上述同一种刷新策略；
任何页面或接口都不得绕过本层自行扫描 items / loans 来拼装可借视图、
在借视图或计数。

投影只存事实字段（含借出 status）；逾期是随时间变化的派生量，统一在
读取时经 app.engines.borrow_rules 的规则现算，两栏与顶细条看到的是同
一份分类结果。
"""
from datetime import date

from app.engines.borrow_rules import classify_loans

STRATEGY = "refresh-within-write-transaction"


def ensure_tables(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS proj_available_items(
      item_id INTEGER PRIMARY KEY, title TEXT, owner TEXT
    );
    CREATE TABLE IF NOT EXISTS proj_on_loan(
      loan_id INTEGER PRIMARY KEY, item_id INT, title TEXT, borrower TEXT,
      status TEXT, due_date TEXT, lent_at TEXT
    );
    """)


def refresh(c):
    """从真源全量重建两块投影。

    必须在写真源的同一事务内调用（调用方负责 commit / rollback）；
    先删空再整体插入，任何一步失败都会随事务回滚，不会留下半截投影。
    """
    c.execute("DELETE FROM proj_available_items")
    c.execute("DELETE FROM proj_on_loan")
    c.execute("""
      INSERT INTO proj_available_items(item_id, title, owner)
      SELECT id, title, owner FROM items WHERE status='available'
    """)
    c.execute("""
      INSERT INTO proj_on_loan(loan_id, item_id, title, borrower, status, due_date, lent_at)
      SELECT l.id, l.item_id, i.title, l.borrower, l.status, l.due_date, l.lent_at
      FROM loans l JOIN items i ON i.id = l.item_id
      WHERE l.status='active'
    """)


def available_rows(c):
    """可借栏：只读投影，不扫真源。"""
    return [dict(r) for r in c.execute(
        "SELECT item_id, title, owner FROM proj_available_items ORDER BY item_id")]


def on_loan_rows(c):
    """在借投影原始行（含 status，供规则引擎分类）。"""
    return [dict(r) for r in c.execute(
        "SELECT loan_id, item_id, title, borrower, status, due_date, lent_at "
        "FROM proj_on_loan ORDER BY loan_id")]


def on_loan_columns(c, today=None):
    """在借栏：投影行经规则引擎分出 active / overdue。"""
    today = today or date.today().isoformat()
    cls = classify_loans(on_loan_rows(c), today)
    return {"active": cls["active"], "overdue": cls["overdue"]}


def top_bar_counts(c, today=None):
    """顶细条计数：由给栏位供数的同一份投影行数出，保证
    顶细条可借数 == 可借栏条数、在借/逾期数 == 在借栏对应条数。"""
    cols = on_loan_columns(c, today)
    return {
        "available": len(available_rows(c)),
        "active": len(cols["active"]),
        "overdue": len(cols["overdue"]),
    }
