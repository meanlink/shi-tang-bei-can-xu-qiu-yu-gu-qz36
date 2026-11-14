"""整批撤回业务规则测试。"""
import time
import pytest
from conftest import auth
from helpers import create_dataset, create_completed_job, create_report_and_delivery


@pytest.fixture()
def env(app_env):
    return app_env


def test_withdrawal_full_cascade(env):
    """撤回生效：排队/运行中作废、批准失效、计划停用、归档禁下载、其他批次不受影响。"""
    c, S = env['client'], env['Session']
    d1 = create_dataset(c, env['admin'], '批次一')
    d2 = create_dataset(c, env['admin'], '批次二')
    # 批次一：一个已批准已完成任务 + 一个排队任务，带计划与归档
    j_done = create_completed_job(S, d1['id'], approved=True)
    rid, did = create_report_and_delivery(S, j_done)
    rq = c.post('/api/jobs', headers=auth(env['admin']),
                json={'name': '排队试算', 'dataset_id': d1['id'], 'params': {}})
    assert rq.status_code == 201
    j_queued = rq.json()['id']
    # 批次二：已批准任务，应照常可用
    j_other = create_completed_job(S, d2['id'], approved=True)

    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d1['id'], 'reason': '档口记错为二楼，整批撤回'})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w['status'] == 'completed'
    assert len(w['affected']['jobs']) == 2
    assert len(w['affected']['reports']) == 1
    assert len(w['affected']['deliveries']) == 1

    from src.models import Job, Report, Delivery
    with S() as db:
        assert db.get(Job, j_queued).status == 'voided'
        jd = db.get(Job, j_done)
        assert jd.withdrawn is True and jd.approved is False and jd.status == 'completed'
        rep = db.get(Report, rid)
        assert rep.enabled is False and rep.withdrawn is True
        dl = db.get(Delivery, did)
        assert dl.blocked is True
        # 其他批次照常
        jo = db.get(Job, j_other)
        assert jo.withdrawn is False and jo.approved is True

    # 归档文件仍在磁盘（留作审计），但下载被拒
    import os
    assert os.path.exists(os.path.join(str(env['art']), dl.filename))
    dlr = c.get(f'/api/deliveries/{did}/download?format=csv', headers=auth(env['viewer']))
    assert dlr.status_code == 410
    # 停用计划不能重新启用
    tr = c.post(f'/api/reports/{rid}/toggle', headers=auth(env['admin']))
    assert tr.status_code == 409
    # 撤回批次不能再发起试算
    nr = c.post('/api/jobs', headers=auth(env['analyst']),
                json={'name': '撤回后试算', 'dataset_id': d1['id'], 'params': {}})
    assert nr.status_code == 409
    # 其他批次仍可发起试算
    ok = c.post('/api/jobs', headers=auth(env['analyst']),
                json={'name': '其他批次试算', 'dataset_id': d2['id'], 'params': {}})
    assert ok.status_code == 201
    # 已撤回结果不能再批准
    ar = c.post(f'/api/jobs/{j_done}/approve', headers=auth(env['admin']))
    assert ar.status_code == 409


def test_permissions(env):
    c = env['client']
    d = create_dataset(c, env['admin'])
    # analyst/viewer 不能发起撤回
    for token in (env['analyst'], env['viewer']):
        r = c.post('/api/withdrawals', headers=auth(token),
                   json={'dataset_id': d['id'], 'reason': '无权限撤回测试原因'})
        assert r.status_code == 403
    # 原因过短被拒
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '短'})
    assert r.status_code == 422
    # 不存在的批次
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': 9999, 'reason': '不存在的批次撤回原因'})
    assert r.status_code == 404
    # viewer 可查看列表
    r = c.get('/api/withdrawals', headers=auth(env['viewer']))
    assert r.status_code == 200


def test_duplicate_withdrawal_rejected(env):
    c = env['client']
    d = create_dataset(c, env['admin'])
    r1 = c.post('/api/withdrawals', headers=auth(env['admin']),
                json={'dataset_id': d['id'], 'reason': '第一次撤回，原因足够长'})
    assert r1.status_code == 201
    r2 = c.post('/api/withdrawals', headers=auth(env['admin']),
                json={'dataset_id': d['id'], 'reason': '重复撤回，原因足够长'})
    assert r2.status_code == 409


