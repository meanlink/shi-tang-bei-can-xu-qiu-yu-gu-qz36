"""领餐批次整批撤回。

撤回是对数据批次的终局性操作，在单个数据库事务内完成全部级联：
排队/运行中的试算作废、已批准结果失去批准、分发计划停用、历史归档禁下载。
所有写库语句都是幂等的条件更新，处理中断后重试不会重复记账，
且任何迟到的写回（计算完成、批准、归档）都必须先检查 withdrawn 标记，
因此撤回一旦生效就不可能被并发或迟到操作恢复可用。
"""
import time
from fastapi import HTTPException
from sqlalchemy import select, update
from src.models import Dataset, Job, Report, Delivery, Withdrawal
from src.services.audit import record

ACTIVE_WITHDRAWAL = ('processing', 'failed')
ANY_WITHDRAWAL = ACTIVE_WITHDRAWAL + ('completed',)


def snapshot(db, dataset):
    """收集批次当前的全部关联对象，用于页面展示与处理结果留痕。"""
    jobs = list(db.scalars(select(Job).where(Job.dataset_id == dataset.id).order_by(Job.id)))
    job_ids = [j.id for j in jobs]
    reports = list(db.scalars(select(Report).where(Report.job_id.in_(job_ids)).order_by(Report.id))) if job_ids else []
    report_ids = [r.id for r in reports]
    deliveries = list(db.scalars(select(Delivery).where(Delivery.report_id.in_(report_ids)).order_by(Delivery.id))) if report_ids else []
    return {
        'dataset': {'id': dataset.id, 'name': dataset.name},
        'jobs': [{'id': j.id, 'name': j.name, 'status': j.status, 'approved': j.approved,
                  'voided': j.status in ('queued', 'running')} for j in jobs],
        'reports': [{'id': r.id, 'name': r.name, 'enabled': r.enabled} for r in reports],
        'deliveries': [{'id': d.id, 'filename': d.filename, 'blocked': d.blocked} for d in deliveries],
    }


def is_dataset_withdrawn(db, dataset_id):
    """存在处理中/失败/完成任一撤回单即视为已撤回：失败也不允许继续派生新业务。"""
    return db.scalar(select(Withdrawal.id).where(
        Withdrawal.dataset_id == dataset_id,
        Withdrawal.status.in_(ANY_WITHDRAWAL),
    ).limit(1)) is not None


def withdrawn_dataset_ids(db, dataset_ids):
    """批量查询已撤回批次，供列表页一次取全，避免 N+1 查询。"""
    if not dataset_ids:
        return set()
    rows = db.scalars(select(Withdrawal.dataset_id).where(
        Withdrawal.dataset_id.in_(dataset_ids),
        Withdrawal.status.in_(ANY_WITHDRAWAL),
    )).all()
    return set(rows)


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    existing = db.scalar(select(Withdrawal).where(
        Withdrawal.dataset_id == dataset.id,
        Withdrawal.status.in_(ANY_WITHDRAWAL),
    ).order_by(Withdrawal.id.desc()))
    if existing:
        raise HTTPException(409, f'该批次已存在撤回单（#{existing.id}，状态 {existing.status}），不可重复撤回')
    now = time.time()
    w = Withdrawal(dataset_id=dataset.id, reason=data.reason.strip(), status='processing',
                   affected=snapshot(db, dataset), created_by=user.id,
                   created_at=now, updated_at=now)
    db.add(w)
    db.flush()
    record(db, user.email, 'withdrawal.create', {'id': w.id, 'dataset_id': dataset.id})
    # 撤回单先随请求事务提交落库；级联处理由路由在新事务中调用 start，
    # 这样处理失败只回滚级联动作，撤回单本身保留为 failed 可重试
    return w


def start(db, w, actor):
    return process(db, w, actor=actor)


def process(db, w, actor='system'):
    """幂等推进撤回处理。可被请求线程或 worker 重复调用，不重复记账。"""
    if w.status == 'completed':
        return w
    now = time.time()
    try:
        # 保存点：级联失败仅回滚级联动作，撤回单状态与审计记录仍在同一事务内保留
        db.begin_nested()
        dataset = db.get(Dataset, w.dataset_id)
        if not dataset:
            raise RuntimeError('数据批次已不存在，无法定位撤回对象')
        job_ids = list(db.scalars(select(Job.id).where(Job.dataset_id == dataset.id)))
        # 1) 排队与运行中的试算直接作废（条件更新，重复执行无副作用）
        db.execute(update(Job).where(
            Job.dataset_id == dataset.id, Job.status.in_(('queued', 'running'))
        ).values(status='voided', finished_at=now))
        # 2) 全部试算打上撤回终局标记，已批准结果失去批准；迟到写回据此拒绝复活
        db.execute(update(Job).where(Job.dataset_id == dataset.id).values(withdrawn=True, approved=False))
        if job_ids:
            # 3) 分发计划停用并锁定，worker 与手工启用都不会再投递
            db.execute(update(Report).where(Report.job_id.in_(job_ids)).values(enabled=False, withdrawn=True))
            report_ids = list(db.scalars(select(Report.id).where(Report.job_id.in_(job_ids))))
            if report_ids:
                # 4) 已归档文件保留作审计，仅阻断下载
                db.execute(update(Delivery).where(Delivery.report_id.in_(report_ids)).values(blocked=True))
        w.affected = snapshot(db, dataset)
        w.status = 'completed'
        w.error = ''
        w.finished_at = now
        w.updated_at = now
        record(db, actor, 'withdrawal.completed', {
            'id': w.id, 'dataset_id': dataset.id,
            'jobs': len(w.affected['jobs']), 'reports': len(w.affected['reports']),
            'deliveries': len(w.affected['deliveries']),
        })
    except Exception as exc:
        # 回滚到保存点，保留撤回单；随后记录失败态与失败审计
        db.rollback()
        w = db.get(Withdrawal, w.id)
        w.status = 'failed'
        w.error = str(exc)[:990]
        w.updated_at = time.time()
        record(db, actor, 'withdrawal.failed', {'id': w.id, 'error': w.error})
    return w


def retry(db, w, user):
    if w.status == 'completed':
        raise HTTPException(409, '撤回已完成，无需重试')
    if w.status != 'failed':
        raise HTTPException(409, '撤回仍在处理中，请稍后刷新查看')
    # 重试请求本身由路由统一记审计，这里只做幂等推进
    return process(db, w, actor=user.email)


def resume_stale(db):
    """worker 周期调用：接管处理中断（进程崩溃等）留下的 processing 撤回单。"""
    stale = list(db.scalars(select(Withdrawal).where(Withdrawal.status == 'processing')))
    for w in stale:
        process(db, w, actor='worker')
    return stale
