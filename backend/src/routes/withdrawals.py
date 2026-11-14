from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config import database
from src.config.database import get_db
from src.models import Withdrawal
from src.schemas.withdrawal import WithdrawalInput
from src.middlewares.auth import current_user, admin_only
from src.services import withdrawals
from src.services.audit import record
from src.utils.serialization import withdrawal_dict
router = APIRouter(prefix='/withdrawals')

@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    rows = db.scalars(select(Withdrawal).order_by(Withdrawal.id.desc()).limit(100))
    return [withdrawal_dict(w) for w in rows]

@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    w = db.get(Withdrawal, id)
    if not w:
        raise HTTPException(404, '撤回单不存在')
    return withdrawal_dict(w)

@router.post('', status_code=201)
def create(data: WithdrawalInput, db=Depends(get_db), u=Depends(admin_only)):
    w = withdrawals.create(db, data, u)
    db.commit()
    # 级联处理放在独立事务：失败只回滚级联动作，撤回单本身保留为 failed 可重试。
    # 动态取当前会话工厂，保证与请求依赖使用同一个数据库。
    with database.Session() as work:
        w = work.get(Withdrawal, w.id)
        withdrawals.start(work, w, u.email)
        work.commit()
        return withdrawal_dict(work.get(Withdrawal, w.id))

@router.post('/{id}/retry')
def retry(id: int, db=Depends(get_db), u=Depends(admin_only)):
    w = db.get(Withdrawal, id)
    if not w:
        raise HTTPException(404, '撤回单不存在')
    record(db, u.email, 'withdrawal.retry.request', {'id': id})
    db.commit()
    with database.Session() as work:
        w = work.get(Withdrawal, id)
        withdrawals.retry(work, w, u)
        work.commit()
        return withdrawal_dict(work.get(Withdrawal, id))
