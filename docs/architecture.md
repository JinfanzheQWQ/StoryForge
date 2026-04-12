# 架构文档

## 1. 总体目标

当前版本的架构目标不是“生成一篇小说文本”这么简单，而是把整个项目拆成可持续演进的三层能力：

1. 结构化小说生产
2. 面向视频生产的中间产物构建
3. 通过 API 和异步任务队列对外服务

## 2. 分层结构

```text
Client / CLI / API
        |
        v
FastAPI Routers / CLI Commands
        |
        v
Application Layer
  - AppContainer
  - AsyncTaskQueue
        |
        v
Orchestrator / Pipelines
  - run_story_pipeline
  - run_video_pipeline
        |
        v
Domain Services
  - NovelGeneratorService
  - NovelToVideoService
        |
        v
Integrations
  - LangChain backend
  - DeepSeek-compatible model endpoint
  - Seedream image client
  - Seedance manifest / submit client
  - ffmpeg concat script builder
```

## 2.1 技术栈视角

当前实现从技术栈上可以拆成五层：

1. 运行时与工程层：`Python 3.11+`、`uv`
2. 服务层：`FastAPI`、`Pydantic`、`AsyncTaskQueue`
3. Agent 层：`LangChain create_agent + ToolStrategy`
4. 模型集成层：`DeepSeek`、`Seedream 4.5`、`Seedance 2.0`
5. 工作流层：`Orchestrator + Pipelines + Domain Services`

更完整的技术说明见：

- [tech-stack.md](/Users/xy/StoryForge/docs/tech-stack.md)

## 3. 为什么现在引入 FastAPI 和队列

小说生成、角色分析、视频分段规划都属于典型的长耗时任务，不适合直接阻塞 HTTP 请求。当前设计把 API 和执行链路拆开：

- API 只负责接收请求和返回 `task_id`
- 队列负责后台执行
- 用户通过 `/v1/tasks/{task_id}` 轮询结果

当前队列是内存态实现，适合本地开发和第一阶段原型。后续可以很自然迁移到 Redis / RabbitMQ / Celery / Arq / TaskIQ。

## 4. 小说生成架构

当前小说生成部分，严格来说属于“结构化多 Agent 工作流”，不是单一 prompt，也不是完全自治智能体。

### 4.1 多 Agent 角色

当前小说生成不是一个“大 prompt 干到底”的模式，而是按职责拆成多个结构化 Agent：

#### Story Architect

产出：

- 标题
- premise
- theme
- setting
- story_engine
- visual_motifs
- tone_notes

价值：

- 把抽象创意变成可落地的项目底稿
- 为后续角色和章节提供稳定约束

#### Character Designer

产出：

- 角色卡
- 欲望
- 冲突
- 弧光
- 视觉特征
- 结构化音色卡
- 角色图 prompt

价值：

- 不只是给“人物设定”
- 同时为后续角色图生成和视频音频 prompt 提供直接输入

#### Chapter Planner

产出：

- 章节标题
- 章节目标
- 关键冲突
- 场景 beats
- cliffhanger
- featured_characters

价值：

- 让每章都能自然拆成多个视频片段

#### Chapter Writer

产出：

- Markdown 章节草稿
- visual_hooks
- continuity_refs

价值：

- 保证文本可阅读
- 同时保留足够强的影视化抓手

#### Editorial Reviewer

产出：

- overall_verdict
- strengths
- continuity_risks
- revision_notes

价值：

- 防止只顾生成，不顾连续性和项目开发可用性

### 4.2 为什么用结构化输出

结构化输出有三个直接好处：

1. 后续节点更容易消费上一节点的结果
2. 更容易保存为 JSON 中间产物
3. 更方便做测试、审计和回放

当前结构化 schema 在：

- [src/storyforge/domains/novel/schemas.py](/Users/xy/StoryForge/src/storyforge/domains/novel/schemas.py)

## 5. 视频链路架构

视频链路围绕“一个小说拆成多个片段视频”设计，而不是直接追求一次生成完整长视频。

### 5.1 当前步骤

1. 角色视觉分析
2. 角色定妆卡任务清单
3. 视频片段规划
4. 基于角色定妆卡的场景图任务清单
5. Seedance 片段视频清单
6. `ffmpeg` 合并脚本

### 5.1.1 这部分算不算 Agent

视频链路里需要区分两类能力：

- 算 Agent 的部分：
  - 角色视觉设计 Agent
  - 短视频分段导演 Agent
- 不算 Agent 的部分：
  - Seedream 生图 client
  - Seedance 视频 client
  - 文件落盘、轮询、下载、拼接脚本

所以当前视频链路不是“全链路都是 Agent”，而是“Agent 负责规划，工作流负责执行，模型 client 负责实际调用”。

