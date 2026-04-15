# 架构文档

这份文档描述 StoryForge 的系统分层、核心工作流和模块边界。  
它关注“系统怎么组织”，不重复使用说明和 HTTP 接口细节。

这里不展开具体接口示例、联调步骤或路线图：

- 怎么使用：看 [usage.md](usage.md)
- 接口 contract：看 [api.md](api.md)
- 代码修改约定：看 [development.md](development.md)
- 当前状态与下一步：看 [status.md](status.md)

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
  - MySQLProjectStore / MySQLTaskStore
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
  - MySQL persistence
```

## 小说生成链路

小说生成是结构化多 Agent 工作流。主流程位于：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)

核心角色包括：

1. `Story Architect`
2. `Story Drafter`
3. `Cast Analyzer`
4. `Character Designer`
5. `Chapter Planner`
6. `Editorial Reviewer`

当前已经拆成两个明确阶段：

```text
StoryBrief
  -> StoryArchitectureSchema
  -> StoryDraftSetSchema
  -> StorySourcePackage
  -> [用户可审阅 / 编辑]
  -> StoryArchitectureSchema (analysis)
  -> CastAnalysisSchema
  -> CharacterRosterSchema
  -> ChapterPlanSetSchema
  -> StoryOutline
  -> EditorialReview
  -> NovelPackage
```

其中：

- `project.story` 只负责生成 `StorySourcePackage`
- `project.story_analysis` 只负责从 `story_source` 生成 `NovelPackage`

关键中间产物：

- `story_source.json`
- `novel_package.json`
- `novel_audit.json`

其中：

- `novel_package.json` 是运行态最小包，包含 `brief`、精简后的 `outline` 和精简后的 `chapters`
- `novel_audit.json` 保存 `review`、`workflow_trace`，以及从运行包剥离出来的分析上下文

### 小说链路约定

当前小说链路有一个明确约定：

- **小说链路先产出完整小说草稿，再从草稿里解析 cast、角色和章节结构**
- **角色结构、层级、排序与关系图以 `Cast Analyzer` 的 LLM 解析结果为主**
- **`Story Architect` 只负责故事引擎、主题、舞台和视觉母题，不负责预设最终角色人数**
- **live LLM 模式下，结构化阶段失败会先重试 3 次，仍失败则显式终止任务，不再用旧的 brief-first 结果静默顶替**
- **运行时已移除 DryRun / 非 LLM 演示模式，真实任务必须带可用 DeepSeek 配置**
- `heuristics` 只负责 fallback 和 repair，不再主导“到底有几个核心角色、谁和谁是关系双方”

对架构层来说，最重要的实现边界是：

1. `Story Architect` 先给出项目底稿，但不允许提前钉死角色结构
2. 再由 `Story Drafter` 根据 brief 与项目底稿写出一版完整小说草稿
3. 再由 `Cast Analyzer` 基于小说草稿解析 cast slots、角色层级、关系图与排序规则
4. cast slots 会尽量保留小说草稿中的角色指代和 `source_evidence`，避免把“记者 / 线人 / 前任 / 退休警察”压扁成泛化配角
5. `Character Designer` 与 `Chapter Planner` 再消费这份草稿与 cast 结构
6. 当前 `story_source` 就是正文真源；结构化分析阶段不再重写章节正文，而是直接分析这份正文
7. 只有当 LLM 缺字段、跑偏或不可用时，才由 heuristics / repair 补位
8. `Cast Analyzer` 的每个 slot 都必须带正文证据；没有正文证据的角色不应进入核心 cast。当前证据校验允许对“带修饰语的人名或稳定称呼”做容错匹配，但不会放过正文中根本不存在的人物
9. `Character Designer` 必须严格覆盖上游目标 slots，不能新增正文里没有支撑的人物
10. story 阶段的核心运行文件是 `story_source.json`、`novel_package.json` 和 `novel_audit.json`

### 小说域内部拆分

小说域当前已经按职责拆分：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)
  主流程、outline 组装、章节写作编排
- [`../src/storyforge/domains/novel/prompts.py`](../src/storyforge/domains/novel/prompts.py)
  小说多阶段 prompt 构造，包含 cast 分析、角色生成、章节规划、章节写作、审校
- [`../src/storyforge/domains/novel/schemas.py`](../src/storyforge/domains/novel/schemas.py)
  小说结构化输出 schema，包括 `CastAnalysisSchema` 与角色 `cast_slot_id`
- [`../src/storyforge/domains/novel/fallbacks.py`](../src/storyforge/domains/novel/fallbacks.py)
  deterministic fallback，包括 cast analysis fallback
- [`../src/storyforge/domains/novel/repair.py`](../src/storyforge/domains/novel/repair.py)
  cast analysis、角色与章节规划修补
- [`../src/storyforge/domains/novel/rules.py`](../src/storyforge/domains/novel/rules.py)
  brief 启发规则与性别修正规则

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
  -> Manual ffmpeg concat
```

