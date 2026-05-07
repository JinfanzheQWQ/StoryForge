# Agent Tool Skill Mode 方案

## 目标

下一版 Agent 要从固定 Runner 升级为 **LLM 控制的 Tool Agent**。

用户看到的是纯聊天创作体验；LLM 负责理解目标、读取流程 Skill、决定下一步调用哪个 Tool；后端只执行白名单 Tool，并把结果返回给 Agent 继续推理。

核心形态：

```text
用户聊天
  -> LLM Agent
  -> Skill Playbook
  -> Tool Registry
  -> Tool Executor
  -> Existing Backend APIs / TaskQueue
  -> Observation
  -> LLM Agent 继续决策
```

## 设计原则

- Chat 是主界面，不暴露流水线控制台。
- LLM 可以决定下一步，但不能直接执行任意代码、读写文件或调用未注册能力。
- Skill 只描述流程策略，不执行动作。
- Tool 是唯一可执行能力，必须有名称、说明、JSON schema、权限、幂等规则和结果 schema。
- Tool Executor 是安全边界，负责校验参数、检查权限、处理确认、提交任务和记录日志。
- 长任务统一返回 `task_id`，Agent 通过观察结果继续推进。
- 删除、重做、提交昂贵模型调用、覆盖已有产物必须先获得用户确认。
- 每个会话都必须可恢复、可审计、可停止。

## 总体架构

```text
React Agent Chat
  -> Agent Chat API
  -> Agent Runtime
     -> LLM Planner
     -> Skill Loader
     -> Tool Registry
     -> Tool Executor
     -> Memory Store
     -> Observation Store
  -> Existing Project APIs
  -> TaskQueue
  -> Artifacts API
```

模块职责：

- `Agent Runtime`：会话主循环，维护当前消息、可用 Skill、可用 Tool、执行状态和下一步动作。
- `LLM Planner`：读取用户消息、会话记忆、Skill 和 Tool 描述，输出 `assistant_message` 或 `tool_call`。
- `Skill Loader`：加载小说转视频、独立生图、后续生视频等产品流程说明。
- `Tool Registry`：注册后端可执行工具，提供 tool schema 给 LLM。
- `Tool Executor`：验证 tool call，执行后端动作，返回 observation。
- `Memory Store`：保存会话消息、用户确认、项目上下文、工具调用结果和产物引用。
- `Observation Store`：保存每次 tool call 的输入、输出、错误、耗时和关联 task。

## Skill 设计

Skill 是 Agent 的流程说明，适合写成 Markdown 或 YAML。

示例目录：

```text
skills/
  novel_to_video/
    SKILL.md
    tools.yaml
    examples.md
  image_generation/
    SKILL.md
    tools.yaml
```

小说转视频 Skill 必须定义：

- 适用场景：用户想把创意、小说、故事梗概做成剧情短视频。
- 默认目标：先澄清创意，再生成小说，再生成视频。
- 必问信息：题材、长度、风格、画幅、模型偏好、是否需要对白。
- 阶段顺序：小说正文、场景结构、分段合同、角色图、场景母图、九宫格、分段视频、合并成片。
- 用户确认点：开始生产、替换角色图、重做场景图、生成视频、删除项目。
- 失败处理：展示失败阶段、失败原因、可重试动作。
- 输出策略：每阶段只展示用户需要判断的内容，不展示内部 JSON。

Skill 示例：

```markdown
# Novel To Video Skill

当用户要把创意做成剧情短视频时：
1. 如果创意不足，先用自然语言追问关键缺失信息。
2. 如果信息足够，生成生产计划并请用户确认。
3. 用户确认后调用 create_project。
4. 调用 generate_story。
5. 等待 task 完成后调用 generate_scene_structure。
6. 继续调用 generate_segment_contracts、generate_character_images、generate_scene_masters、generate_storyboards、generate_segment_videos、merge_video。
7. 每个阶段完成后读取 get_project_artifacts。
8. 需要用户判断时暂停，等待用户选择。
```

## Tool Registry

Tool 是后端真实能力。第一版 Tool 不追求多，先覆盖小说转视频完整链路。

核心 Tool：

```text
create_project
generate_story
generate_scene_structure
generate_segment_contracts
generate_character_images
regenerate_character_image
select_character_candidate
generate_scene_masters
generate_storyboards
generate_segment_video
rerun_segment_video
merge_video
get_project_artifacts
get_task_status
pause_task_flow
cancel_task_flow
delete_agent_session
```

Tool 定义字段：

```json
{
  "name": "generate_story",
  "description": "根据项目 brief 生成小说正文。",
  "input_schema": {},
  "output_schema": {},
  "requires_confirmation": false,
  "idempotency_key_fields": ["session_id", "project_id", "stage"],
  "risk_level": "normal"
}
```

高风险 Tool：

- `delete_agent_session`
- `delete_project`
- `regenerate_character_image`
- `select_character_candidate`
- `rerun_segment_video`
- `merge_video`

这些 Tool 必须设置 `requires_confirmation=true`。

## Agent Runtime 循环

一次会话的主循环：

```text
1. 接收用户消息。
2. 保存 message。
3. 读取 session memory。
4. 选择适用 Skill。
5. 把 Skill 摘要、可用 Tools、当前 artifacts 摘要交给 LLM。
6. LLM 输出：
   - assistant_message
   - tool_call
   - ask_confirmation
   - wait_for_task
7. 如果是 tool_call，Tool Executor 执行并写入 observation。
8. 如果是 wait_for_task，前端或后台 worker 轮询 task。
9. 如果 task 完成，把 observation 交回 LLM 决定下一步。
10. 直到完成、暂停、取消或等待用户输入。
```

