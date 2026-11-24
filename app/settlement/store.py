"""结算组的 SQLite 持久化。

领域台账（app.settlement.ledger）是内存结构，本模块负责把理赔快照、
事件流与追回幂等键落库；加载时重建台账，保证重试与进程重启安全。
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.settlement.ledger import new_ledger


class SettlementStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS settlement_groups(
              group_id TEXT PRIMARY KEY,
              member_id TEXT NOT NULL,
              service_date TEXT NOT NULL,
              cap_cents INTEGER NOT NULL,
              seq INTEGER NOT NULL,
              recovered_total INTEGER NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settlement_claims(
              claim_id TEXT PRIMARY KEY,
              group_id TEXT NOT NULL,
              member_id TEXT NOT NULL,
              service_date TEXT NOT NULL,
              payer TEXT NOT NULL,
              billed_cents INTEGER NOT NULL,
              approved_cents INTEGER NOT NULL,
              deductible_cents INTEGER NOT NULL,
              seq INTEGER NOT NULL,
              late INTEGER NOT NULL,
              due_cents INTEGER NOT NULL,
              paid_cents INTEGER NOT NULL,
              recovered_cents INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settlement_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              group_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settlement_recovery_keys(
              confirmation_key TEXT PRIMARY KEY,
              group_id TEXT NOT NULL,
              claim_id TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              created_at TEXT NOT NULL
            );
            ''')

    def list_groups(self):
        with self.connect() as db:
            rows = db.execute("SELECT group_id FROM settlement_groups ORDER BY group_id").fetchall()
        return [row["group_id"] for row in rows]

    def load(self, group_id):
        """从库中重建台账；组不存在时返回 None。"""
        with self.connect() as db:
            group = db.execute("SELECT * FROM settlement_groups WHERE group_id=?", (group_id,)).fetchone()
            if group is None:
                return None
            return self._load_in(db, group)

    def _load_in(self, db, group):
        group_id = group["group_id"]
        claim_rows = db.execute("SELECT * FROM settlement_claims WHERE group_id=? ORDER BY seq",
                                (group_id,)).fetchall()
        event_rows = db.execute("SELECT payload FROM settlement_events WHERE group_id=? ORDER BY id",
                                (group_id,)).fetchall()
        key_rows = db.execute("SELECT confirmation_key FROM settlement_recovery_keys WHERE group_id=?",
                              (group_id,)).fetchall()
        ledger = new_ledger(group["member_id"], group["service_date"])
        ledger["cap"] = group["cap_cents"]
        ledger["seq"] = group["seq"]
        ledger["recovered_total"] = group["recovered_total"]
        ledger["order"] = [row["claim_id"] for row in claim_rows]
        for row in claim_rows:
            ledger["claims"][row["claim_id"]] = {
                "claim_id": row["claim_id"], "member_id": row["member_id"],
                "service_date": row["service_date"], "payer": row["payer"],
                "billed_cents": row["billed_cents"], "approved_cents": row["approved_cents"],
                "deductible_cents": row["deductible_cents"], "seq": row["seq"],
                "late": bool(row["late"]), "due": row["due_cents"],
                "paid": row["paid_cents"], "recovered": row["recovered_cents"],
            }
        ledger["events"] = [json.loads(row["payload"]) for row in event_rows]
        ledger["recovery_keys"] = {row["confirmation_key"] for row in key_rows}
        ledger["_loaded_events"] = len(ledger["events"])
        return ledger

    def transact(self, group_id, mutation):
        """在一个写事务内加载台账、执行变更并落库。

        mutation 接收当前台账（组不存在时为 None），返回
        ``(ledger, result)``；ledger 为 None 表示本次无写入。result 原样透传。
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            group = db.execute("SELECT * FROM settlement_groups WHERE group_id=?", (group_id,)).fetchone()
            ledger = self._load_in(db, group) if group is not None else None
            ledger, result = mutation(ledger)
            if ledger is not None and ledger["claims"]:
                self._persist(db, group_id, ledger)
        return result

    def _persist(self, db, group_id, ledger):
        now = datetime.now(timezone.utc).isoformat()
        db.execute('''INSERT INTO settlement_groups(group_id,member_id,service_date,cap_cents,seq,recovered_total,updated_at)
                      VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(group_id) DO UPDATE SET cap_cents=excluded.cap_cents, seq=excluded.seq,
                      recovered_total=excluded.recovered_total, updated_at=excluded.updated_at''',
                   (group_id, ledger["member_id"], ledger["service_date"], ledger["cap"],
                    ledger["seq"], ledger["recovered_total"], now))
        for claim_id in ledger["order"]:
            claim = ledger["claims"][claim_id]
            db.execute('''INSERT INTO settlement_claims(
                          group_id,claim_id,member_id,service_date,payer,billed_cents,approved_cents,
                          deductible_cents,seq,late,due_cents,paid_cents,recovered_cents)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(claim_id) DO UPDATE SET due_cents=excluded.due_cents,
                          paid_cents=excluded.paid_cents, recovered_cents=excluded.recovered_cents,
                          late=excluded.late, seq=excluded.seq''',
                       (group_id, claim["claim_id"], claim["member_id"], claim["service_date"], claim["payer"],
                        claim["billed_cents"], claim["approved_cents"], claim["deductible_cents"], claim["seq"],
                        int(claim["late"]), claim["due"], claim["paid"], claim["recovered"]))
        start = ledger.get("_loaded_events", 0)
        for event in ledger["events"][start:]:
            db.execute("INSERT INTO settlement_events(group_id,kind,payload,created_at) VALUES(?,?,?,?)",
                       (group_id, event["type"], json.dumps(event, ensure_ascii=False), now))
        known = {row["confirmation_key"] for row in
                 db.execute("SELECT confirmation_key FROM settlement_recovery_keys WHERE group_id=?",
                            (group_id,)).fetchall()}
        for event in ledger["events"]:
            if event["type"] == "RECOVERY_CONFIRMED" and event["confirmation_key"] not in known:
                db.execute('''INSERT OR IGNORE INTO settlement_recovery_keys
                              (confirmation_key,group_id,claim_id,amount_cents,created_at)
                              VALUES(?,?,?,?,?)''',
                           (event["confirmation_key"], group_id, event["claim_id"],
                            event["amount_cents"], now))
                known.add(event["confirmation_key"])
        ledger["_loaded_events"] = len(ledger["events"])