def test_late_completion_cannot_revive(env, monkeypatch):
    """撤回与计算完成竞争：任务运行中被撤回，worker 迟到写回必须丢弃。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    rq = c.post('/api/jobs', headers=auth(env['admin']),
                json={'name': '运行中试算', 'dataset_id': d['id'], 'params': {}})
    jid = rq.json()['id']
    from src.models import Job
    with S() as db:
        j = db.get(Job, jid)
        j.status = 'running'  # 模拟 worker 已抢占
        db.commit()
    # 撤回生效
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '运行中撤回，原因足够长'})
    assert r.status_code == 201
    # 模拟 worker 计算完成后的迟到写回（与 worker.execute 相同的 CAS 语句）
    from sqlalchemy import update
    with S() as db:
        rowcount = db.execute(update(Job).where(
            Job.id == jid, Job.status == 'running', Job.withdrawn == False
        ).values(status='completed', finished_at=time.time())).rowcount
        db.commit()
        assert rowcount == 0
        j = db.get(Job, jid)
        assert j.status == 'voided' and j.withdrawn is True


def test_late_approval_loses(env):
    """撤回与批准同时提交：撤回优先后，迟到批准被拒。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    jid = create_completed_job(S, d['id'], approved=False)
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '批准竞争撤回，原因足够长'})
    assert r.status_code == 201
    ar = c.post(f'/api/jobs/{jid}/approve', headers=auth(env['admin']))
    assert ar.status_code == 409
    from src.models import Job
    with S() as db:
        assert db.get(Job, jid).approved is False


def test_late_delivery_blocked(env):
    """撤回赶上归档写入：撤回后 worker 到期投递不再产生新归档，旧归档阻断下载。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    jid = create_completed_job(S, d['id'], approved=True)
    rid, did = create_report_and_delivery(S, jid)
    before = len(c.get('/api/deliveries', headers=auth(env['admin'])).json())
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '归档竞争撤回，原因足够长'})
    assert r.status_code == 201
    # worker tick 不应再为该计划投递
    from src.worker import tick
    tick()
    after = len(c.get('/api/deliveries', headers=auth(env['admin'])).json())
    assert after == before
    # 旧归档下载被拒
    assert c.get(f'/api/deliveries/{did}/download?format=json',
                 headers=auth(env['admin'])).status_code == 410


def test_failed_withdrawal_retry_idempotent(env, monkeypatch):
    """注入故障制造 failed 撤回单，重试成功且不重复记账。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    jid = create_completed_job(S, d['id'], approved=True)
    rid, did = create_report_and_delivery(S, jid)

    import src.services.withdrawals as wsvc
    real_snapshot = wsvc.snapshot
    calls = {'n': 0}
    def flaky(db, dataset):
        calls['n'] += 1
        if calls['n'] == 2:  # 第一次 process 内部的收尾快照失败
            raise RuntimeError('注入的存储故障')
        return real_snapshot(db, dataset)
    monkeypatch.setattr(wsvc, 'snapshot', flaky)

    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '失败重试场景，原因足够长'})
    assert r.status_code == 201
    assert r.json()['status'] == 'failed'
    wid = r.json()['id']

    # 撤回单已落库；故障期间已执行的级联随保存点回滚
    from src.models import Job, Report, Delivery, Withdrawal, Audit
    with S() as db:
        assert db.get(Withdrawal, wid).status == 'failed'
        j = db.get(Job, jid)
        assert j.withdrawn is False and j.approved is True
        assert db.get(Report, rid).withdrawn is False
        assert db.get(Delivery, did).blocked is False
        failed_audits = db.query(Audit).filter(Audit.action == 'withdrawal.failed').count()
        assert failed_audits == 1

    monkeypatch.undo()
    # 重试成功
    rr = c.post(f'/api/withdrawals/{wid}/retry', headers=auth(env['admin']))
    assert rr.status_code == 200
    assert rr.json()['status'] == 'completed'
    with S() as db:
        assert db.get(Job, jid).withdrawn is True
        assert db.get(Report, rid).enabled is False
        assert db.get(Delivery, did).blocked is True
        # completed 审计只记一次，重试不重复记账
        assert db.query(Audit).filter(Audit.action == 'withdrawal.completed').count() == 1
        assert db.query(Audit).filter(Audit.action == 'withdrawal.retry.request').count() == 1

    # 已完成撤回单再重试被拒
    again = c.post(f'/api/withdrawals/{wid}/retry', headers=auth(env['admin']))
    assert again.status_code == 409


