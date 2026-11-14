from pydantic import BaseModel, Field
class WithdrawalInput(BaseModel):
    dataset_id: int
    reason: str = Field(min_length=4, max_length=500)
