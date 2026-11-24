"""顺位结算领域：晚到高顺位理赔的重算、追回与补付。

结算以同一成员同一服务日为一个结算组（settlement group），金额一律使用整数分。
组内按支付方优先级给付（数字越小顺位越高），合计净实付不得超过票据上限。

状态以事件溯源方式维护：
- CLAIM_REGISTERED  理赔登记（首次或晚到，晚到会触发各方应付重算）
- PAYMENT_MADE      实际付款
- RECOVERY_CONFIRMED 追回确认（带幂等键，重试不会重复补付）

重算只调整"应付（due）"，已经实际付出的钱通过付款与追回事件体现；
在旧款追回确认之前，净实付不能超过票据上限，因此高顺位只能先付可用余额，
其余进入待补（pending），待追回确认后按优先级补齐。
"""
from datetime import date

PAYER_PRIORITY = {"MEDICARE": 1, "PRIVATE": 2, "SELF": 3}


class SettlementError(ValueError):
    """结算规则冲突，code 为稳定的机器可读错误码。"""

    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def priority_of(payer):
    try:
        return PAYER_PRIORITY[payer.upper()]
    except KeyError:
        raise SettlementError("BAD_PAYER", payer)


def group_key(member_id, service_date):
    if isinstance(service_date, date):
        service_date = service_date.isoformat()
    return member_id + "|" + service_date


def _claim_view(claim):
    """对外的理赔视图，派生实付/待补等字段。"""
    view = {key: claim[key] for key in
            ("claim_id", "member_id", "service_date", "payer", "billed_cents",
             "approved_cents", "deductible_cents", "seq", "late")}
    view["due_cents"] = claim["due"]
    view["paid_cents"] = claim["paid"]
    view["recovered_cents"] = claim["recovered"]
    # 净实付 = 实付 - 已追回
    net_paid = claim["paid"] - claim["recovered"]
    view["net_paid_cents"] = net_paid
    gap = claim["due"] - net_paid
    # gap>0：还差多少没付（待补）；gap<0：多付多少待追回
    view["pending_topup_cents"] = max(0, gap)
    view["overpaid_recovery_cents"] = max(0, -gap)
    view["pending_cents"] = gap
    view["settled"] = gap == 0
    return view


def new_ledger(member_id, service_date):
    """创建空结算组台账。"""
    return {
        "group_id": group_key(member_id, service_date),
        "member_id": member_id,
        "service_date": service_date.isoformat() if isinstance(service_date, date) else service_date,
        "cap": 0,
        "seq": 0,
        "claims": {},          # claim_id -> 理赔状态
        "order": [],           # claim_id 登记顺序
        "recovered_total": 0,  # 全组已确认追回总额
        "events": [],
        "recovery_keys": set(),
    }


def _sorted_claims(ledger):
    return sorted(ledger["claims"].values(),
                  key=lambda claim: (priority_of(claim["payer"]), claim["claim_id"]))


def _recalc(ledger):
    """按当前全部理赔重算各方应付（due），并在票据上限内安排可执行付款。

    应付重算：顺位优先，每方应付 = min(核准额, 上限 - 前置应付合计)。
    付款安排：净实付不得超过票据上限，且只能动用"已确认追回"释放的额度，
    所以高顺位在旧款追回前只能付当前可用余额，不足部分留待追回后补付。
    """
    claims = _sorted_claims(ledger)
    cap = ledger["cap"]
    running_due = 0
    for claim in claims:
        claim["due"] = min(claim["approved_cents"], max(0, cap - running_due))
        running_due += claim["due"]
    # 可用付款空间 = 票据上限 - 当前全组净实付（净实付本身恒不超过上限）
    net_paid = sum(claim["paid"] - claim["recovered"] for claim in claims)
    available = max(0, cap - net_paid)
    for claim in claims:
        unpaid = claim["due"] - (claim["paid"] - claim["recovered"])
        amount = min(max(0, unpaid), available)
        if amount:
            claim["paid"] += amount
            available -= amount
            ledger["events"].append({
                "type": "PAYMENT_MADE",
                "claim_id": claim["claim_id"],
                "amount_cents": amount,
                "reason": "LATE_TOPUP" if claim["late"] else "SCHEDULED",
            })


