# 架构文档

StoryForge 采用分层架构：API 负责入口，application 负责任务与持久化，pipeline 负责阶段编排，domain 负责业务规则，integrations 负责外部 provider 调用。

## 总体结构

```text
Web 工作台 / HTTP API
        ↓
FastAPI routers + schemas
        ↓
Application container / task queue / stores
        ↓
Story pipeline / video planning pipeline / media pipeline
        ↓
Novel domain / video domain
        ↓
LLM provider / Seedream / Seedance / ffmpeg / MySQL / filesystem
```

## 目录职责

```text
src/storyforge/
├── agents/          # LLM backend 抽象与 LangChain 实现
├── api/             # FastAPI、router、schema、artifacts、静态前端
├── application/     # 容器、任务队列、任务运行时、项目和任务存储
├── core/            # 配置、IO、环境变量、通用工具
├── domains/         # 小说域和视频域业务规则
├── integrations/    # DeepSeek、OpenAI、Seedream、Seedance、ffmpeg
├── pipelines/       # 小说、视频规划、媒体生成阶段编排
└── cli.py           # CLI 入口
```

## 运行时组件

### API

- `api/main.py` 创建 FastAPI 应用。
- `api/routers/projects.py` 提供项目、阶段任务、prompt 保存、prompt 重置和项目删除接口。
- `api/routers/tasks.py` 提供任务查询接口。
- `api/artifacts.py` 根据输出目录和 manifest 组装页面产物索引。
- `api/static/app/` 提供 Web 工作台前端模块。

### Application

- `AppContainer` 装配配置、任务队列、项目存储、任务存储和 handler。
- `AsyncTaskQueue` 执行阶段任务。
- `TaskStore` 和 `ProjectStore` 保存项目、任务与 run 历史。
- task handler 把 HTTP 阶段请求转换成 pipeline 调用。

### Pipeline

- `story_pipeline.py` 生成小说正文、结构化小说包和审稿结果。
- `video_planning.py` 生成场景结构、分段合同和规划产物。
- `video_pipeline.py` 生成角色图、场景图、视频片段和合并总片。

### Domain

- 小说域负责故事结构、角色结构、正文真源、角色证据和审稿规则。
- 视频域负责 scene / chunk / segment 规划、连续性合同、动作容量、时长预算、关键帧角色集合和修复规则。

### Integrations

- LLM provider 通过 LangChain backend 调用。
- Seedream client 负责图片任务提交、轮询和下载。
- Seedance client 负责视频任务提交、轮询和下载。
- ffmpeg 工具负责本地视频合并。

## 数据流

### 1. 小说阶段

输入：brief。

输出：

- `story_source.json`
- `novel_package.json`
- `novel_audit.json`

`story_source.json` 是正文真源。后续结构化和视频规划都基于它执行。

### 2. 场景结构阶段

输入：`story_source.json` 和小说结构化结果。

输出：

- `story_memory.json`
- `character_visual_bible.json`
- scene skeleton
- scene 级过渡合同

这一阶段确定章节关键事件、scene 边界、角色视觉基线和跨 scene 进入方式。

### 3. 分段合同阶段

输入：场景结构。

输出：

- `scene_plan.json`
- `segment_plan.json`
- `segment_contract_progress.json`
- `continuity_report.json`
- 媒体任务清单

这一阶段确定每个 segment 的镜头、动作、时长、首中尾帧、对白字幕、音频方向和视频 motion plan。

### 4. 图片阶段

输入：角色视觉设定、scene plan、segment plan 和图片 manifest。

输出：

- `assets/characters/*.png`
- `assets/frames/*.png`
- `seedream_character_execution.json`
- `seedream_scene_execution.json`

图片阶段按当前帧真实出镜角色和参考图绑定生成，不让未出镜角色污染单帧 prompt。

### 5. 视频阶段

输入：关键帧、Seedance manifest 和视频 prompt。

输出：

- `rendered/*.mp4`
- `seedance_execution.json`
- `rendered/full_story.mp4`

Seedance 提交使用 segment 关键帧作为时间锚点，不提交场景母图或角色图作为视频参考。

## 视频规划合同

### `scene_transition_contract`

描述当前 scene 如何从上一场进入：

- 当前 scene 开场可拍状态
- 过桥动作
- 视觉桥接
- 声音桥接
- 切换方式

### `scene_bible`

锁定 scene 的环境基线：

- 地点
- 时间
- 天气
- 光线
- 空间布局
- 背景锚点
- 固定道具

### `shot_state`

锁定 segment 的镜头和动作：

- 景别
- 镜头运动
- 角色调度
- 动作推进
- 情绪推进
- 道具连续性
- 方向
- 尾部状态

### `continuity_link`

描述当前 segment 与上一段的关系：

- 开场承接
- 允许变化
- 禁止漂移
- 尾部状态

### `motion_plan`

描述视频关键帧之间的可见推进：

- `start_to_mid`
- `mid_to_end`
- `camera_path`
- `character_motion`
- `continuity_guard`

视频 prompt 会优先消费 `motion_plan`，并把实际提交图片写成 `图片1 / 图片2 / 图片3`。

## Artifact API

`GET /v1/tasks/{task_id}/artifacts` 是前端工作台的数据入口。它返回：

- 文档索引
- 角色图
- 场景帧
- 视频片段
- 总片
- planned segments
- continuity report
- scene / segment 连续性分组
- prompt 和真实请求视图
- segment diagnostics

前端按这个接口渲染时间线、Prompt Editor、Request Inspector、场景工作台和分段审片台。

## 前端结构

```text
api/static/app/
├── api.js
├── events.js
├── refresh.js
├── state.js
├── render/
│   ├── detail.js
│   ├── detail_assets.js
│   ├── story_structure.js
│   ├── scene_workbench.js
│   ├── segment_review.js
│   ├── prompt_tools.js
│   ├── request_debug.js
│   ├── timeline.js
│   ├── timeline_data.js
│   ├── task_state.js
│   ├── continuity_ui.js
│   └── document_assets.js
```

前端只展示后端返回的事实数据，不在浏览器端推断业务合同。

## 持久化

- MySQL 保存项目、任务、任务结果和 run 历史。
- 输出目录保存 JSON、图片、视频和执行报告。
- 任务记录保存 payload、result、status、error 和时间戳。
- 项目删除会清理数据库记录和安全范围内的输出目录。

## 失败与恢复

- 每个阶段任务都有明确 `status` 和 `error`。
- 结构化 LLM 输出失败会进入重试，仍失败则显式标记任务失败。
- 分段合同阶段保存 progress，可从失败位置继续。
- 服务启动时未完成任务会回到 `queued`。
- 媒体任务失败会在对应 execution JSON 中记录 provider 返回和执行摘要。

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [API 文档](api.md)
- [开发文档](development.md)
- [产品状态](status.md)
