"""
P8-QA-3: 接口契约测试 — 前端 API ts 调用 vs 后端路由匹配。

策略：
- 解析 frontend/src/api/*.ts 中的 client.{get,post,put,delete}(path) 调用
- 对比后端 FastAPI 路由表（通过 app.routes 枚举）
- 发现路径不匹配时报错

注意：前端 baseURL = '/api'，后端 api_router prefix = '/api'，
      director/workbench 路由直接挂在 /api 下。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract]

FRONTEND_API_DIR = Path(__file__).parent.parent.parent / "frontend" / "src" / "api"

# 前端 client.METHOD<T>('path', ...) 或 client.METHOD('path', ...) 调用的正则
# 支持泛型参数：client.post<AsyncResult>('/path', payload)
_CALL_RE = re.compile(
    r"client\.(get|post|put|delete|patch)(?:<[^>]*>)?\s*\(\s*[`'\"]([^`'\"]+)[`'\"]"
)

# 路径中的模板变量（如 ${projectId}）替换为占位符
_TEMPLATE_VAR_RE = re.compile(r"\$\{[^}]+\}")


def _normalize_path(path: str) -> str:
    """将模板变量替换为 :param 占位符，便于比较。"""
    return _TEMPLATE_VAR_RE.sub(":param", path)


def _extract_frontend_routes() -> dict[str, set[str]]:
    """返回 {method: {path, ...}} 的前端路由集合。"""
    routes: dict[str, set[str]] = {m: set() for m in ("get", "post", "put", "delete", "patch")}
    for ts_file in FRONTEND_API_DIR.glob("*.ts"):
        if ts_file.name == "client.ts":
            continue
        content = ts_file.read_text(encoding="utf-8")
        for method, path in _CALL_RE.findall(content):
            normalized = _normalize_path(path)
            routes[method].add(normalized)
    return routes


def _extract_backend_routes() -> dict[str, set[str]]:
    """通过 FastAPI app.routes 枚举后端路由。"""
    import app.main as main_module

    routes: dict[str, set[str]] = {m: set() for m in ("get", "post", "put", "delete", "patch")}
    for route in main_module.app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        path = route.path
        # 将 FastAPI 路径参数 {param} 替换为 :param
        normalized = re.sub(r"\{[^}]+\}", ":param", path)
        for method in route.methods or []:
            m = method.lower()
            if m in routes:
                routes[m].add(normalized)
    return routes


class TestApiContract:
    """前端 API 调用 vs 后端路由契约检查。"""

    def setup_method(self):
        self.frontend = _extract_frontend_routes()
        self.backend = _extract_backend_routes()

    def test_frontend_routes_exist_in_backend(self):
        """前端调用的每个路由必须在后端存在。"""
        missing = []
        for method, paths in self.frontend.items():
            for path in paths:
                # 前端 baseURL = /api，路径已包含 /api 前缀
                full_path = path if path.startswith("/api") else f"/api{path}"
                normalized_full = re.sub(r"\{[^}]+\}", ":param", full_path)
                if normalized_full not in self.backend[method]:
                    missing.append(f"{method.upper()} {path}")

        if missing:
            missing_str = "\n  ".join(sorted(missing))
            pytest.fail(
                f"前端调用了后端不存在的路由（{len(missing)} 个）:\n  {missing_str}"
            )

    def test_batch_generate_images_path(self):
        """批量图片生成路径契约：前端 /batch/generate-images → 后端 /api/batch/generate-images。"""
        assert "/batch/generate-images" in self.frontend["post"] or \
               "/api/batch/generate-images" in self.frontend["post"], \
            "前端 batchGenerateImages 路径不匹配"

    def test_batch_generate_videos_path(self):
        """批量视频生成路径契约。"""
        assert "/batch/generate-videos" in self.frontend["post"] or \
               "/api/batch/generate-videos" in self.frontend["post"], \
            "前端 batchGenerateVideos 路径不匹配"

    def test_director_script_path(self):
        """director/script 路径契约。"""
        assert "/director/script" in self.frontend["post"] or \
               "/api/director/script" in self.frontend["post"], \
            "前端 directorScript 路径不匹配"

    def test_director_reference_images_path(self):
        """director/reference-images 路径契约。"""
        assert "/director/reference-images" in self.frontend["post"] or \
               "/api/director/reference-images" in self.frontend["post"], \
            "前端 directorReferenceImages 路径不匹配"

    def test_director_produce_path(self):
        """director/produce 路径契约。"""
        assert "/director/produce" in self.frontend["post"] or \
               "/api/director/produce" in self.frontend["post"], \
            "前端 directorProduce 路径不匹配"

    def test_workbench_projects_path(self):
        """workbench projects CRUD 路径契约。"""
        assert "/projects" in self.frontend["post"] or \
               "/api/projects" in self.frontend["post"], \
            "前端 createProject 路径不匹配"

    def test_payment_create_order_path(self):
        """支付创建订单路径契约。"""
        assert "/payment/create-order" in self.frontend["post"] or \
               "/api/payment/create-order" in self.frontend["post"], \
            "前端 createOrder 路径不匹配"
