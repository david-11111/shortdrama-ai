"""
QA-006 复现用例：workbench.py asset 端点重复定义两遍。

预期：每个路由路径只定义一次。
实际：get_asset 和 create_asset 各定义两次（第 155 行和第 399/431 行），
      FastAPI 以最后一个为准，前面的被覆盖。
"""
import pytest

pytestmark = [pytest.mark.contract]


def test_no_duplicate_asset_routes():
    """复现：检查 workbench router 中是否有重复路由。"""
    import app.main as main_module

    route_signatures = []
    for route in main_module.app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        for method in route.methods or []:
            sig = (method, route.path)
            route_signatures.append(sig)

    duplicates = [sig for sig in route_signatures if route_signatures.count(sig) > 1]
    unique_duplicates = list(set(duplicates))

    assert not unique_duplicates, (
        f"BUG QA-006 confirmed: duplicate routes found: {unique_duplicates}"
    )
