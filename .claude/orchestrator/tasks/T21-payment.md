# T21 指令 — 支付集成（微信/支付宝）

## 任务目标

实现积分充值支付功能：用户选择套餐 → 创建订单 → 跳转支付 → 回调确认 → 积分到账。

支持微信支付（Native/JSAPI）和支付宝（当面付/电脑网站支付）。

## 需要创建/修改的文件

### 1. `app/config.py` — 添加支付配置

```python
    # 微信支付
    wechat_app_id: str = ""
    wechat_mch_id: str = ""
    wechat_api_key: str = ""
    wechat_cert_serial: str = ""
    wechat_private_key_path: str = ""
    wechat_notify_url: str = ""

    # 支付宝
    alipay_app_id: str = ""
    alipay_private_key: str = ""
    alipay_public_key: str = ""
    alipay_notify_url: str = ""
    alipay_return_url: str = ""
```

### 2. `alembic/versions/003_add_orders_table.py`（新建）

创建订单表：

```sql
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    order_no VARCHAR(64) UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    amount_cents INTEGER NOT NULL,          -- 金额（分）
    credits INTEGER NOT NULL,               -- 对应积分数
    payment_method VARCHAR(20) NOT NULL,    -- wechat / alipay
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending / paid / failed / refunded
    trade_no VARCHAR(128),                  -- 第三方交易号
    paid_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_orders_user_id ON orders(user_id);
CREATE INDEX idx_orders_order_no ON orders(order_no);
CREATE INDEX idx_orders_status ON orders(status);
```

### 3. `app/services/payment.py`（新建）

支付服务，封装微信/支付宝下单和回调验签：

