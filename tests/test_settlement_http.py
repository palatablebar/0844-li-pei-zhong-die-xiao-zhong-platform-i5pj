"""结算 HTTP、SQLite 持久化与端到端工作台核对测试。"""


def claim(cid, payer, billed, approved, member="M1", day="2026-11-10", late=False):
    payload = {"claim_id": cid, "member_id": member, "service_date": day, "payer": payer,
               "billed_cents": billed, "approved_cents": approved, "deductible_cents": 0}
    if late:
        payload["late"] = True
    return payload


def gid(member="M1", day="2026-11-10"):
    return member + "|" + day


def register(client, payload):
    return client.post("/api/settlement/claims", json=payload)


def test_full_late_claim_recovery_flow_over_http(client):
    # 低顺位先签发
    response = register(client, claim("K2", "PRIVATE", 10000, 10000))
    assert response.status_code == 200
    # 晚到高顺位：重算，旧款未追回前净实付不超过上限
    response = register(client, claim("K1", "MEDICARE", 10000, 8000, late=True))
    view = response.get_json()
    assert view["within_cap"] is True
    assert view["net_paid_total_cents"] == 10000
    k1 = next(row for row in view["claims"] if row["claim_id"] == "K1")
    assert k1["net_paid_cents"] == 0
    assert k1["pending_topup_cents"] == 8000
    # 确认追回后补齐
    response = client.post(f"/api/settlement/groups/{gid()}/recoveries",
                           json={"claim_id": "K2", "amount_cents": 8000, "confirmation_key": "REC-1"})
    assert response.status_code == 200
    view = response.get_json()
    k1 = next(row for row in view["claims"] if row["claim_id"] == "K1")
    assert k1["net_paid_cents"] == 8000
    assert view["all_settled"] is True


def test_partial_balance_is_paid_same_day(client):
    register(client, claim("K2", "PRIVATE", 10000, 6000))
    response = register(client, claim("K1", "MEDICARE", 10000, 8000, late=True))
    view = response.get_json()
    k1 = next(row for row in view["claims"] if row["claim_id"] == "K1")
    # 余额 4000 当天即付，剩余 4000 待补
    assert k1["net_paid_cents"] == 4000
    assert k1["pending_topup_cents"] == 4000
    assert view["within_cap"] is True


def test_recovery_retry_is_idempotent_and_does_not_double_topup(client):
    register(client, claim("K2", "PRIVATE", 10000, 10000))
    register(client, claim("K1", "MEDICARE", 10000, 8000, late=True))
    body = {"claim_id": "K2", "amount_cents": 8000, "confirmation_key": "REC-1"}
    first = client.post(f"/api/settlement/groups/{gid()}/recoveries", json=body).get_json()
    retry = client.post(f"/api/settlement/groups/{gid()}/recoveries", json=body).get_json()
    assert first["recovered_total_cents"] == retry["recovered_total_cents"] == 8000
    assert retry["idempotent_hit"] is True
    k1_first = next(row for row in first["claims"] if row["claim_id"] == "K1")
    k1_retry = next(row for row in retry["claims"] if row["claim_id"] == "K1")
    assert k1_first["paid_cents"] == k1_retry["paid_cents"] == 8000
    # 事件流里只有一次追回确认
    recoveries = [event for event in retry["events"] if event["type"] == "RECOVERY_CONFIRMED"]
    assert len(recoveries) == 1


def test_state_survives_reload_and_recovery_key_persists(client, tmp_path):
    register(client, claim("K2", "PRIVATE", 10000, 10000))
    register(client, claim("K1", "MEDICARE", 10000, 8000, late=True))
    client.post(f"/api/settlement/groups/{gid()}/recoveries",
                json={"claim_id": "K2", "amount_cents": 8000, "confirmation_key": "REC-1"})
    # 用同一数据库重新创建应用，模拟进程重启
    from app.main import create_app
    db_path = str(tmp_path / "workbench.sqlite3")
    app = create_app(db_path)
    app.config.update(TESTING=True)
    new_client = app.test_client()
    response = new_client.get(f"/api/settlement/groups/{gid()}")
    assert response.status_code == 200
    view = response.get_json()
    assert view["recovered_total_cents"] == 8000
    # 重启后同一确认键重试仍然幂等
    retry = new_client.post(f"/api/settlement/groups/{gid()}/recoveries",
                            json={"claim_id": "K2", "amount_cents": 8000, "confirmation_key": "REC-1"}).get_json()
    assert retry["idempotent_hit"] is True
    assert retry["recovered_total_cents"] == 8000


