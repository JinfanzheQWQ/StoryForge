# StoryForge

<p align="left">
  <img alt="License" src="https://img.shields.io/github/license/JinfanzheQWQ/StoryForge">
  <img alt="Stars" src="https://img.shields.io/github/stars/JinfanzheQWQ/StoryForge?style=social">
  <img alt="Last Commit" src="https://img.shields.io/github/last-commit/JinfanzheQWQ/StoryForge">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-service-009688?logo=fastapi&logoColor=white">
  <img alt="LangChain" src="https://img.shields.io/badge/LangChain-1.2%2B-1C3C3C">
  <img alt="DeepSeek" src="https://img.shields.io/badge/LLM-DeepSeek-4F46E5">
  <img alt="Seedream" src="https://img.shields.io/badge/Image-Seedream%204.5-E11D48">
  <img alt="Seedance" src="https://img.shields.io/badge/Video-Seedance%202.0-F59E0B">
</p>

<p align="left">
  <strong>Agentic fiction-to-video workflow for turning a story brief into a novel, character art, scene frames, and video clips.</strong>
</p>

<p align="left">
  StoryForge is built for creator tools, prototype studios, and narrative production pipelines that need structured outputs, staged execution, and reviewable media assets instead of one-shot prompts.
</p>

StoryForge 是一个面向“小说生成 + 小说转视频”的工程化工作流系统。它把大模型生成、角色设定、生图、生视频、任务编排和产物管理串成了一条可运行的生产链路，而不是单个 prompt 的演示脚本。

当前版本支持：

- 基于 `LangChain >= 1.2` 的结构化多 Agent 小说生成
- 基于 `DeepSeek` 的默认 LLM 接入
- 基于 `Doubao Seedream 4.5` 的角色图与场景首尾帧生成
- 基于 `Seedance 2.0` 的视频片段生成、下载与 `ffmpeg` 合并
- `FastAPI` + 异步任务队列 + MySQL 项目 / 任务持久化
- 浏览器端五步式工作台、CLI 和 HTTP API 三种入口

## 核心工作流

StoryForge 默认采用五阶段后台任务流，而不是一键全跑：

1. 生成小说正文
2. 生成结构化信息
3. 生成角色图
4. 生成场景图
5. 生成视频

在第 1 步和第 2 步之间，页面会先展示并允许编辑 `story_source`，再决定是否继续进入结构化与媒体阶段。

## 主要特性

- 结构化多 Agent 小说生成链路：`Story Architect`、`Story Drafter`、`Cast Analyzer`、`Character Designer`、`Chapter Planner`、`Editorial Reviewer`
- 小说链路改为 story-first：先生成完整小说草稿并落成 `story_source.json`，再从这份可编辑正文里解析 cast、生成角色卡和结构化章节蓝图；`Story Architect` 只负责项目底稿，不再提前钉死角色结构
- Web 工作台支持先展示并编辑生成后的小说正文；保存正文后，旧的结构化结果和媒体资产会被标记为需要重做
- 角色结构约定：以 LLM `Cast Analyzer` 结果为主，优先依据已生成小说草稿抽取 cast slots，heuristics 只做 fallback / repair
- 小说结构化阶段在 live LLM 模式下采用 fail-fast：坏结构最多自动重试 3 次，仍失败就显式报错，不再用 brief-first 结果静默顶替
- LangChain 结构化输出当前使用 `ChatModel.with_structured_output(method="function_calling", include_raw=True)`，避免 DeepSeek OpenAI-compatible 接口在 agent 工具消息链里报 `tool_calls` 错误；如果模型没触发 tool call 但返回了 JSON 文本，会自动回收解析
- 结构化阶段具备后端幂等保护：同一故事正文修订已有 queued / running / completed 结构化任务时，不会重复创建任务
- 运行时已移除 DryRun / 非 LLM 演示模式：Web、API、CLI 默认都要求真实 DeepSeek 配置，非 LLM 模式会直接报错
- 视频规划与执行解耦：先产出角色视觉档案、片段规划、场景帧和 Seedance manifest，再决定是否提交真实任务
- Seedance manifest 标题继承真实小说标题，旧产物重载时会优先从 `novel_package.json` / `story_source.json` 恢复标题
- 角色一致性链路：角色定妆卡 -> 场景首尾帧 -> 视频片段
- 角色定妆图使用白底三视图模板：只显示角色姓名，生成正面 / 左侧面 / 背面，减少信息格、色卡和材质块对角色一致性的干扰
- 音频与字幕链路：对白、旁白、硬字幕文案会进入 Seedance prompt
- 项目级管理：支持同一项目下多次运行结果追踪
- 元数据持久化：基于 MySQL
- 页面会展示任务和各阶段失败原因，便于定位 LLM schema、Seedream、Seedance 或下载失败
- 自动产物落盘：核心 JSON、图片、视频和执行报告会保存到输出目录

## 技术栈

- Python `>= 3.11`
- `uv`
- `FastAPI`
- `Pydantic`
- `LangChain[openai] >= 1.2`
- `httpx`
- `PyMySQL`
- `ffmpeg`

默认模型配置：

- LLM：`deepseek-chat`
- Image：`doubao-seedream-4-5-251128`
- Video：`doubao-seedance-2-0-260128`

## 产品预览

下面这组图已经不是简单占位框，而是按当前产品方向绘制的静态 SaaS mockup。后续你只需要把它们替换成真实截图即可，README 结构不用再改。

<p align="center">
  <img src="docs/assets/screenshots/home-showcase-mockup.svg" alt="StoryForge home showcase mockup" width="100%">
</p>

