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

## 顺位结算台账字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `group_id` | text | 结算组主键，格式为 `member_id\|service_date` |
| `cap_cents` | int | 票据上限，取组内最高 `billed_cents` |
| `due_cents` | int | 按支付方优先级重算后的应付金额 |
| `paid_cents` | int | 累计已付（含补付，未扣减追回） |
| `recovered_cents` | int | 该笔已确认追回金额 |
| `net_paid_cents` | int | 净实付 = `paid_cents - recovered_cents`，全组合计不得超过 `cap_cents` |
| `pending_topup_cents` | int | 待补金额：应付高于净实付的差额，追回确认后按顺位补齐 |
| `overpaid_recovery_cents` | int | 待追回金额：净实付高于应付的多付部分 |
| `late` | bool | 是否为晚到件，晚到件登记会触发全组应付重算 |
| `confirmation_key` | text | 追回确认幂等键，同键重试不重复补付 |
| `idempotent_hit` | bool | 本次追回请求是否命中既有确认（未产生新记账） |
