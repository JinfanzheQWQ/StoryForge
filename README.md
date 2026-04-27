# StoryForge

StoryForge 是一套“故事到视频”的分步生产工作台。它把一个故事想法拆成可审阅、可修改、可重试的生产流程：先生成小说正文，再生成视频结构规划、角色图、场景关键帧和分段视频。

StoryForge 不把整条链路包装成不可检查的一键黑盒。每个阶段都会落盘结构化产物，页面可以查看 prompt、真实请求参数、参考图片顺序、诊断信息和失败原因，方便你在继续消耗图片 / 视频生成成本前先判断结果是否合理。

## 核心能力

- 根据 brief 生成小说正文。
- 在页面修改并保存正文真源 `story_source.json`。
- 基于正文生成 `chapter -> scene -> chunk -> segment` 视频规划。
- 生成角色定妆图、场景母图、片段首帧 / 中段 / 尾帧。
- 角色定妆图 Prompt 可在页面中直接修改；单角色重做会先生成候选图，确认后才替换当前图。
- 使用 Seedance 按 `图片1 / 图片2 / 图片3` 的时间锚点生成中文剧情视频。
- 展示单个 segment 的图片 prompt、视频 prompt、真实 provider 请求参数和参考图绑定。
- 支持按 frame、segment、scene、stage 粒度重做，不强制整项目重跑。
- 使用 MySQL 保存项目、任务、run 历史和产物索引。

## 生产流程

1. 创建项目并生成小说。
2. 审阅并修改正文。
3. 生成场景结构。
4. 生成分段合同。
5. 生成角色图。
6. 生成场景母图和片段关键帧。
7. 按 segment 生成视频。
8. 按需合并已完成视频片段。

## 技术栈

- Web / API：`FastAPI`
- 数据库：`MySQL`
- 任务执行：进程内异步队列
- 结构化 LLM 工作流：`LangChain`
- LLM provider：`DeepSeek`、`OpenAI / ChatGPT 5.4`
- 生图模型：`doubao-seedream-4-5-251128`
- 生视频模型：`doubao-seedance-2-0-260128`

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

## 配置

默认配置文件：

- [`configs/storyforge.example.toml`](configs/storyforge.example.toml)
- [`configs/storyforge.live.example.toml`](configs/storyforge.live.example.toml)

常用配置项：

- `llm.provider` / `llm.model`
- `llm.available_providers`
- `llm.max_tokens`
- `seedream.base_url` / `seedream.model` / `seedream.watermark`
- `seedance.base_url` / `seedance.model` / `seedance.watermark`
- `queue.concurrency`
- `database.*`

## 工作台

项目详情页是主要生产界面：

- 小说页：查看、修改并保存正文真源。
- 场景工作台：查看 scene 分组、场景母图状态、过渡合同和 scene 级风险。
- 角色页：查看角色定妆图、编辑角色 Prompt、查看真实 Seedream 提交请求；单角色重做先生成候选图，确认后替换或放弃。
- 分段审片台：查看关键帧、视频、prompt、请求参数、诊断信息和重做入口。
- Prompt Editor：修改首帧、中段、尾帧和视频 prompt。
- Request Inspector：查看真实提交 payload、Prompt Diff、参考图绑定和 provider 请求摘要。
- 时间线 / 资产区：查看图片、视频、文档和合并总片。

## 核心产物

StoryForge 会在配置的输出根目录下写出生产产物。JSON 文件按用途分为：

- 核心运行文件：`story_source.json`、`novel_package.json`、`story_memory.json`、`character_visual_bible.json`、`scene_plan.json`、`segment_plan.json`
- 媒体任务清单：`character_image_manifest.json`、`scene_image_manifest.json`、`seedance_manifest.json`
- 恢复、风险和修复：`segment_contract_progress.json`、`scene_structure_source.json`、`continuity_report.json`、`continuity_repair_<id>.json`
- 执行报告和审阅文件：`novel_audit.json`、`seedream_character_execution.json`、`seedream_scene_execution.json`、`seedance_execution.json`
- 媒体文件：`assets/characters/*.png`、`assets/frames/*.png`、`rendered/*.mp4`、`rendered/full_story.mp4`

## API

常用接口：

- `POST /v1/projects/novel`
- `POST /v1/projects/scene-structure`
- `POST /v1/projects/segment-contracts`
- `POST /v1/projects/characters`
- `PUT /v1/projects/{project_id}/character-prompts/{source_task_id}/{character_name}`
- `POST /v1/projects/scenes`
- `POST /v1/projects/videos`
- `GET /v1/projects`
- `GET /v1/projects/{project_id}`
- `DELETE /v1/projects/{project_id}`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/artifacts`

接口字段和响应结构见 [`docs/api.md`](docs/api.md)。

## 仓库结构

```text
StoryForge/
├── configs/                 # 运行配置
├── docs/                    # 产品、API、架构和维护文档
├── examples/                # 示例 brief
├── src/storyforge/
│   ├── agents/              # LLM backend 抽象与 LangChain 实现
│   ├── api/                 # FastAPI、router、schema、静态工作台
│   ├── application/         # 任务队列、运行时、持久化、项目存储
│   ├── core/                # 配置、IO、环境变量工具
│   ├── domains/             # 小说与视频领域服务
│   ├── integrations/        # provider client 与 ffmpeg 工具
│   ├── pipelines/           # story / video pipeline 编排
│   └── cli.py               # CLI 入口
├── tests/
├── .env.example
├── pyproject.toml
└── uv.lock
```

## 检查

```bash
uv run ruff check src/storyforge tests
uv run pytest
```

前端模块测试使用 Node：

```bash
for test_file in tests/js/*.test.mjs tests/frontend/*.test.mjs; do node "$test_file"; done
```

## 文档

- [使用文档](docs/usage.md)
- [API 文档](docs/api.md)
- [架构文档](docs/architecture.md)
- [开发文档](docs/development.md)
- [产品状态](docs/status.md)

## License

MIT
