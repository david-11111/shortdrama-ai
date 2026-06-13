from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.volc_billing import import_billing_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Volcengine billing TSV rows into DB.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = asyncio.run(import_billing_file(args.path))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
