from flask import jsonify


MESSAGES = {
    "EMPTY_FILE": "文件为空",
    "BLANK_FILE": "文件只有空白",
    "HEADER_ONLY": "文件只有表头",
    "HEADER_MISMATCH": "表头与本项目字段不一致",
    "UNCLOSED_QUOTE": "引号未闭合，文件已拒收",
    "TOO_MANY_ROWS": "数据行超过上限",
    "FILE_TOO_LARGE": "文件超过大小上限",
    "KEY_MISSING": "主键为空",
    "CONFLICT_DUPLICATE": "同一键存在冲突内容",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "阶段不存在",
    "RUN_NOT_FOUND": "批次不存在",
    "STALE_REVIEW": "批次已被更新，请刷新后复核",
    "GATE_BLOCKED": "存在阻断项，不能签发",
    "NOT_APPROVED": "批次尚未签发",
    "BAD_REQUEST": "请求内容不完整",
    "GROUP_NOT_FOUND": "结算组不存在",
    "CLAIM_NOT_FOUND": "理赔记录不存在",
    "BAD_PAYER": "支付方不在支持范围内",
    "BAD_AMOUNT": "金额字段不合法",
    "BAD_DATE": "服务日不是合法 ISO 日期",
    "APPROVED_OVER_BILLED": "核准金额超过票据金额",
    "GROUP_MISMATCH": "成员或服务日与结算组不一致",
    "BAD_RECOVERY_AMOUNT": "追回金额必须为正整数",
    "RECOVERY_OVER_PAID": "追回金额超过该笔净实付",
    "SETTLEMENT_RULE": "结算规则校验未通过",
}


class DomainIssue(Exception):
    def __init__(self, code: str, status: int = 400, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(code)


def error_response(exc: DomainIssue):
    return jsonify(error=exc.detail or MESSAGES.get(exc.code, "请求无法处理"), code=exc.code), exc.status
