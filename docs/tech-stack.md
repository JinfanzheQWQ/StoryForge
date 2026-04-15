# 技术栈与 Agent 定位

这份文档回答两个问题：

1. StoryForge 现在用了哪些技术
2. 这套系统到底算不算 Agent

这里不重复模块分层、接口 contract 或操作步骤：

- 系统分层：看 [architecture.md](architecture.md)
- HTTP 接口：看 [api.md](api.md)
- 使用方式：看 [usage.md](usage.md)

## 技术栈

### 运行时与工程管理

- Python `>= 3.11`
- `uv`
- `tomllib`
- 自定义 `.env` 加载器

### 服务层

- `FastAPI`
- `Uvicorn`
- `Pydantic`
- 进程内异步任务队列
- `PyMySQL`
- 生产元数据存储：MySQL-only

### Agent / LLM 层

- `LangChain[openai] >= 1.2`
- `ChatModel.with_structured_output(...)`
- `DeepSeek`

### 媒体与集成层

- `httpx`
- `Doubao Seedream 4.5`
- `Seedance 2.0`
- `ffmpeg`
- MySQL 8+

### 测试

- `pytest`
- `ruff`

## 这套系统算 Agent 吗

结论：

- 小说生成链路：算，属于结构化多 Agent 工作流
- 视频规划链路：部分算，属于 Agent + 工作流混合
- 整个项目：更准确的说法是“Agentic workflow”

它不是：

- 通用自治智能体
- 带长期记忆的开放式 Agent
- 会自主挑工具和多轮反思的自治系统

它是：

- 多角色分工的结构化生成系统
- 节点间通过 schema 传递结果的工作流
- 有明确中间产物和可审计 trace 的内容生产管线

## 哪些部分算 Agent

### 小说生成链路

- `Story Architect`
- `Story Drafter`
- `Cast Analyzer`
- `Character Designer`
- `Chapter Planner`
- `Editorial Reviewer`

相关代码：

- [`../src/storyforge/agents/langchain_agent.py`](../src/storyforge/agents/langchain_agent.py)
- [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)

### 视频规划链路

- 角色视觉设计 Agent
- 视频分段导演 Agent

相关代码：

- [`../src/storyforge/domains/video/service.py`](../src/storyforge/domains/video/service.py)

## 哪些部分不算 Agent

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

## 当前能力定位

比较准确的定位是：

- 强工作流
- 强 schema 约束
- 弱自治
- 弱长期记忆

当前已经有：

- 角色化分工
- 结构化输出
- deterministic fallback / repair
- 可回放中间产物
- 可插拔模型接入

当前结构化 LLM 调用约定：

- 小说结构化输出按 provider 使用 LangChain chat model 的 `with_structured_output(...)`
- `DeepSeek`: `method="function_calling"`
- `OpenAI / ChatGPT 5.4`: `method="json_schema"`
- StoryForge 外层负责 structured retry，默认最多 3 次
- 如果模型没有返回 parsed tool 结果但 raw 文本里有 JSON，会自动提取 JSON 再做 Pydantic 校验
- 小说结构化生产主链路不再使用 `create_agent + ToolStrategy`，避免 DeepSeek OpenAI-compatible 工具消息链兼容问题；但 backend 代码里仍保留 `create_agent()` 的普通文本生成实现

当前还没有：

- 长期 memory / retrieval
- Planner / Executor / Critic 自修正闭环
- 多 Agent 并行协商
- speaker embedding / 声纹级声音一致性

## 推荐对外介绍方式

推荐说法：

> StoryForge 是一个基于 LangChain + DeepSeek 的结构化多 Agent 小说生成与小说转视频工作流系统，外层通过 FastAPI 和异步任务队列提供服务，图像与视频阶段分别接入 Seedream 4.5 和 Seedance 2.0。

不建议说法：

> 这是一个完全自治的通用 Agent 系统。

## 代码映射

- Agent 抽象：
  - [`../src/storyforge/agents/base.py`](../src/storyforge/agents/base.py)
- LangChain backend：
  - [`../src/storyforge/agents/langchain_agent.py`](../src/storyforge/agents/langchain_agent.py)
- 小说工作流：
  - [`../src/storyforge/domains/novel/service.py`](../src/storyforge/domains/novel/service.py)
- 视频工作流：
  - [`../src/storyforge/domains/video/service.py`](../src/storyforge/domains/video/service.py)
- 流程编排：
  - [`../src/storyforge/agents/orchestrator.py`](../src/storyforge/agents/orchestrator.py)
  - [`../src/storyforge/pipelines/story_pipeline.py`](../src/storyforge/pipelines/story_pipeline.py)
  - [`../src/storyforge/pipelines/video_pipeline.py`](../src/storyforge/pipelines/video_pipeline.py)
- API 与任务系统：
  - [`../src/storyforge/api/main.py`](../src/storyforge/api/main.py)
  - [`../src/storyforge/application/tasks.py`](../src/storyforge/application/tasks.py)
- 模型集成：
  - [`../src/storyforge/integrations/llm.py`](../src/storyforge/integrations/llm.py)
  - [`../src/storyforge/integrations/seedream.py`](../src/storyforge/integrations/seedream.py)
  - [`../src/storyforge/integrations/seedance.py`](../src/storyforge/integrations/seedance.py)
