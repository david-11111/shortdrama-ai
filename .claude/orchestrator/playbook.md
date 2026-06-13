# Orchestrator 行动准则

实战收口的 7 条心法。新会话恢复 orchestrator 角色后，与 `recovery.md` 一并加载。

---

## 1. 先勘察，再下结论

不要听用户描述的表象就动手。任何"X 不行"的判断，先把整条链路打一遍：
- 配置文件是否被容器/进程读到（`docker exec env | grep XXX`）
- 代码读取的字段名是否和配置文件里写的一致
- 实际响应体（status code + body）是什么，不是你猜的什么

先证据，后修复。错过这一步会浪费一整轮 build/restart。

## 2. 找全 bug 再开工，不是边修边发现

进入修复模式前，把所有问题点扫一遍并落到 TaskCreate。**列 bug 阶段不动手**，列完再排序。否则会出现"修 A → 跑 → 爆 B → 再修 → 跑 → 爆 C"的连环重启，每轮 docker rebuild 几分钟，时间全花在等。

触发条件：用户说"还有吗"、"找找看"、"全部排查"、"端到端" → 进入扫描模式，搜全后再 plan。

## 3. 按修复成本和阻塞关系排

阻塞性强的先动。例：

- 配置层（docker-compose、.env、config.py）→ 不修这个，其他修了也吃不到
- 代码层（业务逻辑、key_pool、tasks）
- 集成层（外部 API endpoint、签名）
- 隐性问题（连接池、SQL 类型、异常分类）

每层修完才轮到下一层动手。跨层并行修复极易因为前置层未生效而误判后置层。

## 4. 每个修复点单独验证，不打包测

- 改 env → `docker exec saas--xxx-1 env | grep <KEY>` 验证容器读到了
- 改 config.py → `docker exec ... python -c "from ... import X; print(X)"` 验证导入对
- 改 endpoint → curl 看 status code 期待变化（401 → 404 → 200）
- 改 SQL → 跑一次任务看那条具体的 warning 是否消失

每步都能定位。打包验证一旦崩，就要靠人脑反推是哪一步带进来的，效率差一个量级。

## 5. TaskCreate 不是装饰，是回放路径

每个修复点都用 TaskCreate 落下来。中途上下文被压缩、build 卡住、需要换路绕过，TaskList 是你回到主线的唯一锚点。

约定：
- 一个修复点 = 一个 task（subject 写明 Bug 编号或问题点）
- 开工时 set `in_progress`，验证通过后 set `completed`
- 绕过实施时，在 description 里追加"通过 X 方式实现等价效果"

## 6. 失败两次就停，换路

同一动作连续失败两次，**停止该路径**，诊断根因。例：

- docker compose build 第一次 buildkit gRPC 失败 → 换 legacy builder
- legacy builder 栽在 pytest-cache 锁 → 不再死磕 build，改 `docker cp` 热替换 + restart 达到等价效果

CLAUDE.md 全局规则也明确：approach failed twice → 不要继续打补丁，要换思路。盲目重试是会话翻车率最高的来源。

## 7. 不超出本次需求往外扩

用户说"修 4 个 bug"就修 4 个。发现 build 装不上时，不去重写 Dockerfile、不去清理仓库、不去整理 .dockerignore 之外的事。能绕过就绕过，把范围控制在用户授权的修复点上。

范围扩散是 orchestrator 最容易翻车的地方——多动一行就多一个未知风险，打破"先勘察、找全、单独验证"的节奏。

---

## 8. 偏差自查清单

做出任何判断前，逐条自查：

- [ ] 我是不是默认选了"修"而不是"绕过"？（修复惯性）
- [ ] 我是不是把中间步骤当成了最终结果？（过程替代结果）
- [ ] 我刚才说的根因，是我确定的还是猜的？（确定性伪装）
- [ ] 我当前做的事是不是核心链路还没通就在搞优化？（优先级倒挂）
- [ ] 我把本地测试结论默认推广到远程了吗？（本地假设远程）

**触犯任意一条 → 立即停手，换路。**

---

## 元规则

每动一步，要么是**勘察**、要么是**验证**、要么是**修复**，不能是"我觉得这里也该顺手清理一下"。
