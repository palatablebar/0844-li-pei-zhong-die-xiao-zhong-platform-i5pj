# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据。
- `GET /api/examples/{profile}`：下载样例。
- `GET /healthz`：健康检查。

## 顺位结算（追回补付）

- `POST /api/settlement/claims`：登记一笔理赔。同成员同服务日自动归入同一结算组；`late=true` 表示晚到件，触发全组各方应付重算。
- `GET /api/settlement/groups`：返回全部结算组台账，供工作台核对各方应付、实付、已追回、净实付、待补与待追回。
- `GET /api/settlement/groups/{group_id}`：读取单个结算组（`group_id` 为 `成员|服务日`）。
- `POST /api/settlement/groups/{group_id}/recoveries`：确认一笔旧款追回，提交 `claim_id`、`amount_cents`、`confirmation_key`；确认后按支付方顺位补齐待补。`confirmation_key` 为业务幂等键，同键重试返回 `idempotent_hit=true` 且不重复补付。
