"""采集转换管道的计算规则：按表达式依赖字段判断事件能否参与计算。

一条标准化事件里可能只有部分字段转换失败。表达式引用哪些字段，决定了
这条事件对它的影响：

- 事件不满足表达式的纳入条件 → ``未纳入``，本来就不参与统计；
- 参与统计的前提字段不可用 → ``被阻断``，并生成指向原始事件的阻断记录；
- 依赖字段全部可用 → ``正常产出``，按分组生成聚合结果。

可选依赖字段失败时同样要阻断：这类字段通常用于剔除某些事件，值取不到就
无法判断这条事件该不该算进去，继续计算会悄悄改变下游收到的数据范围。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.event_parser import EventParseService
from app.store import store

EXPRESSION_TABLE = "_transform_expressions"

OUTCOME_LABELS = {
    "produced": "正常产出",
    "blocked": "被阻断",
    "excluded": "未纳入",
}


class TransformCalculationService:
    def __init__(self) -> None:
        self.event_service = EventParseService()

    def list_expressions(self) -> list[dict[str, Any]]:
        return [dict(expr) for expr in store.rows(EXPRESSION_TABLE)]

    def get_expression(self, expression_no: str) -> dict[str, Any] | None:
        for expr in store.rows(EXPRESSION_TABLE):
            if expr.get("表达式编号") == expression_no:
                return expr
        return None

    # ---------- 事件到表达式的判定 ----------

    @staticmethod
    def _dependency_fields(expr: dict[str, Any]) -> dict[str, bool]:
        """依赖字段 → 是否必填；纳入条件与分组引用的字段也算依赖。"""
        deps: dict[str, bool] = {}
        for dep in expr.get("依赖字段") or []:
            deps[str(dep["field"])] = bool(dep.get("required", True))
        for field in (expr.get("纳入条件") or {}).keys():
            deps.setdefault(field, True)
        if expr.get("聚合字段"):
            deps.setdefault(str(expr["聚合字段"]), True)
        grouping_field = (expr.get("分组方式") or {}).get("field")
        if grouping_field:
            deps.setdefault(str(grouping_field), True)
        return deps

    @staticmethod
    def _field_state(event: dict[str, Any], field: str) -> dict[str, Any]:
        return (event.get("字段") or {}).get(field) or {
            "source": field,
            "label": field,
            "required": True,
            "raw_value": None,
            "value": None,
            "status": "missing",
            "status_label": "源数据缺值",
            "error": f"字段 {field} 不在解析配置的字段映射里",
        }

    def _reference(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "raw_event_id": event.get("raw_event_id"),
            "行号": event.get("行号"),
            "原文": dict(event.get("原文") or {}),
        }

    def evaluate_event(self, expr: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        """判定单条事件对某个表达式的归属。"""
        record = {
            "表达式编号": expr["表达式编号"],
            "节点编号": expr.get("节点编号"),
            "名称": expr.get("名称"),
            "raw_event_id": event.get("raw_event_id"),
            "行号": event.get("行号"),
            "原始事件": self._reference(event),
            "outcome": None,
            "outcome_label": None,
            "reason": None,
            "failed_fields": [],
            "contribution": None,
            "group": None,
        }

        # 1. 先看纳入条件：条件字段取不到值时不能猜，必须阻断。
        for field, allowed in (expr.get("纳入条件") or {}).items():
            state = self._field_state(event, field)
            if state.get("status") != "ok":
                failed = self._failed_field(state)
                record.update({
                    "outcome": "blocked",
                    "outcome_label": OUTCOME_LABELS["blocked"],
                    "reason": f"无法判断是否满足纳入条件：{failed['error']}",
                    "failed_fields": [failed],
                })
                return record
            if allowed and state.get("value") not in allowed:
                record.update({
                    "outcome": "excluded",
                    "outcome_label": OUTCOME_LABELS["excluded"],
                    "reason": f"{state.get('label') or field}「{state.get('value')}」不在统计范围内",
                })
                return record

        # 2. 依赖字段是否可用。可选字段失败同样阻断，避免改变下游数据范围。
        failed_fields: list[dict[str, Any]] = []
        optional_failed: list[dict[str, Any]] = []
        for field, required in self._dependency_fields(expr).items():
            state = self._field_state(event, field)
            if state.get("status") == "ok":
                continue
            failed = self._failed_field(state)
            failed["required"] = required
            if required:
                failed_fields.append(failed)
            else:
                optional_failed.append(failed)

        if failed_fields or optional_failed:
            reasons: list[str] = []
            for failed in failed_fields:
                reasons.append(f"必填依赖字段不可用：{failed['error']}")
            for failed in optional_failed:
                reasons.append(
                    f"可选依赖字段不可用：{failed['error']}；"
                    "该字段用于限定统计范围，继续计算会改变下游收到的数据范围"
                )
            record.update({
                "outcome": "blocked",
                "outcome_label": OUTCOME_LABELS["blocked"],
                "reason": "；".join(reasons),
                "failed_fields": failed_fields + optional_failed,
            })
            return record

        # 3. 正常参与计算。
        record.update({
            "outcome": "produced",
            "outcome_label": OUTCOME_LABELS["produced"],
            "group": self._group_key(expr, event),
            "contribution": self._contribution(expr, event),
        })
        return record

    @staticmethod
    def _failed_field(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "field": state.get("source") or state.get("label"),
            "label": state.get("label"),
            "raw_value": state.get("raw_value"),
            "status": state.get("status"),
            "status_label": state.get("status_label"),
            "error": state.get("error"),
        }

    @staticmethod
    def _group_key(expr: dict[str, Any], event: dict[str, Any]) -> str | None:
        grouping = expr.get("分组方式") or {}
        if not grouping:
            return None
        field = grouping.get("field")
        state = TransformCalculationService._field_state(event, field)
        value = state.get("value")
        if value is None:
            return None
        if grouping.get("type") == "time_hour":
            return str(value)[:13].replace("T", " ") + ":00"
        return str(value)

    @staticmethod
    def _contribution(expr: dict[str, Any], event: dict[str, Any]) -> float:
        if expr.get("聚合方式") == "sum":
            field = expr.get("聚合字段")
            value = TransformCalculationService._field_state(event, field).get("value")
            factor = float(expr.get("换算系数") or 1)
            return round(float(value or 0) * factor, 6)
        return 1.0

    # ---------- 聚合 ----------

    def _aggregate(self, expr: dict[str, Any], records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        produced = [record for record in records if record["outcome"] == "produced"]
        groups: dict[str | None, list[dict[str, Any]]] = {}
        for record in produced:
            groups.setdefault(record["group"], []).append(record)

        results: list[dict[str, Any]] = []
        for group_key, items in groups.items():
            total = round(sum(item["contribution"] for item in items), 6)
            results.append({
                "分组": group_key if group_key is not None else "全部",
                "产出条数": len(items),
                "数值": total,
                "输出字段": expr.get("输出字段"),
                "输出单位": expr.get("输出单位"),
                "关联行号": [item["行号"] for item in items],
                "关联原始事件": [item["原始事件"] for item in items],
            })
        results.sort(key=lambda item: str(item["分组"]))
        return results

    @staticmethod
    def _summary(records: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "正常产出": sum(1 for record in records if record["outcome"] == "produced"),
            "被阻断": sum(1 for record in records if record["outcome"] == "blocked"),
            "未纳入": sum(1 for record in records if record["outcome"] == "excluded"),
            "事件总数": len(records),
        }

    def calculate(
        self,
        *,
        config_no: str,
        expression_no: str | None = None,
    ) -> dict[str, Any] | None:
        config = self.event_service.get_config(config_no)
        if config is None:
            return None
        events = self.event_service.ensure_events(config_no)

        expressions = [
            expr for expr in self.list_expressions()
            if expr.get("解析编号") in (None, config_no)
        ]
        if expression_no:
            expressions = [expr for expr in expressions if expr.get("表达式编号") == expression_no]

        expression_results: list[dict[str, Any]] = []
        all_records: list[dict[str, Any]] = []
        blocking_records: list[dict[str, Any]] = []
        for expr in expressions:
            records = [self.evaluate_event(expr, event) for event in events]
            results = self._aggregate(expr, records)
            summary = self._summary(records)
            expression_results.append({
                "表达式编号": expr.get("表达式编号"),
                "节点编号": expr.get("节点编号"),
                "名称": expr.get("名称"),
                "公式": expr.get("公式"),
                "输出字段": expr.get("输出字段"),
                "输出单位": expr.get("输出单位"),
                "依赖字段": [dict(dep) for dep in expr.get("依赖字段") or []],
                "纳入条件": dict(expr.get("纳入条件") or {}),
                "summary": summary,
                "结果": results,
                "计算记录": records,
                "阻断记录": [record for record in records if record["outcome"] == "blocked"],
            })
            all_records.extend(records)
            blocking_records.extend(record for record in records if record["outcome"] == "blocked")

        return {
            "解析编号": config_no,
            "source_name": config.get("source_name"),
            "生成时间": datetime.now().isoformat(timespec="seconds"),
            "summary": self._summary(all_records),
            "表达式": expression_results,
            "计算记录": all_records,
            "阻断记录": blocking_records,
            "事件": [
                {
                    "raw_event_id": event.get("raw_event_id"),
                    "行号": event.get("行号"),
                    "status": event.get("status"),
                    "原文": dict(event.get("原文") or {}),
                }
                for event in events
            ],
        }
