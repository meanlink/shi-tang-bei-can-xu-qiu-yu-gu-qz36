"""历史数据直接升级：旧库没有新列时迁移自动补齐，数据不丢。"""
import tempfile, pathlib
from sqlalchemy import create_engine, inspect, text


def test_migration_adds_columns_to_legacy_db():
    tmp = pathlib.Path(tempfile.mkdtemp())
    url = f'sqlite:///{tmp}/legacy.db'
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(150), name VARCHAR(160), role VARCHAR(20), password VARCHAR(300))'))
        c.execute(text('CREATE TABLE datasets (id INTEGER PRIMARY KEY, name VARCHAR(160), source VARCHAR(200), records JSON, checksum VARCHAR(64), created_at FLOAT)'))
        c.execute(text("INSERT INTO datasets VALUES (1,'旧批次','old.json','[]','abc',0)"))
        c.execute(text('CREATE TABLE jobs (id INTEGER PRIMARY KEY, name VARCHAR(160), dataset_id INTEGER, params JSON, status VARCHAR(20), result JSON, error VARCHAR(1000), approved BOOLEAN, created_by INTEGER, created_at FLOAT, finished_at FLOAT)'))
        c.execute(text("INSERT INTO jobs VALUES (1,'旧试算',1,'{}','completed','{}','',1,1,0,0)"))
        c.execute(text('CREATE TABLE reports (id INTEGER PRIMARY KEY, name VARCHAR(160), job_id INTEGER, destination VARCHAR(120), interval_seconds INTEGER, next_run FLOAT, enabled BOOLEAN)'))
        c.execute(text("INSERT INTO reports VALUES (1,'旧计划',1,'组',86400,0,1)"))
        c.execute(text('CREATE TABLE deliveries (id INTEGER PRIMARY KEY, report_id INTEGER, created_at FLOAT, checksum VARCHAR(64), filename VARCHAR(160), destination VARCHAR(120))'))
        c.execute(text("INSERT INTO deliveries VALUES (1,1,0,'sha','f.csv','组')"))
        c.execute(text('CREATE TABLE audits (id INTEGER PRIMARY KEY, actor VARCHAR(150), action VARCHAR(80), detail JSON, at FLOAT)'))

    import os
    os.environ['DATABASE_URL'] = url
    os.environ['ARTIFACT_DIR'] = str(tmp / 'art')
    os.environ['SEED_DEMO'] = 'false'
    from src.config import database
    prev_engine, prev_bind = database.engine, database.Session.kw['bind']
    database.engine = engine
    database.Session.configure(bind=engine)
    try:
        from migrations.initial import migrate
        migrate()  # 第一次：补列、建 withdrawals 表
        migrate()  # 第二次：幂等，不报错
        cols = {t: {c['name'] for c in inspect(engine).get_columns(t)} for t in ('jobs', 'reports', 'deliveries')}
        assert 'withdrawn' in cols['jobs'] and 'withdrawn' in cols['reports'] and 'blocked' in cols['deliveries']
        assert 'withdrawals' in inspect(engine).get_table_names()
        with engine.begin() as c:
            # 旧数据保留，新列取安全默认值
            assert c.execute(text('SELECT name, withdrawn FROM jobs')).fetchone() == ('旧试算', 0)
            assert c.execute(text('SELECT filename, blocked FROM deliveries')).fetchone() == ('f.csv', 0)
            assert c.execute(text('SELECT name FROM datasets')).fetchone()[0] == '旧批次'
    finally:
        # 还原全局绑定，避免污染同进程其他用例
        database.engine = prev_engine
        database.Session.configure(bind=prev_bind)
