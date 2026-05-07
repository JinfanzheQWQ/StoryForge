# Chat-first Agent 自动创作模式方案

StoryForge Agent 第一版采用 **Chat-first 交互 + 受控 Session Runner**。用户看到的是聊天机器人式创作体验；后端执行仍然是严格状态机，按固定白名单阶段推进现有小说转视频流水线。

核心原则：

```text
前端像聊天机器人
后端不是自由聊天机器人
执行仍然是受控 Agent Session + Runner
```

## 产品目标

用户通过聊天输入一句创意，Agent 先理解需求并生成生产计划，用户确认后系统自动跑完整小说转视频流程。

```text
用户聊天输入创意
  -> Agent 解析需求
  -> Agent 返回生产计划并等待确认
  -> 用户确认开始
  -> 自动生成小说正文
  -> 自动生成场景结构
  -> 自动生成分段合同
  -> 自动生成角色图
  -> 自动生成场景母图
  -> 自动生成九宫格分镜图
  -> 自动生成分段视频
  -> 自动合并成片
  -> Agent 在聊天中返回成片和项目工作台链接
```

示例体验：

```text
用户：帮我做一个大学表白短片，清新电影感。
Agent：我会生成 1 章校园情感短片，使用九宫格分镜，16:9，GPT Image 2。是否开始？
用户：开始。
Agent：正在生成小说正文...
Agent：小说已完成，正在拆分场景结构...
Agent：角色图完成，正在生成场景母图...
Agent：视频已合并完成，这是成片。你也可以进入项目工作台继续修改。
```

## 设计原则

- Chat 是交互层，不是执行层。
- LLM 必须负责受控意图解析、计划摘要和回复文案，不直接执行任意工具。
- Agent 需求理解不允许使用硬编码关键词、题材枚举或风格枚举做规则兜底。
- Agent 只能调用后端白名单能力，不能直接操作文件、落盘 JSON 或 shell。
- 外部 Agent 只调用 Session/Message API，不直接调用角色图、场景图、九宫格、视频等底层阶段接口。
- 每一步执行必须走现有任务队列和阶段任务，产物继续落到普通项目工作台。
- Agent Session 不能做成长期占用 `TaskQueue` worker 的父任务；必须使用独立 Session Runner 轮询和推进子任务。
- 第一版只做 `novel_to_video` 的 `auto_full_pipeline`，不做无限画布、自由节点、任意工具调用、多 Agent 协作或复杂人工审批流。
- 第一版只有 Session Memory，不做跨项目 Long-Term Memory。

## 服务架构

Chat-first Agent 是独立服务层，负责编排已有小说转视频阶段任务，不新增媒体 pipeline。

```text
Human User / External Agent
  -> Agent Chat API
  -> AgentSessionStore / AgentMessageStore / AgentSessionEventStore
  -> AgentIntentPlanner
  -> AgentSessionRunner
  -> StageTaskGateway
  -> Existing Project APIs / TaskQueue
  -> Existing Novel-To-Video Pipelines
  -> Artifacts API
  -> Agent Chat Result
```

运行关系：

```text
React Agent Chat Page
  -> POST /v1/agent-sessions
  -> POST /v1/agent-sessions/{session_id}/messages
  -> GET /v1/agent-sessions/{session_id}
  -> GET /v1/agent-sessions/{session_id}/messages
  -> GET /v1/agent-sessions/{session_id}/events
  -> DELETE /v1/agent-sessions/{session_id}

External Agent
  -> same Session/Message API

FastAPI Agent Router
  -> validate request
  -> create session
  -> append user message
  -> append assistant plan / progress / result messages
  -> return session state

AgentIntentPlanner
  -> turn user message into StoryBriefInput + production settings
  -> produce a human-readable plan message
  -> never execute media generation

AgentSessionRunner
  -> scan runnable sessions
  -> inspect current child task
  -> submit next stage task through StageTaskGateway
  -> update session memory, events and assistant messages
  -> never execute media generation directly

TaskQueue
  -> execute existing project.story / project.scene_structure / project.segment_contracts / project.characters / project.scenes / project.storyboards / project.videos

Artifacts API
  -> aggregate generated story, images, storyboard grids, clips and merged video
  -> feed current preview and final result back to Session API
```

