# 开发文档

这份文档面向维护 StoryForge 代码库的开发者。  
它关注“代码应该怎么改、改到哪里、如何验证”，而不是业务使用方法。

这里不重复系统分层图、接口示例或路线图：

- 模块边界：看 [architecture.md](architecture.md)
- HTTP 接口：看 [api.md](api.md)
- 当前状态与下一步：看 [status.md](status.md)

## 开发原则

### 业务对象优先放 `domains/`

小说和视频的核心规则、schema、领域服务都应放在 `domains/`，不要直接依赖 FastAPI。

### 外部系统必须通过 `integrations/`

DeepSeek、Seedream、Seedance、ffmpeg、MySQL 等外部系统都应通过适配层接入，避免把网络调用散落到领域逻辑中。

### API 不承载业务规则

`api/` 只负责：

- 解析请求
- 调用应用层
- 返回响应

长任务、状态传播和结果合并都不应直接写进 router。

### 对外入口稳定，内部实现可以继续拆

如果某个 service / pipeline 变大，优先在内部继续拆模块，而不是先改公开入口。  
当前 `NovelGeneratorService` 和 `NovelToVideoService` 都采用了这个策略。

## 当前代码组织

### 应用层

- [`../src/storyforge/application/container.py`](../src/storyforge/application/container.py)
- [`../src/storyforge/application/tasks.py`](../src/storyforge/application/tasks.py)
- [`../src/storyforge/application/task_runtime.py`](../src/storyforge/application/task_runtime.py)
- [`../src/storyforge/application/task_handlers.py`](../src/storyforge/application/task_handlers.py)
- [`../src/storyforge/application/task_support.py`](../src/storyforge/application/task_support.py)

职责：

- 容器装配
- 任务分发
- 状态切换
- 结果传播
- 项目 / 任务存储

### 小说域

- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)
- [`../src/storyforge/domains/novel/prompts.py`](../src/storyforge/domains/novel/prompts.py)
- [`../src/storyforge/domains/novel/schemas.py`](../src/storyforge/domains/novel/schemas.py)
- [`../src/storyforge/domains/novel/repair.py`](../src/storyforge/domains/novel/repair.py)
- [`../src/storyforge/domains/novel/rules.py`](../src/storyforge/domains/novel/rules.py)
- [`../tests/_deterministic_novel_builders.py`](../tests/_deterministic_novel_builders.py)

维护约定：

- 小说链路先走 `Story Drafter`，再走 `Cast Analyzer`
- 角色结构不要再直接从 brief 主分析，优先基于已生成小说草稿解析
- prompt 模板统一放 `prompts.py`
- 结构化输出 schema 统一放 `schemas.py`
- 角色卡必须显式保留 `cast_slot_id`，不要只靠数组顺序猜测主角和配角对应关系
- 新的 deterministic 测试夹具放 `tests/_deterministic_novel_builders.py`
- 新的纠偏逻辑放 `repair.py`
- 新的 brief 启发规则放 `rules.py`，但它们只做 repair / 规则判断，不做主分析
- deterministic builders / repair / heuristics 与 `service.py` 分离维护

### 小说 Prompt 维护约定

当前小说 prompt 采用统一分层：

1. `system_prompt`
   只定义该 Agent 的角色和职责，不堆具体业务细则
2. `user_prompt`
   携带项目上下文、上游结构化结果和当前阶段硬约束
3. `schema`
   约束返回结构
4. `repair`
   负责字段规整、顺序校正、名称归一化和轻量修补

当前小说链路的顺序是：

1. `Story Architect`
2. `Story Drafter`
3. `Cast Analyzer`
4. `Character Designer`
5. `Chapter Planner`
6. `Editorial Reviewer`

如果要改“角色层级”“角色数量判断”“前两位角色顺序”“主配角关系图”这类行为，优先顺序必须是：

1. 先改 `Story Drafter` 是否把关键角色真实写进小说草稿
2. 再改 `Cast Analyzer` prompt 和 schema
3. 再改消费它的角色 / 章节 prompt
4. 最后才考虑是否补 heuristic 或 repair

不要反过来先堆关键词规则。

当前小说链路的默认约定是：

