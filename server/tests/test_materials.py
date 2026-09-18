"""Durable receipt integrity, transaction boundaries, branch authorization and paging."""

import asyncio
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from app.agent.tools.base import ToolExecutionContext
from app.agent.tools.materials import build_material_tools
from app.database import Database
from app.persistence import materials
from app.persistence.agent_runtime import AgentRepository
from app.persistence.errors import DomainError
from app.persistence.materials import MaterialRepository, canonical_json
from app.persistence.models import AgentRun, AgentToolReceipt
from app.persistence.scope import LOCAL_SCOPE, Identity


@pytest.fixture
def material_database(settings):
    database = Database(settings)
    yield database
    database.close()


def seed(db, key="seed", identity=LOCAL_SCOPE):
    return AgentRepository(db).create_session_run(identity, content="test", idempotency_key=key)


def finish(db, run_id):
    db.get(AgentRun, run_id).status = "completed"
    db.commit()


def save(repo, run_id, call_id="call-1", result=None, **kwargs):
    return repo.save(
        LOCAL_SCOPE,
        run_id=run_id,
        call_id=call_id,
        tool_name="search_documents",
        arguments={"query": "中文 evidence"},
        result=result or {"ok": True, "value": "exact"},
        **kwargs,
    )


def test_receipt_complete_paging_idempotency_and_rollback(material_database):
    result = {"ok": True, "rows": [{"text": "中文 🎈 evidence" * 1000, "count": 42}]}
    with material_database.session_factory() as db:
        _, run = seed(db)
        repo = MaterialRepository(db)
        receipt = save(repo, run.id, result=result)
        assert receipt["complete"] and len(receipt["preview"]) == 1000
        assert (
            receipt["content_hash"] == hashlib.sha256(canonical_json(result).encode()).hexdigest()
        )
        db.commit()
        # A new instance after recovery returns the original committed result.
    with material_database.session_factory() as db:
        repo = MaterialRepository(db)
        assert save(repo, run.id, result={"ok": True, "value": "changed upstream"}) == receipt
        assert repo.replay(
            LOCAL_SCOPE, run.id, "call-1", "search_documents", {"query": "中文 evidence"}
        ) == (True, result)
        assert repo.replay(LOCAL_SCOPE, run.id, "new-call", "search_documents", {}) == (False, None)
        with pytest.raises(DomainError) as conflict:
            repo.replay(LOCAL_SCOPE, run.id, "call-1", "search_documents", {"query": "different"})
        assert conflict.value.status_code == 409
        assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 1
        chunks, cursor = [], ""
        while True:
            page = repo.read(
                LOCAL_SCOPE, run.id, receipt_id=receipt["receipt_id"], cursor=cursor, max_chars=1001
            )
            chunks.append(page["content"])
            assert len(page["content"]) <= 1001
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert json.loads("".join(chunks)) == result
        by_call = repo.read(LOCAL_SCOPE, run.id, call_id="call-1")
        assert by_call["receipt_id"] == receipt["receipt_id"]
        with pytest.raises(DomainError, match="different arguments"):
            repo.save(
                LOCAL_SCOPE,
                run_id=run.id,
                call_id="call-1",
                tool_name="other",
                arguments={},
                result={},
            )
        db.rollback()
        previous_checkpoint = dict(db.get(AgentRun, run.id).checkpoint)
        pending = save(repo, run.id, "rolled-back")
        db.get(AgentRun, run.id).checkpoint = {"receipt_id": pending["receipt_id"]}
        db.rollback()
        assert db.get(AgentToolReceipt, pending["receipt_id"]) is None
        assert db.get(AgentRun, run.id).checkpoint == previous_checkpoint


