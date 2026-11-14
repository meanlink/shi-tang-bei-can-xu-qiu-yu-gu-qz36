"""撤回与归档写入竞争的守卫逻辑（行锁 FOR UPDATE 仅 MySQL 生效，SQLite 验证守卫分支）。"""
import time
from conftest import auth
from helpers import create_dataset, create_completed_job


def test_deliver_skips_disabled_or_withdrawn_report(app_env):
    env = app_env
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'], '并发守卫批次')
    jid = create_completed_job(S, d['id'], approved=True)
    from src.models import Report, Delivery, Job
    from src.services.reports import deliver
    with S() as db:
        # 情况一：计划已停用（撤回事务刚提交），投递直接放弃
        r1 = Report(name='停用计划', job_id=jid, destination='组', interval_seconds=86400,
                    next_run=time.time() - 1, enabled=False, withdrawn=True)
        db.add(r1); db.flush()
        assert deliver(db, r1) is None
        # 情况二：任务撤回标记已置位，即使计划仍启用也放弃
        j = db.get(Job, jid)
        j.withdrawn = True
        r2 = Report(name='启用但任务撤回', job_id=jid, destination='组', interval_seconds=86400,
                    next_run=time.time() - 1, enabled=True)
        db.add(r2); db.flush()
        assert deliver(db, r2) is None
        db.commit()
        assert db.query(Delivery).count() == 0