<p align="center">
  <img src="docs/assets/screenshots/project-detail-mockup.svg" alt="StoryForge project detail mockup" width="49%">
  <img src="docs/assets/screenshots/pipeline-studio-mockup.svg" alt="StoryForge pipeline studio mockup" width="49%">
</p>

建议后续按同样版式替换为：

- 首页 / 品牌展示截图
- 项目详情与资产页截图
- 五步工作流或视频生产页截图

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 准备环境变量

```bash
cp .env.example .env
```

至少需要配置：

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=...
SEEDREAM_API_KEY=...
SEEDANCE_API_KEY=...
SEEDREAM_BASE_URL=...
SEEDANCE_BASE_URL=...
```

还必须配置 MySQL 密码：

```bash
STORYFORGE_DB_PASSWORD=...
```

### 3. 检查配置文件

默认配置文件是 [`configs/storyforge.example.toml`](configs/storyforge.example.toml)。
`configs/` 目录现在只保留两份配置：

- [`configs/storyforge.example.toml`](configs/storyforge.example.toml)：主配置，默认开发与日常运行使用
- [`configs/storyforge.live.example.toml`](configs/storyforge.live.example.toml)：真实提交模板，适合需要默认自动提交 Seedream / Seedance 的场景

关键配置项包括：

- `llm.provider` / `llm.model`
- `seedream.base_url` / `seedream.model`
- `seedance.base_url` / `seedance.model`
- `queue.concurrency`
- 内容合规由接入的 LLM / 媒体供应商负责，StoryForge 后端不再做本地规则拦截

### 4. 启动 Web 控制台与 API

```bash
uv run storyforge api serve
```

启动后访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

开发页面样式或前端模块时可以临时加 `--reload`。跑 Seedream / Seedance 这类长任务时不要使用 `--reload`，否则代码保存会触发服务热重载，中断正在执行的任务。

### 5. 按页面流程执行

1. 在页面创建故事并生成小说
2. 在“小说”标签页审阅并按需修改正文
3. 手动触发结构化信息生成
4. 在同一条 story run 上生成角色图
5. 基于同一条 story run 生成场景图
6. 生成视频片段，并在需要时手动合并总片

## CLI 用法

初始化目录：

```bash
uv run storyforge init
```

运行 demo brief。该命令同样需要真实 DeepSeek 配置：

```bash
uv run storyforge pipeline demo
```

使用自己的 brief：

```bash
uv run storyforge pipeline build \
  --brief examples/briefs/demo_story.toml \
  --config configs/storyforge.example.toml \
  --llm
```

从已有小说包继续规划视频：

```bash
uv run storyforge video plan \
  --novel-package outputs/your-story/novel_package.json \
  --config configs/storyforge.example.toml \
  --llm
```

## API 概览

常用接口：

- `POST /v1/projects/novel`
- `POST /v1/projects/story-analysis`
- `POST /v1/projects/characters`
- `POST /v1/projects/scenes`
- `POST /v1/projects/videos`
- `GET /v1/projects`
- `GET /v1/projects/{project_id}`
- `DELETE /v1/projects/{project_id}`
- `GET /v1/projects/{project_id}/story-source/{source_task_id}`
- `PUT /v1/projects/{project_id}/story-source/{source_task_id}`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/artifacts`

删除项目时，后端会同步清理项目元数据、任务记录和安全范围内的输出目录。
完整字段、请求示例和阶段接口说明见：[docs/api.md](docs/api.md)

## 输出产物

核心产物包括：

- `story_source.json`
- `novel_package.json`
- `novel_audit.json`
- `segment_plan.json`
- `seedream_character_execution.json`
- `seedream_scene_execution.json`
- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`
- `rendered/full_story.mp4`

CLI 默认输出到 `outputs/<story-slug>/`，Web 项目任务会在同一 `output_dir` 上分阶段复用。
更完整的目录结构、产物职责和联调顺序见：[docs/usage.md](docs/usage.md)

## 仓库结构

```text
StoryForge/
├── configs/                 # 配置文件
├── docs/                    # 项目文档
├── examples/                # 示例 brief
├── src/storyforge/
│   ├── agents/              # Agent backend 与 orchestrator
│   ├── api/                 # FastAPI、模板和静态资源
│   ├── application/         # 队列、任务运行时、持久化
│   ├── core/                # 配置、IO、环境变量工具
│   ├── domains/             # 小说 / 视频领域服务
│   ├── integrations/        # DeepSeek、Seedream、Seedance、ffmpeg
│   ├── pipelines/           # story / video pipeline
│   └── cli.py               # CLI 入口
├── tests/
├── .env.example
├── pyproject.toml
└── uv.lock
```

## 当前状态

当前已经打通：

- 小说生成
- 结构化解析
- 角色图 / 场景图
- Seedance 视频片段生成与下载
- 手动总片合并
- Web 控制台、CLI、HTTP API
- MySQL 项目 / 任务持久化

当前仍需继续补强：

- 生产级持久化执行队列
- 对象存储与公网素材管理
- 更强的角色 / 音色一致性
- 认证、权限和生产级治理

详细状态、限制与路线图见：[docs/status.md](docs/status.md)

## 测试

运行静态检查：

```bash
uv run ruff check src/storyforge tests
```

运行测试：

```bash
uv run pytest
```

## 文档索引

- [使用文档](docs/usage.md)
- [API 文档](docs/api.md)
- [架构文档](docs/architecture.md)
- [开发文档](docs/development.md)
- [技术栈与 Agent 定位](docs/tech-stack.md)
- [工程状态与路线图](docs/status.md)

## License

MIT