模块边界：

- `Agent Chat API`：会话创建、消息发送、会话查询、消息查询、事件查询和会话删除。
- `AgentSessionStore`：保存 session 当前状态、计划、设置、结果和错误。
- `AgentMessageStore`：保存聊天消息、计划卡片、进度消息、错误消息和结果消息。
- `AgentSessionEventStore`：保存机器可读进度事件，给前端和外部 Agent 查询。
- `AgentIntentPlanner`：调用 LLM，把用户自然语言转成受控 `StoryBriefInput`、生产设置和计划回复。
- `AgentSessionRunner`：状态机推进器，只做轻量调度，不做长时间阻塞生成。
- `StageTaskGateway`：把 session stage 映射到现有项目阶段任务，封装 payload 生成和任务提交。
- `TaskQueue`：继续执行所有重任务。
- `Artifacts API`：继续作为产物聚合来源，Session 不重复解析落盘 JSON。

必须保持：

- Session Runner 不能占用 `TaskQueue` worker 等待子任务。
- Chat API 不能把底层阶段接口直接暴露给外部 Agent。
- Assistant 消息必须反映真实 session 状态，不能虚构已完成产物。

MVP 实现方式：

- 第一版 Runner 由 Session API 轮询触发推进；`GET /v1/agent-sessions/{session_id}`、`GET /messages`、`GET /events` 都可以触发一次轻量推进。
- 确认开始后立即提交 `project.story`，Session 进入 `waiting_story`。
- 当前子任务完成后，下一次轮询提交下一阶段任务；如果子任务失败，Session 进入 `failed` 并追加错误消息。
- 后续可以增加后台扫描器，但不能把 Agent Session 做成长期占用 `TaskQueue` worker 的父任务。

## 后端模块

新增候选模块：

```text
src/storyforge/application/agent_sessions.py
src/storyforge/application/agent_orchestrator.py
src/storyforge/application/agent_intent.py
src/storyforge/application/persistence/mysql_agent_sessions.py
src/storyforge/api/routers/agent_sessions.py
src/storyforge/api/schemas_agent.py
```

职责：

- `agent_sessions.py`：Session、Message、Event 领域模型和存储接口。
- `agent_orchestrator.py`：状态机推进、阶段提交、任务完成检测。
- `agent_intent.py`：LLM-only 意图解析、计划生成和结构化校验。
- `mysql_agent_sessions.py`：MySQL session/message/event 持久化。
- `agent_sessions.py` router：Chat-first Session API。
- `schemas_agent.py`：请求和响应 schema。

## 数据模型

### `agent_sessions`

```text
session_id
project_id
source_task_id
current_task_id
product_type
mode
status
current_stage
user_prompt
intent_json
plan_json
settings_json
result_json
error_text
created_at
updated_at
finished_at
```

字段说明：

- `product_type`：第一版固定 `novel_to_video`。
- `mode`：第一版固定 `auto_full_pipeline`。
- `status`：`created`、`planning`、`waiting_confirmation`、`running`、`waiting_task`、`completed`、`failed`、`paused`、`canceled`。
- `current_stage`：当前自动生产阶段。
- `source_task_id`：根小说任务 id。
- `current_task_id`：当前正在等待的阶段任务 id。
- `intent_json`：从用户消息解析出的项目 brief。
- `plan_json`：自动生产计划。
- `settings_json`：模型、比例、水印、视频模式等生产参数。
- `result_json`：最终项目链接、产物路径、成片 URL、统计信息。

### `agent_session_messages`

```text
message_id
session_id
role
type
content
payload_json
created_at
```

字段说明：

- `role`：`user`、`assistant`、`system`。
- `type`：`text`、`plan`、`progress`、`error`、`result`、`action`。
- `content`：用户或 Agent 可读文案。
- `payload_json`：计划卡片、快捷动作、产物引用、错误详情等结构化信息。

消息类型约定：

- `text`：普通对话。
- `plan`：Agent 解析出的生产计划，等待用户确认。
- `progress`：自动生产进度。
- `error`：失败阶段和错误原因。
- `result`：最终视频、工作台链接和统计信息。
- `action`：暂停、继续、重新跑当前阶段、进入工作台等快捷动作。

### `agent_session_events`

