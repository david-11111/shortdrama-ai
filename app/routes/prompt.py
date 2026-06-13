from fastapi import APIRouter, Depends, HTTPException

from app.middleware.auth import get_current_user
from app.services.prompt.engine import get_library_filters, retrieve_prompt_matches

router = APIRouter(prefix="/prompt", tags=["prompt"])


@router.get("/library-filters")
async def library_filters(current_user: dict = Depends(get_current_user)):
    return get_library_filters()


@router.post("/retrieve")
async def retrieve(body: dict, current_user: dict = Depends(get_current_user)):
    query = body.get("query", "")
    if not query:
        return {"matches": [], "total": 0}

    filter_mode = body.get("filter_mode", "")
    filter_value = body.get("filter_value", "")

    library_ids = None
    if filter_mode and filter_value:
        from app.services.prompt.engine import resolve_filtered_library_ids
        library_ids = resolve_filtered_library_ids(filter_mode, filter_value)

    result = retrieve_prompt_matches(
        query,
        stage=body.get("stage", "script"),
        top_k=body.get("top_k"),
        global_context=body.get("style_hint", ""),
        local_context=body.get("context_hint", ""),
        library_ids=library_ids,
    )
    return result


@router.post("/refine")
async def refine_prompt_endpoint(body: dict, current_user: dict = Depends(get_current_user)):
    """提示词精炼：中文优化 + 英文翻译。"""
    raw = body.get("prompt", "").strip()
    context = body.get("context", "")
    if not raw:
        raise HTTPException(400, "prompt is required")

    from app.services.doubao import generate_text
    from app.services.key_pool import key_pool

    key_name, api_key = key_pool.acquire("doubao")
    try:
        user_text = f"[背景] {context}\n[画面描述] {raw}" if context else raw

        refine_system = (
            "你是专业的短剧视频提示词优化师。"
            "将用户输入的画面描述优化为更具体、更有画面感的中文描述。"
            "只输出优化后的描述，不要解释。"
        )
        try:
            refined_result = generate_text(api_key, {"system_prompt": refine_system, "prompt": user_text, "max_tokens": 300})
            refined_cn = refined_result["text"].strip().strip('"').strip("'")
        except Exception as exc:
            raise HTTPException(500, f"refine failed: {exc}")

        translate_system = (
            "You are a Seedance prompt engineer. "
            "Translate the Chinese video description into a structured English prompt. "
            "Structure: subject → appearance → action → camera → lighting → style. "
            "Under 120 words. One paragraph. End with 'Negative:' line."
        )
        try:
            en_result = generate_text(api_key, {"system_prompt": translate_system, "prompt": refined_cn, "max_tokens": 200})
            refined_en = en_result["text"].strip()
        except Exception:
            refined_en = raw

        return {"original": raw, "refined_cn": refined_cn, "refined_en": refined_en}
    finally:
        key_pool.release(key_name)


@router.get("/index")
async def prompt_index(current_user: dict = Depends(get_current_user)):
    """提示词快速索引（话题/场景/问题分类）。"""
    try:
        from app.services.prompt.engine import get_quick_index
        return get_quick_index()
    except Exception as exc:
        raise HTTPException(500, f"prompt index failed: {exc}")


@router.get("/context-vocab")
async def context_vocab(current_user: dict = Depends(get_current_user)):
    """上下文词汇表。"""
    try:
        from app.services.prompt.engine import get_context_vocab
        return get_context_vocab()
    except Exception as exc:
        raise HTTPException(500, f"context vocab failed: {exc}")


@router.post("/rebuild-index")
async def rebuild_index(current_user: dict = Depends(get_current_user)):
    """重建关键词索引和向量索引。"""
    try:
        from app.services.prompt.engine import rebuild_index as rebuild_kw
        from app.services.vector_store import rebuild_index as rebuild_vec
        rebuild_kw()
        count = rebuild_vec()
    except Exception as exc:
        raise HTTPException(500, f"rebuild failed: {exc}")
    return {"status": "ok", "message": f"索引已重建，向量库 {count} 条"}


@router.get("/templates")
async def list_prompt_templates(current_user: dict = Depends(get_current_user)):
    """提示词模板列表。"""
    try:
        from app.services.prompt.template import list_templates
        return {"templates": list_templates()}
    except Exception as exc:
        raise HTTPException(500, f"templates failed: {exc}")
