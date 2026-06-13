"""
回归测试目录。

规则：
- 每个 P0/P1 bug 修复后，对应的 tests/bugs/qa_XXX_*.py 复现用例
  移入此目录，并改为"修复后应通过"的断言。
- 文件命名：regression_qa_XXX_<描述>.py
- 每个文件顶部注明：对应 issue ID、修复 PR、修复终端。

当前待入库（等对应终端修复后）：
  - QA-001: api-biz 修复 _dispatch_director_task 后
  - QA-004: api-biz 修复 str(item) → json.dumps 后
  - QA-005: api-biz 修复批量预扣回滚后
  - QA-006: api-biz 清理 workbench.py 重复路由后
  - QA-008: api-biz 实现取消任务退积分后
"""
