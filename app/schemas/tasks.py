from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TaskSubmitResponse(BaseModel):
    task_id: str
    status: str = "queued"
    message: str = "Task submitted successfully"
    main_chain_path: str = "platform_direct_task"


class BatchTaskSubmitResponse(BaseModel):
    parent_task_id: str
    child_task_ids: list[str]
    status: str = "queued"
    total_credits_reserved: int
    main_chain_path: str = "platform_direct_task"


class TaskStatusResponse(BaseModel):
    task_id: str
    task_type: str
    status: str
    progress: int = 0
    stage_text: Optional[str] = None
    result: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskListResponse(BaseModel):
    tasks: list[TaskStatusResponse]
    total: int
    page: int
    page_size: int


class TaskCancelResponse(BaseModel):
    task_id: str
    status: str
    message: str
