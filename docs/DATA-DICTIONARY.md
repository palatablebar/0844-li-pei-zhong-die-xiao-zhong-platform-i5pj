# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `claim_id` | text | 主键 |
| `member_id` | text | 业务字段 |
| `service_date` | date | 业务字段 |
| `payer` | text | 业务字段 |
| `billed_cents` | int | 业务字段 |
| `approved_cents` | int | 业务字段 |
| `deductible_cents` | int | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。
