"""瀵兼紨瀵硅瘽缂栨帓寮曟搸 鈥?浠庡師鐗堝畬鏁磋縼绉汇€?
瀹屾暣娴佺▼锛歝ompile brief 鈫?瀵兼紨搴撴绱?鈫?鏋勫缓 system prompt 鈫?Doubao 鐢熸垚 鈫?瑙ｆ瀽 CONTINUITY/SHOTS 鈫?閫愰暅澶存鼎鑹?鈫?鏋勫缓 shot_rows + execution_plan銆?"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Callable

from app.config import get_settings
from app.services.context_budget import (
    ContextBudget,
    PromptMessageBudget,
    build_prompt_messages,
    limit_text as budget_limit_text,
    trim_messages,
)
from app.services.director_preflight import analyze_shot_risk
from app.services.key_pool import key_pool

logger = logging.getLogger(__name__)

MAX_ENGINE_SYSTEM_CHARS = 32000
MAX_ENGINE_USER_CHARS = 48000
MAX_ENGINE_TOTAL_CHARS = 96000
MAX_ENGINE_HISTORY_MESSAGES = 20
MAX_ENGINE_HISTORY_MESSAGE_CHARS = 6000
ENGINE_HISTORY_BUDGET = ContextBudget(
    max_messages=MAX_ENGINE_HISTORY_MESSAGES,
    max_message_chars=MAX_ENGINE_HISTORY_MESSAGE_CHARS,
    max_total_chars=MAX_ENGINE_HISTORY_MESSAGES * MAX_ENGINE_HISTORY_MESSAGE_CHARS,
)
ENGINE_PROMPT_BUDGET = PromptMessageBudget(
    max_system_chars=MAX_ENGINE_SYSTEM_CHARS,
    max_user_chars=MAX_ENGINE_USER_CHARS,
    max_total_chars=MAX_ENGINE_TOTAL_CHARS,
    history_budget=ENGINE_HISTORY_BUDGET,
)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """浣犳槸涓€鍚嶇煭鍓у婕旓紝璐熻矗鎶婄敤鎴锋兂娉曡浆鍖栦负鍙洿鎺ユ墽琛岀殑鍒嗛暅鏂规銆備綘鐨勫缓璁繀椤诲儚鐪熸鐨勫婕斿湪鐗囧満璇磋瘽锛氬叿浣撱€佸彲钀藉湴銆佹湁灞傛銆?
## 瀵兼紨寤鸿缁撴瀯锛堝繀椤绘寜姝ゅ洓灞傝緭鍑猴級

### 浜虹墿寤鸿
蹇呴』瑕嗙洊浠ヤ笅缁村害锛岀己淇℃伅鏃跺仛瀵兼紨鍖栧悎鐞嗚ˉ鍏紝浣嗘瘡椤瑰繀椤诲叿浣撳彲瑙嗗寲锛屼笉鍫嗙┖璇嶏細
- 骞撮緞鎰?/ 姘旇川鍩鸿皟
- 鑴稿瀷 / 楠ㄧ浉 / 浜斿畼鐗圭偣
- 鐪肩 / 寰〃鎯?/ 绁炴€?- 鍙戝瀷 / 濡嗛€?/ 鏈嶈
- 浣撴€?/ 鍔ㄤ綔鐘舵€?- 鎬ф牸澶栨樉 / 褰撳墠鎯呯华鐘舵€?
### 鍦烘櫙寤鸿
鐜銆佸厜绾裤€佹椂闂存劅銆佺┖闂村眰娆★紝鑷冲皯 2 鍙ュ叿浣撴弿杩般€?
### 琛ㄦ紨寤鸿
瑙掕壊鍦ㄨ繖涓暅澶撮噷鐨勬牳蹇冨姩浣溿€佹儏缁妭鎷嶃€佷笌瀵规墜鎴栭亾鍏风殑鍏崇郴銆?
### 闀滃ご璇█
鏅埆銆佹満浣嶃€佽繍鍔ㄦ柟寮忋€佽妭濂忔劅锛岃娓呮涓轰粈涔堣繖鏍锋媿銆?
---

## 鎵ц缁撴瀯杈撳嚭锛堝繀椤诲湪鍒嗛暅鍓嶈緭鍑猴級

濡傛灉杈撳嚭鍒嗛暅锛屽繀椤诲厛鐢ㄤ互涓嬫牸寮忚緭鍑烘墽琛岀粨鏋勫潡锛?<!--CONTINUITY{
  "character_continuity": "浜虹墿缁熶竴璁惧畾锛堜竴鍙ヨ瘽閿佸畾锛?,
  "scene_continuity": "鍦烘櫙缁熶竴璁惧畾锛堜竴鍙ヨ瘽閿佸畾锛?,
  "prop_continuity": "鍏抽敭閬撳叿缁熶竴璁惧畾",
  "character_master": "涓昏鏍稿績瑙嗚閿氱偣",
  "scene_master": "鍦烘櫙鏍稿績瑙嗚閿氱偣",
  "performance_beats": "鍏ㄧ墖鎯呯华鑺傛媿搴忓垪",
  "camera_plan": "鍏ㄧ墖闀滃ご璇█鍩鸿皟",
  "hook_line": "鍓?绉掗挬瀛愯璁?,
  "product_focus": "浜у搧/鍗栫偣鍑虹幇鏃舵満锛堝箍鍛婄被蹇呭～锛?
}CONTINUITY-->

