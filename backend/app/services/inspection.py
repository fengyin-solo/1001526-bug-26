"""巡检任务业务规则：状态流转、字段校验与统计口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检单号", "巡检站点", "巡检人员"]
RESULT_FIELDS = ["巡检日期", "巡检项目", "发现问题数", "巡检时长"]
STATUS_ORDER = ["待派发", "巡检中", "已提交", "已作废"]
ACTION_RULES = {"派发巡检": "巡检中", "提交结果": "已提交", "作废巡检": "已作废"}
NEGATIVE_ACTIONS = ["作废巡检"]
# 待处理只包含还在流转中的单子；已提交、已作废都是终态，不再计入待处理。
PENDING_STATUSES = ("待派发", "巡检中")
FINISHED_STATUSES = ("已提交", "已作废")
# 发现问题数只按有效巡检单汇总：已提交且未作废的单子才计入。
VALID_PROBLEM_STATUSES = ("已提交",)
# 各动作允许的出发状态；终态单子重复动作直接拦下，保证统计不重复累加。
ACTION_ALLOWED_FROM = {
    "派发巡检": ("待派发",),
    "提交结果": ("巡检中",),
    "作废巡检": ("待派发", "巡检中"),
}
REPEAT_MESSAGES = {
    "派发巡检": "已派发，请勿重复派发",
    "提交结果": "已提交，请勿重复提交",
    "作废巡检": "已作废，请勿重复操作",
}


def _is_pending(status: Any) -> bool:
    return status in PENDING_STATUSES


def _problem_count(row: dict[str, Any]) -> int:
    """发现问题数按整数读取；历史脏数据（非数字）按 0 处理，不污染汇总。"""
    try:
        return max(int(float(row.get("发现问题数"))), 0)
    except (TypeError, ValueError):
        return 0


def _in_current_month(value: Any) -> bool:
    text = str(value or "")
    return bool(text) and text[:7] == date.today().strftime("%Y-%m")


class InspectionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡检单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def get_stats(self) -> dict[str, int]:
        """巡检任务页与概览看板共用同一份统计口径，按行实时汇总。

        待处理 = 待派发 + 巡检中；本月发现问题只累加已提交的有效巡检单。
        """
        rows = store.rows(MODULE)
        return {
            "待处理巡检": sum(1 for row in rows if row.get("status") in PENDING_STATUSES),
            "待派发巡检": sum(1 for row in rows if row.get("status") == "待派发"),
            "巡检中任务": sum(1 for row in rows if row.get("status") == "巡检中"),
            "本月发现问题": sum(
                _problem_count(row)
                for row in rows
                if row.get("status") in VALID_PROBLEM_STATUSES
                and _in_current_month(row.get("巡检日期"))
            ),
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in RESULT_FIELDS:
            if values.get(field) not in (None, ""):
                entry[field] = values[field]
        entry["status"] = STATUS_ORDER[0]
        entry["巡检状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡检任务可执行范围"
        serial = entry.get("巡检单号", entry_id)
        current = entry.get("status")
        allowed = ACTION_ALLOWED_FROM[action]
        if current not in allowed:
            if current == ACTION_RULES[action]:
                return None, f"巡检单 {serial} {REPEAT_MESSAGES[action]}"
            if current in FINISHED_STATUSES:
                return None, f"巡检单 {serial} 当前状态为{current}，不能再执行「{action}」"
            return None, f"巡检单 {serial} 当前状态为{current}，不能执行「{action}」，请先完成前置流转"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if action == "提交结果":
            # 提交前补录/校验巡检站点与巡检人员，缺字段要能定位到具体单号。
            for field in ("巡检站点", "巡检人员"):
                if values.get(field) not in (None, ""):
                    entry[field] = values[field]
            missing = [
                field
                for field in ("巡检站点", "巡检人员")
                if not str(entry.get(field) or "").strip()
            ]
            if missing:
                return None, f"巡检单 {serial} 的{'、'.join(missing)}未填写，无法提交结果"
            for field in RESULT_FIELDS:
                if values.get(field) not in (None, ""):
                    entry[field] = values[field]
            if not str(entry.get("巡检日期") or "").strip():
                entry["巡检日期"] = date.today().isoformat()
            entry["发现问题数"] = _problem_count(entry)
        entry["status"] = target
        entry["巡检状态"] = target
        entry["pending"] = _is_pending(target)
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡检单 {serial} 已{action}"
