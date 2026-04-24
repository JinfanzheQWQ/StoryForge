# 架构文档

这份文档描述 StoryForge 的系统分层、核心工作流和模块边界。

配套文档：

- 使用方式见 [usage.md](usage.md)
- 接口说明见 [api.md](api.md)
- 开发约定见 [development.md](development.md)
- 工程状态见 [status.md](status.md)

## 设计目标

StoryForge 不是单次 prompt 演示，而是一套可拆阶段、可审阅、可恢复、可追踪的小说到视频生产链路。

当前设计目标：

1. 先生成可编辑的小说正文
2. 再把正文转成结构化视频规划
3. 再基于统一合同生成图片与视频
4. 通过 Web、API 和 CLI 暴露统一入口

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
  - run_story_generation_pipeline
  - run_story_scene_structure_pipeline
  - run_story_segment_contracts_pipeline
  - run_character_image_pipeline
  - run_scene_image_pipeline
  - run_video_render_pipeline
          |
          v
Domain Services
  - NovelGeneratorService
  - NovelToVideoService
          |
          v
Integrations
  - LangChain chat backend
  - Seedream
  - Seedance
  - ffmpeg
  - MySQL
```

## 阶段任务模型

StoryForge 当前把整条链路拆成这些阶段任务：

- `project.story`
- `project.scene_structure`
- `project.segment_contracts`
- `project.continuity_repair`
- `project.continuity_repair_batch`
- `project.characters`
- `project.scenes`
- `project.videos`

统一原则：

- API 负责接收请求并返回 `task_id`
- 后台队列负责执行、状态切换和结果持久化
- 同一 story run 的阶段任务共享同一个输出目录
- 所有产物以文件落盘，并通过任务结果返回给前端

## 小说工作流

小说工作流位于：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)

当前采用结构化多 Agent 流程：

1. `Story Architect`
2. `Story Drafter`
3. `Cast Analyzer`
4. `Character Designer`
5. `Chapter Planner`
6. `Editorial Reviewer`

对应阶段边界：

- `project.story`
  生成并保存 `story_source.json`
- `project.scene_structure`
  基于当前正文生成角色、章节、scene skeleton 与视频基础规划
- `project.segment_contracts`
  基于 scene skeleton 生成正式 segment contracts 与媒体 manifest

核心约定：

- `story_source.json` 是正文真源
- 角色、章节和场景结构都基于正文解析
- `Cast Analyzer` 负责核心角色槽位与正文证据抽取
- `Character Designer` 严格消费 `cast_slot_id`
- repair 层只做字段规整、顺序校正和名称归一化
- schema 层负责角色名唯一、`cast_slot_id` 唯一和结构完整性

小说域内部拆分：

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)
- [`../src/storyforge/domains/novel/prompts.py`](../src/storyforge/domains/novel/prompts.py)
- [`../src/storyforge/domains/novel/schemas.py`](../src/storyforge/domains/novel/schemas.py)
- [`../src/storyforge/domains/novel/repair.py`](../src/storyforge/domains/novel/repair.py)
- [`../src/storyforge/domains/novel/rules.py`](../src/storyforge/domains/novel/rules.py)

## 视频规划工作流

视频链路不是一次性长视频生成，而是“规划 -> 关键帧 -> 视频片段 -> 手动合并”的分段式工作流。

当前主规划结构：

```text
chapter -> scene -> chunk -> segment
```

核心规划文件：

- `story_memory.json`
- `scene_plan.json`
- `segment_plan.json`
- `scene_structure_source.json`
- `segment_contract_progress.json`
- `continuity_report.json`

阶段职责：

- `project.scene_structure`
  生成 `story_memory.json`、`character_visual_bible.json` 和第一版 `scene_plan.json`
- `project.segment_contracts`
  生成正式 `scene_plan.json`、`segment_plan.json`、媒体 manifest 和连续性报告

当前视频规划链路：

1. `Chapter Event Planner`
   先从当前章节正文抽取 must-cover 关键事件；如果单个 event 已经合并了过多推进阶段，会在这一层直接失败重试并要求拆细
2. `Chapter Scene Planner`
   再生成当前章节的 `scene skeleton`，并为每个 scene 回填 `covered_event_ids`、紧凑版 `covered_event_summaries` 与 `scene_transition_contract`；prompt 会显式要求不要把过多相邻关键事件一口吞进同一个 scene
3. `Scene Chunk Planner`
   只生成当前 `scene` 的连续 chunks，并要求首个 chunk 消费跨 scene 过渡合同；prompt 与结构化校验都会同时读取当前 scene 绑定的 `covered_event_ids + covered_event_summaries`，提前拦截把后续 scene 关键推进偷写进本 scene 的越界 chunk；同时会校验 `must_cover / transition_goal` 与 `expected_segment_count` 是否匹配，提前拦截动作容量明显过载的 chunk；如果常规重试后仍卡在动作容量过载，会自动进入一次 `video-scene-chunk-repair`，只定向修当前失败 chunk
4. `Scene Segment Planner`
   只生成当前 chunk 的 `segment contracts`，并要求首个 segment 把 scene 级 entry state 落到 `opening_match / timed_beats`；同时会按 `timed_beats` 校验时长预算、动作容量和关键帧距离，必要时在当前 chunk 内直接触发结构化重试拆段；如果常规重试后仍卡在某个 segment 的尾部 beat 覆盖不完整，会自动进入一次 `video-scene-segment-timeline-repair`；如果仍卡在某个 segment 的动作容量过载，会自动进入一次 `video-scene-segment-action-repair`
5. `本地 Prompt 组装`
   本地补齐图片 / 视频阶段需要的 prompt 字段

这样拆分的目的：

- 先把“这章必须发生的事”固定下来，避免 scene 规划在章节中途提前收束
- 把长篇正文压缩成章节批次视图
- 让 LLM 单次只处理当前 scene 或当前 chunk
- 用本地富化降低重复字段输出
- 为失败恢复保留更细粒度 checkpoint

scene skeleton 的额外硬约束：

- 每个 scene 必须输出 `covered_event_ids`
- 每个 scene 会额外保留紧凑版 `covered_event_summaries`，供后续 chunk planner / repair / 边界校验复用
- 非首个 scene 必须输出合法的 `scene_transition_contract`
- 所有 scene 的 `covered_event_ids` 拼接后，必须与章节关键事件顺序完全一致
- 单个 scene 只能覆盖连续事件块
- 最后一个 scene 必须覆盖章节最后一个关键事件
- 如果 scene 漏掉章节后半段事件，结构化阶段会直接失败重试
- `scene_plan.json` 保留 `scene_transition_contract` 与 `covered_event_summaries`，scene 级边界信息

## 视频域代码结构

视频域服务入口是 [`../src/storyforge/domains/video/service.py`](../src/storyforge/domains/video/service.py)。它负责初始化、公开入口、主流程编排、逐章规划调度和 plan 后处理。

核心模块职责：

- `chapter_orchestration.py`：章节事件规划、章节 scene 规划和 `chapter -> scene` 展开编排。
- `chunk_orchestration.py`：scene chunk 规划、segment contract 规划、合同归一化、跨 chunk 承接状态和定向 repair 编排。
- `chapter_event_validation.py`：章节事件覆盖、事件粒度、正文定位、章节正文读取和 targeted split 校验。
- `structure_validation.py`：scene / chunk / transition 结构校验、角色视觉表校验、软放行与重复 / 落点 / 边界判定。
- `segment_validation.py`：segment contract 与 segment plan 总体验证，包括时长预算、`timed_beats` 覆盖、关键帧语义距离、方向一致性和多人特写冲突。
- `structured_generation.py`：结构化 LLM 调用、重试循环、prompt metrics 注入和 response coercion。
- `structured_retry_prompts.py`：结构化 retry 文案 builder 和按错误类型追加的修复提示。
- `prompting.py`：planner prompt、media prompt、repair prompt 和共享规则块。
- `repair.py`：LLM 输出修补、continuity repair 入口、repair report 组装、repair 结果校验和 plan 重建。
- `enrichment.py`：首帧 / 尾帧本地 prompt、音效和音乐方向补全。
- `materialization.py`：chapter scene、scene segment、帧角色校验、角色 profile、voice map、runtime scene / segment 与修复结果回写物化。
- `planning.py`：默认推导、story memory、媒体任务构建、规划产物路径 / 读取与任务装配。
- `text_rules.py`：文本相似度、推进点、边界词、方向词等共用规则。

## 场景一致性与连续性合同

视频规划的核心合同由三层构成：

- `scene_transition_contract`
  锁定当前 scene 如何从上一场进入，包括 entry match、bridge action 和 reveal 方式
- `scene_bible`
  锁定地点、时间、天气、光线、背景锚点、固定道具和空间布局
- `shot_state`
  锁定镜头景别、镜头推进、角色调度、动作推进和尾部状态
- `continuity_link`
  描述当前片段与上一段的承接关系、开场对齐要求和允许变化

此外，每个 scene 还会生成：

- `scene_master_frame`

`scene_master_frame` 的职责是：

- 作为无角色空场景母图
- 锁定背景环境、透视、光线和固定道具
- 为首帧 / 中段锚点帧 / 尾帧提供统一场景基线

关键帧与视频的执行链路：

```text
scene_master_frame
  + 当前帧角色图
  + 条件承接帧
  -> 场景关键帧
  -> Seedance 视频片段
