from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .settings import DATABASE_URL

class Base(DeclarativeBase):
    pass

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
Session = sessionmaker(engine, expire_on_commit=False)

def get_db():
    # 动态取模块属性：会话工厂可被测试或运维环节替换，路由始终拿到当前工厂
    with Session() as db:
        yield db