LLM 输出必须是结构化对象：

```json
{
  "type": "tool_call",
  "assistant_message": "我先创建项目并生成小说正文。",
  "tool_name": "generate_story",
  "arguments": {
    "project_id": "project-id",
    "brief": {}
  },
  "requires_user_confirmation": false
}
```

## Memory 模型

下一版需要三类记忆。

Session Memory：

- 当前聊天消息。
- 当前项目。
- 当前阶段。
- 当前等待的 task。
- 最近 observation。
- 用户已确认的决策。

Project Memory：

- 项目 brief。
- 角色设定。
- 场景设定。
- 用户对产物的选择。
- 已保存的最终产物。

Preference Memory：

- 用户偏好的画幅、模型、风格、字幕习惯。
- 第一版可以只设计表结构，不默认启用自动引用。
- 引用偏好前必须让用户知道可被修改。

## 后端数据模型

新增表建议：

```text
agent_tools
- tool_name
- description
- input_schema_json
- output_schema_json
- risk_level
- requires_confirmation
- enabled
- created_at
- updated_at

agent_tool_calls
- call_id
- session_id
- tool_name
- arguments_json
- status
- task_id
- observation_json
- error_text
- created_at
- updated_at

agent_skills
- skill_id
- name
- version
- content
- enabled
- created_at
- updated_at

agent_memories
- memory_id
- scope
- owner_id
- project_id
- session_id
- title
- content
- metadata_json
- created_at
- updated_at
```

现有 `agent_sessions`、`agent_session_messages`、`agent_session_events` 可以继续作为聊天和事件主体。

## API 设计

Agent Chat API：

```http
POST /v1/agent-sessions
POST /v1/agent-sessions/{session_id}/messages
GET  /v1/agent-sessions/{session_id}
GET  /v1/agent-sessions/{session_id}/messages
GET  /v1/agent-sessions/{session_id}/events
POST /v1/agent-sessions/{session_id}/confirm
POST /v1/agent-sessions/{session_id}/pause
POST /v1/agent-sessions/{session_id}/resume
POST /v1/agent-sessions/{session_id}/cancel
```

Tool API：

```http
GET  /v1/agent-tools
GET  /v1/agent-tools/{tool_name}
POST /v1/agent-tool-calls
GET  /v1/agent-tool-calls/{call_id}
```

Skill API：

```http
GET /v1/agent-skills
GET /v1/agent-skills/{skill_id}
```

## 前端交互

页面仍然是聊天主界面。

左侧：

- 历史会话。
- 项目快捷入口。
- 可收起。

中间：

- 聊天消息。
- 用户输入框。
- Agent 的计划、确认请求、错误和结果。

右侧：

- 当前项目摘要。
- 当前等待任务。
- 当前产物预览。
- Tool 调用轨迹的简化视图。

不要把 Tool JSON 默认展示给普通用户。开发模式可以展开请求详情。

## 安全边界

禁止：

- LLM 直接执行 shell。
- LLM 直接读取或写入本地文件。
- LLM 调用未注册 Tool。
- LLM 绕过确认执行删除、覆盖、重做、提交高成本任务。
- 前端直接提交任意落盘路径。

必须：

- Tool 参数用 Pydantic 校验。
- Tool 调用写入审计日志。
- Tool 调用支持幂等键。
- 异步 Tool 返回 task id。
- Agent 只能基于真实 observation 回复已完成状态。
- 失败必须暴露 tool name、阶段、错误原因和可选下一步。

## MVP 范围

第一阶段：

- Tool Registry 内存注册。
- Tool Executor 包装现有项目阶段 API。
- Novel To Video Skill 文件。
- LLM Planner 输出 `assistant_message`、`tool_call`、`ask_confirmation`、`wait_for_task`。
- Session Memory 保存 tool calls 和 observations。
- 前端展示 Tool Agent 聊天流和当前等待任务。

第二阶段：

- 后台 Agent worker 继续推进等待任务。
- Tool call 审计表。
- Skill 管理接口。
- 高风险 Tool 确认卡片。
- 项目级记忆。

第三阶段：

- 用户偏好记忆。
- 多产品 Skill：独立生图、单独生视频、简易剪辑。
- 外部 Agent SDK。
- SSE 或 WebSocket 实时事件。

## 迁移策略

当前固定 Runner 可以保留为 `auto_full_pipeline` Tool。下一版先让 LLM 调用这个 Tool，之后逐步拆成更细粒度 Tool。

推荐顺序：

1. 新增 Tool Registry 和 Tool Executor。
2. 把当前 `AgentSessionRunner` 封装成 `run_novel_to_video_pipeline` Tool。
3. 新增 `Novel To Video Skill`，让 LLM 根据 Skill 决定何时调用该 Tool。
4. 再把完整流程拆成阶段级 Tool。
5. 前端从“固定阶段按钮”转成“聊天确认卡片 + 当前 Tool 状态”。

这样可以先得到真正的 LLM Tool Agent 形态，同时不一次性重写整个生产链路。

## 验收标准

- 用户能自然聊天描述目标。
- LLM 能根据 Skill 生成下一步计划。
- LLM 能输出结构化 tool call。
- 后端只执行已注册 Tool。
- 高风险 Tool 会等待用户确认。
- 长任务完成后 Agent 能读取 observation 并继续下一步。
- 刷新页面后能恢复消息、tool calls、当前 task 和项目状态。
- Agent 回复的完成状态必须来自真实 Tool observation。
- 外部 Agent 能通过同一套 API 调用完整流程。
