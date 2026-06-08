"""
分层检索引擎 — DM → DWS → ODS 层层递进检索
"""
import time
import chromadb

from config import RETRIEVAL_LAYERS, RETRIEVAL_TOP_K, RETRIEVAL_THRESHOLD
from models import (
    BusinessConcept, TableMatch, RetrievalResult, ConceptExtractionResult,
)
from retrieval.matcher import match_layer, match_layer_hybrid
from retrieval.ranker import rank_matches


def search(
    concepts: list[BusinessConcept],
    collection: chromadb.Collection,
    layers: list[str] | None = None,
    top_k: int = RETRIEVAL_TOP_K,
    threshold: float = RETRIEVAL_THRESHOLD,
    db_conn=None,
    visible_business_lines: list[str] | None = None,
) -> RetrievalResult:
    """分层递进检索

    对每个业务概念，按 layers 顺序检索（默认 DM→DWS→ODS）
    上一层命中则跳过下层；全部未命中则标记为 unmatched

    Args:
        concepts: 业务概念列表
        collection: ChromaDB Collection
        layers: 检索层级顺序，默认 ["DM", "DWS", "ODS"]
        top_k: 每层语义检索返回数量
        threshold: 语义匹配相似度阈值

    Returns:
        RetrievalResult 包含所有概念的匹配结果 + 检索日志
    """
    if layers is None:
        layers = list(RETRIEVAL_LAYERS)

    start_time = time.time()
    all_matches: list[TableMatch] = []
    unmatched: list[str] = []
    log: list[str] = []

    # 按层统计
    layer_stats: dict[str, dict] = {layer: {"hit": 0, "miss": 0} for layer in layers}
    total_exact = 0
    total_semantic = 0

    log.append("=" * 56)
    log.append(f"DataPilot 分层检索引擎 — 共 {len(concepts)} 个概念，{len(layers)} 层检索")
    log.append(f"检索顺序: {' → '.join(layers)}")
    log.append(f"语义阈值: {threshold}  |  Top-K: {top_k}")
    log.append("=" * 56)

    for i, concept in enumerate(concepts, 1):
        found = False
        log.append(f"\n[{i}/{len(concepts)}] 检索概念: [{concept.type}] {concept.concept}")
        if concept.candidates:
            log.append(f"    同义词: {', '.join(concept.candidates)}")
        if concept.qualifier:
            log.append(f"    限定条件: {concept.qualifier}")

        t0 = time.time()
        for layer in layers:
            layer_matches = match_layer_hybrid(
                concept, collection, layer,
                db_conn=db_conn,
                top_k=top_k, threshold=threshold,
            )

            if layer_matches:
                best = layer_matches[0]
                match_type = "精确匹配" if best.score >= 0.99 else "语义匹配"

                log.append(f"    [{layer}层] ✓ 命中 — {match_type}")
                log.append(f"             表: {best.table_name} ({best.table_comment})")
                log.append(f"             得分: {best.score}  |  字段数: {len(best.columns)}")

                if match_type == "精确匹配":
                    total_exact += 1
                else:
                    total_semantic += 1

                layer_stats[layer]["hit"] += 1
                all_matches.append(best)
                found = True
                break
            else:
                log.append(f"    [{layer}层] ✗ 未命中，降级")
                layer_stats[layer]["miss"] += 1

        elapsed = (time.time() - t0) * 1000
        if not found:
            log.append(f"    [结果] 三层均未命中 → 标记为待确认")
            unmatched.append(concept.concept)
            all_matches.append(TableMatch(
                concept=concept.concept,
                matched=False,
                message=f"DM/DWS/ODS 三层检索均未找到 '{concept.concept}' 的匹配，请确认数据源或补充数据字典",
            ))
        else:
            log.append(f"    耗时: {elapsed:.0f}ms")

    # 汇总
    total_time = time.time() - start_time
    matched = len(all_matches) - len(unmatched)
    log.append(f"\n{'='*56}")
    log.append(f"检索汇总")
    log.append(f"{'='*56}")
    log.append(f"概念总数: {len(concepts)}  |  命中: {matched}  |  未命中: {len(unmatched)}")
    log.append(f"命中率: {matched/len(concepts)*100:.1f}%" if concepts else "无概念")
    log.append(f"精确匹配: {total_exact}  |  语义匹配: {total_semantic}")
    for layer in layers:
        s = layer_stats[layer]
        log.append(f"  {layer}层: 命中 {s['hit']}, 降级 {s['miss']}")
    log.append(f"总耗时: {total_time:.1f}s")

    # 去重 + 排序
    final_matches = rank_matches(all_matches)

    # ── 业务条线过滤 ──
    if visible_business_lines:
        from auth.database import get_session
        from auth.models import table_business_lines as tbl, BusinessLine

        with get_session() as session:
            rows = session.query(tbl.c.table_name).join(
                BusinessLine, tbl.c.business_line_id == BusinessLine.id
            ).filter(
                BusinessLine.code.in_(visible_business_lines)
            ).all()
            allowed_tables = {r.table_name for r in rows}

        for m in final_matches:
            if m.matched and m.table_name and m.table_name not in allowed_tables:
                m.matched = False
                m.message = f"无权限访问表 {m.table_name}（业务条线限制）"

    return RetrievalResult(
        matches=final_matches,
        unmatched_concepts=unmatched,
        retrieval_log=log,
    )


def search_from_extraction(
    extraction: ConceptExtractionResult,
    collection: chromadb.Collection,
    **kwargs,
) -> RetrievalResult:
    """快捷函数：从概念提取结果直接检索"""
    return search(extraction.concepts, collection, **kwargs)
