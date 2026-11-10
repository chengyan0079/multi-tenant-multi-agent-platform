"""提示词缓存：先 Redis 后 Nacos（PROMPT 组），Redis 不可用降级直连，均 async。"""

from __future__ import annotations

import json
from typing import Optional

from backend.app_state import app_state
from backend.common.config_center.groups import ConfigGroup
from backend.common.config_center import ConfigCenterError, get_config_center_client
from backend.common.logger import logger

PROMPT_TTL_S = 3600


def _cache_key(data_id: str) -> str:
    return f"agent:prompt:{data_id}"


async def get_prompt(data_id: str, group: str = ConfigGroup.PROMPT.value) -> Optional[str]:
    """取提示词内容：先 Redis，未命中再回源 Nacos；回源成功后回填 Redis（带 TTL）。"""
    r = app_state.redis
    if r is not None:
        try:
            cached = await r.get(_cache_key(data_id))
            if cached:
                return cached if isinstance(cached, str) else cached.decode("utf-8")
        except Exception as e:
            logger.exception(f"提示词缓存：Redis 读取失败，回退 Nacos: {e}")

    try:
        content = await get_config_center_client().get_config(data_id, group)
    except ConfigCenterError as e:
        logger.exception(f"提示词缓存：Nacos 读取失败 data_id={data_id}: {e}")
        content = None

    if content is not None and r is not None:
        try:
            await r.set(_cache_key(data_id), content, ex=PROMPT_TTL_S)
        except Exception as e:
            logger.exception(f"提示词缓存：Redis 回填失败 data_id={data_id}: {e}")
    return content


async def get_prompt_json(data_id: str, group: str = ConfigGroup.PROMPT.value) -> Optional[dict]:
    """提示词为 JSON 时解析；非 JSON（纯文本模板）返回 None。"""
    content = await get_prompt(data_id, group)
    if content is None:
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return None


async def warmup_prompts(group: str = ConfigGroup.PROMPT.value) -> int:
    """启动预热：把某 group 下全部配置拉取并写入 Redis（带 TTL）。返回预热条数。"""
    r = app_state.redis
    if r is None:
        logger.warning("提示词预热：Redis 不可用，跳过（运行时将直连 Nacos）")
        return 0
    try:
        # 注意：await 优先级低于属性访问 '.'，必须先 await 存到变量，再对结果取 .get，
        # 否则会解析成 await(list_configs(...).get(...))，即在协程上调用 .get 而报
        # "coroutine object has no attribute 'get'" 并触发 never awaited 警告。
        resp = await get_config_center_client().list_configs(group=group, page_size=200)
        items = resp.get("pageItems") or []
    except ConfigCenterError as e:
        logger.exception(f"提示词预热：Nacos 列举失败: {e}")
        return 0
    n = 0
    for it in items:
        did = it.get("dataId")
        if not did:
            continue
        try:
            content = await get_config_center_client().get_config(did, group)
            if content is None:
                continue
            await r.set(_cache_key(did), content, ex=PROMPT_TTL_S)
            n += 1
        except Exception as e:
            logger.exception(f"提示词预热：单条失败 data_id={did}: {e}")
    logger.info(f"提示词预热完成：group={group} 共 {n} 条")
    return n


async def refresh_prompt(data_id: str, group: str = ConfigGroup.PROMPT.value) -> None:
    """配置变更后主动刷新该提示词缓存（新增/修改写入带 TTL，删除则清除）。"""
    r = app_state.redis
    if r is None:
        return
    try:
        content = await get_config_center_client().get_config(data_id, group)
        if content is None:
            await r.delete(_cache_key(data_id))
        else:
            await r.set(_cache_key(data_id), content, ex=PROMPT_TTL_S)
    except Exception as e:
        logger.exception(f"提示词刷新失败 data_id={data_id}: {e}")
