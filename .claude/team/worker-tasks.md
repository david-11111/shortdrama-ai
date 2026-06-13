# WORKER 终端 — 导演编排逻辑完整迁移

## 严正声明

这是一次完整迁移，不是"先搭壳后面再补"。原版 600 行编排逻辑已经跑通了半年，现在 SaaS 里的 `director_chat_task` 是一个裸 Doubao 调用——没有导演库检索、没有提示词融合、没有结构化分镜输出、没有自动触发后续步骤。这是不可接受的。

**你的任务：把原版 `E:/shortdrama_ai/app/main.py:3438-4338` 的全部逻辑搬到 SaaS，一行不漏。**

---

## 迁移清单

### 第一步：新建 `app/services/director_chat_engine.py`

把以下函数从原版 `E:/shortdrama_ai/app/main.py` 完整复制过来，组成一个独立模块：

| 函数 | 原版行号 | 作用 |
|---|---|---|
| `CHAT_SYSTEM_PROMPT` | 3438-3496 | 导演系统提示词（含 {library_block} 占位） |
| `CHAT_SHOT_POLISH_SYSTEM_PROMPT` | 3499-3507 | 镜头润色系统提示词 |
| `_compact_library_hint` | 3510-3517 | 压缩库条目文本 |
| `_detect_content_profile` | 3544-3562 | 题材识别（广告/漫剧/段子） |
| `_STRATEGY_BLOCKS` + `_build_director_strategy_block` | 3565-3600 | 题材策略块 |
| `_normalize_shot_item` | 3603-3610 | 标准化 shot 结构 |
| `_PACK_HINT_RULES` + `_infer_pack_hint` | 3612-3630 | 推断视角/姿态提示 |
| `_extract_execution_constraints` | 3653-3671 | 提取执行约束 |
| `_recommend_locks` | 3674-3692 | 推荐锁定维度 |
| `_build_keyframe_beats` | 3704-3761 | 构建关键帧节拍 |
| `_fix_json_str` | 3764-3768 | 修复 JSON 尾逗号 |
| `_parse_shots_with_fallback` | 3771-3843 | 4 级 fallback 解析 SHOTS |
| `_classify_library_layer` | 3854-3859 | 库条目分层分类 |
| `_build_chat_library_block` | 3862-3878 | 构建分层库文本块 |
| `_polish_chat_shot_prompt` | 3881-3901 | 单镜头润色（调 Doubao） |
| 关键词常量 | 3528-3541, 3633-3650, 3846-3851, 3696-3701 | 各类关键词表 |

**适配点**（只有这几处需要改，其他原样复制）：
- `_polish_chat_shot_prompt` 里的 `_call_doubao` 改为调 SaaS 的 `app.services.doubao.generate_text`
- `from .services.prompt_engine import ...` 改为 `from app.services.prompt.engine import ...`
- `from .services.director_presets import ...` 改为 `from app.services.director.presets import ...`
- `from .config import DOUBAO_CHAT_MODEL` 改为 `from app.config import get_settings`

### 第二步：新建 `app/services/director_chat_engine.py` 的主函数

```python
def run_director_chat(
    message: str,
    project_id: str,
    history: list[dict] = None,
    preset_key: str = "",
    shots_in: list = None,
) -> dict:
    """
    完整的导演对话编排。返回结构化结果。
    
    流程：
    1. compile_director_brief（快速提取结构化 brief）
    2. 导演库检索（retrieve_prompt_matches）
    3. 构建 system prompt（策略块 + 库文本 + 编译结果）
    4. 调 Doubao 生成（要求结构化输出）
    5. 解析 CONTINUITY + SHOTS
    6. 对每个 shot 做库检索 + 润色
    7. 构建 shot_rows + execution_plan
    8. 返回完整结果
    """
```

这个函数的逻辑完全对标原版 `main.py:4138-4338`。

### 第三步：重写 `app/tasks/director_tasks.py` 的 `director_chat_task`

```python
@celery_app.task(bind=True, queue="text", soft_time_limit=300, time_limit=360, acks_late=True)
def director_chat_task(self, task_id, user_id, payload, transaction_id=None):
    # ...
    publish_progress(task_id, status="running", progress=10, stage_text="编译需求中...")
    
    from app.services.director_chat_engine import run_director_chat
    
    result = run_director_chat(
        message=messages[-1]["content"],
        project_id=project_id,
        history=messages[:-1],
        preset_key=payload.get("preset_key", ""),
    )
    
    # 写入 shot_rows
    if result.get("shot_rows"):
        asyncio.run(_save_shot_rows(project_id, result["shot_rows"], user_id))
    
    publish_complete(task_id, result)
    return result
```

**注意**：`soft_time_limit` 从 120 改为 300（润色多个 shot 需要时间）。

### 第四步：确认 `compile_director_brief` 和 `build_compiled_context` 存在

这两个函数在原版 `E:/shortdrama_ai/app/services/doubao.py:288-306`。

检查 SaaS 的 `app/services/doubao.py` 是否有。如果没有，从原版复制过来。

### 第五步：确认 `resolve_director_preset` 存在

检查 `app/services/director/presets.py` 是否有 `resolve_director_preset` 函数。如果没有或签名不同，从原版 `E:/shortdrama_ai/app/services/director_presets.py` 复制。

---

## 不要动的文件

- `app/services/prompt/engine.py` — 已验证可用
- `app/services/doubao.py` — 只读（除非需要加 compile_director_brief）
- `app/services/seedance.py` / `app/services/seedream.py` — 已验证可用
- `app/celery_app.py` — 不动
- 前端任何文件 — 不动

## 可以动的文件

- `app/services/director_chat_engine.py` — **新建**（核心）
- `app/tasks/director_tasks.py` — 重写 `director_chat_task`
- `app/services/doubao.py` — 如果缺 `compile_director_brief`，追加

## 验收标准

提交一个 director_chat 任务（message="做一个睫毛视频，要有创意"），返回结果必须包含：

```json
{
  "reply": "导演的完整回复文本...",
  "shot_rows": [...],           // 结构化分镜数组
  "continuity": {               // 人物/场景/道具设定
    "character_continuity": "...",
    "scene_continuity": "...",
    "prop_continuity": "..."
  },
  "execution_plan": {...},      // 执行计划
  "matched_libraries": [...],   // 命中的导演库名称
  "recommended_locks": [...],   // 推荐锁定维度
  "action": "shots_updated"     // 不是 "chat_only"
}
```

如果返回的还是纯文字聊天（没有 shot_rows），说明你没搬对。

## 执行顺序

1. 读原版 `E:/shortdrama_ai/app/main.py:3438-4338`（全部）
2. 读原版 `E:/shortdrama_ai/app/services/doubao.py:288-340`（compile 函数）
3. 读原版 `E:/shortdrama_ai/app/services/director_presets.py`（resolve 函数）
4. 新建 `app/services/director_chat_engine.py`
5. 重写 `director_chat_task`
6. 容器内测试验证

