# 开发文档

这份文档面向维护 StoryForge 代码库的开发者。  
它关注“代码应该怎么改、改到哪里、如何验证”，而不是业务使用方法。

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
- [`../src/storyforge/domains/novel/fallbacks.py`](../src/storyforge/domains/novel/fallbacks.py)
- [`../src/storyforge/domains/novel/repair.py`](../src/storyforge/domains/novel/repair.py)
- [`../src/storyforge/domains/novel/rules.py`](../src/storyforge/domains/novel/rules.py)

维护约定：

- 小说链路先走 `Story Drafter`，再走 `Cast Analyzer`
- 角色结构不要再直接从 brief 主分析，优先基于已生成小说草稿解析
- prompt 模板统一放 `prompts.py`
- 结构化输出 schema 统一放 `schemas.py`
- 角色卡必须显式保留 `cast_slot_id`，不要只靠数组顺序猜测主角和配角对应关系
- 新的 deterministic 结果放 `fallbacks.py`
- 新的纠偏逻辑放 `repair.py`
- 新的 brief 启发规则放 `rules.py`，但它们只做 fallback / repair，不做主分析
- 不要再把 fallback / repair / heuristics 塞回 `service.py`

### 小说 Prompt 维护约定

当前小说 prompt 采用统一分层：

1. `system_prompt`
   只定义该 Agent 的角色和职责，不堆具体业务细则
2. `user_prompt`
   携带项目上下文、上游结构化结果和当前阶段硬约束
3. `schema`
   约束返回结构
4. `repair`
   兜底处理 LLM 漏字段、顺序错位、泛称映射错误等问题

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
5. 每个 slot 都应尽量保留 `source_evidence`
6. `Character Designer` 必须一一消费这些 slot，并回填 `cast_slot_id`
7. 角色正式名字必须全表唯一；该约束由 `CharacterRosterSchema` 强制校验
8. 如果 LLM 输出同名角色，必须直接触发 structured retry；重试仍失败就显式报错，不再本地偷偷改名
9. `Chapter Planner` 必须以小说草稿的真实章节事件为事实基础，不要重新发明章节顺序
10. 当前 `story_source` 就是正文真源；结构化分析阶段不再额外重写章节正文
11. 一旦 repair 后的 `story_shape` 已明确为 `single_lead_with_supporting_cast` 或 `ensemble`，不要再让 heuristics 把它强行改回双主角
12. live LLM 模式下，结构化输出如果坏 JSON、缺失 structured parsed 结果、返回空结构或 schema 校验失败，最多重试 3 次；仍失败就直接抛错，不再 silent fallback
13. 运行时不要再依赖 DryRun；如果缺少 DeepSeek 配置，应明确报错。测试如需 deterministic backend，必须在测试代码里显式 patch 注入

如果未来再遇到“明明是多角色故事，却只被压成一个或两个人”的问题，优先检查：

1. `build_story_drafter_user_prompt`
2. `build_cast_user_prompt`
3. `CastAnalysisSchema`
4. `_repair_cast_analysis`
5. `_fallback_cast_analysis`

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
- fallback 与任务装配放 `planning.py`
- pipeline facade 不要重新堆积辅助函数

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
  保留 prompt、schema、fallback、repair 的维护约定
- `docs/status.md`
  保留当前状态、限制和路线图

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

## 本地开发命令

启动 Web / API：

```bash
uv run storyforge api serve
```

需要调前端样式或接口热加载时，可以临时使用 `--reload`。不要在真实图片 / 视频长任务执行时使用 `--reload`，否则保存文件会触发服务重启，导致任务被中断并重新排队。

运行 demo brief。该命令同样需要真实 DeepSeek 配置：

```bash
uv run storyforge pipeline demo
```

使用自定义 brief：

```bash
uv run storyforge pipeline build --brief path/to/story.toml --llm
```

如果 DeepSeek 走自定义兼容网关，也可以只在 `.env` 里配置：

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

## 当前优先开发方向

建议优先级：

1. 生产级持久化执行队列
2. Seedance 下载器 / 对象存储适配
3. 生产级任务治理、幂等与失败恢复
4. 更强的角色一致性 / 声音一致性控制

## 已知实现约定

- 结构化 LLM 输出仍然通过 LangChain 实现，但不要再回到 `create_agent + ToolStrategy` 做小说结构化输出；当前使用 `ChatModel.with_structured_output(method="function_calling", include_raw=True)`，优先消费 parsed 结果，必要时回收 raw JSON 文本，由 StoryForge 外层负责 3 次 structured retry。
- 阶段接口应尽量具备幂等保护；当前 `project.story_analysis` 会按 `source_task_id + story_source_revision` 复用已有 queued / running / completed 任务，避免重复结构化。
- `SeedanceManifest.title` 只能表示故事标题，不能写成 `segment_video_manifest` 这类文件用途名；读取旧产物时应优先从 `novel_package.json` / `story_source.json` 恢复标题。
- 任务失败原因必须写入 `TaskRecord.error` / MySQL `error_text`，前端依赖该字段展示失败信息。
- 服务启动时会把残留 `running` 任务重新排回 `queued`；这只是开发期恢复策略，不等价于生产级幂等队列。

## 相关文档

- [README](../README.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
