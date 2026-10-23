"""
prompts_cache - 提示词缓存（先 Redis 再 Nacos，对齐 RAG-Ultra）

读取链路：1) Redis（进程外共享，启动预热写入）；2) Nacos 配置中心（PROMPT 组，命名空间 agent-platform）。
Nacos 不可达/缺失时，调用方应回退到内置模板。Redis 不可用时自动降级直连 Nacos，不阻断业务。
"""
from __future__ import annotations

import json
from typing import Optional

from backend.app_state import app_state
from backend.common.logger import logger
from backend.config import config as app_config
from backend.core.config_center.groups import ConfigGroup
from backend.core.config_center.nacos_config import ConfigCenterError, get_config_center_client

PROMPT_TTL_S = 3600


def _cache_key(data_id: str) -> str:
    return f"agent:prompt:{data_id}"


def get_prompt(data_id: str, group: str = ConfigGroup.PROMPT.value) -> Optional[str]:
    """取提示词内容：先 Redis，未命中再回源 Nacos；回源成功后回填 Redis（带 TTL）。"""
    r = app_state.redis
    if r is not None:
        try:
            cached = r.get(_cache_key(data_id))
            if cached:
                return cached if isinstance(cached, str) else cached.decode("utf-8")
        except Exception as e:
            logger.warning(f"提示词缓存：Redis 读取失败，回退 Nacos: {e}")

    try:
        content = get_config_center_client().get_config(data_id, group)
    except ConfigCenterError as e:
        logger.warning(f"提示词缓存：Nacos 读取失败 data_id={data_id}: {e}")
        content = None

    if content is not None and r is not None:
        try:
            r.set(_cache_key(data_id), content, ex=PROMPT_TTL_S)
        except Exception as e:
            logger.warning(f"提示词缓存：Redis 回填失败 data_id={data_id}: {e}")
    return content


def get_prompt_json(data_id: str, group: str = ConfigGroup.PROMPT.value) -> Optional[dict]:
    """提示词为 JSON 时解析；非 JSON（纯文本模板）返回 None。"""
    content = get_prompt(data_id, group)
    if content is None:
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None


def warmup_prompts(group: str = ConfigGroup.PROMPT.value) -> int:
    """启动预热：把某 group 下全部配置拉取并写入 Redis（带 TTL）。返回预热条数。"""
    r = app_state.redis
    if r is None:
        logger.warning("提示词预热：Redis 不可用，跳过（运行时将直连 Nacos）")
        return 0
    try:
        items = (get_config_center_client().list_configs(group=group, page_size=200)
                 .get("pageItems") or [])
    except ConfigCenterError as e:
        logger.warning(f"提示词预热：Nacos 列举失败: {e}")
        return 0
    n = 0
    for it in items:
        did = it.get("dataId")
        if not did:
            continue
        try:
            content = get_config_center_client().get_config(did, group)
            if content is None:
                continue
            r.set(_cache_key(did), content, ex=PROMPT_TTL_S)
            n += 1
        except Exception as e:
            logger.warning(f"提示词预热：单条失败 data_id={did}: {e}")
    logger.info(f"提示词预热完成：group={group} 共 {n} 条")
    return n


def refresh_prompt(data_id: str, group: str = ConfigGroup.PROMPT.value) -> None:
    """配置变更后主动刷新该提示词缓存（新增/修改写入带 TTL，删除则清除）。"""
    r = app_state.redis
    if r is None:
        return
    try:
        content = get_config_center_client().get_config(data_id, group)
        if content is None:
            r.delete(_cache_key(data_id))
        else:
            r.set(_cache_key(data_id), content, ex=PROMPT_TTL_S)
    except Exception as e:
        logger.warning(f"提示词刷新失败 data_id={data_id}: {e}")
