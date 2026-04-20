# 工程状态

> 截至 `2026-04-20`

这份文档只回答三件事：

1. 当前已经完成了什么
2. 当前主要限制是什么
3. 下一步最值得投入的方向是什么

配套文档：

- 使用方式见 [usage.md](usage.md)
- 接口说明见 [api.md](api.md)
- 架构边界见 [architecture.md](architecture.md)
- 代码维护约定见 [development.md](development.md)

## 当前产品形态

StoryForge 当前是一套面向“小说生成 -> 结构化规划 -> 图片生成 -> 视频生成”的工程化工作流系统。

当前主链路：

1. 生成小说正文
2. 人工审阅并编辑正文
3. 生成场景结构
4. 生成分段合同
5. 生成角色图
6. 按 scene / segment 生成场景图与视频
7. 选择性合并总片

当前默认技术面：

- Web / API：`FastAPI`
- 持久化：`MySQL`
- 队列：进程内异步任务队列
- LLM：`DeepSeek`、`ChatGPT 5.4`
- 生图：`Seedream 4.5`
- 生视频：`Seedance 2.0`

## 已完成

### 小说生成与结构化分析

- 已完成结构化多 Agent 小说工作流，包含 `Story Architect`、`Story Drafter`、`Cast Analyzer`、`Character Designer`、`Chapter Planner`、`Editorial Reviewer`
- 已拆成三个清晰阶段：
  - `project.story`
  - `project.scene_structure`
  - `project.segment_contracts`
- `project.story` 会生成并保存可编辑的 `story_source.json`
- Web 端已支持正文展示、修改和保存
- `project.scene_structure` 会基于当前正文生成角色、章节与场景骨架
- `project.segment_contracts` 会在场景骨架上生成正式视频执行合同
- 角色解析以正文为依据，`source_evidence` 需要能在正文中定位
- `CharacterRosterSchema` 会校验角色名唯一与 `cast_slot_id` 唯一
- 结构化输出采用显式重试与显式失败策略，失败原因会进入任务记录
- LangChain 结构化主链路已按 provider 适配：
  - `DeepSeek` 使用 `function_calling`
  - `OpenAI / ChatGPT 5.4` 使用 `json_schema`
- 结构化结果会优先消费 `parsed`，并支持原始 JSON 回收与二次 JSON 恢复调用
- `llm.max_tokens` 已纳入统一配置，默认值为 `8192`

### 视频规划与连续性体系

- 视频规划已稳定采用 `chapter -> scene -> chunk -> segment` 的分层生成链路
- 已生成并落盘以下核心规划文件：
  - `story_memory.json`
  - `scene_plan.json`
  - `segment_plan.json`
  - `scene_structure_source.json`
  - `segment_contract_progress.json`
  - `continuity_report.json`
- `story_memory.json` 会保存章节级承接信息，包括角色关系、视觉延续和道具延续
- `scene_bible` 已进入主规划、场景图 prompt 与视频 prompt
- `shot_state` 已进入分段合同、场景图 prompt 与视频 prompt
- `continuity_link` 已进入分段合同、首帧承接判断与视频 prompt
- `scene_master_frame` 已作为 scene 级空场景母图接入主链路
- 分段合同支持 `scene + chunk` 级 checkpoint 与失败位置继续
- `scene chunk` 结构化阶段现在会拒绝相邻重复 chunk，并限制单个 scene 的预期 segment 总数，避免把同一事件层层嵌套成超长分段
- `chunk -> segment` 合同阶段现在会拒绝相邻重复 segment；如果只是重复同一拍动作、没有新增推进，会在结构化阶段直接失败
- `chunk -> segment` 合同现在要求每个 `segment` 显式输出非空 `timed_beats`；缺少该字段会在结构化 schema / 重试阶段直接失败，不再由后置阶段本地补节拍
- Seedance 前的 segment 归一化现在是幂等的；已拆出的 subsegment 不会在 checkpoint 合并或再次归一化时被重复拆分成 `seg01_01_01...` 级联结构
- segment 后处理已移除工程化子段标记污染，不再把 `第1段`、`当前子片段` 等内部标签写入标题、字幕、`shot_state` 和 `continuity_link`
- scene chunk / segment contract prompt 现在显式禁止 scene 边界回放，并要求纯动作段不要把动作说明写成硬字幕
- scene chunk / segment contract prompt 进一步收紧为“宁可少段，不可碎段”，告白 / 回应 / 双人对话类内容优先生成更少、更完整的 segment
- scene chunk prompt 现在把 `expected_segment_count` 明确为保守上限而非目标值，并强调“一个 chunk = 一个连续事件目标”，减少把同一动作链拆成多个近义 chunk
- segment contract prompt 现在明确 `expected_segment_count` 不必凑满，`title / summary` 禁止写 `第1段 / 继续 / 延续` 这类工程化标签或弱变化描述
- segment contract prompt 现在明确 `mid_frame_characters` 必须跟随中段 beat 的真实出镜角色，不能直接照搬 scene cast，也不能把只在尾帧出现的人提前写进中段帧
- segment contract prompt 现在明确 `opening_match` 必须写成可拍到的开场状态，并给出 `start / continue` 两类简短示例，降低“空 opening_match / 空泛 opening_match”重试失败
- segment contract prompt 现在明确 `timed_beats` 密度要求：5-6 秒通常 1-2 条，8-12 秒通常 2-3 条，避免用单条泛描述覆盖整段
- `expected_segment_count` 现在是严格执行上限，不再默认放宽 `+1`
- `continuity_link.opening_match / allowed_changes / transition_reason` 现在会在 segment 合同阶段被强校验
- 跨 chunk 首段现在必须在结构化阶段就写成 `continue / cut`，不能把后续 chunk 首段重新写成 `start`
- segment 合同阶段现在会直接校验对白 / 字幕与时长预算是否匹配，超预算会进入结构化重试
- 如果某个 segment 的对白预算仍在单段 12 秒上限内，但 LLM 把 `duration_seconds` 写短了，合同校验会直接把该段时长补到所需秒数，而不是因为 `9 秒 / 12 秒` 这种预算错配直接失败
- 如果某个 segment 的对白预算已经超过单段 12 秒上限，当前 chunk 会在结构化阶段自动触发“重拆段”重试：临时提高该 chunk 的 segment 上限，并要求模型把这轮对白拆成多个正式 segment，而不是直接整批失败
- 如果整 chunk 的常规重试已经耗尽，但最后失败仍然是“某个 segment 超过 12 秒”，系统还会追加一次专门的 overflow repair：把上一轮失败 batch JSON 连同超长 segment 信息一起回喂模型，要求它只修当前 chunk 的超长对白拆分
- `subtitle_lines` 已移除 `timed_beats` 本地兜底，不再把动作 beat 自动回填成硬字幕
- `SceneSegmentContractSchema.timed_beats` 现在要求非空，空数组会在 schema 阶段直接失败
- 结构化重试提示现在会针对 `mid_frame_characters`、`opening_match` 和相邻重复事件给出更具体的修正指令
- 连续性系统已接通：
  - `V1` 规则审校
  - `V2` 可选 LLM 软审校
  - `segment` 级修复
  - `scene` 级修复
  - 批量合同修复
