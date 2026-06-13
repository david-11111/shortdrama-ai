"""
积分预扣中间件。

在任务派发前调用，预扣积分。
任务成功后由 worker 调用 charge 确认。
任务失败后由 worker 调用 refund 退还。
"""
from fastapi import HTTPException

from app.services.credits import InsufficientCreditsError, credit_service


async def reserve_credits(user_id: int, operation: str, quantity: int = 1) -> str:
    """
    预扣积分。返回 transaction_id。
    余额不足抛 HTTPException(402)。
    """
    try:
        transaction_id = await credit_service.reserve(user_id, operation, quantity)
        return transaction_id
    except InsufficientCreditsError as e:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Insufficient credits",
                "message": str(e),
                "operation": operation,
                "quantity": quantity,
            },
        )
