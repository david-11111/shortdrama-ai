"""
Video Provider Registry — 统一路由层。

用法（类似 Claude API 选择模型）:

    from app.services.video_provider import generate_video

    # 换 model 名就换 provider：
    result = generate_video(model="joy-echo", prompt="...", duration=30, ...)
    result = generate_video(model="seedance",  prompt="...", duration=5,  ...)
    result = generate_video(model="wanxiang",  prompt="...", duration=10, ...)

加新 provider 只需在文件底部 register() 一行，不用改 task 路由。
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.error_policy import classify_exception
from app.services.key_pool import key_pool
from app.services.provider_prompt_adapter import adapt_provider_payload

logger = logging.getLogger(__name__)

# ── 统一返回值 ────────────────────────────────────────────────────────


@dataclass
class VideoResult:
    """所有 provider 返回的统一结构。"""
    url: str
    duration: int
    width: int
    height: int
    provider: str
    task_id: str
    billing: dict | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# ── Provider 注册数据 ────────────────────────────────────────────────


@dataclass(frozen=True)
class ProviderConfig:
    name: str                     # 标准名（如 "joy-echo", "seedance"）
    aliases: list[str] = field(default_factory=list)   # 别名（如 ["joy_echo", "joyai-echo"]）
    handler: str = ""             # "module_path:function_name"
    text_only: bool = False       # 纯文本输入（不传参考图）
    needs_key: bool = False       # 是否走 key_pool 获取 API Key
    pool_service: str = ""        # key_pool 服务名（空 = 用 name）
    adapter: str = ""             # provider_prompt_adapter 里的函数名（空 = 不处理）
    default_operation: str = "video_gen"  # 计费操作类型


# ── 注册表 ────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, ProviderConfig] = {}  # name/alias -> config
_CANONICAL: dict[str, str] = {}             # alias -> canonical name


def register(config: ProviderConfig) -> None:
    """注册一个 provider。标准名和所有别名都不能重复。"""
    cname = config.name
    if cname in _PROVIDERS:
        raise ValueError(f"Provider '{cname}' is already registered")
    _PROVIDERS[cname] = config
    _CANONICAL[cname] = cname
    for alias in config.aliases:
        if alias in _CANONICAL:
            raise ValueError(
                f"Alias '{alias}' already registered to provider '{_CANONICAL[alias]}'"
            )
        _CANONICAL[alias] = cname


def get_config(name: str) -> ProviderConfig | None:
    """查 provider 配置。支持标准名和别名。"""
    key = name.lower().strip()
    canonical = _CANONICAL.get(key)
    if canonical is None:
        return None
    return _PROVIDERS.get(canonical)


def resolve(name: str) -> tuple[str, ProviderConfig]:
    """解析 provider 名 → (标准名, 配置)。查不到时抛 ValueError。"""
    cfg = get_config(name)
    if cfg is None:
        raise ValueError(f"Unknown video provider: {name}")
    return cfg.name, cfg


def is_text_only(name: str) -> bool:
    cfg = get_config(name)
    return cfg.text_only if cfg else False


def list_providers() -> list[str]:
    return sorted(_PROVIDERS.keys())


def list_all_names() -> list[str]:
    return sorted(_CANONICAL.keys())


# ── 核心调用函数 ──────────────────────────────────────────────────────


def _resolve_handler(handler_spec: str) -> Any:
    """按 "module_path:function_name" 解析出可调用对象。"""
    if ":" not in handler_spec:
        raise ValueError(f"Invalid handler spec '{handler_spec}' — expected 'module:function'")
    module_path, func_name = handler_spec.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def _normalize_video_result(
    raw: dict[str, Any],
    provider: str,
    task_id: str,
) -> VideoResult:
    """把各 provider 不同的返回值归一化为 VideoResult。"""
    return VideoResult(
        url=raw.get("url") or raw.get("video_url") or raw.get("final_url") or "",
        duration=int(raw.get("duration", raw.get("duration_sec", 0)) or 0),
        width=int(raw.get("width", raw.get("w", 0)) or 0),
        height=int(raw.get("height", raw.get("h", 0)) or 0),
        provider=provider,
        task_id=task_id,
        billing=raw.get("billing_usage") or raw.get("usage"),
        extra={k: v for k, v in raw.items()
               if k not in ("url", "video_url", "final_url", "duration", "duration_sec",
                            "width", "height", "w", "h", "billing_usage", "usage", "task_id")},
    )


def _dispatch_payload(payload: dict[str, Any], *, canonical: str, cfg: ProviderConfig) -> dict[str, Any]:
    """内部：执行单个 provider 调用，返回原始 dict 结果。"""
    handler = _resolve_handler(cfg.handler)
    task_id = payload.get("task_id", "")

    key_name: str | None = None
    try:
        if cfg.needs_key:
            pool_svc = cfg.pool_service or canonical
            key_name, api_key = key_pool.acquire(pool_svc)
            return handler(payload, api_key=api_key, task_id=task_id, user_id=payload.get("user_id", ""))
        else:
            return handler(payload, api_key=None, task_id=task_id, user_id=payload.get("user_id", ""))
    except Exception:
        if key_name:
            error_decision = classify_exception(__import__("sys").exc_info()[1])
            if error_decision.report_to_key_pool:
                key_pool.report_error(key_name)
        raise
    finally:
        if key_name:
            key_pool.release(key_name)


def generate_video(
    model: str,
    prompt: str,
    *,
    image_url: str | None = None,
    duration: int = 5,
    ref_images: list[str] | None = None,
    task_id: str = "",
    user_id: str = "",
    transaction_id: str | None = None,
    **kwargs: Any,
) -> VideoResult:
    """统一视频生成入口。换 `model` 参数即可切换 provider。

    用法:
        from app.services.video_provider import generate_video

        result = generate_video(model="joy-echo", prompt="...", duration=30)
        result = generate_video(model="seedance",  prompt="...", duration=5)
        result = generate_video(model="wanxiang",  prompt="...", image_url="...")

    参数:
        model: provider 名（"joy-echo", "seedance", "ltx2.3" 等）
        prompt: 文本提示词
        image_url: 首帧图 URL（text_only provider 忽略）
        duration: 视频时长（秒）
        ref_images: 参考图列表（text_only provider 忽略）
        task_id: Celery task ID
        user_id: 用户 ID
        transaction_id: 计费事务 ID
        **kwargs: 透传给底层 service 的额外参数

    返回:
        VideoResult（统一结构）
    """
    canonical, cfg = resolve(model)

    # 构建 payload
    payload: dict[str, Any] = {
        "prompt": prompt,
        "duration": duration,
        "provider": canonical,
        "task_id": task_id,
        "user_id": user_id,
        **kwargs,
    }

    if not cfg.text_only:
        if image_url:
            payload["image_url"] = image_url
        if ref_images:
            payload["ref_images"] = ref_images
    else:
        payload.pop("image_url", None)
        payload.pop("ref_images", None)

    # adapter（prompt 适配）
    payload = adapt_provider_payload(payload, task_type="video_gen", provider=canonical)

    # 执行
    raw = _dispatch_payload(payload, canonical=canonical, cfg=cfg)

    # 归一化
    return _normalize_video_result(raw, canonical, task_id)


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    """从完整 payload dict 调度（video_tasks.py 内部使用）。

    payload 需含:
        provider: str  — provider 名
        prompt: str    — 文本提示词（可从 shot_row 解析）
        task_id: str
        user_id: str
        image_url: str | None（可选）
        ref_images: list[str] | None（可选）
        以及其他透传给底层 service 的字段
    """
    provider = str(payload.get("provider", "joy-echo")).lower()
    canonical, cfg = resolve(provider)
    payload["provider"] = canonical

    # 对 text_only provider 清理参考图
    if cfg.text_only:
        payload.pop("image_url", None)
        payload.pop("ref_images", None)

    # adapter（video_tasks.py 已调过 adapt_provider_payload，但这里幂等地再调一次无副作用）
    payload = adapt_provider_payload(payload, task_type="video_gen", provider=canonical)

    raw = _dispatch_payload(payload, canonical=canonical, cfg=cfg)
    return _normalize_video_result(raw, canonical, payload.get("task_id", "")).__dict__


# ── 内置 provider 注册 ────────────────────────────────────────────────

register(ProviderConfig(
    name="joy-echo",
    aliases=["joy_echo", "joyai-echo", "joyai_echo"],
    handler="app.services.joy_echo_official:generate_joy_echo_official_video",
    text_only=True,
    needs_key=False,
    adapter="adapt_joy_echo_payload",
    default_operation="video_gen_15s",
))

register(ProviderConfig(
    name="ltx2.3",
    aliases=["ltx"],
    handler="app.services.comfy_video:generate_comfy_video",
    text_only=True,
    needs_key=False,
    adapter="adapt_ltx_payload",
    default_operation="video_gen_15s",
))

register(ProviderConfig(
    name="wan2.1",
    aliases=["wan", "wan2_1"],
    handler="app.services.comfy_video:generate_comfy_video",
    text_only=False,
    needs_key=False,
    adapter="adapt_ltx_payload",
    default_operation="video_gen",
))

register(ProviderConfig(
    name="comfyui",
    aliases=[],
    handler="app.services.comfy_video:generate_comfy_video",
    text_only=False,
    needs_key=False,
    adapter="",
    default_operation="video_gen",
))

register(ProviderConfig(
    name="seedance",
    aliases=[],
    handler="app.services.seedance:generate_video",
    text_only=False,
    needs_key=True,
    pool_service="seedance",
    adapter="adapt_seedance_payload",
    default_operation="video_gen",
))

register(ProviderConfig(
    name="kling",
    aliases=[],
    handler="app.services.kling:generate_video",
    text_only=False,
    needs_key=True,
    pool_service="kling",
    adapter="",
    default_operation="video_gen",
))

# ── 未来：通义万相（百炼） ──────────────────────────────────────────────
# register(ProviderConfig(
#     name="wanxiang",
#     aliases=["bailian", "tongyi"],
#     handler="app.services.wanxiang:generate_video",
#     text_only=False,
#     needs_key=True,
#     pool_service="wanxiang",
#     adapter="adapt_wanxiang_payload",
#     default_operation="video_gen",
# ))