- 连续性修复会更新合同与报告，并返回后续建议的媒体动作
- 对白、旁白、硬字幕与时长预算已纳入 segment 合同约束

### 媒体生成链路

- 已接通角色定妆图生成
- 角色图采用统一白底三视图模板，只展示角色姓名
- 已接通 scene 级母图生成
- 已接通 segment 级关键帧生成：
  - 首帧
  - 中段锚点帧
  - 尾帧
- 当片段满足中段锚点帧条件时，分段合同必须显式给出 `requires_mid_frame=true` 与 `mid_frame_characters`；运行时不对中段出镜角色做本地脑补
- 场景图按帧选择角色参考图，不同帧只带当前出镜角色
- 已接通 Seedance 视频提交、轮询、下载与失败报告
- 视频片段支持单段生成
- 已接通手动合并总片 `full_story.mp4`
- `scene_id`、`segment_id` 级局部重跑已接入后端任务入口

### Web / API / 数据

- 已提供六阶段 Web 工作台
- 已提供项目列表页、详情页、时间线视图与资产视图
- 时间线已按 `scene` 分组展示 `segment`
- 前端已展示任务失败原因、阶段失败原因和连续性风险摘要
- 前端支持：
  - 生成场景结构
  - 生成分段合同
  - 从失败位置继续
  - 重生成场景母图
  - 修复单个 scene
  - 修复单个 segment
  - 批量修复风险合同
  - 单段生成场景图
  - 单段生成视频
  - 手动合并总片
- 项目、任务、任务结果已持久化到 MySQL
- 删除项目已接通，会同步清理安全范围内的输出目录
- 服务重启后，未完成任务会重新回到 `queued`
- 静态资源响应已设置 `no-store`，避免浏览器缓存影响前端模块加载

### 代码结构与验证

- 应用层已拆分为 container / runtime / handlers / support / persistence
- 小说域已拆分为 service / prompts / schemas / repair / rules
- 视频域已拆分为 service / prompting / repair / planning
- 测试侧 deterministic builders 已与运行时代码分离
- 最近一次本地基线：
  - `.venv/bin/ruff check src/storyforge tests/test_pipelines.py tests/test_api.py`
  - `.venv/bin/pytest tests/test_pipelines.py tests/test_api.py`
  - 结果：`96 passed`

## 当前主要限制

### 基础设施

- 任务队列仍是进程内异步队列，不是生产级持久化消息队列
- 服务重启后的恢复策略是重新排队，不是严格幂等执行
- 当前还没有对象存储
- 当前还没有认证、权限和多用户治理
- 当前还没有 webhook / 回调能力

### 媒体质量

- 角色一致性主要依赖参考图与 prompt 约束
- 声音一致性目前仍是 prompt 级约束，不是声纹级控制
- 硬字幕主要依赖模型生成结果，缺少稳定的后处理校验
- `scene_master_frame` 的环境基线增强目前主要来自文本推导与规则抽取
- 连续性审校已能发现高风险片段，但还没有接入真实视频理解模型

### 长上下文与规划稳定性

- 长篇内容下的 prompt 长度控制仍需继续优化
- 更严格的结构化校验会提升失败可见性，但也可能增加 LLM 重试次数
- 超长章节虽然已经分到 `scene / chunk / segment`，但章节批次摘要仍有继续压缩空间
- 复杂故事下的跨章关系状态、场景状态与动作余波还可以继续细化

## 推荐下一步

### 第一优先级

1. 把执行队列替换成持久化任务队列
2. 接入对象存储与公网素材 URL 管理
3. 继续强化长篇规划的控长能力与章节批次记忆压缩

### 第二优先级

1. 为 `scene_master_frame` 增加更强的评估与重生成闭环
2. 继续提升连续性修复的自动分流与批处理策略
3. 在视频生成侧补更稳定的字幕与音频时长校验
