from app.domain.helpers import D


def decide_rows(items):
    for item in items:
        if item["requested"] > item["billed"] * 11 // 10:
            item["verdict"] = "REJECT"
            item["reason"] = "MATERIAL_OVERPAY"
        elif item["paid"] > item["billed"]:
            item["verdict"] = "REVIEW"
            item["reason"] = "OVER_BILLED"
        elif item["claims"] > 1 and item["paid"] == item["billed"]:
            item["verdict"] = "REVIEW"
            item["reason"] = "FULL_STACK"
        else:
            item["verdict"] = "PASS"
            item["reason"] = "WITHIN_BILLED"
        item.setdefault("verdict", "PASS")
        item.setdefault("reason", "OK")
    return items
