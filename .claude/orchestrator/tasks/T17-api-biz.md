# T17 指令 — api-biz 终端

## 你的身份

你是 `api-biz` 终端。项目根目录是 `D:/20240313整理文件/Desktop/saas/`。

## 任务目标

1. 视频生成端点支持 `provider` 参数（seedance / kling）
2. 新增 TTS 语音合成端点
3. 积分定价表添加 TTS

## 分支

（如果 git 报错可忽略，直接在当前分支工作）

## 需要修改的文件

### 1. `app/main.py` — 视频端点添加 provider 支持

修改 `batch_generate_videos` 端点，让 payload 中的 `provider` 字段传递给 Celery 任务：

```python
@app.post("/api/batch/generate-videos", status_code=202, response_model=BatchTaskSubmitResponse)
async def batch_generate_videos(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # ... 现有逻辑不变 ...

    # 在派发任务时，把 provider 放入 item payload
    for item in items:
        child_id = str(uuid.uuid4())
        child_task_ids.append(child_id)

        # 确保 provider 传入 item
        if "provider" not in item:
            item["provider"] = payload.get("provider", "seedance")

        # ... INSERT + send_task 不变 ...
```

### 2. `app/main.py` — 新增 TTS 端点

在 `batch_generate_images` 之后添加：

```python
@app.post("/api/tts/generate", status_code=202, response_model=TaskSubmitResponse)
async def generate_tts(
    payload: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    TTS 语音合成。
    payload: { text: str, voice?: str, speed?: float }
    """
    user_id = current_user["id"]
    user_tier = current_user["tier"]

    # 限流（复用 text 类型的限流配置，或不限流）
    # await check_rate_limit(user_id, user_tier, "tts", db)

    # 积分预扣
    transaction_id = await reserve_credits(user_id, "tts_synthesis", 1)

    # 派发任务
    task_id = str(uuid.uuid4())
    priority_map = {"free": 5, "pro": 3, "enterprise": 1}
    priority = priority_map.get(user_tier, 5)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("""
                    INSERT INTO tasks (task_id, user_id, task_type, status, priority, payload, credits_reserved)
                    VALUES (:tid, :uid, 'tts', 'queued', :priority, :payload, :credits)
                """),
                {
                    "tid": task_id,
                    "uid": user_id,
                    "priority": priority,
                    "payload": str(payload),
                    "credits": 1,
                },
            )

    celery_app.send_task(
        "app.tasks.tts_tasks.generate_tts_task",
        args=[task_id, str(user_id), payload],
        kwargs={"transaction_id": transaction_id},
        queue="text",
        priority=priority,
    )

    return TaskSubmitResponse(task_id=task_id, status="queued", message="TTS task submitted")
```

注意：需要在文件顶部确保 `TaskSubmitResponse` 已从 schemas 导入（已有）。

### 3. `frontend/src/api/tasks.ts` — 添加 TTS API 方法

```typescript
  submitTts(payload: { text: string; voice?: string; speed?: number }) {
    return client.post<{ task_id: string; status: string; message: string }>('/tts/generate', payload)
  },
```

### 4. `frontend/src/pages/tasks/submit-video.vue` — 添加 provider 选择

在表单中添加 provider 下拉：

```html
<div class="form-group">
  <label>生成引擎</label>
  <select v-model="form.provider">
    <option value="seedance">Seedance (火山引擎)</option>
    <option value="kling">Kling 可灵 (快手)</option>
  </select>
</div>
```

在 form 数据中添加 `provider: 'seedance'` 默认值。

提交时将 provider 放入请求：
```typescript
await tasksApi.submitVideos([{ ...form, provider: form.provider }])
```

## 验收标准

1. `POST /api/batch/generate-videos` 支持 `provider` 字段（默认 seedance）
2. `POST /api/tts/generate` 能接收 text 并派发 TTS 任务
3. 前端视频提交页有引擎选择下拉
4. 前端 tasksApi 有 submitTts 方法
5. TTS 任务名正确：`app.tasks.tts_tasks.generate_tts_task`

## 完成后

告诉 orchestrator：T17 完成，列出修改的文件清单。
