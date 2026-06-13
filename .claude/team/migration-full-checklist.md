# 完整迁移任务 — 35 个缺失端点 + 6 个缺失服务

## 总则

本文件列出原版项目中存在但 SaaS 中缺失的所有功能。全部搬过来，一个不漏。

### 所有终端必须遵守的验收规则（无例外）

1. **不允许说"完成"除非附带实际运行证据**——DB 查询结果、curl 完整响应体、或文件内容输出
2. **不允许只跑编译/import 就报完成**——编译通过只证明语法对，不证明逻辑对
3. **迁移代码时必须逐一检查适配点**：
   - 原版用 SQLite → SaaS 用 PostgreSQL（SQL 语法差异）
   - 原版用本地文件路径 → SaaS 用 OSS/Docker 容器路径
   - 原版用 `_call_doubao` → SaaS 用 `key_pool.acquire` + `doubao.generate_text`
   - 原版用 `from .services.xxx` → SaaS 用 `from app.services.xxx`
   - 原版用 element-plus → SaaS 用原生 HTML + CSS 变量
   - 原版用 ThreadPoolExecutor → SaaS 用 Celery task
4. **每个端点实现后必须实际调用一次**，确认返回结构和原版一致
5. **涉及 DB 写入的，必须 SELECT 确认数据落库**
6. **涉及文件操作的，必须 ls/cat 确认文件存在且内容正确**
7. **如果发现原版依赖的模块在 SaaS 中不存在，立即报告 orchestrator，不要自己造一个 stub**

违反以上任何一条，orchestrator 会打回重做，不计为完成。

---

## 终端分工

### api-biz 负责（18 个端点）

#### 组 A：提示词系统（3 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 1 | POST | `/api/prompt/refine` | `refine_prompt_endpoint` | 提示词精炼 |
| 2 | GET | `/api/prompt/index` | `get_prompt_index` | 提示词索引 |
| 3 | GET | `/api/prompt/context-vocab` | `get_context_vocab` | 上下文词汇表 |

源码位置：`E:/shortdrama_ai/app/main.py`，搜索对应函数名。
SaaS 中已有 `app/routes/prompt.py`，追加到这个文件。

#### 组 B：导演扩展（8 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 4 | POST | `/api/director/chat/jobs` | `director_chat_submit_job` | 异步 chat job 提交 |
| 5 | GET | `/api/director/chat/jobs/{job_id}` | `director_chat_job_status` | chat job 状态查询 |
| 6 | POST | `/api/director/explain-run` | `director_explain_run` | 解释运行结果 |
| 7 | POST | `/api/director/concat-final` | `director_concat_final` | 拼接最终视频 |
| 8 | POST | `/api/director/write-script` | `director_write_script` | 写剧本 |
| 9 | POST | `/api/director/generate-from-prompts` | `director_generate_from_prompts` | 从提示词生成 |
| 10 | POST | `/api/director/generate-shot` | `director_generate_shot` | 生成单个镜头 |
| 11 | GET | `/api/director/{project_id}/{name}` | `director_get_output` | 获取导演输出 |

源码位置：`E:/shortdrama_ai/app/main.py:4100-4600`
SaaS 中追加到 `app/routes/director.py`。

#### 组 C：关键帧（3 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 12 | POST | `/api/keyframes/suggest` | `keyframes_suggest` | AI 关键帧建议 |
| 13 | PUT | `/api/keyframes/plan` | `keyframes_plan` | 关键帧计划 |
| 14 | POST | `/api/keyframes/validate` | `keyframes_validate` | 关键帧验证 |

源码位置：`E:/shortdrama_ai/app/main.py`，搜索 `keyframe`。
SaaS 中新建 `app/routes/keyframes.py`。

#### 组 D：项目媒体与场景（4 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 15 | GET | `/api/projects/{pid}/media` | `list_media` | 项目媒体列表 |
| 16 | GET | `/api/projects/{pid}/media/{mid}/scenes` | `list_scenes` | 媒体场景列表 |
| 17 | GET | `/api/projects/{pid}/media/{mid}/transcript` | `get_transcript` | 获取转录文本 |
| 18 | PATCH | `/api/projects/{pid}/scenes/{sid}` | `update_scene` | 更新场景 |

源码位置：`E:/shortdrama_ai/app/main.py`，搜索对应函数名。
SaaS 中追加到 `app/routes/workbench.py`。

---

### worker 负责（11 个端点的后台任务逻辑）

#### 组 E：生成类（5 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 19 | POST | `/api/projects/{pid}/scenes/{sid}/generate` | `generate_scene` | 场景生成 |
| 20 | GET | `/api/projects/{pid}/scenes/{sid}/generate/status` | `scene_generate_status` | 场景生成状态 |
| 21 | POST | `/api/projects/{pid}/image-to-video` | `image_to_video` | 图生视频 |
| 22 | POST | `/api/projects/{pid}/storyboard` | `create_storyboard` | 创建分镜板 |
| 23 | GET | `/api/projects/{pid}/storyboard/{name}` | `get_storyboard` | 获取分镜板 |