```

补充说明：

- 同 scene 连续段如果命中复用条件，首帧可以直接复用上一段尾帧
- 非首个 scene 的首段不会跨 scene 直接复用上一场尾帧，但会把上一场最后一段尾帧作为额外 temporal anchor 带入首帧生图
- `hard_cut` 的 scene transition 不使用上一场尾帧 temporal anchor

帧级角色规则：

- `involved_characters` 表示该段剧情相关角色
- `start_frame_characters / mid_frame_characters / end_frame_characters` 表示对应关键帧实际出镜角色
- 生图阶段按帧选择参考图，不同帧只带当前出镜角色
- `mid_frame_mode=continuous` 表示中段仍是主镜头连续推进
- `mid_frame_mode=insert_cut` 表示中段是从主镜头短促切入的单人 / 局部插入镜头
- 如果首帧和尾帧是同一组双人 / 多人角色，而中段只保留其中一人，允许这种 `双人 -> 单人 -> 双人` 结构，但必须显式写 `mid_frame_mode=insert_cut`，并在节拍和运镜中写清“从主镜头切入，再切回主镜头”
- `shot_state.screen_direction` 必须与尾部 `end_state_lock / end_frame_prompt / 最后一条 timed_beats` 保持同一运动轴线；如果合同一边写“靠近镜头”，一边又写“背影远去 / 走向深处”，结构化阶段会直接判定为无效合同

## 连续性审校与修复

连续性体系由两层组成：

- `V1` 规则审校
- `V2` LLM 软审校

连续性报告文件：

- `continuity_report.json`

当前 `V1` 规则层除了 scene 内部连续性，也会检查 scene boundary：

- `scene_transition_contract` 记录的上一场退出状态，是否和上一场真实尾部漂移
- `next_scene_entry_match / bridge_action / visual_bridge` 是否过弱
- 当前 scene 首段的 `opening_match` 与前 1-2 拍是否真正消费了 scene 级过桥合同

当前可执行的修复任务：

- `project.continuity_repair`
  支持 `segment` 和 `scene` 两个 scope
- `project.continuity_repair_batch`
  按风险优先级分批修复多个目标

修复任务的产出特点：

- 回写合同与连续性报告
- 返回 `pending_media_actions`
- 由用户决定是否继续重生成场景母图、场景图或视频

## 媒体执行链路

媒体阶段主要使用这些文件：

- `character_image_manifest.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `seedream_character_execution.json`
- `seedream_scene_execution.json`
- `seedance_execution.json`

