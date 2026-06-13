"""Payment routes: plans, order creation, callbacks, order history."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.middleware.auth import get_current_user
from app.services.payment import payment_service

router = APIRouter(prefix="/payment", tags=["payment"])


class CreateOrderRequest(BaseModel):
    plan_id: str
    payment_method: str  # wechat / alipay
    order_type: str = "topup"  # topup / tier_upgrade


@router.get("/plans")
async def list_plans():
    return {
        "plans": payment_service.CREDIT_PLANS,  # backward compatibility
        "credit_plans": payment_service.CREDIT_PLANS,
        "tier_plans": payment_service.TIER_PLANS,
    }


@router.post("/create-order")
async def create_order(req: CreateOrderRequest, user=Depends(get_current_user)):
    if req.payment_method not in ("wechat", "alipay"):
        raise HTTPException(400, "Invalid payment method")
    if req.order_type not in ("topup", "tier_upgrade"):
        raise HTTPException(400, "Invalid order type")
    settings = get_settings()
    if req.payment_method == "wechat" and not settings.wechat_mch_id:
        raise HTTPException(400, "WeChat Pay not configured")
    if req.payment_method == "alipay" and not settings.alipay_app_id:
        raise HTTPException(400, "Alipay not configured")

    order = await payment_service.create_order(
        user_id=int(user["id"]),
        plan_id=req.plan_id,
        payment_method=req.payment_method,
        order_type=req.order_type,
    )

    if req.order_type == "tier_upgrade":
        target_tier = order.get("target_tier") or "pro"
        tier_days = int(order.get("tier_days") or 0)
        description = f"{target_tier.upper()} 套餐升级 {tier_days} 天"
    else:
        description = f"积分充值 {order['credits']} 积分"

    if req.payment_method == "wechat":
        try:
            return await payment_service.create_wechat_native_order(
                order["order_no"],
                int(order["amount_cents"]),
                description,
            )
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
    try:
        return await payment_service.create_alipay_order(
            order["order_no"],
            int(order["amount_cents"]),
            description,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/callback/wechat")
async def wechat_callback(request: Request):
    body = await request.body()
    headers = dict(request.headers)

    verified = await payment_service.verify_wechat_callback(headers, body)
    if not verified:
        raise HTTPException(400, "Verification failed")

    await payment_service.process_payment_success(verified["order_no"], verified["trade_no"])
    return {"code": "SUCCESS", "message": "OK"}


@router.post("/callback/alipay")
async def alipay_callback(request: Request):
    form = await request.form()
    params = dict(form)

    verified = await payment_service.verify_alipay_callback(params)
    if not verified:
        return "fail"

    await payment_service.process_payment_success(verified["order_no"], verified["trade_no"])
    return "success"


@router.get("/orders")
async def list_orders(user=Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT order_no, amount_cents, credits, payment_method, status, paid_at, created_at,
                       order_type, plan_id, tier_target, tier_days
                FROM orders
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 50
                """
            ),
            {"user_id": user["id"]},
        )
        rows = result.mappings().fetchall()
    return {"orders": [dict(r) for r in rows]}