### 5.2 为什么先生成 manifest

因为真实视频生产通常会跨多个异步服务：

- 角色图模型
- 场景图模型
- 视频模型
- 存储
- 任务追踪

如果一开始就把这些都耦合死，后面替换供应商会非常痛苦。现在把过程拆成 manifest，有几个优点：

- 更容易调试
- 更容易做断点续跑
- 更容易接第三方系统
- 更容易做人工审校

### 5.3 Seedance 的定位

当前项目里，Seedance 承担的是：

- 基于首尾帧与 prompt 生成视频片段
- 直接输出带音频的视频片段

因此链路里不再单独引入 TTS。

### 5.4 当前角色一致性策略

当前采用三段式角色一致性约束：

1. 先生成角色定妆卡
2. 再把角色定妆卡作为场景首尾帧的参考图
3. 最后把场景首尾帧交给 Seedance 生成视频

这样做的目的，是尽量把角色一致性收敛在生图阶段，而不是把压力全部交给视频模型。

此外，当前 prompt 里还额外锁定：

1. 年龄感
2. 体型
3. 肩宽
4. 头身比
5. 四肢比例

这能缓解“角色忽老忽幼、忽胖忽瘦”的漂移，但仍然属于 prompt 级控制，不是关键点级别的硬约束。

### 5.5 当前音频生成策略

当前不是把整章小说原文直接丢给 Seedance，而是先让视频片段规划阶段输出：

1. 旁白
2. 角色对白
3. 硬字幕文案
4. 环境音 / 拟音
5. 音乐方向
6. 时间节拍

再由服务层把这些字段以及小说侧的结构化角色音色卡，一起编译成 Seedance 使用的最终音视频 prompt。

当前声音一致性是：

1. 角色设计 Agent 先输出结构化 `voice_profile`
2. 视频服务把 `voice_profile` 编译成 `角色音色锁定`
3. Seedance 按 prompt 生成带原生音频的视频

这解决的是“prompt 层角色声线约束”，不是“声纹级固定说话人”。

## 6. API 与应用层

### 6.1 AppContainer

`AppContainer` 负责把以下对象装配起来：

- `AppConfig`
- `StoryForgeOrchestrator`
- `SeedanceClient`
- `AsyncTaskQueue`

### 6.2 AsyncTaskQueue

当前队列职责：

- 接收任务
- 分配 worker
- 更新状态
- 保存结果

当前状态枚举：

- `queued`
- `running`
- `completed`
- `failed`

### 6.3 任务处理器

当前内置四种任务类型：

- `project.story`
- `project.characters`
- `project.scenes`
- `project.images`
- `project.videos`
- `project.build`

其中：

1. `project.story` 只执行小说生成 pipeline
2. `project.characters` 复用已有 story run，执行角色图生成
3. `project.scenes` 复用同一个 story run 输出目录，执行场景首尾帧生成
4. `project.videos` 复用同一个 story run 输出目录，执行 Seedance 与 ffmpeg 合并
5. `project.images` 是保留给旧脚本和回归测试的兼容图片任务，会连续执行角色图和场景图
6. `project.build` 是保留给旧脚本和回归测试的一键全链路兼容任务

## 7. DeepSeek 接入设计

当前 LLM 接入统一通过：

- [src/storyforge/integrations/llm.py](/Users/xy/StoryForge/src/storyforge/integrations/llm.py)
- [src/storyforge/agents/langchain_agent.py](/Users/xy/StoryForge/src/storyforge/agents/langchain_agent.py)

架构上把 DeepSeek 当成 OpenAI-compatible provider 处理，这样可以继续复用 LangChain 的模型初始化和 `create_agent` / `ToolStrategy`。

## 7.1 当前项目的准确定位

如果要给这套系统下定义，当前最准确的说法是：

- 一个基于 `LangChain + DeepSeek` 的结构化多 Agent 小说与视频规划系统
- 外层由 `FastAPI + 异步任务队列` 提供服务化能力
- 图片与视频执行阶段分别接 `Seedream` 和 `Seedance`

不建议把它描述成“完全自治通用 Agent”，因为当前还没有：

- 长期 memory
- 自主挑选工具
- 动态多轮反思与自修正
- 多 Agent 并行协商机制

## 8. 未来推荐演进

### 第一阶段

- 用 Redis 或数据库替代内存态任务队列
- 引入持久化任务状态和幂等控制

### 第二阶段

- 增加世界观记忆、角色记忆、伏笔记忆
- 增加章节重写 Agent 和分镜审稿 Agent

### 第三阶段

- 提供项目级人工审核、批量重试、失败重放
- 增加多用户权限和项目隔离
