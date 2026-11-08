"""RAG 自研模块：文档解析入库（写侧）与混合检索+精排（读侧）共用同一 Milvus 集合。

- loaders / splitters：MinIO 字节 → **父子片两阶段切分**（全内存、不落盘）
  - 父片（1200 字）不建向量，仅作命中后回填给 LLM 的上下文；
  - 子片（300 字）才有 dense+sparse 向量，参与混合召回；
  - 每个子片带 parent_id / parent_content，额外元数据收口到 extra。
- indexing：qa.parse 消息的解析入库 pipeline，只写子片，写回 agent_file.parse_status
- retrieval：qa Agent retrieve_node 的唯一检索入口；召回子片后按 parent_id 分组，
  在父片原文里用 <mark> 高亮命中的子片（small-to-big）
- ranked：全流程共用的数据结构（Chunk 含 parent_content / highlighted_content）

实现参考 thy-edu-agent/backend/core 的解析与精排策略、RAG-Ultra 的父子片范式，
落地时按本项目架构改造：MinIO 字节输入、LLMFactory 复用已预热模型、
DocumentMilvusStore 集合、config.qa 配置项。
"""
from backend.rag.ranked import Chunk, LoadedPage, TextChunk

__all__ = ["Chunk", "LoadedPage", "TextChunk"]
