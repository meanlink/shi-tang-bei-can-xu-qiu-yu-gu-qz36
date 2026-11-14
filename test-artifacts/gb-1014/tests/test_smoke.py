"""端到端冒烟：seed 演示数据 → 审批/分发正常 → 撤回 → 归档阻断 → 重复撤回拒绝。"""
import tempfile, pathlib, os
from sqlalchemy import create_engine


def test_seed_demo_and_full_flow():
    tmp = pathlib.Path(tempfile.mkdtemp())
    url = f'sqlite:///{tmp}/smoke.db'
    os.environ['DATABASE_URL'] = url
    os.environ['ARTIFACT_DIR'] = str(tmp / 'art')
    os.environ['JWT_SECRET'] = 'smoke-secret'
    os.environ['SEED_DEMO'] = 'false'
    os.environ['REDIS_URL'] = 'redis://127.0.0.1:6390/0'
    from src.config import database, settings as app_settings
    app_settings.ARTIFACT_DIR = str(tmp / 'art')
    engine = create_engine(url, connect_args={'check_same_thread': False})
    prev_engine, prev_bind = database.engine, database.Session.kw['bind']
    database.engine = engine
    database.Session.configure(bind=engine)
    try:
        from migrations.initial import migrate
        migrate()
        from scripts.seed_demo import seed
        counts = seed()
        assert counts['jobs'] >= 1 and counts['deliveries'] >= 1
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.main import app as api_app
        root = FastAPI(); root.mount('/api', api_app)
        c = TestClient(root)
        tok = c.post('/api/auth/login', json={'email': 'admin@demo.local', 'password': 'Demo123!'}).json()['access_token']
        h = {'Authorization': f'Bearer {tok}'}
        # 演示数据里的归档可下载
        did = c.get('/api/deliveries', headers=h).json()[0]['id']
        assert c.get(f'/api/deliveries/{did}/download?format=csv', headers=h).status_code == 200
        # 撤回该批次
        ds_id = c.get('/api/datasets', headers=h).json()[0]['id']
        r = c.post('/api/withdrawals', headers=h, json={'dataset_id': ds_id, 'reason': '冒烟测试整批撤回原因'})
        assert r.status_code == 201 and r.json()['status'] == 'completed'
        # 归档立即禁下载，文件仍在磁盘
        assert c.get(f'/api/deliveries/{did}/download?format=csv', headers=h).status_code == 410
        assert (tmp / 'art').exists() and any((tmp / 'art').iterdir())
        # worker tick 不再投递，也不报错
        from src.worker import tick
        tick()
        # 撤回单列表可查，含关联对象与原因
        wl = c.get('/api/withdrawals', headers=h).json()
        assert len(wl) == 1 and wl[0]['reason'] == '冒烟测试整批撤回原因'
        assert wl[0]['affected']['jobs'] and wl[0]['affected']['deliveries']
        # 重复撤回被拒
        again = c.post('/api/withdrawals', headers=h, json={'dataset_id': ds_id, 'reason': '再次撤回原因足够长'})
        assert again.status_code == 409
    finally:
        database.engine = prev_engine
        database.Session.configure(bind=prev_bind)
