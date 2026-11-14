# 批次撤回功能测试

独立于应用源码的后端测试，使用 SQLite 内存文件库 + FastAPI TestClient，无需 MySQL/Redis。

## 运行

```bash
pip install -r backend/requirements.txt pytest httpx
cd test-artifacts/gb-1014/tests
python3 -m pytest -q
```

conftest.py 会按自身位置自动定位 `backend/`，每个用例使用独立临时数据库与产物目录。

## 覆盖范围

| 文件 | 覆盖的业务规则 |
|---|---|
| test_withdrawal.py | 整批撤回级联（试算作废/批准失效/计划停用/归档禁下载/其他批次不受影响）、权限、重复撤回拒绝、撤回优先于迟到计算完成与批准、归档竞争、失败重试幂等、worker 中断恢复、崩溃恢复 |
| test_race.py | 停用/撤回标记下投递守卫，撤回后不产生新归档 |
| test_upgrade.py | 历史库增量迁移：补列幂等、旧数据保留、withdrawals 表自动建立 |
| test_smoke.py | seed 演示数据端到端：下载 → 撤回 → 410 禁下载 → worker 不再投递 |
| test_audit.py | 撤回全过程审计留痕，重试不重复记账 |
| test_dataset_flag.py | 数据批次列表/详情的 withdrawn 标记 |

并发行锁（`SELECT ... FOR UPDATE`）仅 MySQL/InnoDB 生效，SQLite 不支持，
因此竞争场景在 test_race.py 中以守卫分支功能测试覆盖；生产 MySQL 下由行锁串行化保证。
