"""看板写路径：唯一真源（items / loans）写入 + 投影同事务刷新。

每个写函数都在同一个 SQLite 事务里完成「写真源 → 重建投影 → commit」。
任一步失败（包括投影刷新失败）都会回滚整个事务：真源不会单独写成功，
投影里也不会留下半截行，调用方拿到的就是失败。

规则核对（能否借出）仍由 app.engines.borrow_rules 裁决，本模块只管事务。
"""
from datetime import datetime, timezone

from app.engines.borrow_rules import can_lend
from app.projections import board as board_proj


class WriteError(Exception):
    """可预期的写失败（校验/规则不通过），携带 HTTP 状态码与原因。"""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _now():
    return datetime.now(timezone.utc).isoformat()


def add_item(c, title, owner):
    try:
        cur = c.execute(
            "INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
            (title, owner, "available", "clean"))
        board_proj.refresh(c)
        c.commit()
        return cur.lastrowid
    except Exception:
        c.rollback()
        raise


def lend_item(c, item_id, borrower, due_date):
    try:
        item = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            raise WriteError(404, "item")
        active = c.execute(
            "SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'",
            (item_id,)).fetchone()["c"]
        check = can_lend(item["status"], active)
        if not check["ok"]:
            raise WriteError(409, check["reason"])
        cur = c.execute(
            "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
            (item_id, borrower, "active", due_date, _now()))
        c.execute("UPDATE items SET status='on_loan' WHERE id=?", (item_id,))
        board_proj.refresh(c)
        c.commit()
        return cur.lastrowid
    except Exception:
        c.rollback()
        raise


def return_loan(c, loan_id):
    try:
        loan = c.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone()
        if not loan:
            raise WriteError(404, "loan")
        if loan["status"] != "active":
            raise WriteError(400, "not_active")
        c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
                  (_now(), loan_id))
        c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
        board_proj.refresh(c)
        c.commit()
    except Exception:
        c.rollback()
        raise