#### 组 F：导演生成（1 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 24 | POST | `/api/director/generate` | `director_generate` | 导演一键生成 |

#### 组 G：语音（2 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 25 | POST | `/api/projects/{pid}/scenes/{sid}/voiceover` | `create_voiceover` | 创建配音 |
| 26 | GET | `/api/projects/{pid}/scenes/{sid}/voiceover` | `get_voiceover` | 获取配音 |

#### 组 H：导出（3 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 27 | POST | `/api/projects/{pid}/export/highlight` | `export_highlight` | 导出精彩片段 |
| 28 | GET | `/api/projects/{pid}/exports` | `list_exports` | 导出列表 |
| 29 | POST | `/api/projects/{pid}/cover` | `generate_cover` | 生成封面 |
| 30 | GET | `/api/projects/{pid}/cover` | `get_cover` | 获取封面 |

#### 组 I：报告（2 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 31 | POST | `/api/gold/daily-report` | `create_daily_report` | 创建日报 |
| 32 | GET | `/api/gold/daily-report/{pid}/{date}` | `get_daily_report` | 获取日报 |

---

### worker 负责（6 个缺失服务模块）

| # | 文件 | 原版位置 | 说明 |
|---|---|---|---|
| 33 | `app/services/cover.py` | `E:/shortdrama_ai/app/services/cover.py` | 封面生成 |
| 34 | `app/services/job_registry.py` | `E:/shortdrama_ai/app/services/job_registry.py` | 任务注册表 |
| 35 | `app/services/probe.py` | `E:/shortdrama_ai/app/services/probe.py` | 探针/诊断 |
| 36 | `app/services/prompt_compiler.py` | `E:/shortdrama_ai/app/services/prompt_compiler.py` | 提示词编译 |
| 37 | `app/services/scene_detect.py` | `E:/shortdrama_ai/app/services/scene_detect.py` | 场景检测 |
| 38 | `app/services/video_edit.py` | `E:/shortdrama_ai/app/services/video_edit.py` | 视频编辑 |

迁移方式：从原版完整复制，适配 SaaS 的 import 路径（config、db、storage）。

---

### api-biz 负责（剩余 3 个端点）

#### 组 J：提示词管理（3 个）
| # | 方法 | 路径 | 原版函数 | 说明 |
|---|---|---|---|---|
| 39 | POST | `/api/prompt/rebuild-index` | `rebuild_prompt_index` | 重建提示词索引 |
| 40 | GET | `/api/projects/{pid}/reports/{type}` | `get_project_report` | 项目报告 |
| 41 | GET | `/api/prompt-templates` | `list_prompt_templates` | 提示词模板列表 |

---

### devops 负责

#### 数据库迁移
原版有 5 个表在 SaaS 中不存在：
| # | 表名 | 说明 | 迁移方式 |
|---|---|---|---|
| 42 | `media_files` | 媒体文件记录 | 新建 Alembic migration |
| 43 | `frames` | 视频帧数据 | 新建 Alembic migration |
| 44 | `transcripts` | 转录文本 | 新建 Alembic migration |
| 45 | `reports` | 报告数据 | 新建 Alembic migration |
| 46 | `task_logs` | 任务日志（原版） | 评估是否用 SaaS 的 tasks 表替代 |

还有 1 个表被引用但不存在：
| # | 表名 | 说明 |
|---|---|---|
| 47 | `project_memory` | 项目记忆（director_chat 引用） |

---

### fe-pages 负责

#### 缺失前端页面
| # | 页面 | 原版文件 | 说明 |
|---|---|---|---|
| 48 | Evaluation | `E:/shortdrama_ai/frontend/src/views/Evaluation.vue` | 闭环评测页 |
| 49 | Retrieve | `E:/shortdrama_ai/frontend/src/views/Retrieve.vue` | 提示词检索调试页 |

#### 缺失前端 API 函数
| # | 函数 | 说明 |
|---|---|---|
| 50 | `exportAnnotation()` | 导出标注结果 |
| 51 | `getProjectLogs()` | 获取项目日志 |

---

## 执行顺序

1. **devops 先行**：创建缺失的数据库表（migration），否则端点写入时会报错
2. **worker 第二**：迁移 6 个服务模块，这些是端点的底层依赖
3. **api-biz 第三**：实现 35 个端点（依赖服务模块和数据库表）
4. **fe-pages 最后**：补齐前端页面和 API 函数

## 验收方式

每个端点完成后，终端必须提供：
1. curl 调用示例 + 完整响应体
2. 如果涉及 DB 写入：`SELECT` 查询结果
3. 如果涉及文件生成：`ls` 确认文件存在

orchestrator 收到后会自己再跑一遍验证，对比原版行为，确认一致后才签收。
