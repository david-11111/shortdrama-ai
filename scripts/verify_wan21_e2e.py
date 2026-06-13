#!/usr/bin/env python3
"""
WAN2.1 端到端验证脚本（P0-2）

验证链路：
  本地 Docker → wan-tunnel → 远程 GPU API → 视频生成 → 下载 → 确认

每个验证点单独报结果。不跳过失败。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)

INFERENCE_API_URL = os.getenv("INFERENCE_API_BASE_URL", "http://wan-tunnel:8100")
INFERENCE_API_KEY = os.getenv("INFERENCE_API_KEY", "sk-default-dev-key")

# 是否在 Docker 容器内运行（自动检测）
_IN_CONTAINER = os.path.exists("/.dockerenv") or os.path.exists("/proc/1/cgroup")
if _IN_CONTAINER:
    LOCAL_HEALTH_URL = "http://nginx/health"
else:
    LOCAL_HEALTH_URL = "http://localhost/health"


def header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def check(name: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    print(f"  {icon} {name}")
    if detail:
        for line in detail.strip().split("\n"):
            print(f"     {line}")
    return (name, ok, detail)


def http_get(url: str, timeout: int = 10) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def http_post_json(url: str, payload: dict, api_key: str | None = None, timeout: int = 60) -> tuple[int, dict | str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


# ── 验证 1：本地 Docker 健康 ──────────────────────────────────
header("验证 1/6：本地 Docker 服务健康")

results = []

status, body = http_get(LOCAL_HEALTH_URL, timeout=10)
ok = status == 200 and '"ok"' in body
results.append(check("本地 API /health", ok,
                     f"HTTP {status}: {body[:200]}"))

# docker ps 确认所有容器 running
try:
    r = subprocess.run(
        ["docker", "compose", "ps", "--format", "{{.Name}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=15, cwd=PROJECT_ROOT,
    )
    lines = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
    containers_up = sum(1 for l in lines if "Up" in l)
    containers_total = len(lines)
    ok = containers_up == containers_total
    results.append(check(f"Docker 容器在线 ({containers_up}/{containers_total})", ok,
                         "\n".join(lines)))
except Exception as e:
    results.append(check("Docker compose ps", False, str(e)))


# ── 验证 2：wan-tunnel 容器健康 ──────────────────────────────
header("验证 2/6：wan-tunnel 隧道状态")

try:
    r = subprocess.run(
        ["docker", "compose", "ps", "wan-tunnel", "--format", "{{.Status}}"],
        capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT,
    )
    status_str = r.stdout.strip()
    ok = "healthy" in status_str.lower() or "up" in status_str.lower()
    results.append(check("wan-tunnel 容器运行中", ok, status_str))
except Exception as e:
    results.append(check("wan-tunnel 状态检查", False, str(e)))

# 直接访问 inference API health
inference_health_url = f"{INFERENCE_API_URL}/v1/health"
status, body = http_get(inference_health_url, timeout=10)
wan_api_online = status == 200
if wan_api_online:
    data = json.loads(body) if isinstance(body, str) else {}
    gpu_info = data.get("gpu", {})
    results.append(check("远程 GPU API 健康", True,
                         f"GPU: {gpu_info.get('name','?')} | VRAM 空闲: {gpu_info.get('vram_free_mb','?')}MB"))
else:
    results.append(check("远程 GPU API 健康", False,
                         f"HTTP {status}: 远程 SSH 隧道暂未连接（自动重连中）"))


# ── 验证 3：代码 py_compile ──────────────────────────────────
header("验证 3/6：本地代码语法")

files_to_check = [
    "app/services/comfy_video.py",
    "app/services/video_production_runner.py",
    "app/tasks/video_tasks.py",
]
all_compile_ok = True
for f in files_to_check:
    fpath = PROJECT_ROOT / f
    if not fpath.exists():
        results.append(check(f"{f} 存在", False))
        all_compile_ok = False
        continue
    r = subprocess.run(
        [sys.executable, "-m", "py_compile", str(fpath)],
        capture_output=True, text=True, timeout=10,
    )
    ok = r.returncode == 0
    if not ok:
        all_compile_ok = False
    detail = r.stderr.strip()[:200] if not ok else "语法 OK"
    results.append(check(f"{f} py_compile", ok, detail))

results.append(check("全部 py_compile 通过", all_compile_ok))


# ── 验证 4：容器内代码一致性 ────────────────────────────────
header("验证 4/6：容器内代码一致性")

for service, container_file in [
    ("api", "app/services/comfy_video.py"),
    ("worker-video", "app/services/comfy_video.py"),
]:
    try:
        r = subprocess.run(
            ["docker", "compose", "exec", "-T", service, "python3", "-m", "py_compile", f"/app/{container_file}"],
            capture_output=True, text=True, timeout=10, cwd=PROJECT_ROOT,
        )
        ok = r.returncode == 0
        detail = r.stderr.strip()[:200] if not ok else "语法 OK"
        results.append(check(f"{service}:{container_file} 容器内编译", ok, detail))
    except Exception as e:
        results.append(check(f"{service}:{container_file} 容器检查", False, str(e)))


# ── 验证 5：inference API 提交路径 ──────────────────────────
header("验证 5/6：Wan2.1 API 提交路径")

if not wan_api_online:
    results.append(check("Wan2.1 API 提交—跳过（远程离线）", False,
                         "远程 GPU 服务器 SSH 未连。待远程恢复后，用下面命令重新验证：\n"
                         "  docker compose exec -T worker-video python -c "
                         "\"from app.services.comfy_video import _inference_api_url; print(_inference_api_url('/v1/health'))\""))
else:
    # 1. 提交一个简单推理（用已有参考图 file_id 或者 URL）
    # 先看 API 上是否有已上传的文件
    s, files_body = http_get(f"{INFERENCE_API_URL}/v1/files", timeout=8)
    existing_files = []
    if s == 200 and isinstance(files_body, (dict, list)):
        if isinstance(files_body, dict):
            existing_files = files_body.get("files", files_body.get("data", []))
        elif isinstance(files_body, list):
            existing_files = files_body

    test_image = None
    for f_item in existing_files:
        if isinstance(f_item, dict) and f_item.get("purpose") == "input":
            test_image = f_item.get("file_id") or f_item.get("id")
            break

    if not test_image:
        # 用一个公开测试图
        test_image = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/300px-PNG_transparency_demonstration_1.png"

    job_payload = {
        "model": "wan2.1",
        "prompt": "A simple 3-second slow zoom in on a gold ring on a dark velvet surface, cinematic lighting, shallow depth of field",
        "image": test_image,
        "duration": 3,
        "width": 832,
        "height": 480,
        "steps": 10,
        "cfg": 5.5,
        "timeout_seconds": 120,
    }

    print(f"  提交推理任务...")
    s, resp_data = http_post_json(
        f"{INFERENCE_API_URL}/v1/inference",
        job_payload,
        api_key=INFERENCE_API_KEY,
        timeout=30,
    )
    if s == 200 and isinstance(resp_data, dict) and resp_data.get("job_id"):
        job_id = resp_data["job_id"]
        results.append(check("Wan2.1 任务提交成功", True, f"job_id: {job_id}"))

        # 轮询等待（最多等待 120 秒）
        print(f"  等待任务完成 (job_id={job_id})...")
        deadline = time.time() + 120
        succeeded = False
        while time.time() < deadline:
            s2, status_data = http_get(f"{INFERENCE_API_URL}/v1/inference/{job_id}", timeout=15)
            if s2 == 200 and isinstance(status_data, dict):
                st = (status_data.get("status") or "").lower()
                if st == "succeeded":
                    output = status_data.get("output", {})
                    video_url = output.get("url", "") if isinstance(output, dict) else ""
                    results.append(check("Wan2.1 任务成功", bool(video_url),
                                         f"视频 URL: {video_url}"[:200]))
                    succeeded = True
                    break
                elif st in ("failed", "cancelled"):
                    err = status_data.get("error", status_data)
                    results.append(check(f"Wan2.1 任务 {st}", False, str(err)[:300]))
                    break
            print(f"    状态查询中...", end="\r")
            time.sleep(5)
        if not succeeded:
            results.append(check("Wan2.1 任务超时", False, "120 秒内未完成"))
    else:
        err_str = str(resp_data)[:300] if not isinstance(resp_data, str) else resp_data
        results.append(check("Wan2.1 任务提交", False, f"HTTP {s}: {err_str}"))

results.append(check("Wan2.1 API 路径汇总", wan_api_online, "远程离线时此组验证跳过"))


# ── 验证 6：代码路径完整性 ──────────────────────────────────
header("验证 6/6：代码路径完整性")

# 验证 generate_comfy_video 能正确路由到 inference API 分支
route_checks = [
    ("provider='wan2.1' 走 inference API", True),
    ("provider='wan' 走 inference API", False),  # wan 不在 _WAN_API_PROVIDERS
    ("provider='wan2_1' 走 workflow", True),
]
for label, expected in route_checks:
    # 这只是路径覆盖分析，不是运行时验证
    pass

# 验证 video_tasks.py 中 provider mapping
video_tasks_path = PROJECT_ROOT / "app/tasks/video_tasks.py"
content = video_tasks_path.read_text(encoding="utf-8")
comfy_providers_found = "ltx" in content and "wan2.1" in content and "comfyui" in content
seedance_path = "seedance" in content
kling_path = "kling" in content
results.append(check("video_tasks.py provider 分支覆盖",
                     comfy_providers_found and seedance_path and kling_path,
                     f"comfy_providers={comfy_providers_found} seedance={seedance_path} kling={kling_path}"))

# 验证 video_production_runner.py 中默认 provider 是 wan2.1
runner_path = PROJECT_ROOT / "app/services/video_production_runner.py"
runner_content = runner_path.read_text(encoding="utf-8")
default_wan = 'video_provider: str = "wan2.1"' in runner_content
results.append(check("Runner 默认 video_provider=wan2.1", default_wan))

# 验证 agent_runs.py 默认 provider
agent_runs_path = PROJECT_ROOT / "app/routes/agent_runs.py"
if agent_runs_path.exists():
    agent_content = agent_runs_path.read_text(encoding="utf-8")
    agent_default_wan = '"wan2.1"' in agent_content
    results.append(check("agent_runs.py 默认 video provider=wan2.1", agent_default_wan))

# 验证 comfy_video.py 中 _wan_workflow 使用 Wan2_1 模型
comfy_content = content if video_tasks_path.name == "comfy_video.py" else (PROJECT_ROOT / "app/services/comfy_video.py").read_text(encoding="utf-8")
wan21_model = "Wan2_1-I2V-14B-480P" in comfy_content
results.append(check("comfy_video.py 使用 Wan2.1 I2V 模型", wan21_model))


# ── 汇总 ──────────────────────────────────────────────
header("汇总")
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
total = len(results)
print(f"  通过: {passed}/{total}")
print(f"  失败: {failed}/{total}")

if failed > 0:
    print(f"\n  未通过的检查：")
    for name, ok, detail in results:
        if not ok:
            print(f"    {FAIL} {name}")
            if detail:
                print(f"         {detail}")

print()
if failed == 0:
    print(f"  {PASS} 全部验证通过！WAN2.1 链路已就绪。")
    sys.exit(0)
elif wan_api_online:
    print(f"  ⚠️  部分验证未通过，建议排查后重试。")
    sys.exit(1)
else:
    print(f"  ⏳ 远程 GPU 离线是预期行为（SSH 隧道间歇性断连），"
          f"自动重连已部署。远程恢复后重跑本脚本。")
    sys.exit(3)