执行顺序：

1. 角色定妆图
2. scene 母图
3. segment 首帧 / 中段锚点帧 / 尾帧
4. Seedance 视频片段
5. 手动合并 `full_story.mp4`

Seedance 当前默认使用多模态参考图提交：

- 首帧 / 中段 / 尾帧会作为有顺序的 `reference_image`
- prompt 会用 `图片1 / 图片2 / 图片3` 显式绑定时间顺序，并收敛成“参考图 + 分阶段画面推进 + 音频字幕约束”的短版结构；其中 `画面推进` 会优先消费 `timed_beats` 的秒数与动作描述
- 如果当前段存在真实旁白或对白，`画面推进` 阶段行也会直接带入口播内容，而不只依赖单独的对白清单
- 与此同时，上游 `scene segment planner / segment continuity repair` 的 prompt 也会强制口播型片段把台词落进 `timed_beats`，这样下游视频 prompt 不需要再猜哪一拍发生了哪句口播
- 如果该段是非首个 scene 的首段，prompt 还会额外压入 `scene_transition_contract` 的 entry / bridge / audio bridge 短指令
- 如果完整多图组合被接口拒绝，才会逐步降级到更少参考图的合法组合
- 如果某段没有对白、旁白和字幕，Seedance prompt 会显式声明“无口播、无字幕、只保留环境音 / 拟音 / 音乐”，避免把静音动作段误提交成有字幕或有说话声的片段
- 本地自动生成的 `sound_effects` 只允许来自环境基线；手机、书包、花束等瞬时随身道具不会因为 `scene_bible.fixed_props` 被误写成环境拟音