def register_claim(ledger, claim, late=False):
    """登记一笔理赔；晚到的高顺位理赔会触发全组应付重算。

    同一 claim_id 重复登记按幂等处理，直接返回既有状态，不产生新事件。
    """
    required = ("claim_id", "member_id", "service_date", "payer",
                "billed_cents", "approved_cents", "deductible_cents")
    missing = [key for key in required if key not in claim]
    if missing:
        raise SettlementError("CLAIM_INCOMPLETE", ",".join(missing))
    claim_id = claim["claim_id"]
    if claim_id in ledger["claims"]:
        return ledger["claims"][claim_id]
    key = group_key(claim["member_id"], claim["service_date"])
    if key != ledger["group_id"]:
        raise SettlementError("GROUP_MISMATCH", key + " != " + ledger["group_id"])
    priority_of(claim["payer"])
    billed, approved, deductible = (int(claim["billed_cents"]), int(claim["approved_cents"]),
                                    int(claim["deductible_cents"]))
    if billed < 0 or approved < 0 or deductible < 0:
        raise SettlementError("BAD_AMOUNT", claim_id)
    if approved > billed:
        raise SettlementError("APPROVED_OVER_BILLED", claim_id)
    ledger["seq"] += 1
    stored = {
        "claim_id": claim_id,
        "member_id": claim["member_id"],
        "service_date": claim["service_date"].isoformat()
        if isinstance(claim["service_date"], date) else claim["service_date"],
        "payer": claim["payer"],
        "billed_cents": billed,
        "approved_cents": approved,
        "deductible_cents": deductible,
        "seq": ledger["seq"],
        "late": bool(late),
        "due": 0,
        "paid": 0,
        "recovered": 0,
    }
    ledger["claims"][claim_id] = stored
    ledger["order"].append(claim_id)
    # 票据上限取组内最高票据金额
    ledger["cap"] = max(ledger["cap"], billed)
    ledger["events"].append({
        "type": "CLAIM_REGISTERED",
        "claim_id": claim_id,
        "late": bool(late),
        "billed_cents": billed,
        "approved_cents": approved,
    })
    _recalc(ledger)
    return stored


def confirm_recovery(ledger, claim_id, amount_cents, confirmation_key):
    """确认一笔旧款追回，释放票据额度并按顺位补齐待补应付。

    confirmation_key 为追回确认的业务幂等键：同一笔确认重试不会重复记账、
    不会重复补付。追回额不得超过该理赔的当前净实付。
    """
    if confirmation_key in ledger["recovery_keys"]:
        return _sorted_claims(ledger), False
    claim = ledger["claims"].get(claim_id)
    if claim is None:
        raise SettlementError("CLAIM_NOT_FOUND", claim_id)
    amount = int(amount_cents)
    if amount <= 0:
        raise SettlementError("BAD_RECOVERY_AMOUNT", str(amount))
    net_paid = claim["paid"] - claim["recovered"]
    if amount > net_paid:
        raise SettlementError("RECOVERY_OVER_PAID", claim_id)
    ledger["recovery_keys"].add(confirmation_key)
    claim["recovered"] += amount
    ledger["recovered_total"] += amount
    ledger["events"].append({
        "type": "RECOVERY_CONFIRMED",
        "claim_id": claim_id,
        "amount_cents": amount,
        "confirmation_key": confirmation_key,
    })
    _recalc(ledger)
    return _sorted_claims(ledger), True


def group_view(ledger):
    """组台账视图：供工作台核对各方实付与待补，并做上限守恒校验。"""
    claims = _sorted_claims(ledger)
    rows = [_claim_view(claim) for claim in claims]
    due_total = sum(row["due_cents"] for row in rows)
    paid_total = sum(row["paid_cents"] for row in rows)
    net_paid_total = sum(row["net_paid_cents"] for row in rows)
    topup_total = sum(row["pending_topup_cents"] for row in rows)
    recovery_due_total = sum(row["overpaid_recovery_cents"] for row in rows)
    pending_total = sum(row["pending_cents"] for row in rows)
    return {
        "group_id": ledger["group_id"],
        "member_id": ledger["member_id"],
        "service_date": ledger["service_date"],
        "cap_cents": ledger["cap"],
        "due_total_cents": due_total,
        "paid_total_cents": paid_total,
        "recovered_total_cents": ledger["recovered_total"],
        "net_paid_total_cents": net_paid_total,
        "pending_topup_total_cents": topup_total,
        "overpaid_recovery_total_cents": recovery_due_total,
        "pending_total_cents": pending_total,
        "all_settled": topup_total == 0 and recovery_due_total == 0,
        "within_cap": net_paid_total <= ledger["cap"],
        "claims": rows,
        "events": list(ledger["events"]),
    }
