"""结算应用服务：登记理赔（含晚到重算）、确认追回（幂等补付）、台账核对。"""
from datetime import date

from app.errors import DomainIssue
from app.settlement.ledger import (
    SettlementError,
    confirm_recovery,
    group_key,
    group_view,
    new_ledger,
    register_claim,
)
from app.settlement.store import SettlementStore

CLAIM_FIELDS = ("claim_id", "member_id", "service_date", "payer",
                "billed_cents", "approved_cents", "deductible_cents")


def _domain_error(exc):
    mapping = {
        "BAD_PAYER": ("BAD_PAYER", 400),
        "BAD_AMOUNT": ("BAD_AMOUNT", 400),
        "APPROVED_OVER_BILLED": ("APPROVED_OVER_BILLED", 400),
        "GROUP_MISMATCH": ("GROUP_MISMATCH", 409),
        "CLAIM_INCOMPLETE": ("BAD_REQUEST", 400),
        "CLAIM_NOT_FOUND": ("CLAIM_NOT_FOUND", 404),
        "BAD_RECOVERY_AMOUNT": ("BAD_RECOVERY_AMOUNT", 400),
        "RECOVERY_OVER_PAID": ("RECOVERY_OVER_PAID", 409),
    }
    code, status = mapping.get(exc.code, ("SETTLEMENT_RULE", 400))
    return DomainIssue(code, status, exc.detail)


def _require_claim_payload(data):
    missing = [field for field in CLAIM_FIELDS if data.get(field) in (None, "")]
    if missing:
        raise DomainIssue("BAD_REQUEST", 400, "缺少字段: " + ",".join(missing))
    claim = {field: data[field] for field in CLAIM_FIELDS}
    for field in ("billed_cents", "approved_cents", "deductible_cents"):
        try:
            claim[field] = int(claim[field])
        except (TypeError, ValueError):
            raise DomainIssue("BAD_AMOUNT", 400, field)
    if not isinstance(claim["service_date"], str):
        raise DomainIssue("BAD_REQUEST", 400, "service_date 需为 ISO 日期字符串")
    try:
        date.fromisoformat(claim["service_date"])
    except ValueError:
        raise DomainIssue("BAD_DATE", 400, claim["service_date"])
    return claim


def register(store: SettlementStore, data):
    """登记一笔理赔。``late=true`` 表示晚到件，触发同组各方应付重算。"""
    claim = _require_claim_payload(data)
    late = bool(data.get("late", False))
    gid = group_key(claim["member_id"], claim["service_date"])

    def mutation(ledger):
        if ledger is None:
            ledger = new_ledger(claim["member_id"], claim["service_date"])
        try:
            register_claim(ledger, claim, late=late)
        except SettlementError as exc:
            raise _domain_error(exc)
        return ledger, group_view(ledger)

    return store.transact(gid, mutation)


def recover(store: SettlementStore, group_id, data):
    """确认一笔旧款追回并按顺位补齐待补；confirmation_key 保证重试幂等。"""
    claim_id = data.get("claim_id")
    confirmation_key = data.get("confirmation_key")
    if not claim_id or not confirmation_key:
        raise DomainIssue("BAD_REQUEST", 400, "claim_id 与 confirmation_key 必填")
    try:
        amount = int(data.get("amount_cents"))
    except (TypeError, ValueError):
        raise DomainIssue("BAD_RECOVERY_AMOUNT", 400)

    def mutation(ledger):
        if ledger is None:
            raise DomainIssue("GROUP_NOT_FOUND", 404, group_id)
        try:
            _, changed = confirm_recovery(ledger, claim_id, amount, confirmation_key)
        except SettlementError as exc:
            raise _domain_error(exc)
        view = group_view(ledger)
        view["idempotent_hit"] = not changed
        return ledger, view

    return store.transact(group_id, mutation)


def get_group(store: SettlementStore, group_id):
    ledger = store.load(group_id)
    if ledger is None:
        raise DomainIssue("GROUP_NOT_FOUND", 404, group_id)
    return group_view(ledger)


def list_groups(store: SettlementStore):
    return [get_group(store, group_id) for group_id in store.list_groups()]
