from sqlalchemy import inspect, text
from src.config import database
from src import models

# 历史库直接升级：只做增量加列，不重建或清空既有业务表
_UPGRADES = {
    'jobs': [('withdrawn', 'BOOLEAN NOT NULL DEFAULT 0')],
    'reports': [('withdrawn', 'BOOLEAN NOT NULL DEFAULT 0')],
    'deliveries': [('blocked', 'BOOLEAN NOT NULL DEFAULT 0')],
}

def migrate():
    # 动态取当前引擎，避免在模块导入时固化连接
    engine = database.engine
    database.Base.metadata.create_all(engine)
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _UPGRADES.items():
            if table not in existing:
                continue
            present = {col['name'] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name not in present:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}'))

if __name__ == '__main__':
    migrate()