关键中间产物：

- `character_visual_bible.json`
- `character_image_manifest.json`
- `segment_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`

`character_visual_bible.json`、`character_image_manifest.json`、`segment_plan.json`、`scene_image_manifest.json`、`seedance_manifest.json` 在 `project.story_analysis` 阶段随结构化小说包一起生成。
后续 `project.characters`、`project.scenes`、`project.videos` 只读取并更新这些规划文件，避免到角色图阶段才临时拆分视频。
`project.scenes` 与 `project.videos` 现在都支持可选 `segment_id`，可以只执行单个片段；根任务只刷新 `artifact_revision`，这样前端会看到新产物，但不会把“单段完成”误写成整阶段全量重跑。
`project.videos` 还支持 `merge_only = true` 的手动合并模式。这个模式不会再调用 Seedance，而是把当前已生成的本地 mp4 片段按 manifest 顺序交给 ffmpeg 合并成 `full_story.mp4`。
视频分段 prompt 和归一化层会按中文自然口播语速估算对白、旁白和硬字幕预算，单段说不完时拆成多个 Seedance 安全片段。
视频分段现在会额外规划 `requires_mid_frame`、`mid_frame_prompt`，以及 `start_frame_characters` / `mid_frame_characters` / `end_frame_characters`。其中 `involved_characters` 表示整段剧情相关角色，帧级角色字段表示对应关键帧里真正出镜的人物。
场景图阶段会优先引用角色定妆图，再按 `首帧 -> 中段锚点帧（如有） -> 尾帧` 的顺序生成关键帧；每一帧只会引用该帧角色列表对应的角色图，不再按整段 `involved_characters` 全量喂图。帧级角色归一化会优先读取对应 `timed_beats`，例如中段节拍只有“男主等待”时，中段帧不会因为整段涉及女主就自动绑定女主参考图。视频阶段会先尝试把角色图、中段锚点图、首帧和尾帧一起组装进 Seedance 请求，若接口对图片组合返回 400，再自动回退到更保守的图片组合，优先保证真实任务可提交。
角色定妆图 prompt 会统一追加 `SF-TURN-01` 横版 16:9 白底三视图模板，让所有角色使用相同的纯白背景、正面 / 左侧面 / 背面三栏站姿、人物比例和画风。图上唯一允许出现角色中文姓名，性别、身份和职业只作为内部造型参考，不允许写到图上。

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
- `project.story_analysis`
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
- `/v1/tasks/{task_id}/artifacts` 会把 `segment_plan.json` 转成 `planned_segments`，前端时间线直接按这份规划渲染所有片段，而不是等图片 / 视频都生成出来后再倒推
- 任务失败时 `error` 会进入任务记录，并在前端详情页和阶段卡片中展示
- `project.story_analysis` 对同一 `source_task_id` + `story_source_revision` 做幂等保护，已存在 queued / running / completed 任务时直接返回已有任务
- `project.scenes` / `project.videos` 对同一 `source_task_id` + `segment_id` 的 queued / running 任务做幂等保护，避免双击把同一片段重复排队
- Web 详情页按 `pipeline_root_task_id` 聚合同一制作版本的阶段任务，避免队列详情页误判某个阶段还未执行
- 服务启动时，残留的 `running` 任务会重新回到 `queued`，避免热重载或进程重启直接把长任务标记为失败
- 删除项目会同时删除项目元数据、任务记录和任务结果记录过的输出目录；文件删除由 `application/project_deletion.py` 统一做安全边界校验，只允许删除 `paths.output_dir` 下的项目产物目录

