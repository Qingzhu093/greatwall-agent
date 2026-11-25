"""SQLite 连接生命周期、只读/单写者事务原语与依赖重审传播助手（从 db_schema.py 拆出）。"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

_INIT_DB_LOCK = threading.Lock()
_INITIALIZED_DB_SIGNATURES: dict[str, tuple[int, int]] = {}
# 进程级单写者大闸（可重入）：所有写库短事务严格全序串行（每笔 1-3ms），
# 纯只读查询与纯外部隔离计算（子进程）在锁外 100% 真并行。
_SINGLE_WRITER_LOCK = threading.RLock()


def _db_file_signature(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
        return (int(st.st_dev), int(st.st_ino))
    except OSError:
        return None


def reset_initialized_db_cache(db_path: str | Path | None = None) -> None:
    """清理进程级 Schema 初始化缓存（主要用于测试删除重建同名 DB 文件场景）。"""
    with _INIT_DB_LOCK:
        if db_path is None:
            _INITIALIZED_DB_SIGNATURES.clear()
        else:
            _INITIALIZED_DB_SIGNATURES.pop(os.path.realpath(str(db_path)), None)


def open_rw_connection_with_init(
    db_path: str | Path,
    *,
    init_fn: Callable[[sqlite3.Connection], None],
    init_schema: bool = True,
    force_init: bool = False,
) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    if init_schema:
        real_key = os.path.realpath(str(p))
        sig = _db_file_signature(p)
        need_init = force_init
        if not need_init:
            with _INIT_DB_LOCK:
                if sig is None or _INITIALIZED_DB_SIGNATURES.get(real_key) != sig:
                    need_init = True
        if need_init:
            with _INIT_DB_LOCK:
                sig2 = _db_file_signature(p)
                if force_init or sig2 is None or _INITIALIZED_DB_SIGNATURES.get(real_key) != sig2:
                    init_fn(conn)
                    new_sig = _db_file_signature(p)
                    if new_sig is not None:
                        _INITIALIZED_DB_SIGNATURES[real_key] = new_sig
    return conn


def open_ro_connection(db_path: str | Path) -> sqlite3.Connection:
    p = Path(db_path)
    uri = f"file:{p.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON;")
    conn.execute("PRAGMA busy_timeout=15000;")
    return conn


@contextmanager
def rw_immediate_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Single-Writer SQLite `BEGIN IMMEDIATE` 独占写事务上下文管理器（进程内 RLock 全序 + SQLite 写锁，支持嵌套透传）。"""
    with _SINGLE_WRITER_LOCK:
        if conn.in_transaction:
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise


@contextmanager
def ro_consistent_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """在单一只读事务内取得一致快照视图（严禁写操作）。"""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN DEFERRED")
    try:
        yield conn
    finally:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
