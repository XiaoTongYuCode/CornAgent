"""Explicit browser-test harness. Never used by app.main or make dev.

Requires a dedicated test database URL; model responses are deterministic fixtures.
"""

import asyncio
import json
import os

from app.agent.model import ModelStreamEvent
from app.database import Database
from app.main import create_app
from app.persistence.models import Base
from app.settings import Settings


class BrowserTestModel:
    async def stream(self, messages):
        if messages[-1]["role"] == "tool":
            text = (
                "## 已恢复会话\n\n这是浏览器测试模型的固定回答。\n\n"
                "| 能力 | 结果 |\n| --- | --- |\n| 提问恢复 | 已完成 |\n"
                "| 历史持久化 | 已保存 |\n\n```python\nprint('CornAgent')\n```\n"
            )
            for offset in range(0, len(text), 8):
                yield ModelStreamEvent(kind="content", content=text[offset : offset + 8])
                await asyncio.sleep(0.02)
            return
        yield ModelStreamEvent(kind="reasoning", content="正在运行可恢复会话的测试流程。")
        yield ModelStreamEvent(kind="content", content="先确认一个选项，然后继续。")
        yield ModelStreamEvent(
            kind="tool_calls",
            tool_calls=[
                {
                    "id": "browser-question",
                    "name": "ask_user",
                    "arguments": json.dumps(
                        {
                            "query": "接下来希望如何继续？",
                            "options": [
                                {
                                    "content": "继续生成完整回答，"
                                    "并保留所有已经确认的条件和原始资料",
                                    "description": "使用当前会话的完整背景继续处理；"
                                    "这段较长的说明用于验证桌面省略、悬停全文和触屏换行展示。",
                                },
                                {
                                    "content": "Adjust the requirements before continuing "
                                    "with the original request",
                                    "description": "Review all assumptions and constraints "
                                    "before proceeding, including details that must remain "
                                    "readable on a narrow mobile screen.",
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
        )


def browser_app():
    settings = Settings(
        _env_file=None,
        environment="browser-test",
        database_url=os.environ["CORNAGENT_BROWSER_TEST_DATABASE_URL"],
        file_store_path=".data/browser-test-files",
        agent_user_runs_per_minute=120,
    )
    database = Database(settings)
    Base.metadata.create_all(database.engine)
    database.close()
    return create_app(settings, model_client=BrowserTestModel())