## LangChain 结构化输出策略

StoryForge 当前仍通过 LangChain 接入 DeepSeek。需要区分两条调用路径：

- 普通文本生成代码仍保留 `create_agent()` 实现
- 结构化生产主链路不再使用 `create_agent + ToolStrategy`，而是直接走 `with_structured_output(...)`

当前策略：

- `DeepSeek` 结构化任务使用 `ChatModel.with_structured_output(method="function_calling", include_raw=True)`
- `OpenAI / ChatGPT 5.4` 结构化任务使用 `ChatModel.with_structured_output(method="json_schema", include_raw=True)`
- 优先消费 LangChain 返回的 `parsed` Pydantic 对象
- 如果模型没有返回 tool call，但 raw content 是 JSON 或 Markdown JSON 代码块，会提取 JSON 后再做 Pydantic 校验
- 如果 parsed、tool call 和 raw JSON 都不存在，会抛出明确错误，让外层 structured retry 继续重试，最终将清晰失败原因写入任务记录
- 当前小说主流程实际调用的是 `backend.generate_structured(...)`；代码中的 `backend.generate(...)` / `create_agent()` 不是这条主链路的一部分

## 持久化

当前项目与任务元数据强制使用 MySQL 持久化。
没有可用 MySQL 时，StoryForge 不允许启动运行。
生产代码里不再保留可切换的内存 store 实现；内存版 store 仅存在于测试桩中，用于 API 单测隔离。

MySQL 实现位于：

- [`../src/storyforge/application/persistence/mysql_backend.py`](../src/storyforge/application/persistence/mysql_backend.py)
- [`../src/storyforge/application/persistence/mysql_projects.py`](../src/storyforge/application/persistence/mysql_projects.py)
- [`../src/storyforge/application/persistence/mysql_tasks.py`](../src/storyforge/application/persistence/mysql_tasks.py)
- [`../src/storyforge/application/persistence/mysql_utils.py`](../src/storyforge/application/persistence/mysql_utils.py)

当前执行队列本身仍然是进程内异步队列；虽然元数据落在 MySQL，但真正的消费队列还不是生产级持久化消息队列。

当前恢复策略：

- 服务启动时会扫描 MySQL 中仍处于 `running` 的任务
- 这些任务会被重排为 `queued`
- 已经落盘的 `result` 会被保留，用于前端继续展示已生成产物
- 这不是严格的幂等执行队列；如果外部模型已经接收过请求，重启后仍可能出现重复提交风险

生产环境仍建议替换为 Redis / Celery / Arq / TaskIQ 等真正持久化队列，并引入外部任务幂等键。

## 前端与静态资源

前端当前是原生 HTML / CSS / ES Module 结构，不使用 React。

关键模块：

- [`../src/storyforge/api/templates/console.html`](../src/storyforge/api/templates/console.html)
- [`../src/storyforge/api/static/app`](../src/storyforge/api/static/app)
- [`../src/storyforge/api/static/styles`](../src/storyforge/api/static/styles)

静态资源响应使用 `no-store`，避免浏览器缓存导致新旧 ES Module 混用。

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
