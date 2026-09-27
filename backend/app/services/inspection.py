"""巡检任务业务规则：状态流转、字段校验与统计口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "inspection"
REQUIRED_FIELDS = ["巡检单号", "巡检站点", "巡检人员"]
STATUS_ORDER = ["待派发", "巡检中", "已提交", "已作废"]
# 待处理只包含还在流转中的状态；已提交、已作废一律不计。
PENDING_STATUSES = ["待派发", "巡检中"]
DONE_STATUS = "已提交"
VOID_STATUS = "已作废"
ACTION_RULES = {"派发巡检": "巡检中", "提交结果": "已提交", "作废巡检": "已作废"}
NEGATIVE_ACTIONS = ["作废巡检"]
PROBLEM_FIELD = "发现问题数"
SUBMIT_REQUIRED_FIELDS = ["巡检站点", "巡检人员"]


def parse_count(value: Any) -> int | None:
    """把数量字段解析成非负整数；空值按 0，无法解析时返回 None 交由调用方报错。"""
    if value is None or str(value).strip() == "":
        return 0
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(number, 0)


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

    def stats(self) -> dict[str, int]:
        """巡检看板口径：待处理只算待派发/巡检中；发现问题数只汇总已提交的有效巡检单。

        统计全部由当前单据状态即时汇总，不另外维护计数器，
        因此重复提交、刷新或换人查看都不会出现重复累加。
        """
        rows = store.rows(MODULE)
        month_prefix = date.today().strftime("%Y-%m")
        pending_dispatch = in_progress = submitted = voided = problems_month = 0
        for row in rows:
            status = row.get("status")
            if status == "待派发":
                pending_dispatch += 1
            elif status == "巡检中":
                in_progress += 1
            elif status == DONE_STATUS:
                submitted += 1
                # 有效巡检单：已提交且未作废；本月卡片再按巡检日期收窄。
                if str(row.get("巡检日期") or "").startswith(month_prefix):
                    problems_month += parse_count(row.get(PROBLEM_FIELD)) or 0
            elif status == VOID_STATUS:
                voided += 1
        return {
            "total": len(rows),
            "pending": pending_dispatch + in_progress,
            "pending_dispatch": pending_dispatch,
            "in_progress": in_progress,
            "submitted": submitted,
            "voided": voided,
            "problems_month": problems_month,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        extra_fields = ["巡检日期", "巡检项目", PROBLEM_FIELD, "巡检时长"]
        for field in extra_fields:
            if values.get(field) not in (None, ""):
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        values = values or {}
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡检任务可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        order_no = str(entry.get("巡检单号") or entry_id)
        current = entry.get("status")

        # 状态流转守卫：终态单据拒绝再次操作，保证重复提交不会重复累加。
        if action == "派发巡检":
            if current == "巡检中":
                return None, f"巡检单 {order_no} 已在巡检中，无需重复派发"
            if current != "待派发":
                return None, f"巡检单 {order_no} 当前状态为「{current}」，不能派发巡检"
        elif action == "提交结果":
            if current == DONE_STATUS:
                return None, f"巡检单 {order_no} 已提交，重复提交不会重复累加统计"
            if current == VOID_STATUS:
                return None, f"巡检单 {order_no} 已作废，不能再提交结果"
            if current != "巡检中":
                return None, f"巡检单 {order_no} 当前状态为「{current}」，需先派发巡检再提交结果"
            # 提交时逐字段核验，缺哪个字段、是哪一条单子都要讲清楚。
            missing = [
                field
                for field in SUBMIT_REQUIRED_FIELDS
                if not str(entry.get(field) or values.get(field) or "").strip()
            ]
            if missing:
                return None, f"巡检单 {order_no} 无法提交：{'、'.join(missing)}未填写，请补全后再提交"
            if PROBLEM_FIELD in values:
                count = parse_count(values.get(PROBLEM_FIELD))
                if count is None:
                    return None, f"巡检单 {order_no} 的发现问题数需为非负整数，请核对后再提交"
                entry[PROBLEM_FIELD] = count
            if not str(entry.get("巡检日期") or "").strip():
                entry["巡检日期"] = date.today().isoformat()
        elif action == "作废巡检":
            if current == VOID_STATUS:
                return None, f"巡检单 {order_no} 已作废，请勿重复操作"
            if current == DONE_STATUS:
                return None, f"巡检单 {order_no} 已提交结果，不能再作废"

        entry["status"] = target
        # 与 stats() 同口径：仅待派发、巡检中计入待处理，已提交/已作废都不落待处理。
        entry["pending"] = target in PENDING_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"巡检单 {order_no} 已{action}"