def test_workbench_lists_all_groups_for_reconciliation(client):
    register(client, claim("K1", "MEDICARE", 10000, 8000, member="M1", day="2026-11-10"))
    register(client, claim("K3", "PRIVATE", 5000, 4500, member="M2", day="2026-11-11"))
    response = client.get("/api/settlement/groups")
    groups = response.get_json()["groups"]
    assert {group["group_id"] for group in groups} == {"M1|2026-11-10", "M2|2026-11-11"}
    # 工作台可逐组核对各方实付与待补
    for group in groups:
        assert "within_cap" in group and "claims" in group
        for row in group["claims"]:
            assert {"net_paid_cents", "pending_topup_cents", "overpaid_recovery_cents"} <= set(row)


def test_missing_group_and_claim_return_404(client):
    assert client.get("/api/settlement/groups/NO|BODY").status_code == 404
    response = client.post("/api/settlement/groups/NO|BODY/recoveries",
                           json={"claim_id": "K9", "amount_cents": 100, "confirmation_key": "X"})
    assert response.status_code == 404
    assert response.get_json()["code"] == "GROUP_NOT_FOUND"


def test_bad_inputs_are_rejected(client):
    bad_payer = register(client, claim("K9", "OTHER", 1000, 100))
    assert bad_payer.status_code == 400
    over_billed = register(client, claim("K9", "SELF", 100, 101))
    assert over_billed.get_json()["code"] == "APPROVED_OVER_BILLED"
    missing = client.post("/api/settlement/claims", json={"claim_id": "K9"})
    assert missing.status_code == 400
    register(client, claim("K2", "PRIVATE", 10000, 6000))
    over_recovery = client.post(f"/api/settlement/groups/{gid()}/recoveries",
                                json={"claim_id": "K2", "amount_cents": 6001, "confirmation_key": "X"})
    assert over_recovery.status_code == 409
    assert over_recovery.get_json()["code"] == "RECOVERY_OVER_PAID"


def test_recovery_requires_confirmation_key(client):
    register(client, claim("K2", "PRIVATE", 10000, 6000))
    response = client.post(f"/api/settlement/groups/{gid()}/recoveries",
                           json={"claim_id": "K2", "amount_cents": 100})
    assert response.status_code == 400


def test_invalid_date_and_non_integer_amount_are_rejected(client):
    bad_day = register(client, claim("K9", "SELF", 1000, 100, day="11/10/2026"))
    assert bad_day.status_code == 400
    assert bad_day.get_json()["code"] == "BAD_DATE"
    bad_amount = client.post("/api/settlement/claims",
                             json={"claim_id": "K9", "member_id": "M1", "service_date": "2026-11-10",
                                   "payer": "SELF", "billed_cents": "abc", "approved_cents": 1,
                                   "deductible_cents": 0})
    assert bad_amount.status_code == 400
    assert bad_amount.get_json()["code"] == "BAD_AMOUNT"


def test_recovery_with_non_positive_amount_is_rejected(client):
    register(client, claim("K2", "PRIVATE", 10000, 6000))
    response = client.post(f"/api/settlement/groups/{gid()}/recoveries",
                           json={"claim_id": "K2", "amount_cents": 0, "confirmation_key": "X"})
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_RECOVERY_AMOUNT"


def test_unknown_claim_recovery_returns_404(client):
    register(client, claim("K2", "PRIVATE", 10000, 6000))
    response = client.post(f"/api/settlement/groups/{gid()}/recoveries",
                           json={"claim_id": "GHOST", "amount_cents": 100, "confirmation_key": "X"})
    assert response.status_code == 404
    assert response.get_json()["code"] == "CLAIM_NOT_FOUND"
