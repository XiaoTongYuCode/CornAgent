"""Deterministic demo search. No network calls or real-world search claims."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent.tools.base import ToolDefinition, ToolExecutionContext


class MockSearchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=1000)
    max_results: int = Field(default=3, ge=1, le=5)


DEMO_DOCUMENTS = (
    {
        "title": "[模拟] 晨光方案：模块化电池",
        "url": "https://example.com/cornagent-demo/modular-battery",
        "snippet": "虚构演示资料：晨光方案采用可替换电池模块，便于维护；需要管理模块接口一致性。",
        "keywords": "电池 battery 模块 方案 solution 优点 优势 advantage 维护",
    },
    {
        "title": "[模拟] 晨光方案：集成风险",
        "url": "https://example.com/cornagent-demo/integration-risk",
        "snippet": "虚构演示资料：接口供应商尚未统一，需要验证不同批次模块兼容性；未提供成本数据。",
        "keywords": "电池 battery 风险 risk 缺点 成本 cost 兼容 verifier 核验",
    },
    {
        "title": "[模拟] 松林方案：整体式电池",
        "url": "https://example.com/cornagent-demo/integrated-battery",
        "snippet": "虚构演示资料：松林方案采用整体式封装，接口较少；维修可能需要整体更换。",
        "keywords": "电池 battery 比较 compare 方案 solution 整体 优缺点 analyst",
    },
)


def build_mock_web_search_tool() -> ToolDefinition:
    async def search(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
        context.raise_if_cancelled()
        query = arguments["query"].lower()
        tokens = query.split()
        ranked = sorted(
            enumerate(DEMO_DOCUMENTS),
            key=lambda item: (
                -sum(token in (item[1]["keywords"] + item[1]["title"]).lower() for token in tokens),
                item[0],
            ),
        )
        return {
            "is_mock": True,
            "query": arguments["query"],
            "warning": "仅为本地固定模拟资料，未进行真实网络搜索，不代表真实事实。",
            "results": [
                {key: value for key, value in doc.items() if key != "keywords"}
                for _, doc in ranked[: arguments.get("max_results", 3)]
            ],
        }

    return ToolDefinition(
        name="mock_web_search",
        description="搜索本地固定的虚构演示资料。不是网络搜索；回答必须明确标注模拟资料。",
        parameters=MockSearchArguments.model_json_schema(),
        arguments_model=MockSearchArguments,
        handler=search,
        execution_scopes=frozenset({"root", "child"}),
        read_only=True,
        status_label="正在模拟搜索",
        status_detail=lambda args: str(args.get("query") or ""),
        result_presenter=lambda result: (
            "[模拟资料] " + "；".join(item["title"] for item in result["results"])
        ),
    )
