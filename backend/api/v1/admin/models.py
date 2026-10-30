"""模型配置管理端点（超管）：model_registry 增删改查。

挂在 /api/v1/admin/models 下，鉴权由装配处统一挂 require_super_admin()。
模型配置是平台级全局资源（不分租户），由超管在 /models 界面维护；
运行时 llm_factory 按 model_type 取 active 记录驱动四类模型。
"""
from __future__ import annotations

from typing import Optional

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.api.v1.admin.schemas import EnabledIn, ModelIn
from backend.common.response import success
from backend.observability.exception import BizException, ErrCode
from backend.data.dao.agent.model_dao import ModelDao
from backend.middleware.auth import get_current_user
from backend.security.rbac import Scope
from backend.security.security import require_scope

router = APIRouter(prefix="/models", tags=["admin"])


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
):
    rows = await ModelDao.list_models(model_type)
    total = len(rows)
    start = (page - 1) * page_size
    paged = rows[start : start + page_size]
    return success({"items": [_serialize(r) for r in paged], "total": total, "page": page, "page_size": page_size})


@router.get("/{model_id}", summary="模型详情")
async def get_model(model_id: int, _: object = Depends(require_scope(Scope.MODEL_VIEW)), __: object = Depends(get_current_user)):  # noqa: B008
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    return success(_serialize(row))


@router.post("", summary="新增模型")
async def create_model(body: ModelIn, _: object = Depends(require_scope(Scope.MODEL_ADD)), __: object = Depends(get_current_user)):  # noqa: B008
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
    return success({"id": new_id})


@router.put("/{model_id}", summary="更新模型")
async def update_model(
    model_id: int, body: ModelIn, _: object = Depends(require_scope(Scope.MODEL_UPDATE)), __: object = Depends(get_current_user)  # noqa: B008
):
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
    return success({"id": model_id})


@router.delete("/{model_id}", summary="删除模型")
async def delete_model(model_id: int, _: object = Depends(require_scope(Scope.MODEL_DELETE)), __: object = Depends(get_current_user)):  # noqa: B008
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    await ModelDao.delete(model_id)
    return success({"id": model_id})


@router.patch("/{model_id}/status", summary="状态变更（启停）")
async def set_status(
    model_id: int,
    body: EnabledIn,
    _: object = Depends(require_scope(Scope.MODEL_STATUS)),  # noqa: B008
    __: object = Depends(get_current_user),  # noqa: B008
):
    row = await ModelDao.get(model_id)
    if row is None:
        raise BizException(ErrCode.NOT_FOUND, f"模型不存在: {model_id}")
    await ModelDao.set_enabled(model_id, body.enabled)
    return success({"id": model_id, "enabled": body.enabled})
