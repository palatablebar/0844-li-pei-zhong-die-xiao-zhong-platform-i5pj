"""顺位结算 HTTP 接口。

- POST /api/settlement/claims            登记理赔（late=true 表示晚到高顺位件，触发重算）
- POST /api/settlement/groups/<gid>/recoveries  确认追回，幂等补付
- GET  /api/settlement/groups/<gid>      单组台账（各方实付/待补核对）
- GET  /api/settlement/groups            全量工作台台账
"""
from flask import Blueprint, jsonify, request

from app.settlement import service

settlement_api = Blueprint("settlement_api", __name__)


def store():
    from flask import current_app
    return current_app.extensions["settlements"]


@settlement_api.post("/claims")
def register_claim_route():
    data = request.get_json(silent=True) or {}
    return jsonify(service.register(store(), data))


@settlement_api.post("/groups/<group_id>/recoveries")
def recovery_route(group_id):
    data = request.get_json(silent=True) or {}
    return jsonify(service.recover(store(), group_id, data))


@settlement_api.get("/groups/<group_id>")
def group_route(group_id):
    return jsonify(service.get_group(store(), group_id))


@settlement_api.get("/groups")
def groups_route():
    return jsonify(groups=service.list_groups(store()))
