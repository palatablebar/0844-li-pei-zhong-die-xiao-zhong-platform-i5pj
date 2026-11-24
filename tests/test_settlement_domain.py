"""顺位结算领域规则测试：重算、净实付上限、部分付款、追回补付与幂等。"""
import pytest

from app.settlement.ledger import (
    SettlementError,
    confirm_recovery,
    group_key,
    group_view,
    new_ledger,
    register_claim,
)


def claim(cid, payer, billed, approved, member="M1", day="2026-11-10", deductible=0):
    return {"claim_id": cid, "member_id": member, "service_date": day, "payer": payer,
            "billed_cents": billed, "approved_cents": approved, "deductible_cents": deductible}


def by_id(view, cid):
    return next(row for row in view["claims"] if row["claim_id"] == cid)


def test_basic_priority_payment_uses_full_cap():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000))
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 3000))
    view = group_view(ledger)
    assert by_id(view, "K1")["net_paid_cents"] == 8000
    assert by_id(view, "K2")["net_paid_cents"] == 2000
    assert view["net_paid_total_cents"] == 10000
    assert view["within_cap"] is True
    assert view["all_settled"] is True


def test_late_higher_priority_triggers_recalc_for_every_party():
    # 低顺位 PRIVATE 先到并已按上限全额签发 10000
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 10000))
    view = group_view(ledger)
    assert by_id(view, "K2")["due_cents"] == 10000
    # 晚到的高顺位 MEDICARE，核准 8000：各方应付必须重算
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    view = group_view(ledger)
    assert by_id(view, "K1")["due_cents"] == 8000
    assert by_id(view, "K2")["due_cents"] == 2000  # 低顺位应付被压缩
    assert by_id(view, "K1")["late"] is True


def test_net_paid_never_exceeds_cap_before_recovery():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 10000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    view = group_view(ledger)
    # 旧款 10000 尚未追回，高顺位当天无额度可付，净实付仍恰好等于上限
    assert view["net_paid_total_cents"] == 10000
    assert view["within_cap"] is True
    assert by_id(view, "K1")["net_paid_cents"] == 0
    assert by_id(view, "K1")["pending_topup_cents"] == 8000
    # 低顺位多付部分标记为待追回
    assert by_id(view, "K2")["overpaid_recovery_cents"] == 8000


def test_partial_payment_when_balance_cannot_cover_high_priority():
    # 票据上限 10000，低顺位已付 6000，剩余余额 4000；高顺位需要 8000
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 6000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    view = group_view(ledger)
    # 当天能付的 4000 必须立即付给高顺位，而不是等追回后一次性付
    assert by_id(view, "K1")["net_paid_cents"] == 4000
    assert by_id(view, "K1")["pending_topup_cents"] == 4000
    assert view["net_paid_total_cents"] == 10000
    payments = [event for event in ledger["events"] if event["type"] == "PAYMENT_MADE"]
    assert {"claim_id": "K1", "amount_cents": 4000, "reason": "LATE_TOPUP"} in (
        {key: event[key] for key in ("claim_id", "amount_cents", "reason")} for event in payments)


def test_recovery_confirmed_then_remaining_due_is_topped_up():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 10000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    # 确认从低顺位追回 8000
    _, changed = confirm_recovery(ledger, "K2", 8000, "REC-1")
    assert changed is True
    view = group_view(ledger)
    assert by_id(view, "K2")["recovered_cents"] == 8000
    assert by_id(view, "K1")["net_paid_cents"] == 8000
    assert by_id(view, "K1")["pending_topup_cents"] == 0
    assert by_id(view, "K2")["net_paid_cents"] == 2000
    assert view["all_settled"] is True
    assert view["net_paid_total_cents"] == 10000
    assert view["within_cap"] is True


def test_repeated_recovery_confirmation_is_idempotent():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 10000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    confirm_recovery(ledger, "K2", 8000, "REC-1")
    events_before = len(ledger["events"])
    paid_before = {cid: row["paid"] for cid, row in ledger["claims"].items()}
    # 同一笔确认重试：不新增事件、不重复补付
    _, changed = confirm_recovery(ledger, "K2", 8000, "REC-1")
    assert changed is False
    assert len(ledger["events"]) == events_before
    assert {cid: row["paid"] for cid, row in ledger["claims"].items()} == paid_before
    view = group_view(ledger)
    assert view["recovered_total_cents"] == 8000
    assert by_id(view, "K1")["net_paid_cents"] == 8000


