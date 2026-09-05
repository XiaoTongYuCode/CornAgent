"""Explicit deterministic browser demo; never imported by the production app.

Requires CORNAGENT_DEMO_DATABASE_URL pointing to a migrated, isolated schema.
Both models are test fixtures. The real runtime executes the shared mock tool.
"""

import asyncio
import json
import os

from app.agent.model import ModelStreamEvent
from app.main import create_app
from app.settings import Settings


def tool(name, arguments, call_id):
    return ModelStreamEvent(
        kind="tool_calls",
        tool_calls=[{"id": call_id, "name": name, "arguments": json.dumps(arguments)}],
    )


class DemoRootModel:
    async def stream(self, messages):
        start = max(index for index, message in enumerate(messages) if message["role"] == "user")
        history = messages[start:]
        outputs = [message for message in history if message["role"] == "tool"]
        call_id = f"demo-{len(history)}"
        if not outputs:
            yield tool("mock_web_search", {"query": "电池 方案"}, call_id)
            return
        last = outputs[-1]
        payload = json.loads(last["content"])
        spawned = any(message.get("name") == "spawn_subagents" for message in outputs)
        if last["name"] == "mock_web_search" and not spawned:
            yield tool(
                "spawn_subagents",
                {
                    "tasks": [
                        {
                            "title": title,
                            "instruction": (
                                f"{instruction}。调用 mock_web_search，明确标注模拟资料。"
                            ),
                            "expected_output": "结构化摘要、证据与待验证项",
                            "profile": profile,
                        }
                        for profile, title, instruction in (
                            ("researcher", "收集方案优势", "研究晨光模块化电池优势"),
                            ("analyst", "比较两种方案", "比较晨光与松林方案"),
                            ("verifier", "核验接口风险", "核验接口兼容性与资料缺口"),
                        )
                    ]
                },
                call_id,
            )
        elif last["name"] == "spawn_subagents":
            yield ModelStreamEvent(kind="content", content="子任务已派发，我继续查看模拟成本资料。")
            yield tool("mock_web_search", {"query": "成本 缺口"}, call_id)
        elif last["name"] == "mock_web_search":
            yield tool("list_subagents", {}, call_id)
        elif last["name"] == "list_subagents" or payload.get("undelivered_result_task_ids"):
            yield tool("collect_subagent_results", {}, call_id)
        elif payload.get("pending_task_ids"):
            yield tool(
                "wait_subagents",
                {"task_ids": payload["pending_task_ids"], "return_when": "all"},
                call_id,
            )
        else:
            yield ModelStreamEvent(
                kind="content",
                content=(
                    "## 并行研究演示完成\n\n"
                    "这是**固定测试模型**的演示回答。三个子任务的完整结果已收取。\n\n"
                    "| 模拟方案 | 优势 | 待核验项 |\n| --- | --- | --- |\n"
                    "| 晨光模块化电池 | 便于维护 | 接口兼容性、实际成本 |\n"
                    "| 松林整体式电池 | 接口较少 | 整体更换的维修成本 |\n\n"
                    "以上全部是本地**模拟资料**，没有进行真实网络搜索。"
                ),
            )

    async def compact(self, messages, *, max_tokens):
        return {"summary": "固定演示模型：此前对话为模拟电池方案研究。"}


class DemoChildModel:
    async def stream(self, messages):
        if messages[-1]["role"] != "tool":
            yield tool("mock_web_search", {"query": "电池 方案 风险"}, "child-search")
            return
        await asyncio.sleep(float(os.environ.get("CORNAGENT_DEMO_CHILD_DELAY", "12")))
        yield ModelStreamEvent(
            kind="content",
            content=json.dumps(
                {
                    "status": "completed",
                    "summary": (
                        "模拟资料：模块化方案便于维护，整体式方案接口较少。"
                        "兼容性与成本尚需真实证据。"
                    ),
                    "evidence": [
                        {
                            "claim": "模拟模块接口存在待验证项",
                            "source_title": "[模拟] 晨光方案：集成风险",
                            "url": "https://example.com/cornagent-demo/integration-risk",
                        }
                    ],
                    "warnings": ["固定测试模型，不能作为真实决策依据。"],
                },
                ensure_ascii=False,
            ),
        )

    async def compact(self, messages, *, max_tokens):
        return {"summary": "固定模拟资料"}


def browser_app():
    settings = Settings(
        _env_file=None,
        environment="subagent-browser-demo",
        database_url=os.environ["CORNAGENT_DEMO_DATABASE_URL"],
        redis_url=os.environ.get("CORNAGENT_DEMO_REDIS_URL", "redis://127.0.0.1:6379/0"),
        agent_model="deterministic-demo",
        agent_api_key=None,
        agent_user_runs_per_minute=120,
        file_store_path="server/.data/subagent-browser-demo",
    )
    return create_app(settings, model_client=DemoRootModel(), child_model_client=DemoChildModel())