1. `Story Architect` 只负责项目底稿，不负责钉死最终角色结构
2. `Story Drafter` 先生成完整小说草稿
3. `Cast Analyzer` 再从小说草稿中抽取不可替代的角色指代，而不是直接靠 brief 主分析
4. 每个 slot 都必须保留 `brief_label`
5. 每个 slot 都应尽量保留 `source_evidence`，并优先写正文里可直接定位的裸名或稳定称呼
6. `Character Designer` 必须一一消费这些 slot，并回填 `cast_slot_id`
7. 角色正式名字必须全表唯一；该约束由 `CharacterRosterSchema` 强制校验
8. 如果 LLM 输出同名角色，必须直接触发 structured retry；重试仍失败就显式报错，并由模型重新生成有效角色名
9. `Chapter Planner` 必须以小说草稿的真实章节事件为事实基础，不要重新发明章节顺序
10. 当前 `story_source` 就是正文真源；结构化分析阶段直接分析这份正文
11. 一旦 repair 后的 `story_shape` 已明确为 `single_lead_with_supporting_cast` 或 `ensemble`，不要再让 heuristics 把它强行改回双主角
12. live LLM 模式下，结构化输出如果坏 JSON、缺失 structured parsed 结果、返回空结构或 schema 校验失败，最多重试 3 次；仍失败就直接抛错
13. 运行时要求真实 provider 配置；测试如需 deterministic backend，必须在测试代码里显式 patch 注入

如果未来再遇到“明明是多角色故事，却只被压成一个或两个人”的问题，优先检查：

1. `build_story_drafter_user_prompt`
2. `build_cast_user_prompt`
3. `CastAnalysisSchema`
4. `_repair_cast_analysis`
5. `tests/_deterministic_novel_builders.py::build_cast_analysis`

不要先在角色生成阶段偷偷补角色，也不要先在 brief 层堆关键词硬修。

### 视频域

- [`../src/storyforge/domains/video/service.py`](../src/storyforge/domains/video/service.py)
- [`../src/storyforge/domains/video/prompting.py`](../src/storyforge/domains/video/prompting.py)
- [`../src/storyforge/domains/video/repair.py`](../src/storyforge/domains/video/repair.py)
- [`../src/storyforge/domains/video/planning.py`](../src/storyforge/domains/video/planning.py)
- [`../src/storyforge/pipelines/video_pipeline.py`](../src/storyforge/pipelines/video_pipeline.py)
- [`../src/storyforge/pipelines/video_planning.py`](../src/storyforge/pipelines/video_planning.py)
- [`../src/storyforge/pipelines/video_support.py`](../src/storyforge/pipelines/video_support.py)
- [`../src/storyforge/pipelines/video_models.py`](../src/storyforge/pipelines/video_models.py)

维护约定：

- prompt 构造放 `prompting.py`
- LLM 输出修补放 `repair.py`
- 默认推导、规划产物路径/读取与任务装配放 `planning.py`
- pipeline facade 不要重新堆积辅助函数
- `build_video_project()` 只保留主流程编排；角色 profile、voice map、runtime scene、runtime segment 这类物化逻辑应继续下沉到内部 helper
- 运行时默认规划 helper 与测试静态构造逻辑分开维护；测试夹具放 `tests/`，不要回流到 `planning.py`
- 视频域的普通 structured retry 与 strict repair retry 应继续共用同一套重试执行 / retry request builder，不要再分叉出第三套重试模板

### 视频 Prompt 维护约定

当前视频 prompt 不是一坨总 prompt，而是分层维护：

1. 结构化规划 prompt
2. 本地富化 / 媒体 prompt
3. 连续性修复 prompt
4. 共享规则块

核心文件：

- [`../src/storyforge/domains/video/prompting.py`](../src/storyforge/domains/video/prompting.py)

当前运行时主链路真正使用的规划 prompt 只有这 3 个：

1. `_build_chapter_scene_planner_user_prompt`
   只产出当前章节的 `scenes`
2. `_build_scene_chunk_planner_user_prompt`
   只产出当前 `scene` 的 `chunks`
3. `_build_scene_segment_contract_user_prompt`
   只产出当前 `chunk` 的 `segment contracts`

这 3 个 prompt 的边界不要混：

- `chapter scene planner` 不要输出 `segments`
- `scene chunk planner` 不要输出任何图片 / 视频 prompt
- `scene segment contract planner` 不要输出 `scene_prompt / start_frame_prompt / mid_frame_prompt / end_frame_prompt`
- 关键帧 prompt、Seedance prompt、角色定妆 prompt 应由后面的本地富化阶段生成，不要重新塞回 segment contract planner

