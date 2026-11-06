"""قاعدة البيانات: المخطط، الترحيلات، المعاملات، والتصدير النصي."""

from __future__ import annotations

import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import crypto
from . import permissions as P
from .util import now_iso, stamp

SCHEMA_VERSION = 5

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS health_units (
    unit_id    TEXT PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL DEFAULT 'مؤسسة',
    parent_id  TEXT REFERENCES health_units(unit_id) ON DELETE SET NULL,
    is_center  INTEGER NOT NULL DEFAULT 0,
    active     INTEGER NOT NULL DEFAULT 1,
    manager    TEXT NOT NULL DEFAULT '',
    phone      TEXT NOT NULL DEFAULT '',
    address    TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_units_active ON health_units(active, deleted_at);

CREATE TABLE IF NOT EXISTS roles (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    is_system   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS permissions (
    code     TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_code       TEXT NOT NULL REFERENCES roles(code) ON DELETE CASCADE,
    permission_code TEXT NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (role_code, permission_code)
);

CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    username        TEXT NOT NULL,
    display_name    TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL REFERENCES roles(code),
    unit_id         TEXT REFERENCES health_units(unit_id) ON DELETE SET NULL,
    password_hash   TEXT NOT NULL,
    salt            TEXT NOT NULL,
    iterations      INTEGER NOT NULL DEFAULT 260000,
    must_change     INTEGER NOT NULL DEFAULT 0,
    active          INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    last_login      TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(lower(username));
CREATE INDEX IF NOT EXISTS idx_users_unit ON users(unit_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen  TEXT,
    ip         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id  TEXT PRIMARY KEY,
    ts        TEXT NOT NULL,
    user_id   TEXT,
    username  TEXT NOT NULL DEFAULT '',
    action    TEXT NOT NULL,
    entity    TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    details   TEXT NOT NULL DEFAULT '',
    ip        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity, entity_id);

CREATE TABLE IF NOT EXISTS backup_jobs (
    backup_id TEXT PRIMARY KEY,
    ts        TEXT NOT NULL,
    path      TEXT NOT NULL,
    size      INTEGER NOT NULL DEFAULT 0,
    sha256    TEXT NOT NULL DEFAULT '',
    ok        INTEGER NOT NULL DEFAULT 1,
    note      TEXT NOT NULL DEFAULT '',
    kind      TEXT NOT NULL DEFAULT 'manual'
);
CREATE INDEX IF NOT EXISTS idx_backup_ts ON backup_jobs(ts);
"""


SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS job_titles (
    title_id   TEXT PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL UNIQUE,
    grade      TEXT NOT NULL DEFAULT '',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id      TEXT PRIMARY KEY,
    emp_no           TEXT NOT NULL,
    full_name        TEXT NOT NULL,
    unit_id          TEXT REFERENCES health_units(unit_id),
    job_title_id     TEXT REFERENCES job_titles(title_id),
    grade            TEXT NOT NULL DEFAULT '',
    stage            TEXT NOT NULL DEFAULT '',
    category         TEXT NOT NULL DEFAULT '',
    hire_date        TEXT NOT NULL,
    end_date         TEXT,
    gender           TEXT NOT NULL DEFAULT '',
    status           TEXT NOT NULL DEFAULT 'active',
    notes            TEXT NOT NULL DEFAULT '',
    assigned_user_id TEXT REFERENCES users(user_id) ON DELETE SET NULL,
    version          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_no
    ON employees(lower(emp_no), unit_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_employees_unit ON employees(unit_id);
CREATE INDEX IF NOT EXISTS idx_employees_assigned ON employees(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_employees_name ON employees(full_name);

CREATE TABLE IF NOT EXISTS employee_history (
    history_id     TEXT PRIMARY KEY,
    employee_id    TEXT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    old_value      TEXT NOT NULL DEFAULT '',
    new_value      TEXT NOT NULL DEFAULT '',
    order_no       TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_employee ON employee_history(employee_id, effective_date);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL,
    filename    TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    mime        TEXT NOT NULL DEFAULT '',
    size        INTEGER NOT NULL DEFAULT 0,
    uploaded_by TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_sha ON documents(sha256);

CREATE TABLE IF NOT EXISTS document_links (
    link_id     TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    purpose     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_links_entity ON document_links(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS appreciation_letters (
    letter_id      TEXT PRIMARY KEY,
    unit_id        TEXT REFERENCES health_units(unit_id),
    issuer         TEXT NOT NULL,
    issuer_type    TEXT NOT NULL DEFAULT 'other',
    letter_no      TEXT NOT NULL,
    letter_date    TEXT NOT NULL,
    received_date  TEXT,
    subject        TEXT NOT NULL DEFAULT '',
    target_mode    TEXT NOT NULL,
    target_params  TEXT NOT NULL DEFAULT '{}',
    reference_date TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    notes          TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_letters_unit ON appreciation_letters(unit_id, letter_date);
CREATE INDEX IF NOT EXISTS idx_letters_status ON appreciation_letters(status);

CREATE TABLE IF NOT EXISTS appreciation_letter_recipients (
    letter_id     TEXT NOT NULL REFERENCES appreciation_letters(letter_id) ON DELETE CASCADE,
    employee_id   TEXT NOT NULL REFERENCES employees(employee_id),
    eligible      INTEGER NOT NULL DEFAULT 1,
    effect_days   REAL NOT NULL DEFAULT 0,
    effect_state  TEXT NOT NULL DEFAULT 'pending',
    note          TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (letter_id, employee_id)
);
CREATE INDEX IF NOT EXISTS idx_recipients_employee ON appreciation_letter_recipients(employee_id);

CREATE TABLE IF NOT EXISTS hr_orders (
    order_id       TEXT PRIMARY KEY,
    unit_id        TEXT REFERENCES health_units(unit_id),
    order_type     TEXT NOT NULL,
    order_no       TEXT NOT NULL,
    order_date     TEXT NOT NULL,
    issuer         TEXT NOT NULL DEFAULT '',
    effective_date TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    notes          TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    deleted_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_unit ON hr_orders(unit_id, order_date);

CREATE TABLE IF NOT EXISTS hr_order_recipients (
    order_id    TEXT NOT NULL REFERENCES hr_orders(order_id) ON DELETE CASCADE,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id),
    note        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (order_id, employee_id)
);

CREATE TABLE IF NOT EXISTS rule_packages (
    package_id     TEXT PRIMARY KEY,
    code           TEXT NOT NULL,
    version        INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'draft',
    effective_from TEXT NOT NULL,
    effective_to   TEXT,
    note           TEXT NOT NULL DEFAULT '',
    legal_source   TEXT NOT NULL DEFAULT '',
    created_by     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    published_at   TEXT,
    published_by   TEXT NOT NULL DEFAULT '',
    UNIQUE (code, version)
);
CREATE INDEX IF NOT EXISTS idx_packages_status ON rule_packages(status, effective_from);

CREATE TABLE IF NOT EXISTS rule_rows (
    rule_id    TEXT PRIMARY KEY,
    package_id TEXT NOT NULL REFERENCES rule_packages(package_id) ON DELETE CASCADE,
    rule_type  TEXT NOT NULL,
    name       TEXT NOT NULL DEFAULT '',
    scope      TEXT NOT NULL DEFAULT '{}',
    params     TEXT NOT NULL DEFAULT '{}',
    priority   INTEGER NOT NULL DEFAULT 100,
    active     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_rows_package ON rule_rows(package_id, rule_type);

CREATE TABLE IF NOT EXISTS calc_runs (
    run_id       TEXT PRIMARY KEY,
    employee_id  TEXT NOT NULL REFERENCES employees(employee_id),
    as_of        TEXT NOT NULL,
    package_id   TEXT,
    result       TEXT NOT NULL,
    created_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calc_employee ON calc_runs(employee_id, as_of);
"""


SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS sync_packages (
    package_id       TEXT PRIMARY KEY,
    direction        TEXT NOT NULL,
    source_unit_id   TEXT,
    source_unit_name TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    imported_at      TEXT,
    status           TEXT NOT NULL DEFAULT 'exported',
    manifest         TEXT NOT NULL DEFAULT '{}',
    note             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sync_created ON sync_packages(created_at);
"""


SCHEMA_V4 = """
ALTER TABLE hr_orders ADD COLUMN apply_mode TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE hr_orders ADD COLUMN to_grade TEXT NOT NULL DEFAULT '';
ALTER TABLE hr_orders ADD COLUMN to_stage TEXT NOT NULL DEFAULT '';
ALTER TABLE hr_orders ADD COLUMN applied_at TEXT;
"""


SCHEMA_V5 = """
ALTER TABLE employees ADD COLUMN last_grade_date TEXT;
ALTER TABLE employees ADD COLUMN last_stage_date TEXT;
UPDATE employees SET last_grade_date = COALESCE(
    (SELECT MAX(h.effective_date) FROM employee_history h
     WHERE h.employee_id = employees.employee_id
       AND h.event_type IN ('promotion','grade')), hire_date)
WHERE last_grade_date IS NULL;
UPDATE employees SET last_stage_date = COALESCE(
    (SELECT MAX(h.effective_date) FROM employee_history h
     WHERE h.employee_id = employees.employee_id
       AND h.event_type IN ('promotion','increment','stage')), hire_date)
WHERE last_stage_date IS NULL;
UPDATE appreciation_letters SET issuer_type='minister' WHERE issuer_type='ministry';
UPDATE appreciation_letters SET issuer_type='director_general' WHERE issuer_type='directorate';
UPDATE appreciation_letters SET issuer_type='authority_head' WHERE issuer_type='unit';
UPDATE appreciation_letters SET issuer_type='other' WHERE issuer_type='committee';
"""


class Database:
    """اتصال SQLite آمن للخيوط: اتصال لكل خيط + قفل كتابة واحد."""

    def __init__(self, path: Path | str, key: str = "") -> None:
        self.path = Path(path)
        self.key = key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._closed = False
        self.conn  # noqa: B018 - فتح الاتصال وتهيئة المخطط
        self.migrate()

    # ------------------------------------------------------------------
    # الاتصال
    # ------------------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        connection = getattr(self._local, "conn", None)
        if connection is None:
            if self.key:
                connection = crypto.connect(self.path, self.key)
            else:
                connection = sqlite3.connect(
                    str(self.path), timeout=30, isolation_level=None,
                    check_same_thread=False,
                )
                connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=10000")
            self._local.conn = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "conn", None)
        if connection is not None:
            connection.close()
            self._local.conn = None
        self._closed = True

    @contextmanager
    def write(self):
        """معاملة كتابة واحدة مُسلسَلة (آمنة للتعدد)."""
        connection = self.conn
        with self._write_lock:
            if connection.in_transaction:
                yield connection
                return
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------
    # استعلامات
    # ------------------------------------------------------------------
    def query(self, sql: str, args: tuple | list = ()) -> list[dict]:
        return [dict(row) for row in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple | list = ()) -> dict | None:
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, args: tuple | list = (), default=None):
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row and row[0] is not None else default

    def table_exists(self, name: str) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

    # ------------------------------------------------------------------
    # الميتا
    # ------------------------------------------------------------------
    def get_meta(self, key: str, default: str = "") -> str:
        if not self.table_exists("app_meta"):
            return default
        value = self.scalar("SELECT value FROM app_meta WHERE key=?", (key,))
        return value if value is not None else default

    def set_meta(self, key: str, value: str, conn: sqlite3.Connection | None = None) -> None:
        target = conn or self.conn
        target.execute("INSERT OR REPLACE INTO app_meta(key, value) VALUES (?,?)", (key, str(value)))

    # ------------------------------------------------------------------
    # الترحيل والتهيئة
    # ------------------------------------------------------------------
    def migrate(self) -> None:
        with self._write_lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, note TEXT)")
            applied = {row["version"] for row in
                       self.conn.execute("SELECT version FROM schema_migrations")}
            if 1 not in applied:
                self.conn.executescript(SCHEMA_V1)
                self._seed()
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, note) VALUES (1, ?, ?)",
                    (now_iso(), "المخطط الأساسي: المؤسسات، المستخدمون، الجلسات، التدقيق"))
            if 2 not in applied:
                self._backup_before(2)
                self.conn.executescript(SCHEMA_V2)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, note) VALUES (2, ?, ?)",
                    (now_iso(), "الموظفون والتاريخ الوظيفي والوثائق وكتب الشكر والأوامر والقواعد"))
            if 3 not in applied:
                self._backup_before(3)
                self.conn.executescript(SCHEMA_V3)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, note) VALUES (3, ?, ?)",
                    (now_iso(), "سجل حزم المزامنة (USB)"))
            if 4 not in applied:
                self._backup_before(4)
                self.conn.executescript(SCHEMA_V4)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, note) VALUES (4, ?, ?)",
                    (now_iso(), "تطبيق الدرجة/المرحلة عند اعتماد الأمر"))
            if 5 not in applied:
                self._backup_before(5)
                self.conn.executescript(SCHEMA_V5)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at, note) VALUES (5, ?, ?)",
                    (now_iso(), "تاريخا الدرجة والمرحلة الحالية"))
            self._seed()
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    def _backup_before(self, version: int) -> None:
        """نسخة احتياطية تلقائية قبل ترحيل المخطط."""
        try:
            folder = self.path.parent / "backups"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"pre_migration_v{version}_{stamp()}.db"
            if self.key:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                shutil.copy2(self.path, target)
                return
            destination = sqlite3.connect(str(target))
            try:
                self.conn.backup(destination)
            finally:
                destination.close()
        except (OSError, sqlite3.DatabaseError):
            pass

    def _seed(self) -> None:
        for code, name, description in P.ROLES:
            self.conn.execute(
                "INSERT OR IGNORE INTO roles(code, name, description, is_system) VALUES (?,?,?,1)",
                (code, name, description))
        for code, name, category in P.PERMISSIONS:
            self.conn.execute(
                "INSERT OR IGNORE INTO permissions(code, name, category) VALUES (?,?,?)",
                (code, name, category))
        self._sync_roles()

    def _sync_roles(self) -> None:
        """يزامن صلاحيات الأدوار النظامية مع التعريف في الشيفرة."""
        for role, perms in P.ROLE_PERMISSIONS.items():
            for permission in perms:
                self.conn.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_code, permission_code) "
                    "VALUES (?,?)", (role, permission))

    def role_permissions(self, role: str) -> set[str]:
        rows = self.query(
            "SELECT permission_code FROM role_permissions WHERE role_code=?", (role,))
        perms = {row["permission_code"] for row in rows}
        return perms or P.permissions_for(role)

    # ------------------------------------------------------------------
    # التصدير والفحص
    # ------------------------------------------------------------------
    def export_plaintext(self, dest: Path | str) -> Path:
        """نسخة نصية مكتملة (بلا WAL) صالحة للنقل أو التجهيز."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if self.key:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return crypto.export_plaintext(self.path, self.key, dest)
        if dest.exists():
            dest.unlink()
        source = self.conn
        source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            target.execute("VACUUM")
        finally:
            target.close()
        return dest

    def integrity_check(self) -> str:
        return str(self.scalar("PRAGMA integrity_check", default="unknown"))

    def count(self, table: str, where: str = "", args: tuple = ()) -> int:
        if not self.table_exists(table):
            return 0
        clause = f" WHERE {where}" if where else ""
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}{clause}", args, 0) or 0)
