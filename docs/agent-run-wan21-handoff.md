# Agent Run + Wan2.1 调试交接记录

更新时间：2026-06-02 16:25 左右

## 当前目标

本地 `agent-run` 的视频生成环节要同时支持：

- `seedance`：闭源火山引擎，当前因欠费/403 不可用。
- `wan2.1`：开源模型，经远程 GPU 服务器 API 调用。

用户当前关心的是：为什么 `agent-run` 链路里还没有看到视频产物，以及 Wan2.1 到底是否进入了视频生成链路。

## 已验证事实

### 本地服务

- 本地目录：`E:\shortdrama_ai\saas - 副本`
- 启动脚本：`特工.bat`
- 当前架构采用 Docker Compose。
- `nginx` 曾出现 502，根因是 nginx 缓存了旧的 API 容器 IP：`172.18.0.8:8000`。
- 已通过 `docker compose restart nginx` 修复过一次。
- 修复后验证：
  - `http://localhost/health` 返回 `{"status":"ok"}`
  - `http://localhost/api/auth/me` 未登录时返回 `401`，这是正常鉴权响应，不再是 502。

### Wan2.1 GPU API

远程 GPU 服务器：

```text
ssh -p 14158 root@connect.cqa1.seetacloud.com
password: 3mPAOMC8QLbS
```

远程 API 状态：

