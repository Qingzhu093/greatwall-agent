"""长城 V6-Up (v3.0) 通用仪器基础辅助与返回协议校验器（零第三方依赖）。

核心契约（对齐 09 §4.1 与 agent_kb/04）：
1. 平台测试输入唯一放置在 `spec["public_input"]`，通过 `get_public_input(spec)` 安全读取；
   严禁从候选返回值倒推输入，严禁缺键静默返回 0 分（缺键抛 `InstrumentInputError` -> 映射 `INSTRUMENT_ERROR`）。
2. 所有仪器统一返回：
   `{"status": "OK"|"CANDIDATE_ERROR"|"INSTRUMENT_ERROR"|"INFRA_ERROR",`
   ` "verdict": "PASS"|"FAIL"|"UNDECIDED"|None,`
   ` "tracks": dict[str, float|int|str|bool|None],`
   ` "details": str}`
"""

from __future__ import annotations

import math
from typing import Any

ALLOWED_INSTRUMENT_ROLES = frozenset({"VERDICT", "PROBE", "ENV"})
ALLOWED_INSTRUMENT_TIERS = frozenset({"probe", "official", "heavy"})
ALLOWED_INSTRUMENT_STATUSES = frozenset({"OK", "CANDIDATE_ERROR", "INSTRUMENT_ERROR", "INFRA_ERROR"})
ALLOWED_VERDICTS = frozenset({"PASS", "FAIL", "UNDECIDED"})


class InstrumentInputError(Exception):
    """仪器读取平台测试输入（public_input）缺失或格式非法，归因 INSTRUMENT_ERROR（零处罚探索者）。"""


def get_public_input(spec: dict[str, Any] | None) -> dict[str, Any]:
    """从 evaluator_spec 唯一合法键位 `public_input` 读取测试输入字典。"""
    if not isinstance(spec, dict):
        raise InstrumentInputError("evaluator_spec 必须为 dict")
    if "public_input" not in spec or not isinstance(spec["public_input"], dict):
        raise InstrumentInputError("evaluator_spec 缺少合法字典键 'public_input'（严禁静默判 0 分）")
    return spec["public_input"]


def _is_valid_track_value(val: Any) -> bool:
    if val is None or isinstance(val, (bool, int, str)):
        return True
    if isinstance(val, float):
        return math.isfinite(val)
    return False


def validate_instrument_result(
    raw: Any,
    instrument_role: str = "VERDICT",
) -> tuple[bool, dict[str, Any], str]:
    """严格校验仪器 `evaluate(artifact, spec, tier)` 返回体契约。"""
    if not isinstance(raw, dict):
        return False, {}, f"仪器返回值必须为 dict，实收 {type(raw).__name__}"

    status = raw.get("status")
    if status not in ALLOWED_INSTRUMENT_STATUSES:
        return (
            False,
            {},
            f"仪器返回非法 status={status!r}，仅允许 {sorted(ALLOWED_INSTRUMENT_STATUSES)}",
        )

    role_u = str(instrument_role or "VERDICT").strip().upper()
    verdict = raw.get("verdict")
    if role_u == "PROBE":
        if verdict is not None:
            return False, {}, f"PROBE 探针的 verdict 必须恒为 None，实收 {verdict!r}"
    elif status == "OK":
        if role_u == "VERDICT" and verdict not in ALLOWED_VERDICTS:
            return (
                False,
                {},
                f"VERDICT 仪器 status='OK' 时 verdict 必须为 {sorted(ALLOWED_VERDICTS)}，实收 {verdict!r}",
            )
        if role_u == "ENV" and verdict is not None and verdict not in ALLOWED_VERDICTS:
            return False, {}, f"ENV 仪器返回非法 verdict={verdict!r}"
    else:
        if verdict is not None:
            return False, {}, f"非 OK 状态 ({status}) 的 verdict 必须为 None，实收 {verdict!r}"

    tracks = raw.get("tracks")
    if not isinstance(tracks, dict):
        return False, {}, f"仪器返回 'tracks' 必须为 dict，实收 {type(tracks).__name__}"
    for tk, tv in tracks.items():
        if not isinstance(tk, str) or not _is_valid_track_value(tv):
            return (
                False,
                {},
                f"仪器返回 tracks[{tk!r}] 包含非法或非有限数值 ({tv!r})",
            )

    details = raw.get("details")
    if not isinstance(details, str):
        return False, {}, f"仪器返回 'details' 必须为 str，实收 {type(details).__name__}"

    normalized = {
        "status": status,
        "verdict": verdict,
        "tracks": dict(tracks),
        "details": details,
    }
    return True, normalized, ""


def map_instrument_result_to_obs_status(status: str, verdict: str | None) -> str:
    """将仪器四态 + 三值 verdict 映射为 observations.obs_status。"""
    if status == "OK":
        if verdict == "PASS":
            return "VALID_PASS"
        if verdict == "FAIL":
            return "MEASURED_REJECTION"
        return "VALID_UNDECIDED"
    if status in ("CANDIDATE_ERROR", "INSTRUMENT_ERROR", "INFRA_ERROR"):
        return status
    return "INSTRUMENT_ERROR"
