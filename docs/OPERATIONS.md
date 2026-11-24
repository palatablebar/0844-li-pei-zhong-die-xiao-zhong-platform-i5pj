# 运行说明

## 启动

```bash
docker compose up --build
```

## 测试

```bash
docker compose exec -T app pytest -q
```

## 样例

- `dirty`：包含编码、列数、空值或冲突重复，适合检查隔离区。
- `clean`：可通过当前规则并完成签发。

## 重置

```bash
docker compose down -v
docker compose up --build
```

历史批次保存在 SQLite 卷中。重置会清除本地批次与签发记录。

## 顺位结算

工作台底部「顺位结算 · 追回补付」面板支持登记理赔（勾选晚到件触发同组应付重算）、确认追回并自动补付，以及核对各方应付、净实付、待补与待追回。结算台账默认与批次库同目录（`settlement.sqlite3`），可用 `SETTLEMENT_DB` 覆盖；追回确认靠 `confirmation_key` 幂等，同键重试不会重复补付。
