from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


DEFAULT_AMOUNT_COLUMNS = ("变动金额", "amount", "Amount")
DEFAULT_TYPE_COLUMNS = ("交易类型", "type", "Type")
DEFAULT_TIME_COLUMNS = ("交易时间", "time", "Time")
DEFAULT_ORDER_COLUMNS = ("业务交易单号", "order_no", "OrderNo")
DEFAULT_BALANCE_COLUMNS = ("现金余额", "balance", "Balance")


def money(value: str) -> Decimal:
    text = (value or "0").strip().replace(",", "")
    try:
        return Decimal(text or "0")
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc


def first_present(row: dict[str, str], candidates: Iterable[str], default: str = "") -> str:
    for key in candidates:
        if key in row:
            return row.get(key, default) or default
    return default


def analyze(
    path: Path,
    *,
    include_detail: bool = False,
    amount_column: str = "",
    type_column: str = "",
) -> dict:
    rows = 0
    consume_total = Decimal("0")
    recharge_total = Decimal("0")
    consume_count = 0
    recharge_count = 0
    by_type: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    detail: list[dict[str, str]] = []

    amount_columns = (amount_column,) if amount_column else DEFAULT_AMOUNT_COLUMNS
    type_columns = (type_column,) if type_column else DEFAULT_TYPE_COLUMNS

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            if not any((value or "").strip() for value in row.values()):
                continue
            rows += 1
            amount = money(first_present(row, amount_columns))
            tx_type = first_present(row, type_columns).strip()
            if amount < 0:
                consume_total += -amount
                consume_count += 1
            elif amount > 0:
                recharge_total += amount
                recharge_count += 1
            by_type[tx_type] += amount
            if include_detail:
                detail.append(
                    {
                        "time": first_present(row, DEFAULT_TIME_COLUMNS),
                        "type": tx_type,
                        "order_no": first_present(row, DEFAULT_ORDER_COLUMNS),
                        "amount": str(amount),
                        "balance": first_present(row, DEFAULT_BALANCE_COLUMNS),
                    }
                )

    result = {
        "file": str(path),
        "rows": rows,
        "consume_count": consume_count,
        "recharge_count": recharge_count,
        "consume_yuan": str(consume_total),
        "recharge_yuan": str(recharge_total),
        "net_yuan": str(recharge_total - consume_total),
        "by_type": {key: str(value) for key, value in sorted(by_type.items())},
    }
    if include_detail:
        result["detail"] = detail
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Volcengine account billing TSV export.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--detail", action="store_true", help="Print every billing row.")
    parser.add_argument("--amount-column", default="", help="Override the amount column name.")
    parser.add_argument("--type-column", default="", help="Override the transaction type column name.")
    args = parser.parse_args()

    result = analyze(
        args.path,
        include_detail=args.detail,
        amount_column=args.amount_column,
        type_column=args.type_column,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
