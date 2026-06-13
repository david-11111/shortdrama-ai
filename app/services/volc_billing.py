from __future__ import annotations

import csv
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.db import AsyncSessionLocal


FIELD_ALIASES = {
    "transaction_no": ("流水编号", "娴佹按缂栧彿"),
    "account_id": ("账号ID", "璐﹀彿ID"),
    "account_name": ("账户名", "璐︽埛鍚?"),
    "customer_name": ("客户名称", "瀹㈡埛鍚嶇О"),
    "vendor_name": ("我方主体名称", "鎴戞柟涓讳綋鍚嶇О"),
    "trade_time": ("交易时间", "浜ゆ槗鏃堕棿"),
    "trade_type": ("交易类型", "浜ゆ槗绫诲瀷"),
    "channel": ("交易渠道", "浜ゆ槗娓犻亾"),
    "channel_transaction_no": ("渠道流水号", "娓犻亾娴佹按鍙?"),
    "business_order_no": ("业务交易单号", "涓氬姟浜ゆ槗鍗曞彿"),
    "amount_yuan": ("变动金额", "鍙樺姩閲戦"),
    "cash_balance_yuan": ("现金余额", "鐜伴噾浣欓"),
    "frozen_amount_yuan": ("冻结金额", "鍐荤粨閲戦"),
    "remark": ("备注", "澶囨敞"),
}


def _get(row: dict[str, str], field: str) -> str:
    for key in FIELD_ALIASES[field]:
        if key in row:
            return (row.get(key) or "").strip()
    return ""


def _money(value: str) -> Decimal:
    text_value = (value or "0").strip()
    return Decimal(text_value or "0")


def _time(value: str) -> datetime | None:
    text_value = (value or "").strip()
    if not text_value:
        return None
    return datetime.strptime(text_value, "%Y-%m-%d %H:%M:%S")


def parse_billing_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for raw in reader:
            if not any((value or "").strip() for value in raw.values()):
                continue
            transaction_no = _get(raw, "transaction_no")
            if not transaction_no:
                continue
            rows.append({
                "transaction_no": transaction_no,
                "account_id": _get(raw, "account_id"),
                "account_name": _get(raw, "account_name"),
                "customer_name": _get(raw, "customer_name"),
                "vendor_name": _get(raw, "vendor_name"),
                "trade_time": _time(_get(raw, "trade_time")),
                "trade_type": _get(raw, "trade_type"),
                "channel": _get(raw, "channel"),
                "channel_transaction_no": _get(raw, "channel_transaction_no"),
                "business_order_no": _get(raw, "business_order_no"),
                "amount_yuan": _money(_get(raw, "amount_yuan")),
                "cash_balance_yuan": _money(_get(raw, "cash_balance_yuan")),
                "frozen_amount_yuan": _money(_get(raw, "frozen_amount_yuan")),
                "remark": _get(raw, "remark"),
                "raw_row": raw,
            })
    return rows


async def import_billing_file(path: Path) -> dict[str, Any]:
    rows = parse_billing_file(path)
    inserted = 0
    updated = 0
    consume_yuan = Decimal("0")
    recharge_yuan = Decimal("0")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            for row in rows:
                amount = row["amount_yuan"]
                if amount < 0:
                    consume_yuan += -amount
                elif amount > 0:
                    recharge_yuan += amount

                result = await session.execute(
                    text(
                        """
                        INSERT INTO volc_billing_rows (
                            transaction_no, account_id, account_name, customer_name, vendor_name,
                            trade_time, trade_type, channel, channel_transaction_no, business_order_no,
                            amount_yuan, cash_balance_yuan, frozen_amount_yuan, remark, raw_row
                        )
                        VALUES (
                            :transaction_no, :account_id, :account_name, :customer_name, :vendor_name,
                            :trade_time, :trade_type, :channel, :channel_transaction_no, :business_order_no,
                            :amount_yuan, :cash_balance_yuan, :frozen_amount_yuan, :remark,
                            CAST(:raw_row AS JSONB)
                        )
                        ON CONFLICT (transaction_no) DO UPDATE
                        SET account_id = EXCLUDED.account_id,
                            account_name = EXCLUDED.account_name,
                            customer_name = EXCLUDED.customer_name,
                            vendor_name = EXCLUDED.vendor_name,
                            trade_time = EXCLUDED.trade_time,
                            trade_type = EXCLUDED.trade_type,
                            channel = EXCLUDED.channel,
                            channel_transaction_no = EXCLUDED.channel_transaction_no,
                            business_order_no = EXCLUDED.business_order_no,
                            amount_yuan = EXCLUDED.amount_yuan,
                            cash_balance_yuan = EXCLUDED.cash_balance_yuan,
                            frozen_amount_yuan = EXCLUDED.frozen_amount_yuan,
                            remark = EXCLUDED.remark,
                            raw_row = EXCLUDED.raw_row,
                            updated_at = NOW()
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        **row,
                        "raw_row": json.dumps(row["raw_row"], ensure_ascii=False),
                    },
                )
                if result.scalar():
                    inserted += 1
                else:
                    updated += 1

    return {
        "rows": len(rows),
        "inserted": inserted,
        "updated": updated,
        "consume_yuan": str(consume_yuan),
        "recharge_yuan": str(recharge_yuan),
        "net_yuan": str(recharge_yuan - consume_yuan),
    }
