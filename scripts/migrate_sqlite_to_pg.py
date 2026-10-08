"""Copy the Exomiser SQLite database into an EMPTY PostgreSQL database and verify it.

    TARGET_DATABASE_URL=postgresql+psycopg://user:pw@host:5432/db \
        python scripts/migrate_sqlite_to_pg.py --sqlite /path/app.db

Stop the app first. SQLite is opened read-only and read in ONE snapshot. Schema, copy, triggers,
sequences and verification run in ONE PostgreSQL transaction, committed only if every check
passes. The checksums hash the RAW SQLite values and what PostgreSQL returns through one shared
normaliser, so they verify both the copy and the type conversion. Prints counts and checksums
only, never row contents or driver messages (they can contain patient data).
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import MetaData, Table, Text, cast, create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import JSON, Boolean, DateTime, Enum, Float, Integer

ROOT = Path(__file__).resolve().parent.parent  # repo checkout, or /opt in the container
sys.path.insert(0, str(ROOT / "app"))
from models import Analysis, Individual, User, db

TABLES = [
    "users",
    "individuals",
    "analyses",
    "users_history",
    "individuals_history",
    "analyses_history",
]
BATCH = 500
DT_RE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.(\d{1,6}))?$")
stage = {"at": "start"}  # where we are, for error messages (table names only)


class MigrationError(Exception):
    pass


class Refused(Exception):
    pass


def pk_of(table):
    return "history_id" if table.endswith("_history") else "id"


def convert(table, row_id, col, value):
    """SQLite raw value -> Python value for the PostgreSQL column. Never coerces silently."""
    where = f"{table} id={row_id} column={col.name}"
    if value is None:
        if not col.nullable:
            raise MigrationError(f"NULL in NOT NULL column: {where}")
        return None  # SQL NULL (JSON columns use none_as_null, so this stays SQL NULL)
    t = col.type
    try:
        if isinstance(value, str) and "\x00" in value:
            raise ValueError
        if isinstance(t, Boolean):
            if type(value) is not int or value not in (0, 1):
                raise ValueError
            return bool(value)
        if isinstance(t, DateTime):
            m = DT_RE.match(value) if isinstance(value, str) else None
            if not m:
                raise ValueError
            y, mo, d, h, mi, s, frac = m.groups()
            return datetime(*map(int, (y, mo, d, h, mi, s)), int((frac or "0").ljust(6, "0")))  # noqa: DTZ001 naive UTC
        if isinstance(t, JSON):
            if not isinstance(value, str):
                raise TypeError
            parsed = json.loads(value)
            return JSON.NULL if parsed is None else parsed  # JSON null stays JSON null
        if isinstance(t, Enum):
            if value not in t.enums:
                raise ValueError
            return value
        if isinstance(t, Integer):
            if type(value) is not int:
                raise ValueError
            return value
        if isinstance(t, Float):
            if type(value) not in (int, float):
                raise ValueError
            return float(value)
        if not isinstance(value, str):
            raise TypeError
        return value
    except (ValueError, TypeError):  # includes json.JSONDecodeError
        raise MigrationError(f"value cannot be converted: {where}") from None


def norm(col, v):
    """The one normaliser both checksum sides share. SQL NULL -> None, JSON null -> 'null'."""
    if v is None:
        return None
    t = col.type
    if isinstance(t, Boolean):
        return bool(v)
    if isinstance(t, DateTime):
        if isinstance(v, datetime):
            return v.isoformat(timespec="microseconds")
        y, mo, d, h, mi, s, frac = DT_RE.match(v).groups()
        return f"{y}-{mo}-{d}T{h}:{mi}:{s}.{(frac or '0').ljust(6, '0')}"
    if isinstance(t, JSON):  # both sides pass JSON as text
        return json.dumps(json.loads(v), sort_keys=True, separators=(",", ":"))
    if isinstance(t, Float):
        return repr(float(v))
    return v


def add_row(total, cols, values):
    """Order-independent checksum: sum of per-row SHA-256 values."""
    payload = json.dumps([norm(c, v) for c, v in zip(cols, values)]).encode()
    return (total + int.from_bytes(hashlib.sha256(payload).digest(), "big")) % (1 << 256)


def run_section(conn, sql_text, marker):
    section = sql_text.split("-- ==== SECTION ")[marker]
    conn.exec_driver_sql(section.split("\n", 1)[1])


def check_columns(src, pg_table):
    """Fail loudly if SQLite and the target disagree on columns (no silent column loss)."""
    have = {r[1] for r in src.execute(f'PRAGMA table_info("{pg_table.name}")')}
    want = {c.name for c in pg_table.columns}
    if have != want:
        raise MigrationError(
            f"column mismatch in {pg_table.name}: only in SQLite {sorted(have - want)}, "
            f"only in target {sorted(want - have)}"
        )


def copy_table(conn, src, pg_table):
    """Insert every row; returns (row count, checksum of the raw source values)."""
    name, pk = pg_table.name, pk_of(pg_table.name)
    cols = list(pg_table.columns)
    names = [c.name for c in cols]
    quoted = ", ".join(f'"{n}"' for n in names)
    cur = src.execute(f'SELECT {quoted} FROM "{name}" ORDER BY "{pk}"')  # names from PG catalog
    pk_idx = names.index(pk)
    count, total = 0, 0
    while True:
        raw = cur.fetchmany(BATCH)
        if not raw:
            break
        batch = []
        if name == "users_history":
            # history no longer keeps password hashes: copy NULL, and checksum NULL on both sides
            hi = names.index("password_hash")
            raw = [tuple(None if i == hi else v for i, v in enumerate(r)) for r in raw]
        for r in raw:
            batch.append({c.name: convert(name, r[pk_idx], c, v) for c, v in zip(cols, r)})
            total = add_row(total, cols, r)
        try:
            with conn.begin_nested():
                conn.execute(pg_table.insert(), batch)
        except DBAPIError:
            for rec in batch:  # find the offending row; report names only, never values
                try:
                    with conn.begin_nested():
                        conn.execute(pg_table.insert(), rec)
                except DBAPIError as e:
                    raise MigrationError(
                        f"database rejected row: {name} id={rec[pk]} {describe(e)}"
                    ) from None
            raise MigrationError(f"database rejected a batch in {name}") from None
        count += len(batch)
    return count, total


def describe(e):
    """Exception class plus constraint/column name only; never the message."""
    d = getattr(getattr(e, "orig", None), "diag", None)
    parts = [type(getattr(e, "orig", e)).__name__]
    for attr in ("constraint_name", "column_name"):
        if getattr(d, attr, None):
            parts.append(f"{attr}={getattr(d, attr)}")
    return " ".join(parts)


def pg_digest(conn, pg_table):
    """Stream the table back from PostgreSQL; returns (row count, checksum)."""
    cols = list(pg_table.columns)
    sel = select(*[cast(c, Text) if isinstance(c.type, JSON) else c for c in cols])
    count, total = 0, 0
    for row in conn.execute(sel.execution_options(yield_per=BATCH)):
        total = add_row(total, cols, row)
        count += 1
    return count, total


def reset_sequences(conn):
    for t in TABLES:
        pk = pk_of(t)
        conn.execute(
            text(
                "SELECT setval(pg_get_serial_sequence(:t, :c), "
                f"COALESCE((SELECT MAX({pk}) FROM {t}), 1), "
                f"(SELECT COUNT(*) > 0 FROM {t}))"
            ),
            {"t": t, "c": pk},
        )


def target_leftovers(conn):
    """Anything in public that would collide with, or be mixed into, a fresh migration."""
    ns = "(SELECT oid FROM pg_namespace WHERE nspname = 'public')"
    rels = conn.execute(
        text(
            "SELECT relkind, count(*) FROM pg_class WHERE relnamespace = " + ns + " AND relkind "
            "IN ('r','p','v','m','S','f') GROUP BY relkind"
        )
    ).all()
    types = conn.scalar(
        text(
            "SELECT count(*) FROM pg_type WHERE typnamespace = " + ns + " AND (typtype IN "
            "('e','d','r','m') OR (typtype = 'c' AND typrelid = 0))"
        )
    )
    names = {"r": "table", "p": "table", "v": "view", "m": "view", "S": "sequence", "f": "table"}
    found = [f"{n} {names[k]}(s)" for k, n in rels] + ([f"{types} type(s)"] if types else [])
    conn.rollback()
    return found


def migrate(conn, src, history_sql):
    ok = True
    stage["at"] = "checking target"
    found = target_leftovers(conn)
    if found:
        raise Refused("Refusing to run: target public schema is not empty: " + ", ".join(found))
    stage["at"] = "creating schema"
    db.metadata.create_all(conn)
    run_section(conn, history_sql, 1)
    meta = MetaData()
    pg = {t: Table(t, meta, autoload_with=conn) for t in TABLES}
    for t in pg.values():
        for c in t.columns:
            if isinstance(c.type, JSON):
                c.type = JSON(none_as_null=True)  # Python None -> SQL NULL, JSON.NULL -> JSON null
    src.execute("BEGIN")  # one read snapshot for every table
    src.execute("SELECT count(*) FROM sqlite_master").fetchall()  # starts the read transaction
    for t in TABLES:
        stage["at"] = f"column check {t}"
        check_columns(src, pg[t])

    src_sums = {}
    for t in TABLES:
        stage["at"] = f"copy {t}"
        src_sums[t] = copy_table(conn, src, pg[t])
    # Triggers are created AFTER the copy: copying first means the copy does not generate
    # duplicate history rows (the role is not a superuser, so it cannot disable triggers).
    stage["at"] = "creating triggers"
    run_section(conn, history_sql, 2)
    # Reset sequences/identities to max(id). Done before the smoke test (which inserts a
    # history row) and again after it, because sequence values are not rolled back.
    stage["at"] = "trigger smoke test"
    reset_sequences(conn)
    hist, ana = pg["analyses_history"], pg["analyses"]
    n_hist = conn.scalar(select(func.count()).select_from(hist))
    smoke = "SKIPPED (no analyses)"
    first = conn.scalar(select(func.min(ana.c.id)))
    if first is not None:
        sp = conn.begin_nested()
        conn.execute(ana.update().where(ana.c.id == first).values(description=ana.c.description))
        added = conn.scalar(select(func.count()).select_from(hist)) - n_hist
        sp.rollback()
        smoke = "ok" if added == 1 else f"FAILED ({added} rows added)"
        ok &= added == 1
    reset_sequences(conn)

    print(f"{'table':22} {'rows sqlite':>11} {'rows pg':>8}  checksum")
    for t in TABLES:
        stage["at"] = f"verify {t}"
        n, digest = pg_digest(conn, pg[t])
        good = src_sums[t] == (n, digest)
        ok &= good
        print(f"{t:22} {src_sums[t][0]:>11} {n:>8}  {'ok' if good else 'MISMATCH'}")
    stage["at"] = "ORM read-back"
    counts = []
    with Session(conn) as s:  # (c) every row through the models
        for m in (User, Individual, Analysis):
            n = 0
            for obj in s.scalars(select(m).execution_options(yield_per=100)):
                if m is Analysis:
                    _ = (obj.status, obj.genome_assembly, obj.hpo_terms)
                n += 1
            counts.append(n)
    orm_ok = counts == [src_sums[t][0] for t in TABLES[:3]]
    ok &= orm_ok
    print(f"ORM read-back users/individuals/analyses {counts}: {'ok' if orm_ok else 'MISMATCH'}")
    stage["at"] = "sequence check"
    seq_ok = True
    for t in TABLES:  # (d) next value must exceed max(id); state read, nextval not consumed
        seq = conn.scalar(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": t, "c": pk_of(t)})
        last, called = conn.execute(text(f"SELECT last_value, is_called FROM {seq}")).one()
        mx = conn.scalar(text(f"SELECT COALESCE(MAX({pk_of(t)}), 0) FROM {t}"))
        seq_ok &= (last + 1 if called else last) > mx
    ok &= seq_ok
    print(f"sequences next value > max(id): {'ok' if seq_ok else 'MISMATCH'}")
    print(f"history trigger smoke test: {smoke}")
    if ok:
        conn.commit()
    return ok


def quietly(fn):
    try:
        fn()
    except Exception:  # noqa: BLE001, S110 cleanup must never raise or print
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", required=True, help="path to the SQLite app.db (opened read-only)")
    args = ap.parse_args()
    url = os.environ.get("TARGET_DATABASE_URL")
    if not url:
        print("TARGET_DATABASE_URL is not set")
        return 2
    sqlite_path = Path(args.sqlite).resolve()
    if not sqlite_path.is_file():
        print(f"SQLite file not found: {sqlite_path}")
        return 2

    ok, code, conn, src = False, 1, None, None
    try:
        print(f"source: {sqlite_path} (read-only)")
        print(f"target: {make_url(url).render_as_string(hide_password=True)}")
        history_sql = (ROOT / "scripts" / "pg" / "history.sql").read_text()
        src = sqlite3.connect(f"{sqlite_path.as_uri()}?mode=ro", uri=True, isolation_level=None)
        conn = create_engine(url).connect()
        ok = migrate(conn, src, history_sql)
    except Refused as e:
        print(e)
        code = 2
    except MigrationError as e:
        print(f"ERROR: {e}")
    except KeyboardInterrupt:
        print("ERROR: interrupted")
    except Exception as e:  # noqa: BLE001 never print e: messages can contain row values
        print(f"ERROR: unexpected {describe(e)} during: {stage['at']}")
    finally:
        if conn is not None:
            quietly(conn.rollback)
            quietly(conn.close)
        if src is not None:
            quietly(src.close)
    if code == 2:
        return 2
    print("MIGRATION OK" if ok else "MIGRATION FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
