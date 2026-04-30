# 开发文档

本文档说明 StoryForge 的工程边界、维护规则、测试策略和目录卫生。产品使用看 [usage.md](usage.md)，接口字段看 [api.md](api.md)，系统结构看 [architecture.md](architecture.md)。

## 开发原则

- API 层只做请求校验、任务创建和响应组装。
- 业务规则放在 `domains/`，不要散落到 router 或前端。
- pipeline 负责编排阶段，domain service 负责领域判断。
- 模型服务 HTTP 细节放在 `integrations/`。
- 前端消费 artifacts API，不在页面层解析落盘 JSON。
- prompt、schema、validator 和 tests 必须围绕同一套当前生产结构维护。
- 删除代码前先确认没有 API、pipeline、测试或前端入口引用。

## 后端边界

应用层：

- `application/container.py`：装配配置、存储、队列和任务 handler。
- `application/task_runtime.py`：任务执行上下文。
- `application/task_handlers.py`：阶段任务入口。
- `application/tasks.py`：任务模型、任务队列和任务存储。
- `application/projects.py`：项目模型和项目存储。
- `application/project_deletion.py`：项目删除。

API 层：

- `api/main.py`：FastAPI 应用入口、CORS 和 `/outputs` 挂载。
- `api/routers/projects.py`：项目、阶段任务、prompt、正文和版本选择接口。
- `api/routers/tasks.py`：任务查询和 artifacts 查询。
- `api/artifacts.py`：工作台聚合数据。
- `api/serializers.py`：项目和任务响应序列化。
- `api/schemas.py`：HTTP 请求和响应模型。

小说域：

- `domains/novel/service.py`：小说生成和结构化入口。
- `domains/novel/contracts.py`：小说结构合同。
- `domains/novel/prompts.py`：小说 prompt。
- `domains/novel/repair.py`：结构化结果修补。
- `domains/novel/rules.py`：小说结构规则。

视频域：

- `domains/video/service.py`：视频域统一服务入口。
- `domains/video/chapter_orchestration.py`：章节事件和 scene 规划。
- `domains/video/chunk_orchestration.py`：chunk 和 segment 合同规划。
- `domains/video/chapter_event_validation.py`：章节事件覆盖和粒度校验。
- `domains/video/structure_validation.py`：scene、chunk 和转场合同校验。
- `domains/video/segment_validation.py`：segment 容量、时长、对白和镜头校验。
- `domains/video/prompting.py`：planner、media、repair prompt。
- `domains/video/planning.py`：媒体任务构建和 manifest 装配。
- `domains/video/materialization.py`：规划产物物化。
- `domains/video/repair.py`：连续性修复。
- `domains/video/text_rules.py`：文本规则、推进词和相似度工具。

Pipeline 层：

- `pipelines/story_pipeline.py`：小说生成 pipeline。
- `pipelines/video_planning.py`：场景结构和分段合同 pipeline。
- `pipelines/video_pipeline.py`：角色图、场景母图、视频和合并 pipeline。

## 前端边界

React 前端位于 `frontend/`。

主要模块：

- `src/app/router.tsx`：路由。
- `src/api/`：后端 API client。
- `src/features/landing/`：首页。
- `src/features/projects/`：项目库和小说转视频。
- `src/features/workspace/`：项目工作台和六个生产区块。
- `src/components/`：通用按钮、状态和壳组件。
- `src/styles/`：主题、首页、项目库、创作器和工作台样式。
- `src/types/`：项目、任务、artifact、正文类型。

维护要求：

- 页面容器负责路由、查询和状态分发。
- 业务展示逻辑放到 feature 或 section 模块。
- API endpoint 集中在 `src/api/`。
- query key 统一走 `src/api/queryKeys.ts`。
- 新交互必须有 disabled、loading、错误提示和成功后数据刷新。

## Prompt 维护

小说 prompt：

- 以 `story_source.json` 为真源。
- 角色名、cast slot 和 source evidence 必须稳定。
- 不从 brief 直接假设固定角色人数。

视频 planner prompt：

- 只输出 schema 需要的字段。
- scene 必须写清地点、时间、天气、光线、空间布局、背景锚点和固定道具。
- segment 必须写清开场、推进、收束、时长、动作容量和对白预算。

媒体 prompt：

- 角色图 prompt 只描述单角色定妆图。
- 场景母图 prompt 只描述无人物空场景。
- 视频 prompt 只描述当前 segment 的连续表演、镜头、声音、字幕和收束。
- Seedance 最终提交 prompt 必须按真实参考图顺序写清 `图片1 / 图片2 / 图片3`。

修复 prompt：

- 修复 scene 或 segment 合同，不重写整个故事。
- 修复后必须重新物化相关 plan 和 manifest。

## 测试

后端检查：

```bash
uv run ruff check src/storyforge tests
uv run pytest
```

前端检查：

```bash
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
```

补丁检查：

```bash
git diff --check
```

测试维护要求：

- API 行为改动要补 `tests/test_api.py` 或独立 API 测试。
- pipeline 规则改动要补 `tests/test_pipelines.py` 或对应集成测试。
- Seedream / GPT Image 2 / Seedance 请求格式改动要补集成测试。
- 前端 API client、模型函数和关键 UI 状态要补 Vitest。
- 不保留与当前产品无关的测试夹具。

## 目录卫生

- 不提交 `.env`、`outputs/`、缓存、构建产物和本地日志。
- Python 缓存目录 `__pycache__` 应清理。
- 前端构建产物 `frontend/dist/` 不进仓库。
- 测试临时文件放 `tests/.tmp*`。
- 临时探针和一次性脚本不进入正式代码目录。

## 提交前检查

1. `git status --short` 确认改动范围。
2. `rg` 扫失效字段、废弃入口和无效文案。
3. 跑相关 Python 和前端测试。
4. 跑 `git diff --check`。
5. 文档只写当前产品事实，不写过程记录。