def test_receipts_authorize_identity_session_and_exact_branch(material_database):
    with material_database.session_factory() as db:
        session, first = seed(db)
        repo = MaterialRepository(db)
        original = save(repo, first.id)
        finish(db, first.id)
        second = AgentRepository(db).create_run(LOCAL_SCOPE, session.id, "next", "next")
        own = save(repo, second.id)
        finish(db, second.id)
        sibling = AgentRepository(db).regenerate(LOCAL_SCOPE, second.assistant_message_id, "retry")
        assert set(repo.allowed_run_ids(LOCAL_SCOPE, sibling.id)) == {first.id, sibling.id}
        assert repo.read(LOCAL_SCOPE, sibling.id, receipt_id=original["receipt_id"])["ok"]
        with pytest.raises(DomainError) as exc:
            repo.read(LOCAL_SCOPE, sibling.id, receipt_id=own["receipt_id"])
        assert exc.value.status_code == 404
        # Stable IDs alone do not bypass user, tenant, or session ownership.
        for other in (
            Identity("other", "other", "other"),
            Identity("other", LOCAL_SCOPE.tenant_id, "other"),
        ):
            with pytest.raises(DomainError) as exc:
                repo.read(other, sibling.id, receipt_id=original["receipt_id"])
            assert exc.value.status_code == 404
        _, foreign_run = seed(db, "other-session")
        with pytest.raises(DomainError):
            repo.read(LOCAL_SCOPE, foreign_run.id, receipt_id=original["receipt_id"])
        with pytest.raises(DomainError):
            repo.read(LOCAL_SCOPE, sibling.id, call_id="call-1")
        rows = repo.list(LOCAL_SCOPE, sibling.id)["materials"]
        assert [item["receipt_id"] for item in rows] == [original["receipt_id"]]


def test_material_search_and_cursor_are_complete_and_bound(material_database):
    with material_database.session_factory() as db:
        _, run = seed(db)
        repo = MaterialRepository(db)
        for i in range(13):
            save(repo, run.id, f"call-{i}", result={"ok": True, "value": f"100% exact_{i}"})
        db.commit()
        rows, cursor = [], ""
        while True:
            page = repo.list(LOCAL_SCOPE, run.id, query="100%", limit=3, cursor=cursor)
            rows.extend(page["materials"])
            cursor = page["next_cursor"]
            if not cursor:
                break
        assert len(rows) == len({item["material_id"] for item in rows}) == 13
        assert repo.list(LOCAL_SCOPE, run.id, query="% exact_")["materials"]
        assert not repo.list(LOCAL_SCOPE, run.id, query="%oops")["materials"]
        page = repo.list(LOCAL_SCOPE, run.id, query="100%", limit=3)
        with pytest.raises(DomainError):
            repo.list(LOCAL_SCOPE, run.id, query="100", cursor=page["next_cursor"])
        first = repo.read(LOCAL_SCOPE, run.id, receipt_id=rows[0]["receipt_id"], max_chars=1)
        with pytest.raises(DomainError):
            repo.read(
                LOCAL_SCOPE, run.id, receipt_id=rows[1]["receipt_id"], cursor=first["next_cursor"]
            )


def test_private_material_never_copies_derivatives_or_indexes_them(material_database):
    with material_database.session_factory() as db:
        _, run = seed(db)
        repo = MaterialRepository(db)
        receipt = repo.save(
            LOCAL_SCOPE,
            run_id=run.id,
            call_id="private-read",
            tool_name="read_file",
            arguments={"file_id": "file-1", "cursor": "0"},
            private_result=True,
            result={
                "ok": True,
                "content": "private evidence SECRET",
                "pages": [{"images": [{"data_url": "data:image/png;base64,SECRET"}]}],
            },
            public_result={"ok": True, "file_id": "file-1", "content_chars": 23},
        )
        db.commit()
        item = db.get(AgentToolReceipt, receipt["receipt_id"])
        assert "SECRET" not in item.result_json
        assert "private evidence" not in item.result_json
        assert not receipt["preview"] and not receipt["complete"]
        assert not repo.list(LOCAL_SCOPE, run.id, query="SECRET")["materials"]
        result = repo.read(LOCAL_SCOPE, run.id, receipt_id=item.id)
        assert result["source_read_required"] and result["content"] == ""
        assert result["source_tool"] == "read_file"
        assert result["source_arguments"]["file_id"] == "file-1"
        assert repo.replay(
            LOCAL_SCOPE, run.id, "private-read", "read_file", {"file_id": "file-1", "cursor": "0"}
        ) == (False, None)


def test_material_limits_corruption_and_session_cascade(material_database, monkeypatch):
    with material_database.session_factory() as db:
        session, run = seed(db)
        repo = MaterialRepository(db)
        monkeypatch.setattr(materials, "RECEIPT_MAX_BYTES", 100)
        with pytest.raises(DomainError) as exc:
            save(repo, run.id, result={"text": "x" * 101})
        assert exc.value.code == "agent_material_result_too_large"
        monkeypatch.setattr(materials, "RUN_MATERIAL_MAX_BYTES", 50)
        first = save(repo, run.id)
        with pytest.raises(DomainError) as exc:
            save(repo, run.id, "second")
        assert exc.value.code == "agent_material_capacity_exceeded"
        db.commit()
        item = db.get(AgentToolReceipt, first["receipt_id"])
        item.result_json = '{"tampered":true}'
        db.commit()
        with pytest.raises(DomainError) as exc:
            repo.read(LOCAL_SCOPE, run.id, receipt_id=item.id)
        assert exc.value.code == "agent_material_corrupt"
        finish(db, run.id)
        AgentRepository(db).delete_session(LOCAL_SCOPE, session.id)
        assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 0


def test_material_tools_reauthorize_and_keep_public_parts_small(material_database):
    with material_database.session_factory() as db:
        session, run = seed(db)
        receipt = save(MaterialRepository(db), run.id, result={"value": "source truth" * 1000})
        db.commit()
    tools = {tool.name: tool for tool in build_material_tools(material_database.session_factory)}
    context = ToolExecutionContext(
        tenant_id=LOCAL_SCOPE.tenant_id,
        owner_membership_id=LOCAL_SCOPE.membership_id,
        session_id=session.id,
        run_id=run.id,
    )
    tool = tools["read_tool_result"]
    result = asyncio.run(tool.handler({"receipt_id": receipt["receipt_id"]}, context))
    assert result["ok"] and "source truth" in result["content"]
    projection = tool.project_result(result)
    assert "source truth" not in json.dumps(projection)
    assert projection["content_chars"] == 12000 and tool.private_result
    for name, arguments in (
        ("list_materials", {}),
        ("search_materials", {"query": "truth"}),
        ("read_material", {"material_id": receipt["material_id"]}),
    ):
        assert asyncio.run(tools[name].handler(arguments, context))["ok"]
    context.owner_membership_id = "foreign"
    assert not asyncio.run(tool.handler({"receipt_id": receipt["receipt_id"]}, context))["ok"]


def test_receipts_report_source_completeness_and_reject_invalid_json(material_database):
    with material_database.session_factory() as db:
        _, run = seed(db)
        repo = MaterialRepository(db)
        for call_id, tool_name, result in (
            ("page", "read_url", {"content": "partial", "source_truncated": True}),
            ("cursor", "list_records", {"items": [], "next_cursor": "next"}),
            (
                "search",
                "web_search",
                {"results": [{"url": "https://example.com", "content": "snippet"}]},
            ),
        ):
            reference = repo.save(
                LOCAL_SCOPE,
                run_id=run.id,
                call_id=call_id,
                tool_name=tool_name,
                arguments={},
                result=result,
            )
            assert reference["complete"] and reference["source_truncated"]
        for result in ({"not_json": float("nan")}, {"invalid_utf8": "\ud800"}, {"bytes": b"raw"}):
            with pytest.raises(DomainError) as exc:
                save(repo, run.id, "invalid-json", result=result)
            assert exc.value.code == "agent_material_invalid_result"
        db.commit()


def test_concurrent_receipt_commit_serializes_on_run(material_database):
    if material_database.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL row locks required")
    with material_database.session_factory() as db:
        _, run = seed(db)

    def execute(value):
        with material_database.session_factory() as db:
            result = save(MaterialRepository(db), run.id, result={"value": value})
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, range(4)))
    assert all(item == results[0] for item in results)
    with material_database.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentToolReceipt)) == 1
