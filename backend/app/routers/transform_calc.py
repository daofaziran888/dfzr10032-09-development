"""采集转换管道计算接口：按表达式依赖字段生成转换结果与阻断记录。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.services.transform_calc import OUTCOME_LABELS, TransformCalculationService

router = APIRouter(prefix="/api/transform", tags=["采集转换管道"])

service = TransformCalculationService()


@router.get("/expressions")
def list_expressions() -> dict[str, Any]:
    """列出转换表达式及其依赖字段、纳入条件。"""
    items = service.list_expressions()
    return {
        "items": items,
        "total": len(items),
        "outcome_labels": OUTCOME_LABELS,
    }


@router.get("/expressions/{expression_no}")
def get_expression(expression_no: str) -> dict[str, Any]:
    """读取单个表达式的定义。"""
    expr = service.get_expression(expression_no)
    if expr is None:
        raise HTTPException(status_code=404, detail=f"转换表达式 {expression_no} 不存在")
    return expr


@router.get("/calculate")
def calculate(
    config: str = Query(description="解析编号，例如 PARS-0004"),
    expression: str | None = Query(default=None, description="表达式编号，留空计算全部"),
) -> dict[str, Any]:
    """按标准化事件明细和表达式字段依赖，生成转换结果或阻断记录。"""
    if expression and service.get_expression(expression) is None:
        raise HTTPException(status_code=404, detail=f"转换表达式 {expression} 不存在")
    result = service.calculate(config_no=config, expression_no=expression)
    if result is None:
        raise HTTPException(status_code=404, detail=f"解析配置 {config} 不存在或未启用事件解析")
    return result