```text
event_id
session_id
stage
status
message
task_id
payload_json
created_at
```

事件用于机器读取和外部 Agent 集成；消息用于人类聊天体验。

## 记忆模型

第一版只实现 **Session Memory**，不实现跨项目长期记忆。

Session Memory 由三部分承载：

- `agent_sessions`：当前意图、计划、设置、阶段、任务和结果。
- `agent_session_messages`：本次聊天上下文、确认动作、进度回复和结果回复。
- `agent_session_events`：阶段推进、错误、重新跑当前阶段和完成事件。

Session Memory 必须满足：

- 刷新页面后聊天记录和进度不丢。
- 后端重启后可以继续推进。
- 失败后能知道失败阶段、失败任务和错误原因。
- 外部 Agent 能通过 Session API 恢复上下文。

第一版不做 **Long-Term Memory**：

- 不记住用户跨项目偏好。
- 不跨项目复用角色、世界观、风格设定或素材。
- 不接向量库。
- 不根据历史项目自动改写新项目 brief。

V2 可以新增长期记忆表：

```text
agent_memories
- memory_id
- scope: user / project / character / world / style
- owner_id
- project_id
- title
- content
- tags_json
- embedding_id
- source_session_id
- created_at
- updated_at
```

长期记忆进入实现前必须先补充独立方案，不要混进第一版 Session Runner。

## Chat 状态机

第一版状态机：

```text
created
  -> planning
  -> waiting_confirmation
  -> submitting_story
  -> waiting_story
  -> submitting_scene_structure
  -> waiting_scene_structure
  -> submitting_segment_contracts
  -> waiting_segment_contracts
  -> submitting_characters
  -> waiting_characters
  -> submitting_scenes
  -> waiting_scenes
  -> submitting_storyboards
  -> waiting_storyboards
  -> submitting_videos
  -> waiting_videos
  -> submitting_merge
  -> waiting_merge
  -> completed
```

失败统一进入：

```text
failed
```

支持的用户指令：

- `开始`：从 `waiting_confirmation` 进入自动生产。
- 计划修改：在 `waiting_confirmation` 状态下，普通消息会作为上一轮计划的补充修改处理，而不是全新项目。
- `暂停` / `pause`：将 session 标记为 `paused`，保留 `current_stage` 和 `current_task_id`，不再自动提交下一阶段。
- `继续` / `恢复` / `resume` / `continue`：从 `paused` 恢复并接着当前进度推进。
- `停止` / `停下` / `终止` / `取消` / `stop` / `cancel`：终止当前 Agent Session，进入 `canceled`，不可恢复，不再提交后续阶段。
- `重新跑当前阶段`：独立动作，不等同于继续；仅在 `paused` 或 `failed` 下重新提交当前生产阶段。
- `进入工作台`：返回项目工作台链接。

不支持的用户指令：

- 任意编辑落盘 JSON。
- 任意跳过结构阶段直接生成视频。
- 任意选择未接入模型。
- 绕过会话删除确认直接删除项目或文件。
- 强制杀掉已经进入底层模型调用的单个长任务。第一版停止是会话级终止，保证不再推进后续阶段。

可恢复场景：

- 子任务仍在排队或运行：继续等待。
- 子任务已完成但 session 未推进：读取 task result 后推进下一阶段。
- Session Runner 重启：从 `current_task_id` 和 `current_stage` 恢复。
- 分段合同失败但 progress 可恢复：提交 `resume_from_progress=true`。

不可自动恢复场景：

- 根小说任务失败。
- Agent 意图解析 LLM 不可用。
- Agent 意图解析结构化输出连续失败。
- LLM 连续结构化失败且无 progress。
- 媒体供应商返回不可重试错误。
- 配置缺少必要 API key。

终止场景：

- 用户发送停止类指令后，Session 进入 `canceled`。
- `AgentSessionRunner` 必须把 `canceled` 视为终态，不再读取当前 task result 推进下一阶段。
- 如果当前子任务已经在底层 worker 中执行，第一版不强制中断该 worker；任务完成或失败后也不能推动 Agent 继续生产。

暂停场景：

