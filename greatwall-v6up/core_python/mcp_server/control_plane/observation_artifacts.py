"""短事务内绑定观测编号与已暂存的评测产物。"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from ..db_runtime import _SINGLE_WRITER_LOCK, rw_immediate_tx
from .blind_sandbox import _rmtree_force


@contextmanager
def publish_observation_in_tx(
    conn: sqlite3.Connection, staging_root: Path,
) -> Iterator[Callable[[str], tuple[str, str | None]]]:
    destination = None
    orphan = staging_root.with_name(f"{staging_root.name}.orphan")

    def publish(obs_id: str) -> tuple[str, str | None]:
        nonlocal destination
        final_root = staging_root.parents[1] / obs_id
        code = str(final_root / "code_snapshot") if (staging_root / "code_snapshot").is_dir() else ""
        stage_a = str(final_root / "stage_a_output.json") if (staging_root / "stage_a_output.json").is_file() else None
        if staging_root.is_dir():
            # 事务已分配未入库的编号，同名目录只能来自上次未提交的发布。
            if final_root.exists():
                final_root.rename(orphan)
            staging_root.rename(final_root)
            destination = final_root
        return code, stage_a

    try:
        with _SINGLE_WRITER_LOCK:
            try:
                with rw_immediate_tx(conn):
                    yield publish
            except Exception:
                if destination is not None:
                    destination.rename(staging_root)
                raise
    finally:
        _rmtree_force(orphan)
