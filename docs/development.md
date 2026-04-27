# 开发文档

这份文档说明 StoryForge 的代码维护边界、prompt 维护方式、测试要求和目录卫生。产品使用看 [usage.md](usage.md)，接口字段看 [api.md](api.md)，系统结构看 [architecture.md](architecture.md)。

## 开发原则

- 业务规则优先放在 `domains/`，API 层只做请求解析、响应组装和任务入口。
- 外部 provider 访问必须通过 `integrations/`，不要把 HTTP 细节散落到业务层。
- pipeline 负责阶段编排，domain service 负责领域判断和结构化合同。
- artifacts API 返回页面需要的事实字段，前端不做业务推断。
- prompt、validator、schema 必须围绕同一套当前生产结构维护。
- 删除冗余代码时优先删无引用包装、重复文档和失效字段，不删除当前流程需要的失败保护。

## 代码边界

### 应用层

- `application/container.py`：装配配置、存储、队列和任务处理器。
- `application/task_runtime.py`：任务执行上下文与 handler 构建。
- `application/task_handlers.py`：项目阶段任务入口。
- `application/tasks.py`：任务记录、队列和任务状态。
- `application/projects.py`：项目记录和项目存储。

### API 层

- `api/main.py`：FastAPI 应用入口。
- `api/routers/projects.py`：项目、阶段任务、prompt 保存和重置接口。
- `api/routers/tasks.py`：任务查询接口。
- `api/artifacts.py`：产物索引、planned segment 展示数据、请求视图和 diagnostics 组装。
- `api/schemas.py`：HTTP 请求与响应模型。
- `api/static/app/`：Web 工作台前端模块。

### 小说域

- `domains/novel/service.py`：小说生成与结构化分析入口。
- `domains/novel/contracts.py`：小说结构化数据合同。
- `domains/novel/prompts.py`：小说阶段 prompt。
- `domains/novel/repair.py`：小说结构化结果修补。
- `domains/novel/rules.py`：小说结构化规则。

### 视频域

- `domains/video/service.py`：视频领域公开入口与主服务装配。
- `domains/video/chapter_orchestration.py`：章节事件与章节 scene 规划编排。
- `domains/video/chunk_orchestration.py`：scene chunk 和 segment contract 编排。
- `domains/video/chapter_event_validation.py`：章节事件覆盖和粒度校验。
- `domains/video/structure_validation.py`：scene、chunk、transition 结构校验。
- `domains/video/segment_validation.py`：segment 合同、动作容量、时长、运动合同和多人镜头校验。
- `domains/video/structured_generation.py`：结构化 LLM 调用与重试循环。
- `domains/video/structured_retry_prompts.py`：结构化重试提示构造。
- `domains/video/prompting.py`：视频 planner、media、repair prompt 和共享规则块。
- `domains/video/repair.py`：连续性修复入口和修复报告。
- `domains/video/materialization.py`：规划结果物化和 frame character 校验。
- `domains/video/planning.py`：媒体任务构建、默认值推导和规划产物读取。
- `domains/video/text_rules.py`：文本相似度、推进点、边界词、方向词等规则。

### Pipeline 层

- `pipelines/story_pipeline.py`：小说阶段 pipeline。
- `pipelines/video_planning.py`：场景结构和分段合同 pipeline。
- `pipelines/video_pipeline.py`：角色图、场景图、视频和合并 pipeline。

## Prompt 维护

### 小说 Prompt

小说 prompt 按阶段维护：

- 故事架构
- 正文生成
- 角色解析
- 角色设计
- 章节规划
- 审稿

维护要求：

- `story_source.json` 是正文真源，结构化分析必须以它为准。
- 角色分析需要保留可定位的 `source_evidence`。
- 角色名和 `cast_slot_id` 必须唯一。
- 角色视觉设计必须覆盖目标 cast slot，不从 brief 直接猜主角。

### 视频 Prompt

视频 prompt 分为三类：

- planner prompt：生成 scene、chunk、segment 合同。
- media prompt：生成角色图、场景母图和视频。
- repair prompt：修复 scene 或 segment 合同。

维护要求：

- planner 只输出当前阶段 schema 需要的字段。
- media prompt 只描述当前图片或视频真正需要的信息。
- 视频 prompt 只描述当前 segment 的场景运动、角色调度和音频。
- scene master frame 必须是无角色空场景参考图。
- Seedance prompt 必须按本次真实提交图片顺序写 `图片1 / 图片2 / 图片3`。
- 视频阶段不提交场景母图和角色图给 Seedance。
- 有对白、旁白和字幕时保留音频 / 字幕指令；无口播片段明确禁止字幕和念白。

## 前端维护

前端模块位于 `src/storyforge/api/static/app/`。

主要 render 模块：

- `render/detail.js`：项目详情入口。
- `render/detail_assets.js`：详情页 tab 路由和 helper 注入。
- `render/story_structure.js`：小说和结构页。
- `render/scene_workbench.js`：场景工作台。
- `render/segment_review.js`：分段审片台。
- `render/prompt_tools.js`：Prompt Editor、Request Inspector 和 prompt 展示工具。
- `render/timeline.js`：时间线界面。
- `render/timeline_data.js`：时间线数据归一化。
- `render/request_debug.js`：请求与调试页。
- `render/task_state.js`：阶段状态和按钮文案。
- `render/continuity_ui.js`：连续性风险展示。
- `render/document_assets.js`：文档和总片预览。
- `render/detail_common.js`：详情页通用展示 helper。

维护要求：

- 新 UI 优先落到对应模块，不把逻辑继续堆进 `detail_assets.js`。
- 按当前选中的单个 asset 展示 prompt 和请求参数，不同时展开多个无关点。
- 保存 prompt 与重做动作要区分清楚，避免普通生成事件截获“保存并重做”。
- Request Inspector 展示后端返回的真实请求视图，不在前端拼业务字段。

## 测试

常用检查：

```bash
uv run ruff check src/storyforge tests
uv run pytest
```

前端模块测试：

```bash
for test_file in tests/js/*.test.mjs tests/frontend/*.test.mjs; do node "$test_file"; done
```

针对性开发时优先跑受影响测试，再跑全量检查。

## 提交前检查

- `git status --short` 确认改动范围。
- `git diff --check` 检查空白和补丁格式。
- 跑相关 Python / Node 测试。
- 文档只写系统事实、操作方式和维护约定。
- 不提交 `outputs/`、`.env`、缓存文件或本地开发日志。

## 目录卫生

- 生产输出放在配置的 output root。
- 示例输入放 `examples/`。
- 文档图片放 `docs/assets/`。
- 测试 fixture 放 `tests/`。
- 不新增临时调试脚本；需要时放到临时目录并在提交前删除。

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [产品状态](status.md)
