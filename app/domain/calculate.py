from datetime import date, timedelta
from app.catalog import SPEC
from app.domain.helpers import *  # noqa: F401,F403


def calculate_rows(items):
    out = []
    rows = items
    groups = {}
    priority = {"MEDICARE": 1, "PRIVATE": 2, "SELF": 3}
    for item in items:
        key = (item["member_id"], item["service_date"].isoformat())
        groups.setdefault(key, []).append(item)
    for (member, service_date), claims in groups.items():
        claims.sort(key=lambda row: (priority[row["payer"].upper()], row["claim_id"]))
        billed = max(row["billed_cents"] for row in claims)
        paid = 0
        requested = sum(row["approved_cents"] for row in claims)
        for claim in claims:
            claim["paid"] = min(claim["approved_cents"], max(0, billed - paid))
            paid += claim["paid"]
        out.append({"label": member + "|" + service_date, "billed": billed, "paid": paid, "requested": requested,
                    "claims": len(claims),
                    "breakdown": [f'{claim["payer"]} · {claim["claim_id"]} · {claim["paid"]} 分'
                                  for claim in claims],
                    "metric": D(str(paid), "CALC"),
                    "limit": D(str(billed), "LIMIT")})
    for item in out:
        item.setdefault("label", str(item.get(SPEC["key"], "")))
    return out
