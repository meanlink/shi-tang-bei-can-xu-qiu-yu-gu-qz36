from sqlalchemy import String, JSON, Double, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Withdrawal(Base):
    __tablename__ = 'withdrawals'
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    reason: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default='processing')
    # 关联对象快照与处理结果，保证重试不重复记账，也供页面直接展示
    affected: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
