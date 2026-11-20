"""格式解析器事件接口：按解析配置读取原始事件，产出标准化事件明细。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.event_parser import EventParseService

router = APIRouter(prefix="/api/parser", tags=["格式解析器"])

service = EventParseService()


@router.get("/events/configs")
def list_configs() -> dict[str, Any]:
    """列出可用于事件解析的解析配置（字段映射、类型转换、空值处理）。"""
    items = service.list_configs()
    return {"items": items, "total": len(items)}


@router.get("/events/raw")
def raw_events(config: str = Query(description="解析编号，例如 PARS-0004")) -> dict[str, Any]:
    """按解析配置读取原始事件，保留文件行号与源字段原文。"""
    if service.get_config(config) is None:
        raise HTTPException(status_code=404, detail=f"解析配置 {config} 不存在或未启用事件解析")
    items = service.raw_events(config)
    return {"解析编号": config, "items": items, "total": len(items)}


@router.get("/events")
def normalized_events(
    config: str = Query(description="解析编号，例如 PARS-0004"),
    status: str | None = Query(default=None, description="ok、partial、failed"),
) -> dict[str, Any]:
    """读取标准化事件明细：每个字段都带转换结果，失败区分缺值与转换失败。"""
    if service.get_config(config) is None:
        raise HTTPException(status_code=404, detail=f"解析配置 {config} 不存在或未启用事件解析")
    _config, all_items = service.normalize(config, persist=False)
    items = [item for item in all_items if not status or item["status"] == status]
    return {
        "解析编号": config,
        "summary": service.summary(all_items),
        "items": items,
        "total": len(items),
    }


@router.post("/events/normalize")
def normalize_events(config: str = Query(description="解析编号，例如 PARS-0004")) -> dict[str, Any]:
    """重新执行标准化并落库；返回本次生成的明细与汇总。"""
    config_row = service.get_config(config)
    if config_row is None:
        raise HTTPException(status_code=404, detail=f"解析配置 {config} 不存在或未启用事件解析")
    _config, items = service.normalize(config)
    return {
        "ok": True,
        "message": f"已标准化 {len(items)} 条原始事件",
        "解析编号": config,
        "summary": service.summary(items),
        "items": items,
    }