当前本地富化 / 媒体 prompt 主要包括：

1. `_build_character_sheet_prompt`
   角色三视图定妆图 prompt
2. `_build_scene_master_frame_prompt`
   无角色空场景母图 prompt
3. `_build_seedance_clip_prompt`
   单段视频 prompt

当前修复类 prompt 主要包括：

1. `_build_segment_continuity_repair_user_prompt`
   单段连续性合同修复
2. `_build_scene_continuity_repair_user_prompt`
   单 scene 场景基线修复

当前共享规则块主要包括：

1. `_scene_bible_rule_block`
   统一约束 `scene_bible` 只写环境基线，不写剧情分析
2. `_frame_character_rule_block`
   统一约束帧级出镜角色必须是 `involved_characters` 子集
3. `_segment_audio_budget_rule_block`
   统一约束时长、对白、字幕和 `timed_beats`
4. `_segment_continuity_rule_block`
   统一约束相邻 segment 承接推进
5. `_structured_output_guardrail_line`
   统一约束“只返回结构化结果，不要解释，不要 Markdown”

如果你要改视频 prompt，优先顺序必须是：

1. 先判断改动属于哪一层：
   - 场景拆分：改 `chapter scene planner`
   - scene 内切段：改 `scene chunk planner`
   - 单段合同：改 `scene segment contract planner`
   - 图片 / 视频生成文案：改本地富化 prompt
   - 连续性补救：改 repair prompt
2. 再判断是否应该改共享规则块，而不是在 3 个 planner prompt 里各复制一份
3. 最后才考虑补 validator、repair 或后处理

当前视频 prompt 的硬约定是：

1. planner prompt 只保留任务语义、少量硬约束和紧凑上下文 JSON，字段清单交给 schema 与 validator
2. 字段契约优先交给 structured schema、validator 和 repair 层
3. `story memory`、`scene`、`chunk`、`exit state` 上下文统一走紧凑 JSON，不要再随手 `indent=2` 拉长 prompt
4. `scene -> chunk -> segment` 的信息边界不能回退成“大一统全章总规划”
5. 同一规则不要同时写在 prompt 正文、retry note、repair prompt 和 post-process 里各一份

当前与控长直接相关的 helper 包括：

1. `_prompt_json`
   把上下文压成紧凑 JSON，减少 token 浪费
2. `_build_story_memory_prompt_context`
   只挑当前阶段真正需要的 `story_memory` 视图
3. `_build_chapter_segment_directive`
   生成章节目标、摘要、正文摘录
4. `_build_scene_prompt_focus_terms`
   从当前 `scene / chunk` 抽焦点词，避免整章长摘录直接灌入
5. `_excerpt_relevant_text`
   只截与当前焦点相关的正文片段

如果未来再遇到这些问题，优先检查位置如下：

1. `finish_reason='length'`
   先看 `_build_story_memory_prompt_context`、`_build_chapter_segment_directive`、`_prompt_json`
2. scene / segment 顺序乱
   先看 `_build_scene_chunk_planner_user_prompt`、`_build_scene_segment_contract_user_prompt`
3. 相邻片段重复、像重新开演
   先看 `_segment_continuity_rule_block`，再看 `repair.py` 和 `service.py` 里的 validator
4. 对白 / 字幕说不完
   先看 `_segment_audio_budget_rule_block`，再看 `service.py` 的时长校验和 repair retry
5. 帧里塞了没出镜的人
   先看 `_frame_character_rule_block`，再看 schema 和 validator
6. 帧角色字段空了但系统还在往下跑
   先看 `service.py` 的 `start_frame_characters / mid_frame_characters / end_frame_characters` validator；当前运行时按帧级角色字段严格校验，缺失会直接触发 structured retry / fail-fast

当前运行时使用的 planner 主链路就是这 3 个活跃 prompt。新需求直接改这 3 个 planner prompt，不要额外再开一套并行总规划写法。

### 任务阶段处理维护约定

- [`../src/storyforge/application/task_handlers.py`](../src/storyforge/application/task_handlers.py) 负责阶段入口编排，不要在每个 handler 里重复拼装相同的 `partial_response`
- 阶段启动、阶段中途进度持久化、阶段完成后的关联任务同步，优先复用 `task_handlers.py` 内部共享 helper
- 关联任务同步要明确区分两类语义：
  - 全量结果传播：使用共享结果回写
  - 局部重跑后的产物版本刷新：只刷新 `artifact_revision`