- 用户发送暂停类指令后，Session 进入 `paused`，但 `current_stage`、`current_task_id`、`project_id` 和 `source_task_id` 保持不变。
- `AgentSessionRunner` 必须把 `paused` 视为暂时终态，不自动推进。
- 暂停期间当前子任务可能继续执行并完成，但不会触发下一阶段。
- 用户发送继续类指令后，如果当前 task 已完成，Runner 立即提交下一阶段；如果当前 task 仍在排队或运行，则继续等待该 task。
- “重新跑当前阶段”必须使用独立按钮或独立 API，不得混进“继续”语义；它会提交新阶段任务并替换 `current_task_id`。

## 意图解析

第一版意图解析不做自由 Agent，但必须走 LLM 结构化解析。`AgentIntentPlanner` 的职责是把用户自然语言转成现有 `StoryBriefInput`、生产设置和计划回复，并做 schema 校验。

强制约束：

- 不允许用 `if "校园" in prompt`、`if "悬疑" in prompt` 这类硬编码关键词判断题材。
- 不允许内置固定题材列表、固定风格列表或固定 `must_include` 候选词。
- 不允许在 LLM 不可用时静默用规则推断继续生产。
- LLM 不可用、API key 缺失、结构化输出不合法或连续修复失败时，Session 必须进入 `failed`，追加 error message 和 failed event。
- 只允许做非语义处理：trim 空白、长度校验、schema 校验、默认生产参数补齐。
- `waiting_confirmation` 下的补充消息必须带上上一轮用户创意、上一轮 intent/plan/settings 和最新消息交给 LLM。最新消息如果只是修改字数、模型、比例、水印或流程参数，不能被当成新的故事题材。
- 自动生产开始后，普通消息不能重写生产计划，只能返回提示，引导进入项目工作台修改具体产物。

用户消息：

```json
{
  "content": "写一个大学表白短片，傍晚花园里男生鼓起勇气向女生表白，清新电影感。"
}
```

解析输出：

```json
{
  "brief": {
    "title_hint": "傍晚花园里的告白",
    "idea": "大学男生在傍晚花园中鼓起勇气向女生表白。",
    "genre": "校园情感",
    "tone": "清新、电影感、温柔",
    "target_audience": "年轻观众",
    "chapter_count": 1,
    "total_word_target": 1200,
    "must_include": ["傍晚花园", "表白", "青春感"],
    "style_keywords": ["小清新", "自然光", "电影感"],
    "video_mode": "grid_storyboard"
  },
  "settings": {
    "video_mode": "grid_storyboard",
    "image_model": "gpt-image-2",
    "image_size": "2K",
    "image_aspect_ratio": "16:9",
    "seedream_watermark": false,
    "seedance_watermark": false
  }
}
```

Agent 回复计划：

```text
我会生成一个 1 章校园情感短片，整体风格是清新、电影感、温柔。默认使用九宫格分镜，画面比例 16:9，生图模型 GPT Image 2。确认后我会自动完成小说、角色、场景、分镜、视频和合并。
```

LLM 输出要求：

- `brief.title_hint`、`brief.idea`、`brief.genre`、`brief.tone`、`brief.must_include`、`brief.style_keywords` 都必须来自 LLM 对用户创意的理解。
- `chapter_count`、`total_word_target` 可以由 LLM 根据用户目标建议，但必须经过后端上下限校验。
- `video_mode` 默认 `grid_storyboard`，除非用户明确选择其他已接入模式。
- `image_model` 默认 `gpt-image-2`，除非用户明确选择其他已接入模型。
- `image_size` 默认 `2K`，`image_aspect_ratio` 默认 `16:9`，但必须经过模型能力校验。
- LLM 输出只作为受控 JSON；不得直接执行工具、调用阶段接口或修改文件。

## 阶段调度

用户确认开始后，Runner 按顺序提交现有阶段任务。

### 1. 创建小说任务

调用现有：

```http
POST /v1/projects/novel
```

写入：

- `project_id`
- `source_task_id`
- `current_task_id`
- `current_stage=waiting_story`

追加 assistant 消息：

```text
正在生成小说正文...
```

### 2. 等待小说完成

读取：

```http
GET /v1/tasks/{task_id}
```

完成后追加消息：

```text
小说正文已完成，正在拆分场景结构...
```

### 3. 生成场景结构

调用：

```http
POST /v1/projects/scene-structure
```

payload 固定使用根 `source_task_id`。

