# 视频生成商品化方案

> 目标：让我们的视频生成 API 达到 DeepSeek 级的稳定性。
> 路线：先 A（稳定化自建 GPU），后 C（多 Provider 降级）。

---

## 第一阶段：稳定化自建 GPU（1-2 周）

### 1.1 远程服务器自愈（P0）

**问题**：infer_api 进程挂了没人知道，靠手动 ps/restart。

**方案**：systemd service + watchdog

```ini
# /etc/systemd/system/infer-api.service
[Unit]
Description=Wan2.1 Inference API
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/autodl-tmp/infer_api
ExecStart=/root/autodl-tmp/infer_api/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100 --workers 1
Restart=always
RestartSec=5
WatchdogSec=60
Environment=NVIDIA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
```

效果：进程崩溃后 5 秒自动重启，60 秒无响应自动 kill 重启。

### 1.2 图片上传代理（P0）

**问题**：远程 GPU 服务器出站 HTTPS 受限，无法下载外部图片 URL。

**方案**：改 `_inference_image_ref()`，遇到 HTTPS URL 时：
1. worker-video 本地下载图片
2. 通过 `/v1/files/upload` 上传到远程 API
3. 用返回的 `file_id` 提交推理

```python
def _inference_image_ref(image_ref: str) -> str:
    image_ref = str(image_ref or "").strip()
    if not image_ref:
        raise ValueError("image_url is required")
    if image_ref.startswith("file_"):
        return image_ref  # 已上传
    if image_ref.startswith(("http://", "https://")):
        # 本地下载 + 上传到推理 API（绕过远程 HTTPS 限制）
        local_path = _download_image_locally(image_ref)
        return _upload_image_to_inference_api(local_path)
    local_path = _resolve_local_image_path(image_ref)
    if local_path:
        return _upload_image_to_inference_api(local_path)
    return image_ref
```

### 1.3 SSH 隧道工程化（P1）

**当前**：wan-tunnel 容器内 sshpass + while 循环。
**问题**：Seetacloud 平台可能限制连接时长。

**方案**：
- 改用 autossh（自动检测连接存活并重建）
- 添加 TCP keepalive 参数
- 在 Dockerfile.wan-tunnel 中替换 sshpass 为 autossh

```dockerfile
RUN apt-get install -y autossh
CMD ["autossh", "-M", "0", "-N", "-g", \
     "-o", "ServerAliveInterval=10", \
     "-o", "ServerAliveCountMax=3", \
     "-o", "StrictHostKeyChecking=no", \
     "-L", "0.0.0.0:8100:127.0.0.1:8100", \
     "root@connect.cqa1.seetacloud.com", "-p", "14158"]
```

### 1.4 Provider 健康探测（P1）

**新增服务**：`app/services/provider_health.py`

```python
class ProviderHealthMonitor:
    """定期探测各 provider 的健康状态"""
    
    def probe(self, provider: str) -> ProviderStatus:
        """返回 healthy / degraded / down"""
    
    def get_status(self, provider: str) -> ProviderStatus:
        """获取最新探测结果（缓存 30s）"""
    
    def success_rate(self, provider: str, window_min: int = 5) -> float:
        """最近 N 分钟的成功率"""
```

- Celery Beat 每 30 秒执行一次探测
- 探测方式：`GET /v1/health`，3 秒超时
- 状态存 Redis，供前端展示和降级决策使用
- 连续 3 次探测失败 → 标记 `down`，触发告警

### 1.5 可观测面板（P2）

在 `/admin/providers` 页面展示：
- 各 Provider 在线状态（绿/黄/红）
- 最近 1 小时成功率
- 平均推理时间
- 队列深度
- GPU VRAM 占用

---

## 第二阶段：多 Provider 降级（第 3 周）

### 2.1 Provider 路由器

**新增服务**：`app/services/provider_router.py`

```python
class ProviderRouter:
    """根据健康状态和优先级选择最优 provider"""
    
    # 默认优先级（可配置）
    PRIORITY = [
        {"provider": "wan2.1", "type": "self_hosted", "cost": "low"},
        {"provider": "kling", "type": "third_party", "cost": "medium"},
        {"provider": "seedance", "type": "third_party", "cost": "high"},
    ]
    
    def select(self, *, prefer: str = "", fallback: bool = True) -> str:
        """选择当前最优可用 provider"""
        # 1. 检查 prefer 是否健康
        # 2. 不健康则按优先级遍历
        # 3. 全挂则抛 AllProvidersDown
```

### 2.2 自动降级逻辑

在 `video_tasks.py` 的 ComfyUI 分支加入降级：

```python
if provider in comfy_providers:
    try:
        result = generate_comfy_video(payload, provider=provider)
    except (TimeoutError, RuntimeError) as e:
        # 自建 GPU 失败，自动降级到第三方
        fallback_provider = provider_router.select(fallback=True)
        if fallback_provider and fallback_provider != provider:
            result = _generate_with_fallback(payload, fallback_provider)
        else:
            raise
```

### 2.3 用户体验

前端 OutputBoard 显示：
- 正常时："使用 Wan2.1 生成中…"
- 降级时："Wan2.1 暂时不可用，已切换到 Kling（速度更快但有额外费用）"
- 全挂时："所有视频生成服务暂时不可用，请稍后重试"

---

## 成本对比

| 方案 | 每次视频成本 | 月固定成本 | 稳定性 |
|------|------------|-----------|--------|
| 自建 4090D（autodl） | ~¥0.5（电费+租金分摊） | ~¥500-800 | 中→高（加自愈后） |
| Kling API | ~¥1-3/次 | 0 | 高 |
| Seedance API | ~¥2-5/次 | 0 | 高（但欠费会 403） |

**结论**：自建做主力省钱，第三方做保底兜稳定性。

---

## 实施顺序

| 步骤 | 时间 | 交付物 |
|------|------|--------|
| 1.2 图片上传代理 | 30分钟 | `comfy_video.py` 修改 |
| 1.1 远程 systemd 自愈 | 1小时 | 远程服务器配置 |
| 1.3 SSH 隧道改 autossh | 1小时 | Dockerfile + docker-compose |
| 1.4 Provider 健康探测 | 2小时 | `provider_health.py` + Beat 任务 |
| 2.1 Provider 路由器 | 2小时 | `provider_router.py` |
| 2.2 自动降级 | 1小时 | `video_tasks.py` 修改 |
| 1.5 可观测面板 | 3小时 | 前端页面 |
