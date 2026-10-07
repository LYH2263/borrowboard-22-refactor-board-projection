from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from app import seed, board_service
from app.db import connect
from app.engines.borrow_rules import classify_loans
from app.projections import board as board_proj

app = FastAPI(title="Borrowboard", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def _startup(): seed.init_db()

@app.get("/api/health")
def health(): return {"ok": True, "project": "borrowboard"}

# ---- 投影读接口：左右分栏与顶细条的唯一数据源（只读投影，不扫真源表） ----

@app.get("/api/proj/available")
def proj_available():
    c = connect()
    try:
        return {"rows": board_proj.available_rows(c)}
    finally:
        c.close()

@app.get("/api/proj/on-loan")
def proj_on_loan():
    c = connect()
    try:
        return board_proj.on_loan_columns(c, date.today().isoformat())
    finally:
        c.close()

@app.get("/api/proj/counts")
def proj_counts():
    c = connect()
    try:
        return board_proj.top_bar_counts(c, date.today().isoformat())
    finally:
        c.close()

# ---- 写接口：真源写入 + 投影刷新在同一事务（见 app.board_service） ----

class ItemIn(BaseModel):
    title: str
    owner: str

class LendIn(BaseModel):
    borrower: str
    due_date: str

def _run_write(fn, *args):
    c = connect()
    try:
        return fn(c, *args)
    except board_service.WriteError as e:
        raise HTTPException(e.status, e.reason)
    except Exception:
        # 含投影刷新失败：事务已回滚，真源与投影均未动，绝不能按旧拼装继续报数
        raise HTTPException(500, "write_failed")
    finally:
        c.close()

@app.post("/api/items")
def add_item(body: ItemIn):
    return {"id": _run_write(board_service.add_item, body.title, body.owner)}

@app.post("/api/items/{iid}/lend")
def lend(iid: int, body: LendIn):
    return {"loan_id": _run_write(board_service.lend_item, iid, body.borrower, body.due_date)}

@app.post("/api/loans/{lid}/return")
def return_loan(lid: int):
    _run_write(board_service.return_loan, lid)
    return {"ok": True}

# ---- 真源记录查询（物主一览 / 借还历史，非看板分栏用途） ----

@app.get("/api/items")
def items():
    c = connect(); rows = [dict(r) for r in c.execute("SELECT * FROM items")]; c.close(); return rows

@app.get("/api/loans")
def loans():
    c = connect()
    rows = [dict(r) for r in c.execute(
        "SELECT loans.*, items.title FROM loans JOIN items ON items.id=loans.item_id ORDER BY loans.id DESC")]
    c.close()
    return classify_loans(rows, date.today().isoformat())

@app.get("/api/settings")
def settings():
    c = connect(); rows = {r["key"]: r["value"] for r in c.execute("SELECT * FROM settings")}; c.close(); return rows
