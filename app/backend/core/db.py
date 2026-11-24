"""Mapper for the unchanged supplied 58-table business DDL; auth extension is separate."""
import json, uuid
from decimal import Decimal
from datetime import date, datetime
from django.db import connection
from django.conf import settings
SCHEMA = json.loads((settings.CONTRACTS_DIR / 'design.json').read_text())['schema']
TABLES = {t['name']: t for t in SCHEMA}

def rows(sql, args=()):
    with connection.cursor() as c:
        c.execute(sql, args)
        if not c.description: return []
        names = [d[0] for d in c.description]
        return [dict(zip(names, row)) for row in c.fetchall()]

def one(sql, args=()):
    found = rows(sql, args)
    return found[0] if found else None

def execute(sql, args=()):
    with connection.cursor() as c:
        c.execute(sql, args)
        return c.rowcount

def insert(table, values):
    assert table in TABLES
    columns = {c['name'] for c in TABLES[table]['columns'] if not c.get('generated')}
    assert values and set(values) <= columns, (table, set(values) - columns)
    keys = list(values)
    return one('INSERT INTO "' + table + '" (' + ','.join('"'+k+'"' for k in keys) + ') VALUES (' +
               ','.join(['%s']*len(keys)) + ') RETURNING *', [values[k] for k in keys])

def update(table, pk, values):
    assert table in TABLES and 'id' in {c['name'] for c in TABLES[table]['columns']}
    assert set(values) <= {c['name'] for c in TABLES[table]['columns'] if not c.get('generated')}
    return one('UPDATE "'+table+'" SET '+','.join('"'+k+'"=%s' for k in values)+' WHERE id=%s RETURNING *', [*values.values(), pk])

def get(table, pk, lock=False):
    assert table in TABLES
    return one('SELECT * FROM "'+table+'" WHERE id=%s'+(' FOR UPDATE' if lock else ''), [pk])

def business_no(prefix): return prefix + datetime.now().strftime('%Y%m%d') + uuid.uuid4().hex[:12].upper()

def serial(value):
    if isinstance(value, Decimal): return format(value, 'f')
    # ISO 8601 with an explicit timezone is also parsed consistently by iOS JS.
    if isinstance(value, (date, datetime)): return value.isoformat()
    if isinstance(value, uuid.UUID): return str(value)
    raise TypeError(type(value).__name__)
