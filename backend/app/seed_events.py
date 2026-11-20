"""称重事件样例：解析配置、原始事件与转换表达式。

这些表以 ``_`` 开头，属于解析/转换链路内部数据，不会出现在运营概览的模块列表里。
原始事件保留了文件里的行号（表头是第 1 行，第一条数据从第 2 行开始），
后续标准化明细和计算记录都靠它指回称重原文。
"""
from __future__ import annotations

from typing import Any

# 原始事件里 ``""``、``-`` 这类文本表示源端没有提供值；``复秤中`` 则是
# 已经提供了值、但无法按目标类型转换，两者在解析结果里必须分开记录。
NULL_TOKENS = ["", "-", "--", "NULL", "null", "None", "N/A"]

PARSE_CONFIG_ROWS: list[dict[str, Any]] = [
    {
        "id": 1,
        "解析编号": "PARS-0004",
        "source_name": "地磅称重明细.csv",
        "input_format": "CSV",
        "encoding": "utf-8",
        "header_row": 1,
        "null_tokens": NULL_TOKENS,
        "fields": [
            {
                "source": "时间",
                "target": "event_time",
                "label": "称重时间",
                "type": "datetime",
                "formats": ["%Y-%m-%d %H:%M:%S"],
                "required": True,
            },
            {
                "source": "车牌号",
                "target": "plate_no",
                "label": "车牌号",
                "type": "string",
                "required": True,
            },
            {
                "source": "重量",
                "target": "weight_kg",
                "label": "重量(kg)",
                "type": "decimal",
                "required": True,
            },
            {
                "source": "站点",
                "target": "site",
                "label": "称重站点",
                "type": "string",
                "required": True,
            },
            {
                "source": "单据类型",
                "target": "biz_type",
                "label": "单据类型",
                "type": "string",
                "required": True,
            },
        ],
    },
]

RAW_EVENT_ROWS: list[dict[str, Any]] = [
    {
        "id": 1,
        "解析编号": "PARS-0004",
        "行号": 2,
        "时间": "2026-09-01 08:05:00",
        "车牌号": "鲁A12345",
        "重量": "12.50",
        "站点": "东区站",
        "单据类型": "入库",
    },
    {
        "id": 2,
        "解析编号": "PARS-0004",
        "行号": 3,
        "时间": "2026-09-01 08:35:00",
        "车牌号": "鲁B23456",
        "重量": "复秤中",
        "站点": "东区站",
        "单据类型": "入库",
    },
    {
        "id": 3,
        "解析编号": "PARS-0004",
        "行号": 4,
        "时间": "2026-09-01 09:10:00",
        "车牌号": "鲁C34567",
        "重量": "",
        "站点": "西区站",
        "单据类型": "入库",
    },
    {
        "id": 4,
        "解析编号": "PARS-0004",
        "行号": 5,
        "时间": "2026-09-01 09:20:00",
        "车牌号": "鲁D45678",
        "重量": "8.00",
        "站点": "西区站",
        "单据类型": "出库",
    },
    {
        "id": 5,
        "解析编号": "PARS-0004",
        "行号": 6,
        "时间": "2026-09-01 10:00:00",
        "车牌号": "鲁E56789",
        "重量": "5.00",
        "站点": "",
        "单据类型": "入库",
    },
    {
        "id": 6,
        "解析编号": "PARS-0004",
        "行号": 7,
        "时间": "2026/13/45 99:99",
        "车牌号": "鲁F67890",
        "重量": "7.00",
        "站点": "东区站",
        "单据类型": "入库",
    },
    {
        "id": 7,
        "解析编号": "PARS-0004",
        "行号": 8,
        "时间": "2026-09-01 11:15:00",
        "车牌号": "鲁G78901",
        "重量": "-",
        "站点": "东区站",
        "单据类型": "入库",
    },
    {
        "id": 8,
        "解析编号": "PARS-0004",
        "行号": 9,
        "时间": "2026-09-01 11:45:00",
        "车牌号": "鲁H89012",
        "重量": "9.50",
        "站点": "东区站",
        "单据类型": "盘点",
    },
]

TRANSFORM_EXPRESSION_ROWS: list[dict[str, Any]] = [
    {
        "id": 1,
        "表达式编号": "EXPR-0001",
        "节点编号": "TRAN-0004",
        "解析编号": "PARS-0004",
        "名称": "按小时汇总到货次数",
        "输出字段": "arrival_count",
        "输出单位": "车次",
        "聚合方式": "count",
        "聚合字段": None,
        "公式": "count(*) where biz_type = '入库' group by hour(event_time)",
        "分组方式": {"type": "time_hour", "field": "event_time"},
        "依赖字段": [
            {"field": "event_time", "required": True},
        ],
        "纳入条件": {"biz_type": ["入库"]},
        "启用": True,
    },
    {
        "id": 2,
        "表达式编号": "EXPR-0002",
        "节点编号": "TRAN-0005",
        "解析编号": "PARS-0004",
        "名称": "按重量计算运量",
        "输出字段": "volume_tons",
        "输出单位": "吨",
        "聚合方式": "sum",
        "聚合字段": "weight_kg",
        "换算系数": 0.001,
        "公式": "sum(weight_kg) * 0.001",
        "分组方式": None,
        "依赖字段": [
            {"field": "weight_kg", "required": True},
        ],
        "纳入条件": {},
        "启用": True,
    },
    {
        "id": 3,
        "表达式编号": "EXPR-0003",
        "节点编号": "TRAN-0006",
        "解析编号": "PARS-0004",
        "名称": "按站点汇总入库车次",
        "输出字段": "site_inbound_count",
        "输出单位": "车次",
        "聚合方式": "count",
        "聚合字段": None,
        "公式": "count(*) where biz_type = '入库' group by site",
        "分组方式": {"type": "field", "field": "site"},
        "依赖字段": [
            {"field": "site", "required": True},
            # 重量只用于剔除空车；它转不出来时不能带着这条事件继续算，
            # 否则按站点汇总的口径会被悄悄改变。
            {"field": "weight_kg", "required": False},
        ],
        "纳入条件": {"biz_type": ["入库"]},
        "启用": True,
    },
]

EVENT_SEED_ROWS: dict[str, list[dict[str, Any]]] = {
    "_parse_config": PARSE_CONFIG_ROWS,
    "_raw_events": RAW_EVENT_ROWS,
    "_transform_expressions": TRANSFORM_EXPRESSION_ROWS,
}
