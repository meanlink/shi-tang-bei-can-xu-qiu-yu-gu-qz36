import time, json, logging
from pathlib import Path
from sqlalchemy import select, update
from redis import Redis
from src.config import database
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services import withdrawals
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with database.Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        # CAS 抢占：撤回可能已把任务改为 voided，抢占失败立即退出
        claimed=db.execute(update(Job).where(Job.id==job_id,Job.status=='queued').values(status='running')).rowcount
        db.commit()
        if not claimed:return
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            # 撤回优先：withdrawn=1 时计算结果必须丢弃，迟到写回不能恢复可用
            written=db.execute(update(Job).where(
                Job.id==job_id,Job.status=='running',Job.withdrawn==False
            ).values(result=result,status='completed',finished_at=time.time())).rowcount
            if written:
                record(db,'worker','job.completed',{'id':job_id})
            else:
                record(db,'worker','job.abandoned_after_withdrawal',{'id':job_id})
        except Exception as e:
            logging.exception('Analysis failed')
            failed=db.execute(update(Job).where(
                Job.id==job_id,Job.status=='running',Job.withdrawn==False
            ).values(status='failed',error=str(e)[:990],finished_at=time.time())).rowcount
            if failed:record(db,'worker','job.failed',{'id':job_id,'error':str(e)[:990]})
        db.commit()
def tick():
    with database.Session() as db:
        # 先接管处理中断的撤回单，保证它先于本轮排队与投递生效
        withdrawals.resume_stale(db)
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
        db.commit()
    for job_id in queued:execute(job_id)
    with database.Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with database.Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            # 已撤回批次的运行中任务直接作废，不再重新排队
            if j.withdrawn:
                db.execute(update(Job).where(Job.id==j.id).values(status='voided',finished_at=time.time()))
                record(db,'worker','job.voided_on_recovery',{'id':j.id})
            else:
                db.execute(update(Job).where(Job.id==j.id).values(status='queued'))
                record(db,'worker','job.recovered',{'id':j.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
