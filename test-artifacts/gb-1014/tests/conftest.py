import os, sys, pathlib
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 后端目录按本文件位置定位：tests -> gb-1014 -> test-artifacts -> 仓库根 -> backend
_BACKEND = pathlib.Path(__file__).resolve().parents[3] / 'backend'
sys.path.insert(0, str(_BACKEND))

# 测试开始前固定环境变量，再导入应用模块（只导入一次，避免 declarative 注册表错位）
_TMP = __import__('tempfile').mkdtemp()
os.environ.setdefault('DATABASE_URL', f'sqlite:///{_TMP}/base.db')
os.environ.setdefault('ARTIFACT_DIR', f'{_TMP}/artifacts')
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('REDIS_URL', 'redis://127.0.0.1:6390/0')
os.environ.setdefault('SEED_DEMO', 'false')


@pytest.fixture()
def app_env(tmp_path):
    from src.config import database
    from src import models
    from src.utils.security import hash_password

    db_path = tmp_path / 'test.db'
    art = tmp_path / 'artifacts'
    art.mkdir()
    from src.config import settings as app_settings
    app_settings.ARTIFACT_DIR = str(art)
    engine = create_engine(f'sqlite:///{db_path}', connect_args={'check_same_thread': False})
    Session = sessionmaker(engine, expire_on_commit=False)
    # 每个用例独立库：直接替换模块级 engine/Session，不 reload，保持 Base 注册表一致
    database.engine = engine
    database.Session = Session
    database.Base.metadata.create_all(engine)

    with Session() as db:
        db.add(models.User(email='admin@demo.local', name='负责人', role='admin',
                           password=hash_password('Demo123!')))
        db.add(models.User(email='analyst@demo.local', name='分析员', role='analyst',
                           password=hash_password('Demo123!')))
        db.add(models.User(email='viewer@demo.local', name='观察员', role='viewer',
                           password=hash_password('Demo123!')))
        db.commit()

    from src.main import app as api_app
    from fastapi import FastAPI
    root = FastAPI()
    root.mount('/api', api_app)
    client = TestClient(root)

    def login(email):
        r = client.post('/api/auth/login', json={'email': email, 'password': 'Demo123!'})
        return r.json()['access_token']

    yield {'client': client, 'Session': Session, 'engine': engine, 'art': art,
           'admin': login('admin@demo.local'), 'analyst': login('analyst@demo.local'),
           'viewer': login('viewer@demo.local')}
    # 释放请求依赖可能缓存的连接，避免下个用例连到已删除的 SQLite 文件
    from src.config import database as dbcfg
    engine.dispose()
    if dbcfg.engine is not engine:
        dbcfg.engine.dispose()


def auth(token):
    return {'Authorization': f'Bearer {token}'}
