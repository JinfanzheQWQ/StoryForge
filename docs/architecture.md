# 架构说明

StoryForge 是一个分阶段 AI 媒体生产系统。前端负责产品交互，后端负责任务调度、结构化规划、媒体提交、产物聚合和持久化。

## 总览

```text
React Frontend
  -> FastAPI
  -> Task Queue
  -> Domain Pipelines
  -> LLM / Seedream / Seedance / ffmpeg
  -> MySQL + outputs/
```

## 代码结构

```text
frontend/
├── src/app/             # 路由和全局 provider
├── src/api/             # FastAPI client
├── src/components/      # 通用 UI 组件
├── src/features/        # 首页、项目库、创作器、项目工作台
├── src/styles/          # 视觉系统和页面样式
└── src/types/           # API 与 artifact 类型

src/storyforge/
├── agents/              # LLM backend 抽象和 LangChain 实现
├── api/                 # FastAPI router、schema、serializer、artifact 聚合
├── application/         # 容器、任务队列、项目存储、任务 handler
├── core/                # 配置、环境变量和 IO 工具
├── domains/
│   ├── novel/           # 小说生成、结构化合同和 prompt
│   └── video/           # 视频规划、校验、prompt、修复和媒体任务构建
├── integrations/        # Seedream、Seedance、ffmpeg、LLM 集成
└── pipelines/           # 阶段 pipeline 编排
```

## 运行时职责

- React 前端通过 HTTP 调用 FastAPI，不直接读取本地输出文件。
- FastAPI 接收请求、校验 payload、创建任务并返回 task id。
- `TaskQueue` 异步执行任务，避免媒体长任务阻塞请求。
- `TaskStore` 保存任务状态、错误和结果。
- `ProjectStore` 保存项目、run 关系和最新任务索引。
- pipeline 读取上一阶段产物，写入当前阶段产物，并更新项目状态。
- `/outputs` 暴露生成后的媒体文件，供前端预览。

## 阶段模型

```text
story_source
  -> scene_structure
  -> segment_contracts
  -> character_images
  -> scene_master_frames
  -> segment_videos
  -> merged_video
```

结构层级：

```text
chapter -> scene -> chunk -> segment
```

- `chapter`：小说章节。
- `scene`：地点、时间、光线和空间关系相对稳定的场景单位。
- `chunk`：scene 内连续动作块。
- `segment`：可独立提交 Seedance 的视频片段。

## 领域模块

小说域：

- `domains/novel/service.py`：小说生成和结构化入口。
- `domains/novel/contracts.py`：小说结构合同。
- `domains/novel/prompts.py`：小说 prompt。
- `domains/novel/repair.py`：小说结构修补。

视频域：

- `domains/video/service.py`：视频域统一服务入口。
- `domains/video/chapter_orchestration.py`：章节事件和 scene 规划。
- `domains/video/chunk_orchestration.py`：chunk 和 segment 合同规划。
- `domains/video/structure_validation.py`：scene、chunk 和转场合同校验。
- `domains/video/segment_validation.py`：segment 容量、时长、对白和镜头校验。
- `domains/video/prompting.py`：planner、media、repair prompt。
- `domains/video/planning.py`：媒体任务构建和 manifest 装配。
- `domains/video/repair.py`：连续性修复。

## 媒体任务

角色图任务写入 `character_image_manifest.json`。它们只锁定人物身份和外观。

场景母图任务写入 `scene_image_manifest.json`。它们锁定环境，不包含人物和文字。

视频任务写入 `seedance_manifest.json`。每个 clip 对应一个 segment，包含场景母图、可选上一段尾帧、实际出镜角色图和 Seedance prompt。

合并任务读取已完成 clip，输出 `rendered/full_story.mp4`。

## 连续性模型

连续性由三层共同保证：

- 规划层：scene transition contract 描述空间关系、承接动作、延续元素和禁止漂移。
- 资源层：同一空间可复用场景母图；连续视频可提交上一段尾帧。
- Prompt 层：提交 prompt 明确写出参考图用途、开场状态、推进过程和收束状态。

只有明确属于同一空间推进的 scene 才继承母图或跨 scene 承接尾帧。新地点和空间关系不确定时按新场景处理。

## Artifact API

`GET /v1/tasks/{task_id}/artifacts` 是前端工作台的主数据源。它聚合：

- 小说正文摘要。
- scene 和 segment 蓝图。
- 角色图、场景母图和视频资源。
- motion plan 和媒体 prompt。
- 提交请求、参考图绑定和 provider 摘要。
- 连续性问题和失败原因。
- 合并总片。

前端应消费 artifacts 中的规整字段，不在页面层重新解析落盘 JSON。

## 数据库与文件

MySQL 保存项目、任务、run 记录和产物索引。大文件写入 `outputs/`，数据库保存路径和状态。

默认路径：

```text
outputs/projects/{project_id}/runs/{task_id}/
```

## 配置

配置入口是 `configs/storyforge.example.toml` 或 `STORYFORGE_CONFIG_PATH` 指定的 TOML 文件。环境变量从 `.env` 加载。

关键配置：

- LLM provider、model、base URL 和 API key env。
- Seedream / Seedance model、base URL、watermark、auto submit。
- MySQL 连接参数。
- 输出目录。
- CORS origin。