### 4. 生成分段合同

调用：

```http
POST /v1/projects/segment-contracts
```

如果 artifacts 暴露 `segment_contract_progress.status=failed` 且 `resume_ready=true`：

```json
{
  "resume_from_progress": true
}
```

### 5. 生成角色图

调用：

```http
POST /v1/projects/characters
```

传入 session 的生图模型参数。

### 6. 生成场景母图

调用：

```http
POST /v1/projects/scenes
```

第一版直接生成所有需要的场景母图，不做逐 scene 暂停确认。

### 7. 生成九宫格分镜图

调用：

```http
POST /v1/projects/storyboards
```

第一版生成所有缺失九宫格的 segment。

### 8. 生成分段视频

调用：

```http
POST /v1/projects/videos
```

第一版生成所有缺失视频的 segment。

### 9. 合并成片

调用：

```http
POST /v1/projects/videos
```

payload：

```json
{
  "merge_only": true
}
```

完成后写入：

- `project_id`
- `source_task_id`
- `full_story`
- `workspace_url`
- `artifact_summary`

追加 result 消息：

```text
成片已完成。你可以直接预览视频，也可以进入项目工作台继续修改。
```

## API 设计

### 创建 Session

```http
POST /v1/agent-sessions
```

请求：

```json
{
  "mode": "auto_full_pipeline",
  "product_type": "novel_to_video"
}
```

响应：

```json
{
  "session_id": "session-id",
  "project_id": null,
  "status": "created",
  "current_stage": "created"
}
```

### 发送消息

```http
POST /v1/agent-sessions/{session_id}/messages
```

创意消息：

```json
{
  "content": "大学表白短片，傍晚花园，清新电影感。"
}
```

确认消息：

```json
{
  "content": "开始"
}
```

创意消息响应：

```json
{
  "session": {
    "session_id": "session-id",
    "status": "waiting_confirmation",
    "current_stage": "waiting_confirmation"
  },
  "messages": [
    {
      "role": "assistant",
      "type": "plan",
      "content": "我会生成一个 1 章校园情感短片..."
    }
  ]
}
```

确认消息响应：

```json
{
  "session": {
    "session_id": "session-id",
    "project_id": "project-id",
    "source_task_id": "story-task-id",
    "current_task_id": "story-task-id",
    "status": "waiting_task",
    "current_stage": "waiting_story"
  },
  "messages": [
    {
      "role": "assistant",
      "type": "progress",
      "content": "正在生成小说正文..."
    }
  ]
}
```

### 查询 Session

```http
GET /v1/agent-sessions/{session_id}
```

响应：

```json
{
  "session_id": "session-id",
  "project_id": "project-id",
  "source_task_id": "story-task-id",
  "current_task_id": "task-id",
  "status": "waiting_task",
  "current_stage": "waiting_storyboards",
  "progress": {
    "completed_steps": 6,
    "total_steps": 9,
    "percent": 67
  },
  "result": {
    "workspace_url": "/projects/project-id/workflow/story-task-id",
    "full_story": null
  },
  "error": null
}
```

### 删除 Session

```http
DELETE /v1/agent-sessions/{session_id}
```

默认只删除 Agent 会话、消息和事件，保留绑定项目、任务和产物。

```http
DELETE /v1/agent-sessions/{session_id}?delete_project=true
```

`delete_project=true` 会同时删除绑定项目。前端必须在删除前让用户明确选择“只删会话，保留项目”或“会话和项目都删除”。如果项目存在排队中或运行中的任务，同时删除项目会失败，Session 不会被删除。

响应：

```json
{
  "session_id": "session-id",
  "deleted": true,
  "project_id": "project-id",
  "project_deleted": false
}
```

### 查询消息

```http
GET /v1/agent-sessions/{session_id}/messages
```

响应：

```json
{
  "messages": [
    {
      "message_id": "message-id",
      "role": "user",
      "type": "text",
      "content": "大学表白短片，傍晚花园，清新电影感。",
      "payload": {},
      "created_at": "2026-05-06T12:00:00Z"
    },
    {
      "message_id": "message-id",
      "role": "assistant",
      "type": "plan",
      "content": "我会生成一个 1 章校园情感短片...",
      "payload": {
        "actions": ["开始", "修改需求"]
      },
      "created_at": "2026-05-06T12:00:01Z"
    }
  ]
}
```

