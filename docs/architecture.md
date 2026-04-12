# 架构文档

这份文档描述 StoryForge 的系统分层、核心工作流和模块边界。  
它关注“系统怎么组织”，不重复使用说明和 HTTP 接口细节。

## 设计目标

StoryForge 当前的目标不是只生成一篇小说，而是提供一套可审计、可拆分、可扩展的内容生产链路：

1. 结构化小说生成
2. 面向视频生产的中间产物构建
3. 通过 API、Web 和 CLI 对外提供统一入口

## 系统分层

```text
CLI / Web UI / HTTP API
          |
          v
FastAPI Routers / CLI Commands
          |
          v
Application Layer
  - AppContainer
  - AsyncTaskQueue
  - task_runtime / task_handlers / task_support
  - ProjectStore / TaskStore
          |
          v
Pipelines
  - run_story_pipeline
  - run_image_pipeline
  - run_video_pipeline
          |
          v
Domain Services
  - NovelGeneratorService
  - NovelToVideoService
          |
          v
Integrations
  - LangChain backend / DeepSeek
  - Seedream
  - Seedance
  - ffmpeg
  - MySQL / JSON persistence
```

## 小说生成链路

小说生成是结构化多 Agent 工作流。主流程位于：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)

核心角色包括：

1. `Story Architect`
2. `Character Designer`
3. `Chapter Planner`
4. `Chapter Writer`
5. `Editorial Reviewer`

生成流程：

```text
StoryBrief
  -> StoryArchitectureSchema
  -> CharacterRosterSchema
  -> ChapterPlanSetSchema
  -> StoryOutline
  -> DraftChapter[]
  -> EditorialReview
  -> NovelPackage
```

关键中间产物：

- `outline.json`
- `novel_package.json`
- `editorial_review.json`
- `workflow_trace.json`
- `chapters/*.md`

### 小说域内部拆分

小说域当前已经按职责拆分：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)
  主流程、outline 组装、章节写作编排
- [`../src/storyforge/domains/novel/fallbacks.py`](../src/storyforge/domains/novel/fallbacks.py)
  deterministic fallback
- [`../src/storyforge/domains/novel/repair.py`](../src/storyforge/domains/novel/repair.py)
  角色与章节规划修补
- [`../src/storyforge/domains/novel/rules.py`](../src/storyforge/domains/novel/rules.py)
  brief 启发规则与双角色 / 性别修正规则

## 视频链路

视频链路不是一次性生成长视频，而是“规划 -> 关键帧 -> 片段 -> 合并”的分段式工作流。

生成流程：

```text
NovelPackage
  -> Character Visual Profiles
  -> Character Image Tasks
  -> Video Segments
  -> Scene Image Tasks
  -> Seedance Manifest
  -> Rendered Clips
  -> ffmpeg concat
```

关键中间产物：

- `character_visual_bible.json`
- `character_image_manifest.json`
- `segment_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`

### 视频域内部拆分

视频链路当前也已按职责拆分：

- [`../src/storyforge/pipelines/video_pipeline.py`](../src/storyforge/pipelines/video_pipeline.py)
  对外公开的 pipeline facade
- [`../src/storyforge/pipelines/video_planning.py`](../src/storyforge/pipelines/video_planning.py)
  规划产物生成与读取
- [`../src/storyforge/pipelines/video_support.py`](../src/storyforge/pipelines/video_support.py)
  执行辅助逻辑
- [`../src/storyforge/pipelines/video_models.py`](../src/storyforge/pipelines/video_models.py)
  pipeline 结果模型
- [`../src/storyforge/domains/video/service.py`](../src/storyforge/domains/video/service.py)
  主流程与结构化 Agent 调用
- [`../src/storyforge/domains/video/prompting.py`](../src/storyforge/domains/video/prompting.py)
  prompt 构造
- [`../src/storyforge/domains/video/repair.py`](../src/storyforge/domains/video/repair.py)
  LLM 输出修补
- [`../src/storyforge/domains/video/planning.py`](../src/storyforge/domains/video/planning.py)
  fallback 与任务对象组装

## API 与任务系统

Web 和 API 都不是直接同步执行长任务，而是通过队列提交后台任务。

任务入口：

- `project.story`
- `project.characters`
- `project.scenes`
- `project.images`
- `project.videos`
- `project.build`

相关模块：

- [`../src/storyforge/application/container.py`](../src/storyforge/application/container.py)
- [`../src/storyforge/application/tasks.py`](../src/storyforge/application/tasks.py)
- [`../src/storyforge/application/task_runtime.py`](../src/storyforge/application/task_runtime.py)
- [`../src/storyforge/application/task_handlers.py`](../src/storyforge/application/task_handlers.py)
- [`../src/storyforge/application/task_support.py`](../src/storyforge/application/task_support.py)

设计原则：

- API 只负责接入和返回 `task_id`
- 队列负责执行和状态切换
- 阶段任务复用同一个 `output_dir`
- 任务结果驱动前端实时预览

## 持久化

当前项目与任务元数据支持两种后端：

1. 本地 JSON
2. MySQL

MySQL 实现位于：

- [`../src/storyforge/application/persistence/mysql_backend.py`](../src/storyforge/application/persistence/mysql_backend.py)
- [`../src/storyforge/application/persistence/mysql_projects.py`](../src/storyforge/application/persistence/mysql_projects.py)
- [`../src/storyforge/application/persistence/mysql_tasks.py`](../src/storyforge/application/persistence/mysql_tasks.py)
- [`../src/storyforge/application/persistence/mysql_utils.py`](../src/storyforge/application/persistence/mysql_utils.py)

当前执行队列本身仍然是内存态；元数据可持久化，但任务执行状态还不是生产级持久化队列。

## 模块职责约定

- `domains/`
  放业务规则、结构化 schema、领域对象和领域服务
- `pipelines/`
  放跨领域的产物落盘与阶段编排
- `integrations/`
  放外部系统适配器
- `application/`
  放任务运行时、存储实现、依赖装配
- `api/`
  放 HTTP、模板和静态资源

## 扩展点

当前最明确的扩展方向：

- 替换 LLM provider
- 替换图像 / 视频 provider
- 将执行队列替换为 Redis / Celery / Arq / TaskIQ
- 接入对象存储
- 增加认证、权限和项目治理

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [开发文档](development.md)
- [技术栈与 Agent 定位](tech-stack.md)