执行作用域：

- `project.characters`
  生成角色图
- `project.scenes`
  支持整批、按 `scene_id`、按 `segment_id` 执行
- `project.videos`
  支持整批、按 `segment_id` 执行，以及 `merge_only=true`

## 失败恢复与幂等

结构化阶段的恢复核心是：

- `segment_contract_progress.json`
- `scene_structure_source.json`

恢复原则：

- checkpoint 按 `chapter -> scene -> chunk` 持续落盘
- `resume_from_progress=true` 时，系统从失败位置继续
- 已完成 chunk 不重复生成

任务幂等原则：

- 同一份正文 revision 的 `project.scene_structure` 会复用已有 queued / running / completed 任务
- 同一份正文 revision 的 `project.segment_contracts` 会复用已有 queued / running / completed 任务
- 同一 `segment_id` 或 `scene_id` 的局部任务会做 queued / running 级别的重复提交保护

## LangChain 结构化输出

StoryForge 当前通过 LangChain 接入结构化 LLM。

结构化主链路统一走：

- `backend.generate_structured(...)`

provider 策略：

- `DeepSeek`
  `with_structured_output(method="function_calling", include_raw=True)`
- `OpenAI / ChatGPT 5.4`
  `with_structured_output(method="json_schema", include_raw=True)`

结果消费顺序：

1. 优先读取 `parsed`
2. 尝试从 `raw` 中提取 JSON
3. 再执行一次普通 JSON 恢复调用
4. 失败则抛出明确错误，由外层 structured retry 处理

普通文本生成能力仍可使用 `create_agent()`，但结构化生产链路以 `with_structured_output(...)` 为主。

## 持久化与运行时

当前项目强制使用 MySQL 持久化项目和任务元数据。

相关模块：

- [`../src/storyforge/application/persistence/mysql_backend.py`](../src/storyforge/application/persistence/mysql_backend.py)
- [`../src/storyforge/application/persistence/mysql_projects.py`](../src/storyforge/application/persistence/mysql_projects.py)
- [`../src/storyforge/application/persistence/mysql_tasks.py`](../src/storyforge/application/persistence/mysql_tasks.py)
- [`../src/storyforge/application/persistence/mysql_utils.py`](../src/storyforge/application/persistence/mysql_utils.py)

当前队列形态：

- 元数据持久化在 MySQL
- 任务消费仍是进程内异步队列

服务启动时会把数据库中残留的 `running` 任务重新排回 `queued`。

## 前端结构

前端采用原生 HTML / CSS / ES Module。

关键目录：

- [`../src/storyforge/api/templates/console.html`](../src/storyforge/api/templates/console.html)
- [`../src/storyforge/api/static/app`](../src/storyforge/api/static/app)
- [`../src/storyforge/api/static/styles`](../src/storyforge/api/static/styles)

前端主要职责：

- 展示阶段任务状态
- 展示按 scene 分组的 segment 时间线
- 展示连续性风险与修复入口
- 提供局部生成、局部修复和总片合并入口

静态资源响应使用 `no-store`，避免浏览器缓存混入过期模块文件。

## 模块职责约定

- `domains/`
  放领域规则、schema、prompt 与领域服务
- `pipelines/`
  放跨领域的阶段编排与产物落盘
- `integrations/`
  放外部系统适配器
- `application/`
  放依赖装配、任务运行时和持久化
- `api/`
  放 HTTP 路由、模板和静态资源

## 扩展点

当前最明确的扩展方向：

- 增加新的 LLM provider
- 增加新的图像 / 视频 provider
- 将执行队列替换为持久化消息队列
- 接入对象存储
- 增加认证、权限与项目治理
