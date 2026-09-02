from __future__ import annotations
from datetime import datetime, timezone
from .db import connect, init_db

def record(service,status,detail=''):
    now=datetime.now(timezone.utc).replace(microsecond=0).isoformat(); init_db()
    with connect() as c: c.execute('INSERT OR REPLACE INTO service_health VALUES (?,?,?,?)',(service,now,status,detail[:2000]))

def summary():
    init_db()
    with connect() as c: return list(c.execute('SELECT service,checked_at,status,detail FROM service_health ORDER BY service'))
