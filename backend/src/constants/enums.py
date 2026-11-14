from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
    # 批次撤回生效后，排队与运行中的试算统一作废，且不能被任何迟到写回恢复
    voided = 'voided'
class WithdrawalStatus(str, Enum):
    processing = 'processing'
    completed = 'completed'
    failed = 'failed'