```python
"""
支付服务 — 微信支付 V3 + 支付宝。

功能:
- create_wechat_order: 创建微信支付订单（返回二维码 URL 或支付参数）
- create_alipay_order: 创建支付宝订单（返回跳转 URL）
- verify_wechat_callback: 验证微信支付回调签名
- verify_alipay_callback: 验证支付宝回调签名
- process_payment_success: 支付成功后积分到账
"""
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.db import AsyncSessionLocal

logger = logging.getLogger(__name__)


class PaymentService:
    """支付服务"""

    PRICING_PLANS = [
        {"id": "basic", "name": "基础包", "credits": 100, "price_cents": 990, "description": "100 积分"},
        {"id": "standard", "name": "标准包", "credits": 500, "price_cents": 3990, "description": "500 积分（8折）"},
        {"id": "premium", "name": "高级包", "credits": 2000, "price_cents": 12900, "description": "2000 积分（6.5折）"},
        {"id": "enterprise", "name": "企业包", "credits": 10000, "price_cents": 49900, "description": "10000 积分（5折）"},
    ]

    def get_plan(self, plan_id: str) -> dict | None:
        for plan in self.PRICING_PLANS:
            if plan["id"] == plan_id:
                return plan
        return None

    def generate_order_no(self) -> str:
        """生成唯一订单号"""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"ORD{ts}{uuid.uuid4().hex[:8].upper()}"

    async def create_order(
        self, user_id: int, plan_id: str, payment_method: str
    ) -> dict:
        """创建订单记录"""
        plan = self.get_plan(plan_id)
        if not plan:
            raise ValueError(f"Invalid plan: {plan_id}")

        order_no = self.generate_order_no()

        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("""
                        INSERT INTO orders (order_no, user_id, amount_cents, credits, payment_method, status)
                        VALUES (:order_no, :user_id, :amount_cents, :credits, :payment_method, 'pending')
                    """),
                    {
                        "order_no": order_no,
                        "user_id": user_id,
                        "amount_cents": plan["price_cents"],
                        "credits": plan["credits"],
                        "payment_method": payment_method,
                    },
                )

        return {
            "order_no": order_no,
            "amount_cents": plan["price_cents"],
            "credits": plan["credits"],
            "payment_method": payment_method,
        }

    async def create_wechat_native_order(self, order_no: str, amount_cents: int, description: str) -> dict:
        """创建微信 Native 支付订单（返回二维码链接）"""
        settings = get_settings()
        if not settings.wechat_mch_id:
            raise RuntimeError("WeChat Pay not configured")

        # 微信支付 V3 API — Native 下单
        url = "https://api.mch.weixin.qq.com/v3/pay/transactions/native"
        body = {
            "appid": settings.wechat_app_id,
            "mchid": settings.wechat_mch_id,
            "description": description,
            "out_trade_no": order_no,
            "notify_url": settings.wechat_notify_url,
            "amount": {"total": amount_cents, "currency": "CNY"},
        }

        # 签名（简化版，生产环境需要完整的 V3 签名）
        timestamp = str(int(time.time()))
        nonce = uuid.uuid4().hex
        sign_str = f"POST\n/v3/pay/transactions/native\n{timestamp}\n{nonce}\n{json.dumps(body)}\n"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f'WECHATPAY2-SHA256-RSA2048 mchid="{settings.wechat_mch_id}",nonce_str="{nonce}",timestamp="{timestamp}",serial_no="{settings.wechat_cert_serial}",signature="PLACEHOLDER"',
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            return {"code_url": data.get("code_url"), "order_no": order_no}
        else:
            logger.error("WeChat pay failed: %s %s", resp.status_code, resp.text)
            raise RuntimeError(f"WeChat pay API error: {resp.status_code}")

    async def create_alipay_order(self, order_no: str, amount_cents: int, description: str) -> dict:
        """创建支付宝订单（返回支付页面 URL）"""
        settings = get_settings()
        if not settings.alipay_app_id:
            raise RuntimeError("Alipay not configured")

        # 支付宝电脑网站支付
        amount_yuan = f"{amount_cents / 100:.2f}"
        params = {
            "app_id": settings.alipay_app_id,
            "method": "alipay.trade.page.pay",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": settings.alipay_notify_url,
            "return_url": settings.alipay_return_url,
            "biz_content": json.dumps({
                "out_trade_no": order_no,
                "total_amount": amount_yuan,
                "subject": description,
                "product_code": "FAST_INSTANT_TRADE_PAY",
            }),
        }

        # 生产环境需要 RSA2 签名
        # 这里返回构造好的参数，前端拼接跳转
        return {
            "payment_url": f"https://openapi.alipay.com/gateway.do",
            "params": params,
            "order_no": order_no,
        }

    async def process_payment_success(self, order_no: str, trade_no: str) -> dict:
        """支付成功回调处理：更新订单状态 + 积分到账"""
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # 查询订单
                result = await session.execute(
                    text("SELECT * FROM orders WHERE order_no = :order_no FOR UPDATE"),
                    {"order_no": order_no},
                )
                order = result.mappings().first()
                if not order:
                    raise ValueError(f"Order not found: {order_no}")
                if order["status"] == "paid":
                    return {"message": "Already processed", "order_no": order_no}

                # 更新订单状态
                await session.execute(
                    text("""
                        UPDATE orders
                        SET status = 'paid', trade_no = :trade_no, paid_at = NOW(), updated_at = NOW()
                        WHERE order_no = :order_no
                    """),
                    {"order_no": order_no, "trade_no": trade_no},
                )

                # 积分到账
                await session.execute(
                    text("""
                        UPDATE credit_accounts
                        SET balance = balance + :credits, updated_at = NOW()
                        WHERE user_id = :user_id
                    """),
                    {"credits": order["credits"], "user_id": order["user_id"]},
                )

                # 记录积分交易
                await session.execute(
                    text("""
                        INSERT INTO credit_transactions (user_id, amount, tx_type, description)
                        VALUES (:user_id, :amount, 'topup', :description)
                    """),
                    {
                        "user_id": order["user_id"],
                        "amount": order["credits"],
                        "description": f"充值 {order['credits']} 积分（订单 {order_no}）",
                    },
                )

        logger.info("Payment success: order=%s, credits=%d", order_no, order["credits"])
        return {"message": "Payment processed", "order_no": order_no, "credits": order["credits"]}

    async def verify_wechat_callback(self, headers: dict, body: bytes) -> dict | None:
        """验证微信支付回调（简化版）"""
        # 生产环境需要完整的 V3 回调验签
        try:
            data = json.loads(body)
            if data.get("event_type") == "TRANSACTION.SUCCESS":
                resource = data.get("resource", {})
                # 生产环境需要解密 resource.ciphertext
                return {
                    "order_no": resource.get("out_trade_no"),
                    "trade_no": resource.get("transaction_id"),
                }
        except Exception as exc:
            logger.error("WeChat callback verification failed: %s", exc)
        return None

    async def verify_alipay_callback(self, params: dict) -> dict | None:
        """验证支付宝回调签名（简化版）"""
        # 生产环境需要 RSA2 验签
        trade_status = params.get("trade_status")
        if trade_status == "TRADE_SUCCESS":
            return {
                "order_no": params.get("out_trade_no"),
                "trade_no": params.get("trade_no"),
            }
        return None


payment_service = PaymentService()
```

