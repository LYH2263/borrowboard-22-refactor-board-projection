# Borrowboard · 邻里借用

上架 → 借出通过 → 归还；单物件同时仅一笔在借，含逾期判定。

架构：`items` / `loans` 是唯一真源；看板左右分栏与顶细条只读投影层
（`app/projections/board.py`，策略：随写事务刷新，写路径见
`app/board_service.py` —— 真源写入与投影重建同事务，失败整体回滚）。

| 服务 | 端口 |
| --- | --- |
| 前端 | 5400 |
| API | 10400 |

0-1：`deposit` / `damage_note` / `neighbor_rating`。
