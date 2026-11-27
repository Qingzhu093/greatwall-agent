"""GreatWall Agent v0.3 数据库子包导出。"""

from .enums import *  # noqa: F401, F403
from .migrations import init_database_schema
from .schema_base import BASE_SCHEMA_SQL
from .schema_v03 import SEALED_HANDOFF_TRIGGER_SQL, V03_SCHEMA_SQL

from .schema_v031 import V031_SCHEMA_SQL

SCHEMA_SQL = BASE_SCHEMA_SQL + "\n" + V03_SCHEMA_SQL + "\n" + V031_SCHEMA_SQL + "\n" + SEALED_HANDOFF_TRIGGER_SQL

__all__ = [
    "BASE_SCHEMA_SQL",
    "V03_SCHEMA_SQL",
    "SEALED_HANDOFF_TRIGGER_SQL",
    "SCHEMA_SQL",
    "init_database_schema",
]
