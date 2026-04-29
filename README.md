# StoryForge

StoryForge 是面向中文剧情短视频生产的 AI 创作工作台。产品把“一句话创意”拆成小说正文、结构化规划、角色定妆图、场景母图、分段视频和合并成片，让创作者能按阶段审阅、修改和重做，而不是把整条链路交给黑盒。

## 产品能力

- 从故事创意生成可编辑小说正文。
- 从正文生成 `chapter -> scene -> chunk -> segment` 视频结构。
- 生成角色定妆图，支持单角色 prompt 修改、候选图对比和版本选择。
- 生成 scene 级场景母图，用于锁定地点、光线、透视、背景锚点和固定道具。
- 逐段生成 Seedance 视频，提交当前场景母图、实际出镜角色图和可用的上一段尾帧。
- 在分段审片台查看每个 segment 的视频、资源图、最终提交 prompt、连续性问题和重跑入口。
- 合并已完成的分段视频，形成项目总片。
- 使用 FastAPI、MySQL 和异步任务队列保存项目、任务、run 记录和产物索引。

## 产品流程

```text
输入创意
  -> 生成小说
  -> 编辑正文
  -> 生成场景结构
  -> 生成分段合同
  -> 生成角色图
  -> 生成场景母图
  -> 逐段生成视频
  -> 合并总片
```

## 服务组成

- `frontend/`：React + TypeScript + Vite 前端服务，包含商业首页、项目库、小说转视频创作器和项目工作台。
- `src/storyforge/api/`：FastAPI 服务，提供项目、任务、正文、prompt、媒体生成和 artifacts API。
- `src/storyforge/domains/`：小说和视频领域逻辑。
- `src/storyforge/integrations/`：Seedream、Seedance、ffmpeg 和 LLM 集成。
- `outputs/`：项目产物目录，通过 FastAPI `/outputs` 暴露媒体文件。

## 快速开始

安装 Python 依赖：

```bash
uv sync
```

准备环境变量：

```bash
cp .env.example .env
```

常用变量：

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

启动后端：

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

后端地址：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`
- 输出媒体：`http://127.0.0.1:8000/outputs/...`

启动前端：

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

前端默认地址：`http://127.0.0.1:5173/`。

## 前端页面

- 首页：展示产品品牌、视频背景和创意输入入口。
- 项目库：以媒体作品墙展示项目封面，优先展示视频，其次展示图片。
- 小说转视频：输入项目名、故事创意和生成参数，创建视频项目。
- 项目工作台：按“小说、结构化信息、角色图、场景母图、分段视频、合并视频”推进。
- 角色定妆墙：查看当前角色图，编辑角色 prompt，确认候选图。
- 场景空间板：查看当前 scene 母图、引用片段数量和生成状态。
- 分段审片台：查看 segment 视频、资源图、连续性问题、视频 prompt 和重跑操作。
- 合并交付页：查看完整成片和片段资产。

## 媒体规则

- 角色图只负责稳定人物身份，不作为视频时间帧。
- 场景母图只负责稳定环境，不包含角色、文字、水印或说明性排版。
- 上一段视频尾帧只在连续承接时作为当前片段的开场时间锚点。
- Seedance prompt 会根据真实提交顺序写明 `图片1 / 图片2 / 图片3` 的用途。
- 新地点、空间关系变化明确或连续性不确定时生成新场景母图。

## 核心产物

- `story_source.json`：可编辑正文真源。
- `novel_package.json`：小说包和章节正文。
- `story_memory.json`：故事连续性记忆。
- `character_visual_bible.json`：角色视觉设定。
- `scene_plan.json`：scene 结构、空间合同和场景母图字段。
- `segment_plan.json`：segment 合同、motion plan 和媒体 prompt。
- `character_image_manifest.json`：角色图任务和结果。
- `scene_image_manifest.json`：场景母图任务和结果。
- `seedance_manifest.json`：视频任务、参考图绑定、提交 prompt 和结果。
- `continuity_report.json`：结构风险和连续性诊断。

## 验证

```bash
uv run ruff check src/storyforge tests
uv run pytest
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
git diff --check
```

更多信息：

- [使用说明](docs/usage.md)
- [API 说明](docs/api.md)
- [架构说明](docs/architecture.md)
- [开发文档](docs/development.md)
- [媒体管线设计](docs/media_pipeline_v2_design.md)
- [当前状态](docs/status.md)