### 查询事件

```http
GET /v1/agent-sessions/{session_id}/events
```

响应：

```json
{
  "events": [
    {
      "event_id": "event-id",
      "stage": "waiting_storyboards",
      "status": "running",
      "message": "正在生成九宫格分镜图",
      "task_id": "task-id",
      "created_at": "2026-05-06T12:00:00Z"
    }
  ]
}
```

### 事件流

```http
GET /v1/agent-sessions/{session_id}/events/stream
```

第一版可以先用轮询，不强制实现 SSE。前端定时查询 Session 推进 Runner；messages、events 和 artifacts 在 session 更新时间变化后刷新，避免多个查询接口并发触发重复阶段提交。

## 前端页面设计

路由：

```text
/console/agent
```

页面拆分：

```text
frontend/src/features/agent/
├── AgentChatPage.tsx
├── AgentSessionHistory.tsx
├── AgentMessageList.tsx
├── AgentComposer.tsx
├── AgentProgressRail.tsx
├── AgentArtifactPreview.tsx
└── agentSessionModel.ts
frontend/src/api/agentSessions.ts
frontend/src/types/agent.ts
frontend/src/styles/agent.css
```

页面布局：

```text
左侧窄栏：历史 Agent 会话，可收起
中间主区：聊天流
右侧：阶段进度 / 最近事件 / 当前产物 / 成片
底部：输入框 + 计划确认动作
```

视觉原则：

- 小清新商业风格，浅色雾面背景。
- 中间聊天区为主，不做工程控制台。
- 右侧预览只展示关键产物，不展示大量 JSON。
- 历史会话左栏宽度约 260px，可收起；全局应用侧边栏也可收起。
- 当前阶段用轻量时间线或状态条展示。
- 失败时直接在聊天中展示失败阶段和错误原因。
- 始终提供“进入项目工作台”按钮。

页面状态：

```text
未开始：空聊天页 + 输入框
待确认：计划消息 + 开始/修改需求
运行中：聊天进度消息 + 当前产物预览
暂停：继续/重新跑当前阶段/进入工作台
失败：错误消息 + 重新跑当前阶段/进入工作台
完成：成片播放器 + 进入工作台
```

历史会话删除：

- 历史栏每条会话提供删除入口。
- 删除前必须弹出确认，让用户选择保留项目或同时删除项目。
- 只删会话会移除聊天记录、进度事件和 Session 状态，项目继续保留在作品库。
- 同时删除项目会复用项目删除规则；项目有排队中或运行中的任务时不能删除。

## 外部 Agent 调用方式

外部 Agent 使用会话级动作：

```text
create_session()
send_message(session_id, content)
get_session(session_id)
get_messages(session_id)
get_events(session_id)
delete_session(session_id, delete_project=false)
```

外部 Agent 不需要知道：

- 场景结构接口。
- 分段合同接口。
- 角色图接口。
- 场景母图接口。
- 九宫格接口。
- 视频接口。
- 文件落盘路径。

最终结果：

```json
{
  "status": "completed",
  "project_id": "project-id",
  "workspace_url": "/projects/project-id/workflow/story-task-id",
  "video_url": "/outputs/projects/.../rendered/full_story.mp4",
  "summary": "已生成 1 章、3 个 scene、12 个 segment。"
}
```

## 错误处理

错误分三类：

### 可等待

- 子任务 `queued`。
- 子任务 `running`。

Session 状态保持 `waiting_task`。

### 可重新提交

- 分段合同 checkpoint 可恢复。
- 生图或视频供应商临时失败。
- 网络超时。

Session 记录错误事件，追加 error 消息；用户可以通过“重新跑当前阶段”按钮重新提交当前阶段。暂停状态下的“继续”只表示接着当前任务等待或推进下一阶段，不表示重新生成。

### 不可自动处理

- 用户 prompt 为空。
- 配置缺 API key。
- 小说任务失败。
- 结构化输出多次失败且无 checkpoint。

Session 进入 `failed`，聊天中展示错误说明，并提供项目工作台入口。

## 安全边界

