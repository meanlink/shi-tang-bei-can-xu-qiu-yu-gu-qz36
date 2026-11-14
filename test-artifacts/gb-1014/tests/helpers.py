import time
from conftest import auth

def make_records():
    from src.services.business import seed_records
    return seed_records()

def create_dataset(client, token, name='测试批次-112天'):
    r = client.post('/api/datasets', headers=auth(token),
                    json={'name': name, 'source': 'unit.json', 'records': make_records()})
    assert r.status_code == 201, r.text
    return r.json()

def create_completed_job(Session, dataset_id, approved=False):
    """直接构造一个已完成（可选已批准）的任务，绕过 worker。"""
    from src.models import User, Job, Dataset
    from src.services.business import analyze, metadata
    with Session() as db:
        admin = db.query(User).filter_by(role='admin').one()
        params = {p['key']: p['default'] for p in metadata()['parameters']}
        result = analyze(db.get(Dataset, dataset_id).records, params)
        j = Job(name=f'试算-{dataset_id}', dataset_id=dataset_id, params=params, status='completed',
                result=result, approved=approved, created_by=admin.id, created_at=time.time(),
                finished_at=time.time())
        db.add(j); db.commit()
        return j.id

def create_report_and_delivery(Session, job_id, with_delivery=True):
    from src.models import Report
    from src.services.reports import deliver
    with Session() as db:
        r = Report(name='简报', job_id=job_id, destination='复核组', interval_seconds=86400,
                   next_run=time.time()-1, enabled=True)
        db.add(r); db.flush()
        delivery = deliver(db, r) if with_delivery else None
        db.commit()
        return r.id, (delivery.id if delivery else None)
