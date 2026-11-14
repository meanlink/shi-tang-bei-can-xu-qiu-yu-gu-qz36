import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from src.config import settings
from src.models import Job, Report, Delivery
def create(db, data):
    j=db.get(Job,data.job_id)
    if not j or j.status!='completed' or not j.approved:
        raise HTTPException(409,'请先选择已完成且获批准的分析结果')
    if j.withdrawn:
        raise HTTPException(409,'该结果所属批次已撤回，不能再安排分发')
    r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r
def deliver(db, report):
    # 撤回生效后计划会被停用并锁定；再检查一次以挡住与撤回并发的到期投递
    if not report.enabled or report.withdrawn:
        return
    try:
        # 行锁串行化计划投递：撤回事务若先锁定该行，本次投递直接放弃，
        # 避免“归档写入与撤回同时发生”时产生撤回后的新归档
        report = db.query(Report).filter(Report.id == report.id).with_for_update().one()
    except NoResultFound:
        return
    if not report.enabled or report.withdrawn:
        return
    j=db.get(Job,report.job_id)
    if not j or not j.approved or j.withdrawn: return
    out=io.StringIO()
    out.write('﻿')
    table=j.result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    def safe(v):
        if isinstance(v,(int,float)) and not isinstance(v,bool): return v
        text=str(v)
        return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    data=out.getvalue().encode('utf-8')
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(settings.ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(settings.ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(settings.ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({'job':j.name,'params':j.params,'result':j.result,'checksum':delivery.checksum},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery
