"""上传后自动解析（qa.parse 入队）单测：不连 MinIO / DB / broker。"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from backend.api.v1.tenant.agent import files as files_api


def _row(**overrides):
    row = {
        "id": 9,
        "tenant_id": 7,
        "uploader_user_id": 1,
        "original_name": "LLM基础知识.pdf",
        "file_name": "uuid_v1_upload.pdf",
        "object_key": "files/t7/202611/1/uuid_v1.pdf",
        "bucket": "agent-platform",
        "file_size": 123,
        "content_type": "application/pdf",
        "file_ext": ".pdf",
        "file_version": 1,
        "version_count": 1,
        "checksum": "abc",
        "remark": None,
        "parse_status": "pending",
        "create_at": datetime(2026, 11, 5, 20, 0, 0),
        "updated_at": datetime(2026, 11, 5, 20, 0, 0),
    }
    row.update(overrides)
    return row


def _user():
    return SimpleNamespace(user_id=1, tenant_id=7, is_super_admin=False)


@pytest.mark.asyncio
async def test_enqueue_parse_sets_parsing_and_passes_file_name(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_status(ids, status, *, tenant_id=None):
        calls.append(("status", status, tuple(ids), tenant_id))
        return 1

    async def fake_enqueue(task_type, *, tenant_id, user_id, data, **kwargs):
        calls.append(("enqueue", task_type.value, tenant_id, user_id, data))
        return "key-1"

    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(fake_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)

    key = await files_api._enqueue_parse(_row(), _user())

    assert key == "key-1"
    assert ("status", "parsing", (9,), 7) in calls
    enqueue_call = next(c for c in calls if c[0] == "enqueue")
    assert enqueue_call[1] == "qa.parse"
    assert enqueue_call[4]["file_id"] == 9
    assert enqueue_call[4]["object_key"] == "files/t7/202611/1/uuid_v1.pdf"
    # 原始文件名必须透传，供 Milvus 的 file_name / source_location 使用
    assert enqueue_call[4]["file_name"] == "LLM基础知识.pdf"


@pytest.mark.asyncio
async def test_enqueue_parse_rolls_back_to_pending_on_failure(monkeypatch) -> None:
    statuses: list[str] = []

    async def fake_status(ids, status, *, tenant_id=None):
        statuses.append(status)
        return 1

    async def fake_enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(fake_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)

    assert await files_api._enqueue_parse(_row(), _user()) is None
    assert statuses == ["parsing", "pending"]


@pytest.mark.asyncio
async def test_upload_triggers_auto_parse(monkeypatch) -> None:
    enqueued: list[str] = []

    async def fake_save(**kwargs):
        return {"row": _row()}

    async def fake_status(ids, status, *, tenant_id=None):
        return 1

    async def fake_enqueue(task_type, **kwargs):
        enqueued.append(task_type.value)
        return "key-1"

    monkeypatch.setattr(files_api.FileDao, "save_new_version", staticmethod(fake_save))
    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(fake_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(
        files_api, "config", SimpleNamespace(qa=SimpleNamespace(auto_parse=True, max_upload_mb=200))
    )

    upload = UploadFile(filename="LLM基础知识.pdf", file=BytesIO(b"%PDF-1.4 fake"))
    view = await files_api._process_one_upload(upload, _user(), None)

    assert view["parse_queued"] is True
    assert enqueued == ["qa.parse"]


@pytest.mark.asyncio
async def test_enqueue_parse_survives_status_error(monkeypatch) -> None:
    """状态更新异常不能让「已上传成功」的文件被报成失败。"""

    async def boom_status(ids, status, *, tenant_id=None):
        raise RuntimeError("column parse_status does not exist")

    async def fake_enqueue(task_type, **kwargs):
        return "key-1"

    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(boom_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)

    assert await files_api._enqueue_parse(_row(), _user()) == "key-1"


@pytest.mark.asyncio
async def test_upload_succeeds_when_parse_enqueue_fails(monkeypatch) -> None:
    async def fake_save(**kwargs):
        return {"row": _row()}

    async def boom_status(ids, status, *, tenant_id=None):
        raise RuntimeError("db down")

    async def none_enqueue(task_type, **kwargs):
        return None

    monkeypatch.setattr(files_api.FileDao, "save_new_version", staticmethod(fake_save))
    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(boom_status))
    monkeypatch.setattr(files_api, "enqueue_task", none_enqueue)
    monkeypatch.setattr(
        files_api, "config", SimpleNamespace(qa=SimpleNamespace(auto_parse=True, max_upload_mb=200))
    )

    upload = UploadFile(filename="a.pdf", file=BytesIO(b"%PDF-1.4 fake"))
    view = await files_api._process_one_upload(upload, _user(), None)

    assert view["parse_queued"] is False
    assert view["id"] == 9


@pytest.mark.asyncio
async def test_manual_parse_rolls_back_failed_ids(monkeypatch) -> None:
    status_calls: list[tuple] = []
    enqueued: list[int] = []

    async def fake_many(ids):
        return [
            {"id": 1, "tenant_id": 7, "object_key": "k1", "bucket": "b", "file_ext": ".pdf",
             "original_name": "a.pdf", "file_name": "a_v1.pdf"},
            {"id": 2, "tenant_id": 7, "object_key": "k2", "bucket": "b", "file_ext": ".md",
             "original_name": "b.md", "file_name": "b_v1.md"},
        ]

    async def fake_status(ids, status, *, tenant_id=None):
        status_calls.append((tuple(ids), status, tenant_id))
        return len(ids)

    async def fake_enqueue(task_type, *, data, **kwargs):
        enqueued.append(data["file_id"])
        return None if data["file_id"] == 2 else "key-1"

    monkeypatch.setattr(files_api.FileDao, "get_many", staticmethod(fake_many))
    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(fake_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)

    resp = await files_api.parse_files(
        files_api.ParseRequest(file_ids=[1, 2]), current=_user(), _=None
    )

    assert resp.data == {"queued": 1, "failed": [2]}
    assert enqueued == [1, 2]
    # 先全量置 parsing，再只把入队失败的 2 回退 pending
    assert ((1, 2), "parsing", 7) in status_calls
    assert ((2,), "pending", 7) in status_calls


@pytest.mark.asyncio
async def test_upload_skips_parse_when_disabled(monkeypatch) -> None:
    enqueued: list[str] = []

    async def fake_save(**kwargs):
        return {"row": _row()}

    async def fake_status(ids, status, *, tenant_id=None):
        return 1

    async def fake_enqueue(task_type, **kwargs):
        enqueued.append(task_type.value)
        return "key-1"

    monkeypatch.setattr(files_api.FileDao, "save_new_version", staticmethod(fake_save))
    monkeypatch.setattr(files_api.FileDao, "set_parse_status", staticmethod(fake_status))
    monkeypatch.setattr(files_api, "enqueue_task", fake_enqueue)
    monkeypatch.setattr(
        files_api, "config", SimpleNamespace(qa=SimpleNamespace(auto_parse=False, max_upload_mb=200))
    )

    upload = UploadFile(filename="a.pdf", file=BytesIO(b"%PDF-1.4 fake"))
    view = await files_api._process_one_upload(upload, _user(), None)

    assert view["parse_queued"] is False
    assert enqueued == []
