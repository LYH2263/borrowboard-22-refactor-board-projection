"""读模型投影层：看板两栏 / 细条计数 / 借还记录的唯一派生处。

刷新策略 = 读时现算（read-computed）。本模块不落盘任何投影表、视图或缓存；
每次读取直接从 items / loans 两张真源表的已提交状态派生。写路径只写真源表并在
单事务内原子提交，未提交的借出/归还对投影不可见，因此失败时投影里不会出现半截行。
左右两栏与顶部细条只能消费本模块的输出，不得在路由或前端另行扫表拼装；不得一栏
走写事务刷新、一栏走读时现算。
"""

from datetime import date

from app.engines.borrow_rules import classify_loans


def board_projection(c, today: str | None = None) -> dict:
    """派生看板：可借栏、在借栏（含逾期）与细条计数，三者一次同源产出。"""
    today = today or date.today().isoformat()
    available = [dict(r) for r in c.execute(
        "SELECT * FROM items WHERE status='available'")]
    active_loans = [dict(r) for r in c.execute(
        """SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id
           WHERE loans.status='active'""")]
    cls = classify_loans(active_loans, today)
    # 在借含逾期：逾期是在借的子集，排序时逾期在前（保持既有展示顺序）。
    on_loan = cls["overdue"] + cls["active"]
    return {
        "available": available,
        "on_loan": on_loan,
        "counts": {
            "available": len(available),
            "on_loan": len(on_loan),
            "overdue": len(cls["overdue"]),
        },
    }


def loans_projection(c, today: str | None = None) -> dict:
    """派生借还记录页：全部借出记录分 active / overdue / returned 三桶。"""
    today = today or date.today().isoformat()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    return classify_loans(rows, today)
