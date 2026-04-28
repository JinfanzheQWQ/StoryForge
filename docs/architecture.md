# 架构说明

StoryForge 是 `FastAPI + MySQL + 异步任务队列 + Web 工作台 + LangChain 结构化工作流` 组成的分阶段媒体生产系统。

## 模块边界

```text
src/storyforge/
├── agents/              # LLM backend 抽象和 LangChain 实现
├── api/                 # HTTP API、schema、artifact 聚合、静态工作台
├── application/         # 任务队列、运行时、持久化、项目存储
├── core/                # 配置、路径、环境变量和基础工具
├── domains/
│   ├── novel/           # 小说生成和正文包装
│   └── video/           # 视频规划、校验、prompt、合同和编排
├── integrations/        # Seedream、Seedance、ffmpeg 等外部集成
└── pipelines/           # 各阶段 pipeline
```

## 运行时

- API 层接收请求并创建任务。
- `TaskQueue` 执行异步任务。
- `TaskStore` 保存任务状态、结果和错误信息。
- `ProjectStore` 保存项目、run 记录和产物索引。
- pipeline 读取上一阶段产物，生成当前阶段产物并更新数据库。

## 阶段模型

```text
brief
  -> story_source
  -> scene_structure
  -> segment_contracts
  -> character_images
  -> scene_master_frames
  -> seedance_videos
  -> merged_video
```

规划结构固定为：

```text
chapter -> scene -> chunk -> segment
```

- `chapter`：章节维度。
- `scene`：相对连续的地点、时间和空间关系。
- `chunk`：scene 内连续动作块。
- `segment`：可独立提交 Seedance 的视频片段。

## 视频域代码

- `domains/video/service.py`：视频域公开服务入口。
- `domains/video/chapter_orchestration.py`：章节事件和 scene 结构编排。
- `domains/video/chunk_orchestration.py`：chunk 和 segment 合同编排。
- `domains/video/chapter_event_validation.py`：章节事件覆盖与粒度校验。
- `domains/video/structure_validation.py`：scene、chunk 和过渡合同校验。
- `domains/video/segment_validation.py`：segment 容量、节拍、对白和多人镜头校验。
- `domains/video/structured_generation.py`：结构化 LLM 调用、重试和指标记录。
- `domains/video/structured_retry_prompts.py`：结构化修复提示。
- `domains/video/prompting.py`：planner prompt、媒体 prompt 和 repair prompt。
- `domains/video/planning.py`：把结构化计划转成角色图、场景母图和视频任务清单。
- `domains/video/repair.py`：连续性修复和局部合同修复。

## 媒体任务

### 角色图

角色图任务来自 `character_visual_bible.json`，写入 `character_image_manifest.json`。每个任务包含角色名、角色图 prompt、状态、输出路径、远程 URL 和提交请求摘要。

角色图只用于锁定人物身份和外观，不参与视频时间推进。

### 场景母图

场景母图任务来自 `scene_plan.json`，写入 `scene_image_manifest.json`。每个 scene 生成一张环境基准图，内容为空场景，不包含人物和文字。

同一空间连续推进时，后续 scene 可以复用或承接上一 scene 的母图。新地点、空间关系不确定或锚点不一致时生成新的母图。

### 视频片段

视频任务写入 `seedance_manifest.json`。每个 clip 对应一个 segment，提交 Seedance 时包含：

- 当前 scene 的场景母图。
- 可选的上一段视频尾帧。
- 当前 segment 实际出镜角色图。
- 已解析的 Seedance motion prompt。

`submitted_reference_bindings` 记录真实提交顺序。业务逻辑不得假设固定图片编号，必须读取实际绑定列表。

## 连续性

连续性分为三层：

- 场景层：scene 通过地点、时间、光线、背景锚点、固定道具和空间连续性字段决定是否共用或承接母图。
- 视频层：同一连续空间内的 segment 优先使用上一段视频返回的尾帧作为当前片段开场锚点。
- Prompt 层：Seedance prompt 明确写出开场状态、推进过程、收束状态和参考图用途。

只有明确属于同一空间推进的 scene 才跨 scene 继承场景母图或尾帧。空间变化明确、地点变化明确或连续性不确定时，系统按新场景处理。

## Artifact API

`GET /v1/tasks/{task_id}/artifacts` 聚合当前 run 的可展示数据：

- 小说正文和章节信息。
- scene / segment 结构。
- 角色图和场景母图状态。
- 视频状态和预览地址。
- prompt、motion plan、请求参数和参考图绑定。
- 风险、失败原因和修复建议。

前端不直接解析所有落盘 JSON，而是优先消费 artifact API 返回的规整结构。

## 前端结构

工作台静态文件位于 `src/storyforge/api/static/app/`。

- `api_client.js`：HTTP 请求。
- `state.js`：前端状态。
- `render/`：项目详情页的各区域渲染。
- `render/prompt_tools.js`：prompt 编辑和请求查看。
- `render/segment_review.js`：分段审片台。
- `render/timeline_data.js`：artifact 数据归一化。
- `render/task_state.js`：任务状态和按钮状态。

页面以当前选中的 project、run、scene、segment 为上下文，只展示当前对象的可操作信息。

## 数据库

MySQL 保存：

- 项目。
- 任务。
- run 记录。
- 任务结果路径。
- 产物索引。

大文件仍写入输出目录，数据库只保存索引和状态。
