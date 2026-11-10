"""模型配置管理端点（超管）：model_registry 增删改查。"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import EnabledIn, ModelIn
from backend.broker.publish import publish_config_refresh
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.agent.model_dao import ModelDao
from backend.middleware.auth import get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope
from backend.server.managers.model_manager import ModelManager

router = APIRouter(prefix="/models", tags=["admin"])


async def _refresh_factory() -> None:
    await ModelManager().reload()
    await publish_config_refresh("llm_factory")


def _serialize(row: dict) -> dict:
    # api_key 脱敏返回，避免明文泄露；原值由更新接口在请求上下文里回填，不依赖前端回传
    masked = None if row["api_key"] in (None, "") else "***"
    return {
        "id": row["id"],
        "model_type": row["model_type"],
        "name": row["name"],
        "provider": row["provider"],
        "base_url": row["base_url"],
        "api_key": masked,
        "endpoint_path": row["endpoint_path"],
        "temperature": row["temperature"],
        "timeout_s": row["timeout_s"],
        "max_retries": row["max_retries"],
        "enabled": row["enabled"],
        "sort_order": row["sort_order"],
        "description": row["description"],
        "updated_at": row["updated_at"],
    }


@router.get("", summary="模型列表（分页）")
async def list_models(
    model_type: Optional[str] = Query(None, description="按 model_type 过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _: object = Depends(require_scope(Scope.MODEL_PAGE)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
) -> Any:
    """模型列表分页查询（可按 model_type 过滤）。

    请求：query { model_type?, page, page_size }
    权限：model:page
    返回：items(api_key 已脱敏) / total / page / page_size
    """
    rows, total = await ModelDao.list_models(model_type, page=page, page_size=page_size)
    return success(
        {
            "items": [_serialize(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@router.get("/{model_id}", summary="模型详情")
async def get_model(
    model_id: int,
    _: object = Depends(require_scope(Scope.MODEL_VIEW)),
    __: object = Depends(get_current_user),
):  # noqa: B008
    """模型详情（api_key 已脱敏）。

    请求：path { model_id }
    权限：model:view
    返回：模型视图
    """
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    return success(_serialize(row))


@router.post("", summary="新增模型")
async def create_model(
    body: ModelIn,
    _: object = Depends(require_scope(Scope.MODEL_ADD)),
    __: object = Depends(get_current_user),
):  # noqa: B008
    """新增模型并刷新 LLM 工厂。

    请求：body { model_type, name, provider, base_url, api_key?, endpoint_path?, ... }
    权限：model:add
    返回：{ id }
    """
    new_id = await ModelDao.create(
        model_type=body.model_type,
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        api_key=body.api_key,
        endpoint_path=body.endpoint_path,
        temperature=body.temperature,
        timeout_s=body.timeout_s,
        max_retries=body.max_retries,
        enabled=body.enabled,
        sort_order=body.sort_order,
        description=body.description,
    )
    await _refresh_factory()
    return success({"id": new_id})


@router.put("/{model_id}", summary="更新模型")
async def update_model(
    model_id: int,
    body: ModelIn,
    _: object = Depends(require_scope(Scope.MODEL_UPDATE)),
    __: object = Depends(get_current_user),  # noqa: B008
):
    """更新模型（api_key 留空则保留原值）并刷新 LLM 工厂。

    请求：path { model_id }, body { model_type, name, provider, ... }
    权限：model:update
    返回：{ id }
    """
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    # api_key 未传则保留原值（脱敏不回传，避免误清空）
    api_key = body.api_key if body.api_key is not None else row["api_key"]
    await ModelDao.update(
        model_id,
        model_type=body.model_type,
        name=body.name,
        provider=body.provider,
        base_url=body.base_url,
        api_key=api_key,
        endpoint_path=body.endpoint_path,
        temperature=body.temperature,
        timeout_s=body.timeout_s,
        max_retries=body.max_retries,
        enabled=body.enabled,
        sort_order=body.sort_order,
        description=body.description,
    )
    await _refresh_factory()
    return success({"id": model_id})


@router.delete("/{model_id}", summary="删除模型")
async def delete_model(
    model_id: int,
    _: object = Depends(require_scope(Scope.MODEL_DELETE)),
    __: object = Depends(get_current_user),
):  # noqa: B008
    """删除模型并刷新 LLM 工厂。

    请求：path { model_id }
    权限：model:delete
    返回：{ id }
    """
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    await ModelDao.delete(model_id)
    await _refresh_factory()
    return success({"id": model_id})


@router.patch("/{model_id}/status", summary="状态变更（启停）")
async def set_status(
    model_id: int,
    body: EnabledIn,
    _: object = Depends(require_scope(Scope.MODEL_STATUS)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    """启停模型并刷新 LLM 工厂。

    请求：path { model_id }, body { enabled: bool }
    权限：model:status
    返回：{ id, enabled }
    """
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    await ModelDao.set_enabled(model_id, body.enabled)
    await _refresh_factory()
    return success({"id": model_id, "enabled": body.enabled})