### 4. `app/routes/payment.py`（新建）

支付路由：

```python
"""支付路由 — 订单创建 + 回调"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.middleware.auth import get_current_user
from app.services.payment import payment_service

router = APIRouter(prefix="/payment", tags=["payment"])


class CreateOrderRequest(BaseModel):
    plan_id: str
    payment_method: str  # wechat / alipay


@router.get("/plans")
async def list_plans():
    """获取充值套餐列表"""
    return {"plans": payment_service.PRICING_PLANS}


@router.post("/create-order")
async def create_order(req: CreateOrderRequest, user=Depends(get_current_user)):
    """创建支付订单"""
    if req.payment_method not in ("wechat", "alipay"):
        raise HTTPException(400, "Invalid payment method")

    order = await payment_service.create_order(user["id"], req.plan_id, req.payment_method)

    if req.payment_method == "wechat":
        result = await payment_service.create_wechat_native_order(
            order["order_no"], order["amount_cents"], f"积分充值 {order['credits']} 积分"
        )
    else:
        result = await payment_service.create_alipay_order(
            order["order_no"], order["amount_cents"], f"积分充值 {order['credits']} 积分"
        )

    return result


@router.post("/callback/wechat")
async def wechat_callback(request: Request):
    """微信支付回调"""
    body = await request.body()
    headers = dict(request.headers)

    verified = await payment_service.verify_wechat_callback(headers, body)
    if not verified:
        raise HTTPException(400, "Verification failed")

    await payment_service.process_payment_success(verified["order_no"], verified["trade_no"])
    return {"code": "SUCCESS", "message": "OK"}


@router.post("/callback/alipay")
async def alipay_callback(request: Request):
    """支付宝回调"""
    form = await request.form()
    params = dict(form)

    verified = await payment_service.verify_alipay_callback(params)
    if not verified:
        return "fail"

    await payment_service.process_payment_success(verified["order_no"], verified["trade_no"])
    return "success"


@router.get("/orders")
async def list_orders(user=Depends(get_current_user)):
    """用户订单列表"""
    from sqlalchemy import text
    from app.db import get_db_session

    async with get_db_session() as session:
        result = await session.execute(
            text("""
                SELECT order_no, amount_cents, credits, payment_method, status, paid_at, created_at
                FROM orders
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 50
            """),
            {"user_id": user["id"]},
        )
        rows = result.mappings().fetchall()

    return {"orders": [dict(r) for r in rows]}
```

### 5. 修改 `app/main.py` — 注册支付路由

在路由注册部分添加：
```python
from app.routes.payment import router as payment_router
app.include_router(payment_router, prefix="/api")
```

### 6. `.env.example` — 添加支付配置

```env
# 微信支付
WECHAT_APP_ID=
WECHAT_MCH_ID=
WECHAT_API_KEY=
WECHAT_CERT_SERIAL=
WECHAT_PRIVATE_KEY_PATH=
WECHAT_NOTIFY_URL=https://your-domain.com/api/payment/callback/wechat

# 支付宝
ALIPAY_APP_ID=
ALIPAY_PRIVATE_KEY=
ALIPAY_PUBLIC_KEY=
ALIPAY_NOTIFY_URL=https://your-domain.com/api/payment/callback/alipay
ALIPAY_RETURN_URL=https://your-domain.com/payment/success
```

## 注意事项

- 支付未配置时（app_id 为空），创建订单接口返回明确错误
- 回调验签是简化版，生产环境需要完整的 RSA2/V3 签名验证
- 订单使用 FOR UPDATE 防止并发重复到账
- 积分到账记录 credit_transactions 便于审计

## 验收标准

1. `GET /api/payment/plans` 返回套餐列表
2. `POST /api/payment/create-order` 创建订单并返回支付参数
3. 回调端点能处理支付成功通知
4. 支付成功后积分自动到账
5. 订单表有完整的状态流转
6. `.env.example` 包含支付配置
