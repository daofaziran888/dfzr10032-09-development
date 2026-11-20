"""格式解析器的事件解析：按解析配置读取原始事件，产出标准化事件明细。

每个字段单独记录转换结果，并把结果分成三种：

- ``ok``：成功转换；
- ``missing``：源数据原本就没有提供值（空串、``-`` 等空值标记）；
- ``invalid``：源数据提供了值，但无法按目标类型转换（例如重量写成「复秤中」）。

这两种失败在事件明细里分开保存，后续转换管道据此决定能否继续计算。
原始事件的文件行号一路带到标准化明细和计算记录里，方便指回原文。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.store import store

CONFIG_TABLE = "_parse_config"
RAW_TABLE = "_raw_events"
NORMALIZED_TABLE = "_normalized_events"

FIELD_STATUS_LABELS = {
    "ok": "转换成功",
    "missing": "源数据缺值",
    "invalid": "转换失败",
}
EVENT_STATUS_LABELS = {
    "ok": "全部转换成功",
    "partial": "部分字段失败",
    "failed": "全部字段失败",
}
STATUS_LABELS = FIELD_STATUS_LABELS


def _raw_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _is_null(raw: Any, null_tokens: list[str]) -> bool:
    """源端没有提供值：字段不存在、None 或命中空值标记。"""
    if raw is None:
        return True
    text = str(raw).strip()
    return text == "" or text in null_tokens


def _fail(raw: Any, field: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "value": None,
        "status": "invalid",
        "error": f"{field['target']} 无法转换：{reason}（原始值「{_raw_text(raw)}」）",
    }


def _convert(raw: Any, field: dict[str, Any], null_tokens: list[str]) -> dict[str, Any]:
    """转换单个字段，返回 value/status/error 三件套。"""
    if _is_null(raw, null_tokens):
        return {
            "value": None,
            "status": "missing",
            "error": f"{field['target']} 源数据缺值" + ("" if field.get("required") else "（可选字段）"),
        }

    target_type = str(field.get("type") or "string").lower()
    text = _raw_text(raw).strip()

    if target_type == "string":
        return {"value": text, "status": "ok", "error": None}

    if target_type == "integer":
        try:
            return {"value": int(text), "status": "ok", "error": None}
        except (TypeError, ValueError):
            return _fail(raw, field, "不是整数")

    if target_type == "decimal":
        try:
            value = Decimal(text)
        except (InvalidOperation, ValueError):
            return _fail(raw, field, "不是有效数字")
        if not value.is_finite():
            return _fail(raw, field, "不是有限数字")
        return {"value": float(value), "status": "ok", "error": None}

    if target_type == "boolean":
        lowered = text.lower()
        if lowered in {"true", "1", "是", "y", "yes"}:
            return {"value": True, "status": "ok", "error": None}
        if lowered in {"false", "0", "否", "n", "no"}:
            return {"value": False, "status": "ok", "error": None}
        return _fail(raw, field, "不是布尔值")

    if target_type in {"datetime", "date"}:
        formats = field.get("formats") or (
            ["%Y-%m-%d %H:%M:%S"] if target_type == "datetime" else ["%Y-%m-%d"]
        )
        for pattern in formats:
            try:
                parsed = datetime.strptime(text, pattern)
            except (TypeError, ValueError):
                continue
            if target_type == "date":
                return {"value": parsed.date().isoformat(), "status": "ok", "error": None}
            return {"value": parsed.isoformat(), "status": "ok", "error": None}
        return _fail(raw, field, f"不符合 {target_type} 格式 {'、'.join(formats)}")

    # 未识别的类型按字符串保留，避免整条事件因为配置笔误被丢弃。
    return {"value": text, "status": "ok", "error": None}


class EventParseService:
    """按解析配置读取并标准化原始事件。"""

    def list_configs(self) -> list[dict[str, Any]]:
        configs = []
        for config in store.rows(CONFIG_TABLE):
            configs.append({
                "id": config["id"],
                "解析编号": config["解析编号"],
                "source_name": config.get("source_name"),
                "input_format": config.get("input_format"),
                "encoding": config.get("encoding"),
                "header_row": config.get("header_row"),
                "null_tokens": list(config.get("null_tokens") or []),
                "fields": [dict(field) for field in config.get("fields") or []],
            })
        return configs

    def get_config(self, config_no: str) -> dict[str, Any] | None:
        for config in store.rows(CONFIG_TABLE):
            if config.get("解析编号") == config_no:
                return config
        return None

    def raw_events(self, config_no: str) -> list[dict[str, Any]]:
        """按解析配置读取原始事件，保留原始行号与源字段原文。"""
        config = self.get_config(config_no)
        if config is None:
            return []
        fields = config.get("fields") or []
        events: list[dict[str, Any]] = []
        for row in store.rows(RAW_TABLE):
            if row.get("解析编号") != config_no:
                continue
            raw_values = {field["source"]: row.get(field["source"]) for field in fields}
            events.append({
                "id": row.get("id"),
                "解析编号": row.get("解析编号"),
                "行号": row.get("行号"),
                "raw_event_id": row.get("id"),
                "原始行": dict(row),
                "原文": raw_values,
            })
        events.sort(key=lambda item: (int(item.get("行号") or 0), int(item.get("id") or 0)))
        return events

    def normalize_event(self, config: dict[str, Any], raw_event: dict[str, Any]) -> dict[str, Any]:
        """标准化一条原始事件：逐字段转换并保留行号。"""
        null_tokens = list(config.get("null_tokens") or [])
        row = raw_event.get("原始行") or {}
        field_results: dict[str, dict[str, Any]] = {}
        values: dict[str, Any] = {}
        missing_fields: list[str] = []
        invalid_fields: list[str] = []
        missing_required: list[str] = []
        invalid_required: list[str] = []

        for field in config.get("fields") or []:
            raw = row.get(field["source"])
            result = _convert(raw, field, null_tokens)
            entry = {
                "source": field["source"],
                "label": field.get("label") or field["target"],
                "type": field.get("type") or "string",
                "required": bool(field.get("required", True)),
                "raw_value": raw,
                "value": result["value"],
                "status": result["status"],
                "status_label": FIELD_STATUS_LABELS[result["status"]],
                "error": result["error"],
            }
            field_results[field["target"]] = entry
            if result["status"] == "ok":
                values[field["target"]] = result["value"]
            elif result["status"] == "missing":
                missing_fields.append(field["target"])
                if entry["required"]:
                    missing_required.append(field["target"])
            else:
                invalid_fields.append(field["target"])
                if entry["required"]:
                    invalid_required.append(field["target"])

        failed = len(missing_fields) + len(invalid_fields)
        if failed == 0:
            status = "ok"
        elif failed == len(field_results):
            status = "failed"
        else:
            status = "partial"

        return {
            "id": raw_event.get("id"),
            "raw_event_id": raw_event.get("id"),
            "解析编号": config.get("解析编号"),
            "行号": raw_event.get("行号"),
            "status": status,
            "status_label": EVENT_STATUS_LABELS[status],
            "字段": field_results,
            "value": values,
            "missing_fields": missing_fields,
            "invalid_fields": invalid_fields,
            "missing_required_fields": missing_required,
            "invalid_required_fields": invalid_required,
            "原文": dict(raw_event.get("原文") or {}),
            "原始行": dict(row),
        }

    def normalize(self, config_no: str, *, persist: bool = True) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """标准化该解析配置下的全部原始事件；结果按行号排序。"""
        config = self.get_config(config_no)
        if config is None:
            return None, []
        events = [
            self.normalize_event(config, raw_event)
            for raw_event in self.raw_events(config_no)
        ]
        events.sort(key=lambda item: (int(item.get("行号") or 0), int(item.get("id") or 0)))
        if persist:
            self._save(config_no, events)
        return config, events

    def stored_events(self, config_no: str) -> list[dict[str, Any]]:
        events = [
            event for event in store.rows(NORMALIZED_TABLE)
            if event.get("解析编号") == config_no
        ]
        events.sort(key=lambda item: (int(item.get("行号") or 0), int(item.get("id") or 0)))
        return events

    def ensure_events(self, config_no: str) -> list[dict[str, Any]]:
        """读取已落库的标准化明细；还没有生成过时先执行一次标准化。"""
        events = self.stored_events(config_no)
        if events:
            return events
        return self.normalize(config_no)[1]

    def _save(self, config_no: str, events: list[dict[str, Any]]) -> None:
        rows = store.rows(NORMALIZED_TABLE)
        rows[:] = [event for event in rows if event.get("解析编号") != config_no]
        rows.extend(events)

    def summary(self, events: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "事件总数": len(events),
            "全部成功": sum(1 for event in events if event["status"] == "ok"),
            "部分失败": sum(1 for event in events if event["status"] == "partial"),
            "全部失败": sum(1 for event in events if event["status"] == "failed"),
            "缺值字段数": sum(len(event["missing_fields"]) for event in events),
            "转换失败字段数": sum(len(event["invalid_fields"]) for event in events),
        }