---

## 鍒嗛暅杈撳嚭瑙勫垯

- 濡傛灉閫傚悎鎷嗗垎闀滃ご锛岃緭鍑?2-4 涓暅澶达紝姣忎釜闀滃ご蹇呴』鏈夋槑鏄惧樊寮傘€?- 姣忎釜闀滃ご 2-3 鍙ワ紝鑱氱劍涓讳綋銆佸姩浣溿€侀暅澶磋繍鍔ㄣ€佸厜褰便€?- 杈撳嚭闀滃ご鍒楄〃鏃讹紝蹇呴』浣跨敤浠ヤ笅鏍煎紡鍖呰９锛?<!--SHOTS[{"index":1,"prompt":"闀滃ご鎻愮ず璇?..","ref_prompt":"鍙傝€冨浘鎻愮ず璇?..","duration":5}]SHOTS-->

## 鐢熸垚绾︽潫

- 闀滃ご鎻忚堪蹇呴』鏄彲瑙嗗寲鍐呭锛岀姝㈢┖娉涙蹇点€?- 鍗曢暅澶存椂闀垮缓璁?5-15 绉掋€?- 鎻愮ず璇嶈閫傚悎 Seedance 鐩存帴鐢熸垚瑙嗛銆?
---

## 鍙弬鑰冪殑鎻愮ず璇嶅簱锛堟寜缁村害鍒嗗眰锛?
{library_block}"""


CHAT_SHOT_POLISH_SYSTEM_PROMPT = """浣犳槸闀滃ご鎻愮ず璇嶆鼎鑹插姪鎵嬶紝涓撻棬鏈嶅姟浜庣煭鍓у婕旈摼璺€?
浠诲姟锛氭妸鍘熷闀滃ご鎯虫硶鏀瑰啓鎴愭洿閫傚悎瑙嗛妯″瀷鐢熸垚鐨勬弿杩般€?
瑕佹眰锛?- 淇濈暀鍘熸剰锛屼笉鏀瑰彉闀滃ご鐨勬牳蹇冨姩浣滃拰鎯呯华
- 寮哄寲锛氫富浣撳璨岀壒寰併€佸姩浣滅粏鑺傘€侀暅澶磋繍鍔ㄣ€佸厜褰辫川鎰熴€佺幆澧冨眰娆?- 濡傛灉鍘熷鎻忚堪鏈変汉鐗╋紝蹇呴』淇濈暀骞舵繁鍖栦汉鐗╃殑鐪肩/绁炴€?浣撴€佺粏鑺?- 杈撳嚭 1-2 鍙ュ畬鏁翠腑鏂囨彁绀鸿瘝锛屼笉瑕佸姞瑙ｉ噴"""


# ---------------------------------------------------------------------------
# 鍏抽敭璇嶅父閲?# ---------------------------------------------------------------------------

_AD_KEYWORDS = [
    "广告", "品牌", "产品", "卖点", "转化", "下单", "购买", "价格",
    "优惠", "折扣", "活动", "限时", "新品", "上架", "发布",
    "tvc", "宣传", "商业", "品牌片", "种草", "黄金", "珠宝",
]
_DRAMA_KEYWORDS = [
    "短剧", "剧情", "女主", "男主", "反转", "复仇", "虐恋",
    "霸总", "玛丽苏", "宫斗", "古装", "仙侠", "都市", "情侣",
    "冲突", "对手", "反派", "拉扯", "情绪爆发",
]
_JOKE_KEYWORDS = [
    "段子", "搞笑", "笑点", "反转", "幽默", "日常", "喜剧",
]

_PACK_HINT_RULES: list[tuple[list[str], str]] = [
    (["回头", "转身", "背对", "背影"], "back_turn"),
    (["微笑", "笑容", "浅笑"], "smile"),
    (["全身", "全景", "站立", "站姿"], "full_body"),
    (["侧脸", "侧面", "侧身"], "side_face"),
    (["正脸", "正面", "直视", "面对镜头"], "front_face"),
    (["特写", "面部特写", "眼神特写"], "close_up"),
    (["半身", "上半身", "腰部以上"], "half_body"),
]

_CHARACTER_KEYWORDS = [
    "骨相", "脸型", "五官", "眼神", "神态", "发型", "妆容", "服装", "体态",
    "气质", "年龄", "高颧骨", "下颌线", "薄唇", "低马尾", "西装",
]
_ACTION_KEYWORDS = [
    "动作", "站", "坐", "走", "转身", "回头", "抬头", "低头", "拿", "推",
    "推门", "凝视", "侧身", "迈步",
]
_LIGHTING_KEYWORDS = [
    "光", "光线", "光影", "逆光", "侧光", "冷白光", "暖光", "柔光", "阴影",
]
_CAMERA_KEYWORDS = [
    "镜头", "景别", "特写", "近景", "中景", "远景", "全景", "推", "拉",
    "摇", "手持", "俯拍", "仰拍", "运镜", "缓推", "快切",
]

_LAYER_KEYWORDS = {
    "人物": ["人物", "角色", "眼神", "神态", "骨相", "体态", "气质"],
    "场景": ["场景", "空间", "环境", "光影", "光线", "色调", "氛围"],
    "表演": ["表演", "情绪", "动作", "对白", "冲突", "情感", "克制"],
    "镜头": ["镜头", "运镜", "景别", "机位", "转场", "节奏", "分镜"],
}

_STRATEGY_BLOCKS = {
    "广告": (
        "【题材：广告】【主目标：转化】\n导演策略：\n"
        "- 前 3 秒必须有钩子\n- 产品出现时机明确\n"
        "- 卖点可视化\n- 收口有行动号召\n- 镜头 2-4 个"
    ),
    "短剧": (
        "【题材：短剧】【主目标：情绪】\n导演策略：\n"
        "- 人物骨相/眼神/体态要具体\n- 情绪节拍密度要高\n"
        "- 戏剧张力优先\n- 特写和近景更高频\n- 收口有情绪落点"
    ),
    "段子": (
        "【题材：段子】【主目标：笑点】\n导演策略：\n"
        "- 铺垫->反转->收口\n- 镜头 1-3 个\n- 笑点可视化\n- 反转要突然"
    ),
    "混合": "【题材：混合】导演策略：按用户主线信号偏向输出。",
}

_BEAT_LABELS = ("起", "承", "转", "合")
_ACTION_PEAK_KW = ["转身", "回头", "推门", "起身", "奔跑", "挥手", "抬手"]
_EMOTION_TURN_KW = ["爆发", "崩溃", "哭", "笑", "愤怒", "委屈", "释怀", "震惊"]
_CUT_POINT_KW = ["切", "转场", "快切", "跳切", "叠化", "淡出", "特写", "全景"]

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _compact_library_hint(text: str, limit: int = 120) -> str:
    clean = " ".join(str(text or "").replace("\n", " ").split())
    if not clean:
        return ""
    parts = [p.strip(" 。；;") for p in re.split(r"[。；;\n]", clean) if p.strip()]
    compact = "。".join(parts[:2]) if len(parts) >= 2 else (parts[0] if parts else clean)
    return compact[:limit].rstrip(" 。；;")


def _detect_content_profile(text: str) -> dict:
    t = str(text or "").lower()
    ad_hits = sum(1 for kw in _AD_KEYWORDS if kw in t)
    drama_hits = sum(1 for kw in _DRAMA_KEYWORDS if kw in t)
    joke_hits = sum(1 for kw in _JOKE_KEYWORDS if kw in t)
    scores = {"ad": ad_hits, "drama": drama_hits, "joke": joke_hits}
    top = max(scores, key=lambda k: scores[k])
    if scores[top] == 0:
        return {"content_type": "通用", "primary_goal": "通用"}
    second = sorted(scores, key=lambda k: scores[k], reverse=True)[1]
    if scores[second] >= scores[top] * 0.7:
        return {"content_type": "混合", "primary_goal": "通用"}
    mapping = {"ad": ("广告", "转化"), "drama": ("短剧", "情绪"), "joke": ("段子", "笑点")}
    ct, pg = mapping[top]
    return {"content_type": ct, "primary_goal": pg}


def _build_director_strategy_block(profile: dict) -> str:
    return _STRATEGY_BLOCKS.get(profile.get("content_type", "閫氱敤"), "")


def _normalize_shot_item(raw: dict, idx: int) -> dict:
    return {
        "index": int(raw.get("index", idx + 1)),
        "prompt": str(raw.get("prompt", "")).strip(),
        "ref_prompt": str(raw.get("ref_prompt", raw.get("ref_image_description", ""))).strip(),
        "duration": int(raw.get("duration", 5)),
        "matched_libraries": list(raw.get("matched_libraries", [])),
    }


def _infer_pack_hint(prompt: str, ref_prompt: str = "") -> list[str]:
    blob = (prompt + " " + ref_prompt).lower()
    return [hint for keywords, hint in _PACK_HINT_RULES if any(kw in blob for kw in keywords)]


def _extract_execution_constraints(prompt: str, ref_prompt: str = "") -> dict:
    blob = prompt + " " + ref_prompt

    def _pick(keywords: list[str]) -> str:
        return "。".join(kw for kw in keywords if kw in blob)[:80]

    return {
        "must_character": _pick(_CHARACTER_KEYWORDS),
        "must_action": _pick(_ACTION_KEYWORDS),
        "must_lighting": _pick(_LIGHTING_KEYWORDS),
        "must_camera": _pick(_CAMERA_KEYWORDS),
    }


def _recommend_locks(continuity: dict, shots: list) -> list[str]:
    locks: list[str] = []
    if continuity.get("character_continuity") or continuity.get("character_master"):
        locks.append("character")
    if continuity.get("scene_continuity") or continuity.get("scene_master"):
        locks.append("scene")
    if continuity.get("prop_continuity"):
        locks.append("prop")
    if continuity.get("camera_plan"):
        locks.append("camera")
    if continuity.get("performance_beats") and len(shots) >= 2:
        locks.append("emotion")
    return locks

def _build_keyframe_beats(shots: list, continuity: dict) -> list[dict]:
    if not shots:
        return []
    n = len(shots)
    offsets: list[float] = []
    t = 0.0
    for s in shots:
        offsets.append(t)
        t += float(s.get("duration", 5))

    def _reason(prompt: str, ref: str) -> str:
        blob = (prompt + " " + ref).lower()
        if any(kw in blob for kw in _ACTION_PEAK_KW):
            return "动作峰值"
        if any(kw in blob for kw in _EMOTION_TURN_KW):
            return "情绪转折"
        if any(kw in blob for kw in _CUT_POINT_KW):
            return "镜头切点"
        return "叙事节拍"

    if n == 1:
        indices = [0, 0, 0, 0]
    elif n == 2:
        indices = [0, 0, 1, 1]
    elif n == 3:
        indices = [0, 1, 2, 2]
    else:
        indices = [0, max(1, n // 4), max(1, int(n * 0.65)), n - 1]

    beats: list[dict] = []
    seen: set[int] = set()
    for label, idx in zip(_BEAT_LABELS, indices):
        if idx in seen:
            idx = min(idx + 1, n - 1)
        seen.add(idx)
        shot = shots[idx]
        beats.append({
            "beat": label,
            "shot_index": shot.get("index", idx + 1),
            "time_hint": round(offsets[idx], 1),
            "reason": _reason(shot.get("prompt", ""), shot.get("ref_prompt", "")),
        })
    return beats


def _fix_json_str(raw: str) -> str:
    raw = re.sub(r",\s*\]", "]", raw)
    raw = re.sub(r",\s*\}", "}", raw)
    return raw


def _parse_shots_with_fallback(reply: str) -> tuple[list, str, str]:
    shots: list = []
    parse_mode = "none"

    m = re.search(r"<!--SHOTS(\[[\s\S]*?\])SHOTS-->", reply, re.S)
    if m:
        reply = (reply[:m.start()] + reply[m.end():]).strip()
        try:
            parsed = json.loads(_fix_json_str(m.group(1).strip()))
            _list = parsed if isinstance(parsed, list) else [parsed]
            shots = [_normalize_shot_item(s, i) for i, s in enumerate(_list) if isinstance(s, dict)]
            if shots:
                parse_mode = "primary"
        except Exception:
            pass

    if "<!--SHOTS" in reply:
        reply = re.sub(r"<!--SHOTS.*?(?:SHOTS-->|$)", "", reply, flags=re.S).strip()
    if shots:
        return shots, parse_mode, reply

    cb = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", reply, re.S)
    if cb:
        try:
            parsed = json.loads(_fix_json_str(cb.group(1)))
            if isinstance(parsed, list) and parsed:
                shots = [_normalize_shot_item(s, i) for i, s in enumerate(parsed) if isinstance(s, dict)]
                if shots:
                    parse_mode = "fallback_codeblock"
        except Exception:
            pass
    if shots:
        return shots, parse_mode, reply

    la = re.search(r"(\[[\s\S]{20,}\])", reply, re.S)
    if la:
        try:
            parsed = json.loads(_fix_json_str(la.group(1)))
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                shots = [_normalize_shot_item(s, i) for i, s in enumerate(parsed) if isinstance(s, dict)]
                if shots:
                    parse_mode = "fallback_loose"
        except Exception:
            pass
    if shots:
        return shots, parse_mode, reply

    paras = [p.strip() for p in re.split(r"\n{2,}", reply) if p.strip() and len(p.strip()) > 20]
    if paras:
        shots = [
            {"index": i + 1, "prompt": p[:200], "ref_prompt": "", "duration": 5, "matched_libraries": []}
            for i, p in enumerate(paras[:3])
        ]
        parse_mode = "fallback_minimal"
    return shots, parse_mode, reply


def _classify_library_layer(name: str, tags: list) -> str:
    blob = name + " ".join(tags or [])
    for layer, keywords in _LAYER_KEYWORDS.items():
        if any(kw in blob for kw in keywords):
            return layer
    return "其他"


def _build_chat_library_block(matches: list[dict], max_items: int = 5, max_chars: int = 120) -> str:
    layered: dict[str, list[str]] = {"人物": [], "场景": [], "表演": [], "镜头": [], "其他": []}
    for match in matches[:max_items]:
        name = str(match.get("name", "")).strip()
        hint = _compact_library_hint(str(match.get("prompt_text", "")), limit=max_chars)
        if not hint:
            continue
        layer = _classify_library_layer(name, match.get("tags", []))
        entry = f"  - {name}: {hint}" if name else f"  - {hint}"
        layered[layer].append(entry)
    blocks: list[str] = []
    for layer in ("人物", "场景", "表演", "镜头", "其他"):
        items = layered[layer]
        if items:
            blocks.append(f"【{layer}层】\n" + "\n".join(items))
    return "\n\n".join(blocks)

def _call_doubao_for_engine(messages: list[dict], timeout: int = 90, max_tokens: int = 4096) -> str:
    """Call doubao.generate_text in SaaS format."""
    from app.services.doubao import generate_text

    system_parts = []
    user_parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "".join(item.get("text", "") if isinstance(item, dict) else str(item) for item in content)
        if role == "system":
            system_parts.append(content)
        else:
            user_parts.append(content)

    system_text = budget_limit_text("\n".join(system_parts), MAX_ENGINE_SYSTEM_CHARS)
    user_text = budget_limit_text("\n".join(user_parts), MAX_ENGINE_USER_CHARS)
    overflow = len(system_text) + len(user_text) - MAX_ENGINE_TOTAL_CHARS
    if overflow > 0:
        user_text = budget_limit_text(user_text, max(1000, len(user_text) - overflow))

    key_name, api_key = key_pool.acquire("doubao")
    try:
        result = generate_text(api_key, {
            "system_prompt": system_text,
            "prompt": user_text,
            "temperature": 0.8,
            "max_tokens": max_tokens,
        })
        return result.get("text", "")
    except Exception as exc:
        key_pool.report_error(key_name, str(exc))
        raise
    finally:
        key_pool.release(key_name)


def _limit_text(text: str, max_chars: int) -> str:
    return budget_limit_text(text, max_chars)


def _compact_history_for_prompt(history: list[dict]) -> list[dict]:
    return trim_messages(history, ENGINE_HISTORY_BUDGET)[0]


def _polish_chat_shot_prompt(raw_prompt: str, library_block: str, global_context: str = "", content_profile: dict | None = None) -> str:
    parts = ["【原始镜头】\n" + raw_prompt]
    if content_profile and content_profile.get("content_type", "通用") not in ("通用", ""):
        ct = content_profile["content_type"]
        pg = content_profile.get("primary_goal", "")
        hint = "题材：" + ct + (f"，主目标：{pg}" if pg and pg != "通用" else "")
        parts.append("銆愬婕旂瓥鐣ャ€慭n" + hint)
    if global_context:
        parts.append("銆愮敤鎴烽渶姹傘€慭n" + global_context)
    if library_block:
        parts.append("銆愬彲鍙傝€冩彁绀猴紙鎸夌淮搴﹀垎灞傦級銆慭n" + library_block)
    user_text = "\n\n".join(parts)
    try:
        polished = _call_doubao_for_engine([
            {"role": "system", "content": [{"type": "input_text", "text": CHAT_SHOT_POLISH_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
        ], timeout=8, max_tokens=512)
        polished = polished.strip().strip('"').strip("'")
        return polished or raw_prompt
    except Exception:
        return raw_prompt


# ---------------------------------------------------------------------------
# compile_director_brief / build_compiled_context (浠庡師鐗堣縼绉?
# ---------------------------------------------------------------------------

COMPILE_SYSTEM_PROMPT = """你是导演需求编译器。把用户的自然语言需求提炼为结构化 JSON。
只输出 JSON，不要 markdown。格式：
{
  "director_brief": "一句话总结导演意图",
  "content_type": "广告|短剧|段子|通用",
  "subject": "主体描述",
  "duration_hint": 30,
  "style_keywords": ["关键词1", "关键词2"],
  "must_include": ["必含元素"],
  "emotion_arc": "情绪曲线",
  "shot_count_hint": 4,
  "shot_requirements": ["镜头约束"],
  "character_continuity": "人物设定（如有）",
  "scene_continuity": "场景设定（如有）",
  "prop_continuity": "道具设定（如有）"
}"""


def compile_director_brief(user_message: str, history_context: str = "") -> dict:
    user_text = user_message
    if history_context:
        user_text = f"[对话上下文] {history_context}\n[当前需求] {user_message}"
    raw = _call_doubao_for_engine([
        {"role": "system", "content": [{"type": "input_text", "text": COMPILE_SYSTEM_PROMPT}]},
        {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
    ], timeout=15, max_tokens=1024)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"raw_compile": raw}


def build_compiled_context(brief: dict) -> str:
    if "raw_compile" in brief:
        return brief["raw_compile"]
    parts = []
    if brief.get("director_brief"):
        parts.append(f"导演简报：{brief['director_brief']}")
    if brief.get("content_type"):
        parts.append(f"题材：{brief['content_type']}")
    if brief.get("subject"):
        parts.append(f"主体：{brief['subject']}")
    if brief.get("duration_hint"):
        parts.append(f"时长：约 {brief['duration_hint']} 秒")
    if brief.get("style_keywords"):
        parts.append(f"风格：{'。'.join(brief['style_keywords'])}")
    if brief.get("must_include"):
        parts.append(f"必含：{'。'.join(brief['must_include'])}")
    if brief.get("emotion_arc"):
        parts.append(f"情绪线：{brief['emotion_arc']}")
    if brief.get("shot_count_hint"):
        parts.append(f"建议镜头数：{brief['shot_count_hint']}")
    return "\n".join(parts)

def _build_director_second_draft(
    user_message: str,
    first_draft: str,
    matched_names: list[str],
    content_profile: dict[str, Any],
    polish_block: str = "",
    retrieval_block: str = "",
) -> str:
    profile_name = str(content_profile.get("content_type") or "通用")
    profile_goal = str(content_profile.get("primary_goal") or "通用")
    library_hint = "。".join(matched_names[:8]) if matched_names else "暂无高置信命中词条"
    first = (first_draft or "").strip()
    if not first:
        first = user_message.strip()

    base = (
        "【导演二稿（结构强化）】\n"
        f"- 题材判定: {profile_name}\n"
        f"- 核心目标: {profile_goal}\n"
        f"- 命中词条: {library_hint}\n"
        "- 执行要求: 保持人物/场景连续性，镜头动作可拍，可直接拆分分镜。\n\n"
    )
    retrieval = ""
    if retrieval_block and retrieval_block.strip():
        retrieval = "【案例检索补充（用于增强，不可照抄）】\n" + retrieval_block.strip() + "\n\n"
    polish = (polish_block.strip() + "\n\n") if polish_block and polish_block.strip() else ""
    return base + retrieval + polish + "【二稿正文】\n" + first


def _build_director_score(
    matched_count: int,
    continuity: dict[str, Any],
    shot_rows: list[dict[str, Any]],
    content_profile: dict[str, Any],
) -> dict[str, Any]:
    continuity_keys = ("character_continuity", "scene_continuity", "prop_continuity")
    continuity_hits = sum(1 for k in continuity_keys if str(continuity.get(k, "")).strip())
    shot_count = len(shot_rows)
    prompt_rich = sum(1 for row in shot_rows if len(str(row.get("prompt", "")).strip()) >= 28)

    library_hit_quality = max(20, min(100, 34 + matched_count * 11))
    continuity_stability = max(25, min(100, 38 + continuity_hits * 18 + (10 if shot_count >= 2 else 0)))
    executability = max(20, min(100, 42 + shot_count * 9 + prompt_rich * 3))
    style_fit = 62 if str(content_profile.get("content_type", "閫氱敤")) != "閫氱敤" else 55
    style_fit = max(20, min(100, style_fit + (6 if matched_count >= 2 else 0)))

    total = int(round(
        library_hit_quality * 0.30
        + continuity_stability * 0.28
        + executability * 0.30
        + style_fit * 0.12,
    ))

    suggestions: list[str] = []
    if library_hit_quality < 60:
        suggestions.append("补充更具体的人物/场景关键词，提升导演库匹配精度。")
    if continuity_stability < 60:
        suggestions.append("明确人物、场景、道具三条连续性锚点，减少跨镜漂移。")
    if executability < 65:
        suggestions.append("镜头描述增加动作、机位、光线信息，确保可执行。")
    if style_fit < 60:
        suggestions.append("补充题材风格词（短剧/广告/剧情），统一整体语气。")
    if not suggestions:
        suggestions.append("当前匹配稳定，可直接进入参考图和视频生产。")

    return {
        "total": total,
        "items": {
            "library_hit_quality": library_hit_quality,
            "continuity_stability": continuity_stability,
            "executability": executability,
            "style_fit": style_fit,
        },
        "suggestions": suggestions,
    }


def _build_quality_gate(score: dict[str, Any], shot_count: int, output_options: dict[str, Any]) -> dict[str, Any]:
    items = score.get("items", {}) if isinstance(score, dict) else {}
    total = int(score.get("total", 0)) if isinstance(score, dict) else 0
    lib_score = int(items.get("library_hit_quality", 0))
    exe_score = int(items.get("executability", 0))

    allow_storyboard = shot_count > 0 and total >= 55
    allow_reference_images = shot_count > 0 and total >= 60 and lib_score >= 45
    allow_video_production = shot_count >= 2 and total >= 70 and exe_score >= 65
    # 浣撻獙涓€鑷存€э細瑙嗛閮藉彲鐢熶骇鏃讹紝鍙傝€冨浘涓嶅啀鍗曠嫭鎷︽埅
    if allow_video_production and shot_count > 0:
        allow_reference_images = True

    reasons: list[str] = []
    if output_options.get("need_storyboard", True) and not allow_storyboard:
        reasons.append("分镜质量未达阈值")
    if output_options.get("need_reference_images") and not allow_reference_images:
        reasons.append("参考图触发条件未满足")
    if output_options.get("need_video") and not allow_video_production:
        reasons.append("视频触发条件未满足")

    return {
        "allow_storyboard": allow_storyboard,
        "allow_reference_images": allow_reference_images,
        "allow_video_production": allow_video_production,
        "reason": "；".join(reasons) if reasons else "质量门通过",
    }


# ---------------------------------------------------------------------------
# 涓诲嚱鏁帮細run_director_chat
# ---------------------------------------------------------------------------

def run_director_chat(
    message: str,
    project_id: str,
    history: list[dict] | None = None,
    preset_key: str = "",
    shots_in: list | None = None,
    output_options: dict[str, Any] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict:
    """完整的导演对话编排流程。"""
    from app.services.director.presets import resolve_director_preset
    from app.services.director.creative_enhancer import (
        build_polish_block,
        enhance_user_input,
        evaluate_v1_draft,
    )
    from app.services.director.creative_retrieval import (
        build_case_retrieval_block,
        retrieve_case_context,
    )
    from app.services.prompt.engine import resolve_filtered_library_ids, retrieve_prompt_matches

    history = history or []
    output_options = output_options or {}
    need_advice = bool(output_options.get("need_advice", True))
    need_storyboard = bool(output_options.get("need_storyboard", True))
    # Default off for first round to keep interactive latency predictable.
    enable_shot_polish = bool(output_options.get("enable_shot_polish", False))

    def _emit(progress: int, text: str) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(max(0, min(100, int(progress))), str(text))
        except Exception:
            logger.debug("director progress callback failed", exc_info=True)

    # --- Stage A: compile ---
    _emit(18, "解析需求与上下文...")
    history = _compact_history_for_prompt(history)
    history_context = " | ".join(m.get("content", "")[:120] for m in history[-4:]) if history else ""
    _emit(22, "创作增强器补充结构与锚点...")
    enhancer_meta = enhance_user_input(message, history_context)
    working_message = str(enhancer_meta.get("enhanced_message", "") or message)
    try:
        brief = compile_director_brief(message, history_context)
        compiled_context = build_compiled_context(brief)
    except Exception:
        brief = {}
        compiled_context = ""

    continuity_from_brief: dict = {}
    for ck in ("character_continuity", "scene_continuity", "prop_continuity"):
        cv = brief.get(ck, "")
        if cv and str(cv).strip():
            continuity_from_brief[ck] = str(cv).strip()

    # --- Retrieval ---
    _emit(24, "检索导演词库与风格策略...")
    preset = resolve_director_preset(preset_key)
    library_ids = resolve_filtered_library_ids(preset["filter_mode"], preset["filter_value"])
    retrieval = retrieve_prompt_matches(
        working_message, stage="shot", top_k=8, global_context=working_message, library_ids=library_ids,
    )
    library_block = _build_chat_library_block(retrieval.get("matched", []), max_items=6, max_chars=120)
    content_profile = _detect_content_profile(working_message)
    strategy_block = _build_director_strategy_block(content_profile)
    _emit(26, "检索案例库补充语义上下文...")
    case_retrieval = retrieve_case_context(
        working_message,
        top_k=3,
        min_score=1.0,
        content_profile=content_profile,
    )
    case_block = build_case_retrieval_block(case_retrieval.get("matched", []), max_items=3)
    base_prompt = CHAT_SYSTEM_PROMPT.replace("{library_block}", library_block or "鏆傛棤鍖归厤鏉＄洰")
    system_prompt = (strategy_block + "\n\n" + base_prompt) if strategy_block else base_prompt
    if case_block:
        system_prompt += f"\n\n## 案例检索补充（仅作增强参考，不可照抄）\n{case_block}"
    if compiled_context:
        system_prompt += f"\n\n## 闇€姹傜紪璇戠粨鏋滐紙宸茬粨鏋勫寲鎻愮偧锛塡n{compiled_context}"
    if shots_in:
        system_prompt += "\n褰撳墠闀滃ご鍒楄〃锛歕n" + "\n".join(
            f"闀滃ご{s.get('index', i+1)}: {s.get('prompt', '')[:80]}"
            for i, s in enumerate(shots_in)
        )

    matched_names = [m["name"] for m in retrieval.get("matched", [])]

    # --- Stage B1: Doubao first draft ---
    _emit(36, "V1 初稿生成中（豆包）...")
    first_draft = _call_doubao_for_engine([
        {
            "role": "system",
            "content": [{
                "type": "input_text",
                "text": "你是短剧脚本初稿助手。请根据用户需求给出可执行初稿，包含人物、场景、动作和镜头语言。",
            }],
        },
        {"role": "user", "content": [{"type": "input_text", "text": working_message}]},
    ], timeout=45, max_tokens=1200)
    _emit(44, "V1 质量检测与可打磨点生成...")
    v1_eval = evaluate_v1_draft(first_draft, original_message=message)
    polish_block = build_polish_block(v1_eval)

    # --- Stage B2: Director second draft ---
    _emit(50, "V2 导演建议生成中...")
    second_draft = _build_director_second_draft(
        message,
        first_draft,
        matched_names,
        content_profile,
        polish_block=polish_block,
        retrieval_block=case_block,
    )

    # --- Stage B3: Doubao production draft ---
    _emit(64, "V3 生产稿生成中（豆包）...")
    final_user_prompt = f"{working_message}\n\n{second_draft}" if second_draft else working_message
    messages, prompt_budget_report = build_prompt_messages(
        system_prompt=system_prompt,
        history=history,
        final_user_prompt=final_user_prompt,
        budget=ENGINE_PROMPT_BUDGET,
    )
    reply = _call_doubao_for_engine(messages, timeout=75, max_tokens=2200)

    # --- Parse CONTINUITY ---
    _emit(74, "解析连续性设定...")
    continuity: dict = dict(continuity_from_brief)
    cont_match = re.search(r"<!--CONTINUITY(.*?)CONTINUITY-->", reply, re.S)
    if cont_match:
        try:
            reply_cont = json.loads(cont_match.group(1).strip())
            continuity.update({k: v for k, v in reply_cont.items() if v and str(v).strip()})
        except Exception:
            pass
        reply = (reply[:cont_match.start()] + reply[cont_match.end():]).strip()

    # --- Parse SHOTS ---
    _emit(80, "解析分镜结构...")
    if need_storyboard:
        shots, parse_mode, reply = _parse_shots_with_fallback(reply)
    else:
        shots, parse_mode = [], "disabled_by_option"
    action = "shots_updated" if shots else "chat_only"

    # --- Polish shots ---
    if shots and enable_shot_polish:
        _emit(86, f"润色分镜提示词（最多 {min(len(shots), 3)} 条）...")
        continuity_hint = ""
        if continuity:
            hint_parts = []
            if continuity.get("character_continuity"):
                hint_parts.append("人物：" + continuity["character_continuity"])
            if continuity.get("scene_continuity"):
                hint_parts.append("场景：" + continuity["scene_continuity"])
            continuity_hint = "；".join(hint_parts)

        # 鎺у埗鍗曟瀵兼紨瀵硅瘽鐨勬鼎鑹茶皟鐢ㄤ笂闄愶紝閬垮厤棣栬疆绛夊緟杩囬暱
        max_polish_shots = 3
        shot_lib_map: dict[int, tuple] = {}
        for i, shot in enumerate(shots):
            if i >= max_polish_shots:
                continue
            raw_prompt = shot.get("prompt", "")
            if raw_prompt:
                shot_retrieval = retrieve_prompt_matches(
                    raw_prompt, stage="shot", top_k=4,
                    global_context=message, library_ids=library_ids,
                )
                lib_text = _build_chat_library_block(shot_retrieval.get("matched", []), max_items=4, max_chars=120)
                shot["matched_libraries"] = [m["name"] for m in shot_retrieval.get("matched", [])]
                shot_lib_map[i] = (raw_prompt, lib_text)

        if shot_lib_map:
            def _polish_one(args):
                i, raw_p, lib_t = args
                ctx = (message + " [杩炵画鎬ц瀹歖 " + continuity_hint) if continuity_hint else message
                return i, _polish_chat_shot_prompt(raw_p, lib_t, global_context=ctx, content_profile=content_profile)

            tasks = [(i, rp, lt) for i, (rp, lt) in shot_lib_map.items()]
            pool = ThreadPoolExecutor(max_workers=min(len(tasks), 4))
            futs = {pool.submit(_polish_one, t): t[0] for t in tasks}
            pending = set(futs)
            try:
                done, pending = wait(pending, timeout=45)
                for fut in done:
                    try:
                        idx_shot, polished = fut.result()
                        shots[idx_shot]["prompt"] = polished
                    except Exception:
                        # Keep original prompt if per-shot polish fails.
                        pass
            finally:
                for fut in pending:
                    fut.cancel()
                pool.shutdown(wait=False, cancel_futures=True)

    # --- Build result ---
    _emit(92, "汇总评分与质量门控...")
    exec_keys = ("character_master", "scene_master", "performance_beats", "camera_plan", "hook_line", "product_focus")
    execution_plan = {k: continuity[k] for k in exec_keys if continuity.get(k)}

    cont_fields = {k: continuity[k] for k in ("character_continuity", "scene_continuity", "prop_continuity") if continuity.get(k)}
    exec_fields = {k: continuity[k] for k in exec_keys if continuity.get(k)}
    shot_rows = [
        {
            "shot_index": s.get("index", i + 1),
            "prompt": s.get("prompt", ""),
            "ref_prompt": s.get("ref_prompt", ""),
            "duration": s.get("duration", 5),
            "matched_libraries": s.get("matched_libraries", []),
            "continuity": cont_fields,
            "execution_plan": exec_fields,
            "status": "pending",
            "pack_hint": _infer_pack_hint(s.get("prompt", ""), s.get("ref_prompt", "")),
            **_extract_execution_constraints(s.get("prompt", ""), s.get("ref_prompt", "")),
        }
        for i, s in enumerate(shots)
    ]
    for row in shot_rows:
        row["director_preflight"] = analyze_shot_risk(row, project_goal=message)

    score = _build_director_score(
        matched_count=len(matched_names),
        continuity=continuity,
        shot_rows=shot_rows,
        content_profile=content_profile,
    )
    quality_gate = _build_quality_gate(score, len(shot_rows), output_options)
    process_trace = [
        {"stage": "v1_draft", "status": "done", "has_content": bool((first_draft or "").strip())},
        {"stage": "v1_evaluation", "status": "done", "score": int(v1_eval.get("total", 0)), "needs_polish": bool(v1_eval.get("needs_polish"))},
        {
            "stage": "retrieval_case_bank",
            "status": "done",
            "matched_count": len(case_retrieval.get("matched", [])),
        },
        {"stage": "v2_director_refine", "status": "done", "matched_count": len(matched_names)},
        {
            "stage": "v3_production",
            "status": "done",
            "parse_mode": parse_mode,
            "shot_count": len(shots),
            "prompt_budget": prompt_budget_report.as_dict(),
        },
    ]
    drafts = [
        {"version": "v1", "title": "V1 豆包初稿", "source": "doubao", "content": (first_draft or "").strip()},
        {"version": "v2", "title": "V2 导演建议稿", "source": "director", "content": (second_draft or "").strip()},
        {"version": "v3", "title": "V3 生产稿", "source": "doubao", "content": reply},
    ]
    if not need_advice:
        drafts = []

    _emit(94, "导演结果已生成，准备保存...")

    return {
        "reply": reply,
        "shots": shots,
        "shot_rows": shot_rows,
        "continuity": continuity,
        "execution_plan": execution_plan,
        "recommended_locks": _recommend_locks(continuity, shots),
        "recommended_keyframe_beats": _build_keyframe_beats(shots, continuity),
        "action": action,
        "matched_libraries": matched_names,
        "library_context": library_block,
        "preset_key": preset["preset_key"],
        "drafts": drafts,
        "score": score,
        "quality_gate": quality_gate,
        "process_trace": process_trace,
        "creative_enhancer": {
            "version": str(v1_eval.get("version", "creative_enhancer_v1")),
            "structure": enhancer_meta.get("structure", []),
            "anchors": enhancer_meta.get("anchors", {}),
            "v1_evaluation": v1_eval,
        },
        "creative_retrieval": {
            "version": str(case_retrieval.get("version", "case_bank_v1")),
            "matched_count": len(case_retrieval.get("matched", [])),
            "matched": [
                {
                    "id": m.get("id", ""),
                    "title": m.get("title", ""),
                    "score": m.get("score", 0),
                    "tags": m.get("tags", []),
                }
                for m in case_retrieval.get("matched", [])[:3]
            ],
            "context_block": case_block,
        },
    }