- 外部 Agent 不能提交任意文件路径。
- 外部 Agent 不能直接修改落盘 JSON。
- 外部 Agent 不能执行 shell 或后端代码。
- 用户消息只能触发白名单动作：计划、开始、暂停、继续、重新跑当前阶段、进入工作台。
- 删除会话必须走 `DELETE /v1/agent-sessions/{session_id}`，前端必须让用户选择是否保留项目。
- 上传文件必须走受控 upload API，输出成可访问素材 URL。
- Session settings 必须经过 schema 校验。
- 任务推进只能调用白名单阶段。

## MVP 实施顺序

### 阶段一：Chat Session 骨架

- 新增 Session schema。
- 新增 Message schema。
- 新增 MySQL session/message/event 表。
- 新增 `POST /v1/agent-sessions`。
- 新增 `POST /v1/agent-sessions/{session_id}/messages`。
- 新增 `GET /v1/agent-sessions/{session_id}`。
- 新增 `GET /v1/agent-sessions/{session_id}/messages`。
- 新增 `DELETE /v1/agent-sessions/{session_id}`。
- 新增事件记录。

验收：

- 创建 session 后能持久化。
- 发送创意消息后能保存 user message。
- Agent 能返回 plan message。
- 查询能返回 session、messages 和 events。

### 阶段二：意图解析和确认

- 实现 `AgentIntentPlanner`。
- 调用现有 LLM backend，将用户创意结构化为 `StoryBriefInput`、生产设置和计划回复。
- 使用 schema 校验和有限次数结构化修复。
- LLM 不可用或结构化失败时进入 `failed`，不允许规则兜底继续生产。
- 支持 `waiting_confirmation`。
- 用户发送“开始”后进入 Runner。

验收：

- 用户输入一句创意后，Agent 通过 LLM 返回可读生产计划。
- 任何题材和风格都由 LLM 理解，代码里没有关键词题材/风格判断。
- 用户确认前不自动提交小说任务。
- 用户确认前的计划修改不丢失上一轮创意上下文。
- 生产开始后的普通消息不会重写已提交计划。

### 阶段三：自动调度 Runner

- 实现 `AgentSessionRunner`。
- 支持自动创建小说任务。
- 支持轮询当前 task 并推进下一阶段。
- 支持服务重启后恢复 session。
- 每个阶段追加 progress message 和 event。
- MVP 中 Runner 先由 Session 查询接口触发，后续再按需要增加后台扫描。

验收：

- 一句话确认后能提交小说任务；小说任务完成后轮询 session 能提交场景结构任务。
- 刷新后聊天记录和 session 进度不丢。

### 阶段四：完整小说转视频流水线

- 自动跑角色图、场景母图、九宫格、视频、合并。
- 聚合 artifacts。
- 完成后追加 result message。
- 返回成片和工作台链接。

验收：

- 单个项目能从一句创意自动跑到合并成片。

### 阶段五：前端 Chat Agent 页面

- 新增 Agent 创作入口。
- 新增聊天页。
- 新增消息列表、输入框、快捷动作。
- 新增右侧产物预览和成片播放器。
- 新增工作台跳转。

验收：

- 用户通过聊天就能开始和观察自动生产。
- 失败时能看到明确原因。

### 阶段六：外部 Agent 能力

- 输出 OpenAPI 文档。
- 提供最小 SDK 示例。
- 可选增加 SSE。
- 可选增加文件上传。

验收：

- 外部 Agent 能创建 session、发送消息、轮询进度、拿到最终视频。

## 第一版不做的事

- 不做无限画布。
- 不做自由节点编辑器。
- 不做任意工具调用。
- 不做多 Agent 协作。
- 不做复杂人工审批流。
- 不做自动剪辑平台。
- 不做跨项目素材库自动复用。
- 不做长期用户记忆。

这些能力可以在 Chat-first Agent Session 稳定后再加。

## 验收标准

第一版完成标准：

- 用户能创建 chat session。
- 用户能发送创意消息。
- Agent 能返回生产计划并等待确认。
- 用户确认后，系统能自动依次提交并等待每个阶段任务。
- 聊天流能展示当前阶段、当前任务、失败原因和已生成产物。
- 完成后能返回 `full_story` 和项目工作台链接。
- 后端重启后，未完成 session 能继续推进。
- 外部 Agent 能通过 Session/Message API 完成同样流程。