- 路径：`/root/autodl-tmp/infer_api`
- 进程：`uvicorn main:app --host 127.0.0.1 --port 8100`
- 模型：`wan2.1-i2v-14b-fp8`
- GPU：4090D
- API 健康检查曾返回：

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "comfyui_connected": true,
  "gpu": {
    "name": "cuda:0 NVIDIA GeForce RTX 4090 D : cudaMallocAsync",
    "vram_total_mb": 24210,
    "vram_free_mb": 23710
  },
  "queue": {
    "running": 0,
    "pending": 0
  },
  "models": ["wan2.1-i2v-14b-fp8"]
}
```

本地 Docker 网络访问方式：

- `.env` 中配置：

```text
INFERENCE_API_BASE_URL=http://wan-tunnel:8100
INFERENCE_API_KEY=sk-default-dev-key
WAN_SSH_PASSWORD=3mPAOMC8QLbS
```

- `wan-tunnel` 容器负责 SSH 隧道：

```text
worker-video -> http://wan-tunnel:8100 -> SSH tunnel -> remote 127.0.0.1:8100
```

- 曾在 `worker-video` 容器内验证过：

```powershell
docker compose exec -T worker-video python -c "import urllib.request; print(urllib.request.urlopen('http://wan-tunnel:8100/v1/health', timeout=8).read().decode())"
```

结果健康，说明容器内到 Wan2.1 API 的网络链路是通的。

### Wan2.1 API 曾经真实生成过

服务器侧曾完成过一次真实 API 推理：

- job_id：`job_b6d9e8c2df7b4c6e`
- output file id：`file_out_de785264fe0741f4`
- 生成文件：`wan_api_00001.mp4`

注意：这只证明服务器 API 单独能生成，不证明本地 `agent-run -> video_task -> 写回 selected_video` 已端到端跑通。

## 已做代码接入

### 后端

- `app/services/comfy_video.py`
  - `wan` / `wan2.1` / `wan2_1` 已改为走 inference API，不走本地 ComfyUI `8188`。
  - 流程包括：
    - 上传参考图到 `/v1/files/upload`
    - 提交任务到 `/v1/inference`
    - 轮询 `/v1/inference/{job_id}`

- `app/config.py`
  - 新增：
    - `inference_api_base_url`
    - `inference_api_key`

- `app/tasks/video_tasks.py`
  - comfy/open-source provider 列表包含 `wan` / `wan2.1` / `wan2_1`。

- `app/routes/agent_runs.py`
  - `generate-video-from-pool` 接口默认 provider 是 `wan2.1`。
  - `_normalize_video_pool_provider()` 允许：

```text
seedance, kling, wan, wan2.1, wan2_1, ltx, comfyui
```

### 前端

- `frontend/src/pages/director/agent-run/components/OutputBoard.vue`
  - 在“成果区 -> 图片池”里添加了视频 provider 下拉框：
    - `Seedance`
    - `Wan2.1 API`
  - 下拉框只在关键帧图片池出现后可见。
  - 当前启动页没有 provider 选择框。
  - 浏览器本地存储 key：

```text
agent-run:video-provider
```

可手动设为 Wan2.1：

```js
localStorage.setItem('agent-run:video-provider', 'wan2.1')
location.reload()
```

## 当前用户看到的状态

用户截图显示：

- `agent-run` 仍停在“生成剧本和分镜计划”。
- 右上角统计为：

```text
0 镜头 · 0 图片 · 0 视频
```

- 因此当前页面还不会显示 Wan2.1 下拉框，因为图片池尚未生成。

同时，右侧红色错误截图显示后端又抛了异常。可见堆栈片段：

```text
starlette/_utils.py collapse_excgroups
starlette/middleware/base.py
anyio/_backends/_asyncio.py
starlette/middleware/errors.py
...
/app/monitoring/health.py, line 80, record_request_metrics
...
```

这说明当前需要先查后端异常。它可能阻断了页面刷新、快照接口、登录态接口或 agent-run 继续推进。

## 未验证，不能声称完成

以下事项还没有验证完成：

- 本地 `agent-run` 自动链路是否真的派发了 `video_gen` 任务。
- `video_gen` 任务是否带上 `provider=wan2.1`。
- `worker-video` 是否调用了 inference API 分支，而不是错误走到 ComfyUI `8188` 或 Seedance。
- Wan2.1 生成结果是否下载到本地 storage。
- 生成视频是否写回 `shot_rows.selected_video`。
- 前端成果区是否能显示该视频。

因此不能说“Wan2.1 端到端跑好了”。

## 下一步排查顺序

### 1. 先定位红色异常

查看 API 最新日志：

```powershell
docker compose logs --tail=240 api
```

重点找完整异常，尤其是 `/app/monitoring/health.py:80` 附近具体报错。

查看 `health.py`：

```powershell
Get-Content app/monitoring/health.py
```

判断是 metrics 中间件自身 bug，还是某个请求异常被它包装后显示。

### 2. 确认 agent-run 当前卡在哪个接口

查看 nginx 和 API 最近请求：

```powershell
docker compose logs --tail=160 nginx
docker compose logs --tail=260 api
```

重点接口：

```text
/api/agent-runs/{run_id}/snapshot
/api/agent-runs/{run_id}/actions/...
/api/auth/me
/health
```

### 3. 查当前 run 的任务状态

从截图里当前 run 可能还在“生成剧本和分镜计划”，需要确认是否没有进入关键帧阶段。

如果有 run_id，查：

```powershell
docker compose exec -T api python -c "..." 
```

或直接调用 snapshot 接口，看：

- tasks
- events
- outputs
- keyframe_pool
- shots
- production_status

### 4. 如果已经有关键帧，查 video_gen

查看 worker-video：

```powershell
docker compose logs --tail=260 worker-video
```

确认是否出现：

- `provider=wan2.1`
- `inference_api_wan2.1`
- `/v1/files/upload`
- `/v1/inference`
- `job_id`
- 下载输出视频
- 写回 `selected_video`

如果日志里出现 `ComfyUI` 或 `8188`，说明容器镜像或 provider 分支仍是旧代码。

### 5. 如果没有关键帧，先推进剧本输入

当前页面提示缺少：

- 作品具体是哪部分
- 角色是谁
- 角色身份/定位

可输入：

```text
作品是小金饰品品牌广告；角色是年轻都市女性消费者；定位是高级、克制、精致、有光影质感的黄金首饰广告。继续执行。
```

等产生镜头和关键帧后，成果区才会出现图片池和 Wan2.1 选择框。

## 常用命令

```powershell
docker compose ps api nginx wan-tunnel worker-video
docker compose logs --tail=240 api
docker compose logs --tail=160 nginx
docker compose logs --tail=260 worker-video
docker compose logs --tail=120 wan-tunnel
Invoke-WebRequest -Uri http://localhost/health -UseBasicParsing -TimeoutSec 10
docker compose exec -T worker-video python -c "import urllib.request; print(urllib.request.urlopen('http://wan-tunnel:8100/v1/health', timeout=8).read().decode())"
```

## 需要保持诚实的结论

当前准确状态：

> Wan2.1 GPU API 和 Docker 隧道曾验证可用；本地代码也已接入 `generate-video-from-pool`。但当前 `agent-run` 页面仍未生成镜头、图片、视频，并且后端出现新的 Starlette/health middleware 异常。下一步必须先修复/定位这个异常，再确认 run 是否进入关键帧和视频生成阶段，最后才能验证 Wan2.1 端到端写回。
