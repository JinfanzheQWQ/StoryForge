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

- 角色结构先走 `Cast Analyzer`，不要再让 heuristics 主导角色数量、角色层级和关系双方判断
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
2. `Cast Analyzer`
3. `Character Designer`
4. `Chapter Planner`
5. `Chapter Writer`
6. `Editorial Reviewer`

如果要改“角色层级”“角色数量判断”“前两位角色顺序”“主配角关系图”这类行为，优先顺序必须是：

1. 先改 `Cast Analyzer` prompt 和 schema
2. 再改消费它的角色 / 章节 prompt
3. 最后才考虑是否补 heuristic 或 repair

不要反过来先堆关键词规则。

当前 `Cast Analyzer` prompt 的默认约定是：

1. 先抽取 brief 中所有不可替代的角色指代
2. 再判断 story shape，而不是先按“双主角模板”猜结构
3. 每个 slot 都必须保留 `brief_label`
4. 每个 slot 都应尽量保留 `source_evidence`
5. `Character Designer` 必须一一消费这些 slot，并回填 `cast_slot_id`
6. 一旦 repair 后的 `story_shape` 已明确为 `single_lead_with_supporting_cast` 或 `ensemble`，不要再让 heuristics 把它强行改回双主角

如果未来再遇到“明明是多角色故事，却只被压成一个或两个人”的问题，优先检查：

1. `build_cast_user_prompt`
2. `CastAnalysisSchema`
3. `_repair_cast_analysis`
4. `_fallback_cast_analysis`

不要先在角色生成阶段偷偷补角色。

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
uv run storyforge api serve --reload
```

运行 demo：

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

1. 持久化执行队列
2. Seedance 下载器 / 对象存储适配
3. 生产级任务治理与失败恢复
4. 更强的角色一致性 / 声音一致性控制

## 相关文档

- [README](../README.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