- 如果以后再新增 `project.*` 阶段任务，优先复用现有阶段 helper，而不是再复制一份 handler 模板

## 文档维护原则

- `README.md`
  只保留 GitHub 首页必需内容
- `docs/usage.md`
  保留安装、配置和实际使用方式
- `docs/api.md`
  保留 HTTP 接口
- `docs/architecture.md`
  保留分层和模块关系
- `docs/development.md`
  保留 prompt、schema、deterministic test builders、repair 的维护约定
- `docs/status.md`
  保留当前状态、限制和路线图
- “技术栈 / Agent 定位”这类信息统一收敛到 `README.md` 与对应正式文档中

新增功能时，至少要同步：

1. `README.md` 中的能力边界
2. 对应子文档
3. 必要的测试

## 测试与校验

静态检查：

```bash
uv run ruff check src/storyforge tests
```

运行全部测试：

```bash
uv run pytest
```

只跑关键测试：

```bash
uv run pytest tests/test_api.py tests/test_pipelines.py
```

测试维护约定：

- 跨 `segment` 的连续性修复、局部重跑、合并保留类测试，不要依赖 deterministic planner “默认刚好产出几段”
- 这类测试应显式构造所需的 `segment_plan / scene_plan / scene_image_manifest / seedance_manifest` 夹具，只验证目标行为本身
- 可复用的视频产物夹具优先收敛到 [`../tests/_video_test_artifacts.py`](../tests/_video_test_artifacts.py)，不要继续把长段 JSON 改写逻辑堆回 `tests/test_pipelines.py`
- 常用状态流转优先抽成命名明确的 helper，例如：`补第二段执行合同`、`scene image 完成态`、`seedance clip 完成态 / 可合并态`、`首个 scene+video 失败态`
- 运行态对象的状态流转也按同样规则处理；不要在测试里零散手写 `generated_url / scene_master_frame_url / downloaded_path / submit_status / remote_status` 这类回写

## 本地开发命令

启动 Web / API：

```bash
uv run storyforge api serve
```

需要调前端样式或接口热加载时，可以临时使用 `--reload`。不要在真实图片 / 视频长任务执行时使用 `--reload`，否则保存文件会触发服务重启，导致任务被中断并重新排队。

如果 DeepSeek 走自定义 OpenAI 风格网关，也可以只在 `.env` 里配置：

```bash
DEEPSEEK_BASE_URL=...
```

## 提交前检查

推荐顺序：

1. `uv run ruff check src/storyforge tests`
2. `uv run pytest`
3. 检查 README 和对应文档是否同步

也可以直接运行：

```bash
scripts/check.sh
```

## 目录卫生

清理本地产物：

```bash
scripts/clean-local-artifacts.sh --dry-run
scripts/clean-local-artifacts.sh
```

深度清理：

```bash
scripts/clean-local-artifacts.sh --deep
```

## 已知实现约定

- 结构化 LLM 输出仍然通过 LangChain 实现，但这里说的是生产主链路，不是整个 backend 都不用 `create_agent`。当前小说结构化阶段按 provider 区分：`DeepSeek` 使用 `ChatModel.with_structured_output(method="function_calling", include_raw=True)`，`OpenAI / ChatGPT 5.4` 使用 `ChatModel.with_structured_output(method="json_schema", include_raw=True)`；优先消费 parsed 结果，必要时回收 raw JSON 文本，由 StoryForge 外层负责 3 次 structured retry；`create_agent()` 只保留给普通文本生成实现。
- 阶段接口应尽量具备幂等保护；当前 `project.scene_structure` 与 `project.segment_contracts` 都会按 `source_task_id + story_source_revision` 复用已有 queued / running / completed 任务，避免重复结构化。
- `SeedanceManifest.title` 只能表示故事标题，不能写成 `segment_video_manifest` 这类文件用途名；读取产物时应优先从 `novel_package.json` / `story_source.json` 恢复标题。
- 任务失败原因必须写入 `TaskRecord.error` / MySQL `error_text`，前端依赖该字段展示失败信息。
- 服务启动时会把残留 `running` 任务重新排回 `queued`；这只是开发期恢复策略，不等价于生产级幂等队列。

## 相关文档

- [README](../README.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