def test_partial_recovery_then_second_recovery_completes_topup():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 10000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    # 先只追回 3000：高顺位补 3000（累计 3000），仍欠 5000
    confirm_recovery(ledger, "K2", 3000, "REC-1")
    view = group_view(ledger)
    assert by_id(view, "K1")["net_paid_cents"] == 3000
    assert by_id(view, "K1")["pending_topup_cents"] == 5000
    # 再追回 5000：补齐
    confirm_recovery(ledger, "K2", 5000, "REC-2")
    view = group_view(ledger)
    assert by_id(view, "K1")["net_paid_cents"] == 8000
    assert view["all_settled"] is True


def test_recovery_cannot_exceed_net_paid():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 6000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    # K2 净实付 6000，不能追回 6001
    with pytest.raises(SettlementError) as exc:
        confirm_recovery(ledger, "K2", 6001, "REC-X")
    assert exc.value.code == "RECOVERY_OVER_PAID"


def test_non_positive_recovery_and_unknown_claim_are_rejected():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 6000))
    with pytest.raises(SettlementError) as exc:
        confirm_recovery(ledger, "K2", 0, "REC-0")
    assert exc.value.code == "BAD_RECOVERY_AMOUNT"
    with pytest.raises(SettlementError) as exc:
        confirm_recovery(ledger, "GHOST", 100, "REC-G")
    assert exc.value.code == "CLAIM_NOT_FOUND"


def test_duplicate_claim_registration_is_idempotent():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000))
    events_before = len(ledger["events"])
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 8000), late=True)
    assert len(ledger["events"]) == events_before
    assert len(ledger["claims"]) == 1


def test_cap_is_max_billed_and_approved_over_billed_rejected():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K2", "PRIVATE", 9000, 9000))
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 1000))
    assert ledger["cap"] == 10000
    with pytest.raises(SettlementError) as exc:
        register_claim(ledger, claim("K9", "SELF", 100, 101))
    assert exc.value.code == "APPROVED_OVER_BILLED"


def test_unknown_payer_and_group_mismatch_are_rejected():
    ledger = new_ledger("M1", "2026-11-10")
    with pytest.raises(SettlementError) as exc:
        register_claim(ledger, claim("K9", "OTHER", 1000, 100))
    assert exc.value.code == "BAD_PAYER"
    with pytest.raises(SettlementError) as exc:
        register_claim(ledger, claim("K8", "SELF", 1000, 100, member="M2"))
    assert exc.value.code == "GROUP_MISMATCH"


def test_second_late_claim_keeps_invariant_and_settles_after_recovery():
    ledger = new_ledger("M1", "2026-11-10")
    register_claim(ledger, claim("K3", "SELF", 10000, 10000))
    register_claim(ledger, claim("K2", "PRIVATE", 10000, 6000), late=True)  # 付 6000，SELF 欠 6000
    register_claim(ledger, claim("K1", "MEDICARE", 10000, 5000), late=True)  # 净实付已达上限，无余额可付
    view = group_view(ledger)
    assert view["net_paid_total_cents"] == 10000
    assert by_id(view, "K1")["net_paid_cents"] == 0
    assert by_id(view, "K1")["pending_topup_cents"] == 5000
    # 首次追回 6000：按顺位先补满 MEDICARE 5000，剩余 1000 补 PRIVATE
    confirm_recovery(ledger, "K3", 6000, "R1")
    view = group_view(ledger)
    assert by_id(view, "K1")["net_paid_cents"] == 5000
    assert by_id(view, "K2")["net_paid_cents"] == 1000
    assert by_id(view, "K2")["pending_topup_cents"] == 4000
    assert by_id(view, "K3")["overpaid_recovery_cents"] == 4000
    # 二次追回剩余多付款后，PRIVATE 补齐，全组结清，净实付恒不超过票据上限
    confirm_recovery(ledger, "K3", 4000, "R2")
    view = group_view(ledger)
    assert by_id(view, "K2")["net_paid_cents"] == 5000
    assert by_id(view, "K3")["net_paid_cents"] == 0
    assert view["all_settled"] is True
    assert view["net_paid_total_cents"] == 10000
    assert view["within_cap"] is True
    assert group_key("M1", "2026-11-10") == "M1|2026-11-10"
