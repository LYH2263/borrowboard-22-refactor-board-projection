import pytest
from fastapi import HTTPException
from app import main, projections, seed
from app.db import connect

TODAY = "2026-10-07"  # 晚于种子逾期样例 2020-06-01，早于新借出的 2026-12-31


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    seed.init_db()
    return tmp_path


def board():
    c = connect()
    try:
        return projections.board_projection(c, TODAY)
    finally:
        c.close()


def assert_invariants(b):
    # 细条计数只问投影产物：与两栏条数严格一致，逾期是在借的子集。
    assert b["counts"]["available"] == len(b["available"])
    assert b["counts"]["on_loan"] == len(b["on_loan"])
    assert b["counts"]["overdue"] <= b["counts"]["on_loan"]
    assert all("overdue" in L for L in b["on_loan"])


def test_seed_projection(db):
    b = board()
    assert_invariants(b)
    assert b["counts"] == {"available": 3, "on_loan": 1, "overdue": 1}
    ids = {i["id"] for i in b["available"]}
    assert ids == {1, 2, 3}
    loan = b["on_loan"][0]
    assert loan["item_id"] == 4 and loan["overdue"] is True


def test_lend_moves_item_between_panes(db):
    before = board()
    r = main.lend(1, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))
    assert set(r) == {"loan_id"}
    b = board()
    assert_invariants(b)
    assert 1 not in {i["id"] for i in b["available"]}
    new_loan = next(L for L in b["on_loan"] if L["item_id"] == 1)
    assert new_loan["borrower"] == "邻居乙" and new_loan["overdue"] is False
    assert b["counts"]["available"] == before["counts"]["available"] - 1
    assert b["counts"]["on_loan"] == before["counts"]["on_loan"] + 1
    c = connect()
    active_for_item = c.execute(
        "SELECT COUNT(*) n FROM loans WHERE item_id=1 AND status='active'").fetchone()["n"]
    c.close()
    assert active_for_item == 1  # 无半截重复 loan 行


def test_lend_failure_leaves_no_half_row(db):
    before = board()
    # 种子 item 4 已 on_loan 且挂着 active loan：规则先行拒绝，写入根本不发生。
    with pytest.raises(HTTPException) as ei:
        main.lend(4, main.LendIn(borrower="重复借", due_date="2026-12-31"))
    assert ei.value.status_code == 409
    assert ei.value.detail in {"already_on_loan", "item_not_available"}
    assert board() == before  # 投影前后逐字节一致
    c = connect()
    item_status = c.execute("SELECT status FROM items WHERE id=4").fetchone()["status"]
    active_count = c.execute(
        "SELECT COUNT(*) n FROM loans WHERE item_id=4 AND status='active'").fetchone()["n"]
    c.close()
    assert item_status == "on_loan" and active_count == 1


def test_return_removes_on_loan_row(db):
    assert main.return_loan(1) == {"ok": True}
    b = board()
    assert_invariants(b)
    assert b["on_loan"] == []
    assert b["counts"] == {"available": 4, "on_loan": 0, "overdue": 0}
    assert {i["id"] for i in b["available"]} == {1, 2, 3, 4}
    c = connect()
    row = c.execute("SELECT status, returned_at FROM loans WHERE id=1").fetchone()
    c.close()
    assert row["status"] == "returned" and row["returned_at"]


def test_double_return_does_not_change_projection(db):
    main.return_loan(1)
    before = board()
    with pytest.raises(HTTPException) as ei:
        main.return_loan(1)
    assert ei.value.status_code == 400 and ei.value.detail == "not_active"
    assert board() == before


def test_add_item_refreshes_available_pane(db):
    before = board()
    main.add_item(main.ItemIn(title="梯子", owner="老赵"))
    b = board()
    assert_invariants(b)
    assert b["counts"]["available"] == before["counts"]["available"] + 1
    assert any(i["title"] == "梯子" and i["status"] == "available" for i in b["available"])


def test_loans_projection_buckets(db):
    lid = main.lend(1, main.LendIn(borrower="邻居乙", due_date="2026-12-31"))["loan_id"]
    assert lid == 2
    main.return_loan(lid)
    c = connect()
    try:
        p = projections.loans_projection(c, TODAY)
    finally:
        c.close()
    # 种子逾期 loan(id=1) 仍在 overdue；item 1 的新 loan(id=2) 已归还。
    assert len(p["overdue"]) == 1 and p["overdue"][0]["id"] == 1
    assert len(p["returned"]) == 1 and p["returned"][0]["id"] == 2
