import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d, withdrawn=False):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at, 'withdrawn':withdrawn}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','withdrawn','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled','withdrawn']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination','blocked']}
def withdrawal_dict(w):
    return {'id':w.id,'dataset_id':w.dataset_id,'reason':w.reason,'status':w.status,
            'affected':w.affected or {},'error':w.error,'created_by':w.created_by,
            'created_at':w.created_at,'updated_at':w.updated_at,'finished_at':w.finished_at}
