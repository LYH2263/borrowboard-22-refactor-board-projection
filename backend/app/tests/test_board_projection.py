"""看板投影层用例：真源写入与投影刷新的一致性。

只用标准库 + 纯断言（不依赖 pytest fixture），pytest 与裸 python 都能跑。
每个用例用独立临时 DATA_DIR，互不影响。
"""
import os
import tempfile

from app import seed, board_service
from app.board_service import WriteError
from app.db import connect
from app.projections import board as proj


def fresh_db():
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="borrowboard-test-")
    seed.init_db()


def test_seed_projection_matches_truth():
    fresh_db()
    c = connect()
    avail = proj.available_rows(c)
    cols = proj.on_loan_columns(c)
    counts = proj.top_bar_counts(c)
    assert [r["item_id"] for r in avail] == [1, 2, 3]
    assert len(cols["active"]) == 0 and len(cols["overdue"]) == 1
    assert cols["overdue"][0]["loan_id"] == 1
    assert counts == {"available": 3, "active": 0, "overdue": 1}
    c.close()


def test_lend_moves_item_between_projections():
    fresh_db()
    c = connect()
    lid = board_service.lend_item(c, 1, "邻居乙", "2027-01-01")
    avail = proj.available_rows(c)
    cols = proj.on_loan_columns(c)
    assert all(r["item_id"] != 1 for r in avail)
    assert any(r["loan_id"] == lid and r["borrower"] == "邻居乙" for r in cols["active"])
    counts = proj.top_bar_counts(c)
    assert counts["available"] == len(avail) == 2
    assert counts["active"] == len(cols["active"]) == 1
    assert counts["overdue"] == len(cols["overdue"]) == 1
    c.close()


def test_failed_lend_leaves_no_partial_projection():
    fresh_db()
    c = connect()
    before_avail = proj.available_rows(c)
    before_onloan = proj.on_loan_rows(c)
    try:
        board_service.lend_item(c, 4, "邻居丙", "2027-01-01")  # 4 号已在借
        assert False, "应拒绝重复借出"
    except WriteError as e:
        assert e.status == 409 and e.reason == "item_not_available"
    assert proj.available_rows(c) == before_avail
    assert proj.on_loan_rows(c) == before_onloan
    n = c.execute("SELECT COUNT(*) c FROM loans WHERE borrower='邻居丙'").fetchone()["c"]
    assert n == 0  # 真源里也没有半截借出行
    c.close()


def test_return_clears_on_loan_projection():
    fresh_db()
    c = connect()
    board_service.return_loan(c, 1)
    assert all(r["loan_id"] != 1 for r in proj.on_loan_rows(c))  # 投影不再挂 on_loan
    avail = proj.available_rows(c)
    assert any(r["item_id"] == 4 for r in avail)  # 物件回到可借栏
    counts = proj.top_bar_counts(c)
    assert counts["available"] == len(avail) == 4
    assert counts["active"] == 0 and counts["overdue"] == 0
    c.close()


def test_refresh_failure_rolls_back_source_and_projection():
    fresh_db()
    c = connect()
    orig = proj.refresh
    def boom(conn):
        raise RuntimeError("projection refresh failed")
    proj.refresh = boom  # 模拟投影刷新失败
    try:
        try:
            board_service.lend_item(c, 1, "邻居丁", "2027-01-01")
            assert False, "投影刷新失败必须让整笔写失败"
        except RuntimeError:
            pass
    finally:
        proj.refresh = orig
    # 真源回滚：物件状态没变、没有半截借出行
    assert c.execute("SELECT status FROM items WHERE id=1").fetchone()["status"] == "available"
    n = c.execute("SELECT COUNT(*) c FROM loans WHERE borrower='邻居丁'").fetchone()["c"]
    assert n == 0
    # 投影与真源一致：可借栏仍含 1 号，顶细条可借数 == 可借栏条数
    avail = proj.available_rows(c)
    assert any(r["item_id"] == 1 for r in avail)
    assert proj.top_bar_counts(c)["available"] == len(avail) == 3
    c.close()


def test_add_item_refreshes_projection():
    fresh_db()
    c = connect()
    iid = board_service.add_item(c, "冲击钻", "老赵")
    avail = proj.available_rows(c)
    assert any(r["item_id"] == iid and r["owner"] == "老赵" for r in avail)
    assert proj.top_bar_counts(c)["available"] == len(avail) == 4
    c.close()


def test_counts_always_equal_column_lengths():
    fresh_db()
    c = connect()
    board_service.lend_item(c, 2, "邻居戊", "2020-01-01")  # 借出即逾期
    board_service.lend_item(c, 3, "邻居己", "2099-01-01")
    cols = proj.on_loan_columns(c)
    counts = proj.top_bar_counts(c)
    assert counts["available"] == len(proj.available_rows(c))
    assert counts["active"] == len(cols["active"]) == 1
    assert counts["overdue"] == len(cols["overdue"]) == 2
    c.close()
