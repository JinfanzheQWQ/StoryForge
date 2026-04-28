# StoryForge

StoryForge 是一套把故事生产成中文剧情短视频的 Web 工作台。它把创作流程拆成可审阅、可修改、可重做的阶段：小说正文、场景结构、分段合同、角色定妆图、场景母图和分段视频。

系统不会把整条链路包装成黑盒。每个阶段都会写出结构化产物，页面可以查看当前 segment 的 prompt、真实提交参数、参考图绑定顺序、生成状态和失败原因，便于在继续消耗生图 / 生视频成本前做判断。

## 核心能力

- 根据 brief 生成小说正文，并在页面保存正文真源。
- 基于正文生成 `chapter -> scene -> chunk -> segment` 视频规划。
- 生成角色定妆图：白底三视图、单角色、统一风格，支持编辑 prompt 后重做。
- 生成 scene 级场景母图：无人物、无文字、纯环境参考图。
- 使用 Seedance 按“场景母图 + 可选上一段视频尾帧 + 出镜角色图 + motion prompt”生成中文剧情视频。
- 页面按当前选中的 segment 展示视频计划、motion prompt、提交请求、参考图绑定和媒体状态。
- 支持单角色、单 scene、单 segment、单阶段重做。
- 使用 MySQL 保存项目、任务、run 记录和产物索引。

## 生产流程

1. 创建项目并生成小说。
2. 审阅并保存正文。
3. 生成场景结构。
4. 生成分段合同。
5. 生成角色图。
6. 生成场景母图。
7. 按 segment 生成视频。
8. 合并已完成视频片段。

## 媒体模型

- 生图模型：`doubao-seedream-4-5-251128`
- 生视频模型：`doubao-seedance-2-0-260128`

场景母图只负责锁定地点、空间透视、光线、背景锚点和固定道具。角色图只负责锁定角色身份、脸、发型、服装、体型和年龄感。视频 prompt 负责描述角色在场景中的运动轨迹、动作状态、镜头调度、声音、字幕和收束状态。

Seedance 提交时会在请求中明确列出参考图顺序。场景母图不是时间帧；上一段视频尾帧如果存在，只作为当前片段开场时间锚点；角色图不是时间锚点。

## 快速开始

安装依赖：

```bash
uv sync
```

创建环境变量文件：

```bash
cp .env.example .env
```

配置必要密钥：

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=...
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://api.openai.com/v1
SEEDREAM_API_KEY=...
SEEDREAM_BASE_URL=...
SEEDANCE_API_KEY=...
SEEDANCE_BASE_URL=...
STORYFORGE_DB_PASSWORD=...
```

启动 Web 工作台和 API：

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

`--reload` 只适合调前端样式或接口。运行 Seedream / Seedance 长任务时不要使用热重载。

## 工作台

- 创建页：输入 brief、选择 LLM provider、创建项目。
- 小说页：查看、修改并保存正文真源。
- 场景工作台：查看 scene 分组、场景母图状态、空间连续性和风险提示。
- 角色页：查看角色定妆图、编辑角色 prompt、生成候选图并选择是否替换。
- 分段审片台：只显示当前选中的 segment，集中展示视频、prompt、请求参数、参考图和重做入口。
- Prompt Editor：编辑当前 segment 的场景母图 prompt 或视频 prompt。
- Request Inspector：查看当前媒体任务真实提交 payload、参考图顺序和 provider 请求摘要。
- 作品库：查看当前项目的图片、视频、文档和合并总片。

## 核心产物

- `story_source.json`：可编辑正文真源。
- `novel_package.json`：小说包与章节正文。
- `story_memory.json`：故事连续性记忆。
- `character_visual_bible.json`：角色视觉设定。
- `scene_plan.json`：scene 结构、空间合同和场景母图信息。
- `segment_plan.json`：segment 执行合同、motion 计划和 prompt。
- `character_image_manifest.json`：角色图任务清单与结果。
- `scene_image_manifest.json`：场景母图任务清单与结果。
- `seedance_manifest.json`：视频任务清单、参考图绑定、提交 prompt 和结果。
- `continuity_report.json`：结构风险和连续性诊断。
- `assets/characters/`：角色图。
- `assets/frames/`：场景母图。
- `rendered/`：分段视频和合并视频。

## API

常用接口：

- `POST /v1/projects/novel`
- `POST /v1/projects/scene-structure`
- `POST /v1/projects/segment-contracts`
- `POST /v1/projects/characters`
- `PUT /v1/projects/{project_id}/character-prompts/{source_task_id}/{character_name}`
- `POST /v1/projects/scenes`
- `POST /v1/projects/videos`
- `POST /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset`
- `PUT /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}`
- `GET /v1/projects`
- `GET /v1/projects/{project_id}`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/artifacts`

接口字段见 [`docs/api.md`](docs/api.md)。

## 仓库结构

```text
StoryForge/
├── configs/                 # 运行配置
├── docs/                    # 产品、API、架构和状态文档
├── examples/                # 示例 brief
├── src/storyforge/
│   ├── agents/              # LLM backend 抽象与 LangChain 实现
│   ├── api/                 # FastAPI、router、schema、静态工作台
│   ├── application/         # 任务队列、运行时、持久化、项目存储
│   ├── core/                # 配置、IO、环境变量工具
│   ├── domains/             # 小说域和视频域业务逻辑
│   ├── integrations/        # Seedream / Seedance / ffmpeg 集成
│   └── pipelines/           # 阶段 pipeline
└── tests/                   # Python 与前端轻量测试
```

## 验证

```bash
uv run ruff check src tests
uv run pytest
node tests/js/prompt_tools.test.mjs
node tests/js/segment_review.test.mjs
node tests/js/timeline_data.test.mjs
```
