# 技术栈与 Agent 定位

## 1. 当前代码分别用了什么技术

### 运行时与工程管理

- `Python >= 3.11`
- `uv` 管理依赖、虚拟环境与命令执行
- `tomllib` 读取 `TOML` 配置
- 自定义 `.env` 加载器读取运行时密钥和接口地址

### API 与服务层

- `FastAPI` 暴露 HTTP 接口
- `Uvicorn` 作为本地开发服务入口
- `Pydantic` 做请求体验证和结构化 schema 校验
- 内存态异步任务队列 `AsyncTaskQueue` 做长任务调度

### Agent / LLM 层

- `LangChain >= 1.2`
- `create_agent(...)` 构建结构化 Agent 调用
- `ToolStrategy(schema)` 约束结构化输出
- `DeepSeek` 作为当前默认 LLM
- 通过 OpenAI-compatible 方式接入 DeepSeek `base_url`

### 领域工作流层

- `StoryForgeOrchestrator` 负责编排 story pipeline 和 video pipeline
- `NovelGeneratorService` 负责编排小说生成节点
- `NovelToVideoService` 负责编排视频规划节点
- `dataclasses` + `Pydantic schema` 共同承载中间产物

### 模型与媒体集成

- `httpx` 调用外部模型接口
- `Doubao Seedream 4.5` 负责角色图与场景首尾帧生成
- `Seedance 2.0` 负责视频片段生成、状态查询、结果下载
- `ffmpeg` 脚本生成功能用于后续片段拼接

### 测试与验证

- 标准库 `unittest`
- JSON / Markdown / 本地文件产物回放

## 2. 这套代码算 Agent 吗

结论先说：

- `小说生成链路`：算，属于“结构化多 Agent 工作流”
- `视频规划链路`：部分算，属于“Agent + 工作流混合”
- `整个项目`：更准确的说法是“Agentic workflow / 基于 Agent 的内容生产管线”

它不是下面这种意义上的 Agent：

- 不是通用自主智能体
- 不是带长期记忆和自主工具探索的开放式 Agent
- 不是会自己动态发明任务、自己拆工具、自己循环反思很多轮的自治系统

它是下面这种意义上的 Agent：

- 不同节点有明确角色分工
- 每个节点有独立 system prompt / user prompt
- 每个节点输出结构化结果给下游节点消费
- 节点之间由 orchestrator 和 pipeline 串成有状态工作流

## 3. 哪些部分算 Agent，哪些不算

### 算 Agent 的部分

#### 小说生成链路

- `Story Architect`
- `Character Designer`
- `Chapter Planner`
- `Chapter Writer`
- `Editorial Reviewer`

这些节点都通过：

- [langchain_agent.py](/Users/xy/StoryForge/src/storyforge/agents/langchain_agent.py)
- [service.py](/Users/xy/StoryForge/src/storyforge/domains/novel/service.py)

来执行结构化生成，所以它们是典型的“角色化、多节点、结构化 Agent”。

其中 `Character Designer` 现在不只输出人物关系和角色图 prompt，也输出结构化 `voice_profile`，至少包含：

- `voice_style`
- `timbre`
- `speaking_rate`
- `emotional_baseline`
- `accent_or_texture`
- `dialogue_delivery`
- `forbidden_voice_changes`

#### 视频规划链路里算 Agent 的部分

- 角色视觉设计 Agent
- 短视频分段导演 Agent

这些节点通过：

- [service.py](/Users/xy/StoryForge/src/storyforge/domains/video/service.py)

里的 `_run_structured_agent(...)` 调用大模型，输出角色视觉圣经和视频片段规划。

### 不算 Agent 的部分

- `SeedreamClient`
- `SeedanceClient`
- `FastAPI`
- `AsyncTaskQueue`
- `StoryForgeOrchestrator`
- `run_story_pipeline(...)`
- `run_video_pipeline(...)`

这些更准确属于：

- 集成层
- 基础设施层
- 工作流编排层

它们负责调度、校验、存储、轮询、下载和文件落盘，不负责“自主推理角色任务”。

## 4. 当前 Agent 能力强度怎么定义

当前比较准确的定位是：

- `L1-L2` 的结构化生产 Agent
- 强工作流、弱自治
- 强 schema 约束、弱开放式工具使用

当前已经有：

- 角色化分工
- 结构化输出
- fallback
- 可测试中间产物
- 可插拔模型接入
- 小说角色音色卡到视频 prompt 的贯通
- 连续片段首尾帧复用
- 更明确的角色年龄感 / 体态锁定 prompt

当前还没有：

- Agent 自主挑工具
- 动态多轮反思
- Planner / Executor / Critic 的闭环自修正
- 长期 memory / retrieval
- 多 Agent 并行协商
- 真正的 speaker embedding / 声纹级声音一致性控制

## 5. 如果你要对外介绍，建议怎么说

推荐说法：

> StoryForge 当前是一个基于 LangChain + DeepSeek 的结构化多 Agent 小说生成与小说转视频工作流系统，外层用 FastAPI 和异步任务队列封装，图片与视频阶段分别接入 Seedream 4.5 和 Seedance 2.0。

不建议说法：

> 这是一个完全自治的通用 Agent 系统。

因为当前实现还没有到那个级别，文档里应该避免夸大。

## 6. 代码映射速查

- Agent 抽象：
  - [base.py](/Users/xy/StoryForge/src/storyforge/agents/base.py)
- LangChain Agent 后端：
  - [langchain_agent.py](/Users/xy/StoryForge/src/storyforge/agents/langchain_agent.py)
- 小说多 Agent 工作流：
  - [service.py](/Users/xy/StoryForge/src/storyforge/domains/novel/service.py)
- 视频规划 Agent 工作流：
  - [service.py](/Users/xy/StoryForge/src/storyforge/domains/video/service.py)
- 流程编排：
  - [orchestrator.py](/Users/xy/StoryForge/src/storyforge/agents/orchestrator.py)
  - [story_pipeline.py](/Users/xy/StoryForge/src/storyforge/pipelines/story_pipeline.py)
  - [video_pipeline.py](/Users/xy/StoryForge/src/storyforge/pipelines/video_pipeline.py)
- API 与任务队列：
  - [main.py](/Users/xy/StoryForge/src/storyforge/api/main.py)
  - [tasks.py](/Users/xy/StoryForge/src/storyforge/application/tasks.py)
- 模型集成：
  - [llm.py](/Users/xy/StoryForge/src/storyforge/integrations/llm.py)
  - [seedream.py](/Users/xy/StoryForge/src/storyforge/integrations/seedream.py)
  - [seedance.py](/Users/xy/StoryForge/src/storyforge/integrations/seedance.py)