def test_worker_resume_interrupted_processing(env):
    """处理中断留下 processing：worker 周期接管并完成。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    jid = create_completed_job(S, d['id'], approved=True)
    # 直接插入一张中断的 processing 撤回单
    from src.models import Withdrawal
    from src.services.audit import record
    with S() as db:
        from src.models import User
        admin = db.query(User).filter_by(role='admin').one()
        w = Withdrawal(dataset_id=d['id'], reason='中断恢复场景，原因足够长', status='processing',
                       affected={}, created_by=admin.id, created_at=time.time(), updated_at=time.time())
        db.add(w); db.commit()
        wid = w.id
    from src.worker import tick
    tick()
    from src.models import Job, Withdrawal as W
    with S() as db:
        assert db.get(W, wid).status == 'completed'
        assert db.get(Job, jid).withdrawn is True


def test_worker_recovery_voids_running_withdrawn_job(env):
    """worker 崩溃重启：已撤回批次的 running 任务恢复为 voided，普通任务重新排队。"""
    c, S = env['client'], env['Session']
    d1 = create_dataset(c, env['admin'], '恢复批次一')
    d2 = create_dataset(c, env['admin'], '恢复批次二')
    r1 = c.post('/api/jobs', headers=auth(env['admin']),
                json={'name': '任务A', 'dataset_id': d1['id'], 'params': {}}).json()['id']
    r2 = c.post('/api/jobs', headers=auth(env['admin']),
                json={'name': '任务B', 'dataset_id': d2['id'], 'params': {}}).json()['id']
    from src.models import Job
    with S() as db:
        for i in (r1, r2):
            j = db.get(Job, i); j.status = 'running'
        db.commit()
    c.post('/api/withdrawals', headers=auth(env['admin']),
           json={'dataset_id': d1['id'], 'reason': '崩溃恢复撤回，原因足够长'})
    # 模拟 worker 启动恢复逻辑（main 中的恢复段）
    from sqlalchemy import select, update
    with S() as db:
        for j in db.scalars(select(Job).where(Job.status == 'running')):
            if j.withdrawn:
                db.execute(update(Job).where(Job.id == j.id).values(status='voided', finished_at=time.time()))
            else:
                db.execute(update(Job).where(Job.id == j.id).values(status='queued'))
        db.commit()
    with S() as db:
        assert db.get(Job, r1).status == 'voided'
        assert db.get(Job, r2).status == 'queued'


def test_retry_requires_failed_state(env):
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    r = c.post('/api/withdrawals', headers=auth(env['admin']),
               json={'dataset_id': d['id'], 'reason': '正常完成的撤回，原因足够长'})
    wid = r.json()['id']
    # 完成态不能重试；不存在的撤回单 404
    assert c.post(f'/api/withdrawals/{wid}/retry', headers=auth(env['admin'])).status_code == 409
    assert c.post('/api/withdrawals/9999/retry', headers=auth(env['admin'])).status_code == 404


def test_report_creation_uses_only_approved_non_withdrawn(env):
    """撤回后不能基于旧结果建新分发计划。"""
    c, S = env['client'], env['Session']
    d = create_dataset(c, env['admin'])
    jid = create_completed_job(S, d['id'], approved=True)
    c.post('/api/withdrawals', headers=auth(env['admin']),
           json={'dataset_id': d['id'], 'reason': '停用分发场景，原因足够长'})
    r = c.post('/api/reports', headers=auth(env['admin']),
               json={'name': '新计划', 'job_id': jid, 'destination': '复核组',
                     'interval_seconds': 86400, 'delay_seconds': 0})
    assert r.status_code == 409
