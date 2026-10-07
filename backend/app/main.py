from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import projections, seed
from app.db import connect
from app.engines.borrow_rules import can_lend

app = FastAPI(title="Borrowboard", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

@app.get("/api/items")
def items():
    # 物件真源表的原始视图（物主页用），不是看板分栏投影。
    c = connect()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM items")]
    finally:
        c.close()

@app.get("/api/board")
def board():
    # 左右两栏与细条计数共用同一个读时现算投影，路由自身不扫表、不拼装。
    c = connect()
    try:
        return projections.board_projection(c)
    finally:
        c.close()

class ItemIn(BaseModel):
    title: str
    owner: str

@app.post("/api/items")
def add_item(body: ItemIn):
    c = connect()
    try:
        try:
            cur = c.execute("INSERT INTO items(title,owner,status,data_quality) VALUES (?,?,?,?)",
                            (body.title, body.owner, "available", "clean"))
            c.commit()
        except Exception:
            c.rollback()
            raise
        return {"id": cur.lastrowid}
    finally:
        c.close()

class LendIn(BaseModel):
    borrower: str
    due_date: str

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    c = connect()
    try:
        item = c.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if not item: raise HTTPException(404, "item")
        active = c.execute("SELECT COUNT(*) c FROM loans WHERE item_id=? AND status='active'", (iid,)).fetchone()["c"]
        check = can_lend(item["status"], active)
        if not check["ok"]:
            raise HTTPException(409, check["reason"])
        try:
            cur = c.execute(
                "INSERT INTO loans(item_id,borrower,status,due_date,lent_at) VALUES (?,?,?,?,?)",
                (iid, body.borrower, "active", body.due_date, datetime.now(timezone.utc).isoformat()))
            c.execute("UPDATE items SET status='on_loan' WHERE id=?", (iid,))
            c.commit()
        except Exception:
            # 任一写入失败：loan 插入与 item 状态更新一起回滚，投影里不留半截行。
            c.rollback()
            raise
        return {"loan_id": cur.lastrowid}
    finally:
        c.close()

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    c = connect()
    try:
        loan = c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()
        if not loan: raise HTTPException(404, "loan")
        if loan["status"] != "active":
            raise HTTPException(400, "not_active")
        try:
            c.execute("UPDATE loans SET status='returned', returned_at=? WHERE id=?",
                      (datetime.now(timezone.utc).isoformat(), lid))
            c.execute("UPDATE items SET status='available' WHERE id=?", (loan["item_id"],))
            c.commit()
        except Exception:
            c.rollback()
            raise
        return {"ok": True}
    finally:
        c.close()

@app.get("/api/loans")
def loans():
    c = connect()
    try:
        return projections.loans_projection(c)
    finally:
        c.close()

@app.get("/api/settings")
def settings():
    c = connect()
    try:
        return {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}
    finally:
        c.close()
