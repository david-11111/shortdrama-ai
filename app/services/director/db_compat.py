# -*- coding: utf-8 -*-
"""SQLite compatibility shim for director services in SaaS context.

Director services use synchronous SQLite for their own tables,
independent of the main PostgreSQL database.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Director data stored in a dedicated SQLite file alongside the SaaS app
_DB_PATH = Path(__file__).resolve().parents[3] / "director_data.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
