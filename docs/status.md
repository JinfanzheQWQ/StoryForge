# 工程状态

> 截至 `2026-04-21`

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
- `project.scene_structure` 现在先抽取章节 must-cover 关键事件，再生成 `scene skeleton`
- 已生成并落盘以下核心规划文件：
  - `story_memory.json`
  - `scene_plan.json`
  - `segment_plan.json`
  - `scene_structure_source.json`
  - `segment_contract_progress.json`
  - `continuity_report.json`
- `story_memory.json` 会保存章节级承接信息，包括角色关系、视觉延续和道具延续
- scene skeleton 现在带 `covered_event_ids`，用于把 scene 与章节关键事件做显式绑定
- 章节 scene 规划现在会强校验关键事件覆盖完整性：所有 `covered_event_ids` 拼接后必须与章节关键事件顺序完全一致，最后一个 scene 必须覆盖章节尾部落点
- 如果 scene 规划漏掉章节后半段事件，系统会直接失败重试，而不是静默产出只覆盖前半章的 `scene_plan.json`
- `scene_bible` 已进入主规划、场景图 prompt 与视频 prompt
- `shot_state` 已进入分段合同、场景图 prompt 与视频 prompt
- `continuity_link` 已进入分段合同、首帧承接判断与视频 prompt
- `scene_master_frame` 已作为 scene 级空场景母图接入主链路
- `scene_prompt` 运行时字段已移除；当前只保留 `scene_master_frame_prompt` 与 `start/mid/end_frame_prompt`
- 场景图阶段现在会按当前帧真实出镜角色做 prompt 净化：自动剔除未出镜角色，以及 `scene_bible / shot_state / continuity_link` 里的服装、发型等造型覆盖描述
- 默认 `mid_frame_prompt` 已不再回灌整段片段总述，避免中段锚点帧被未来状态污染
- `scene_master_frame` prompt 过滤已补强：`两人 / 双人 / 剪影 / 并肩 / 相对 / 接吻` 这类弱人物信号也会被判成人物内容并从母图 prompt 中移除
- `scene_master_frame` 与 scene 级环境 prompt 现在还会过滤 `fixed_props` 里的随身 / 临时动作道具，例如手机、书包、雨伞、花束、信封，避免把人物携带物误画成空场景里的背景摆件
- segment 本地环境音生成现在只会消费过滤后的环境 `fixed_props`；手机、书包这类瞬时随身道具不会再被自动扩写成 `手机相关细节声`
- Seedance prompt 在提交前会再次净化 `sound_effects`；如果某个道具音效只是瞬时随身道具，且 `prop_continuity` 并未明确跟踪它，就不会继续写进视频 prompt
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
- segment contract 现在新增 `mid_frame_mode`：
  - `continuous` 表示中段仍是主镜头连续推进
  - `insert_cut` 表示中段是从主镜头短促切入的单人 / 局部插入镜头
- 如果首帧和尾帧是同一组双人 / 多人，而中段只拍其中一人的反应特写，系统现在允许这种 `双人 -> 单人 -> 双人` 结构，但必须显式写 `mid_frame_mode=insert_cut`，并把运镜写成“从主镜头切入，再切回主镜头收束”
- segment contract prompt 现在把这条规则进一步压成“二选一”决策句，并显式给出非法反例，减少模型输出“首尾整组 / 中段单人 / 仍是 continuous”的半对半错结构
- segment contract prompt 现在明确 `opening_match` 必须写成可拍到的开场状态，并给出 `start / continue` 两类简短示例，降低“空 opening_match / 空泛 opening_match”重试失败
- segment contract prompt 现在明确 `timed_beats` 密度要求：5-6 秒通常 1-2 条，8-12 秒通常 2-3 条，避免用单条泛描述覆盖整段
- segment contract prompt 现在明确 `narration` 只在存在真实旁白 / 心声 / 画外音时填写；已有 `dialogue_lines` 时，不允许再用 `narration` 或 `subtitle_lines` 复述动作和对白
- `expected_segment_count` 现在是严格执行上限，不再默认放宽 `+1`
- `continuity_link.opening_match / allowed_changes / transition_reason` 现在会在 segment 合同阶段被强校验
- 跨 chunk 首段现在必须在结构化阶段就写成 `continue / cut`，不能把后续 chunk 首段重新写成 `start`
- 跨 chunk 首段现在会显式继承上一 chunk 尾部状态摘要：`visible_tail_state`、`carry_over_elements`、`opening_match_seed` 会一起进入 prompt、校验和重试，减少“同一 scene 像重新开演”的情况
- segment 合同阶段现在会直接校验对白 / 字幕与时长预算是否匹配，超预算会进入结构化重试
- 如果某个 segment 的对白预算仍在单段 12 秒上限内，但 LLM 把 `duration_seconds` 写短了，合同校验会直接把该段时长补到所需秒数，而不是因为 `9 秒 / 12 秒` 这种预算错配直接失败
- 如果某个 segment 的对白预算已经超过单段 12 秒上限，当前 chunk 会在结构化阶段自动触发“重拆段”重试：临时提高该 chunk 的 segment 上限，并要求模型把这轮对白拆成多个正式 segment，而不是直接整批失败
- 如果整 chunk 的常规重试已经耗尽，但最后失败仍然是“某个 segment 超过 12 秒”，系统还会追加一次专门的 overflow repair：把上一轮失败 batch JSON 连同超长 segment 信息一起回喂模型，要求它只修当前 chunk 的超长对白拆分
- `subtitle_lines` 已移除 `timed_beats` 本地兜底，不再把动作 beat 自动回填成硬字幕
- Segment 归一化已移除 `summary -> narration` 的本地兜底；对白段里的描述性 `narration` 会在进入 Seedance 时长预算前被剔除，减少本地重复拆出的 `_01/_02` 子段
- `SceneSegmentContractSchema.timed_beats` 现在要求非空，空数组会在 schema 阶段直接失败
- 结构化重试提示现在会针对 `mid_frame_characters`、`opening_match` 和相邻重复事件给出更具体的修正指令
- 结构化重试提示现在会单独指出“首尾双人 / 中段少人”的错误，并要求 LLM 要么保留整组角色，要么显式改成 `mid_frame_mode=insert_cut` 的中段插入镜头
- 这类重试提示现在还会回填具体角色名，直接给出“改回整组 + continuous”或“保留子集 + insert_cut + 双人 -> 单人 -> 双人运镜”的修正模板
- segment 合同校验现在会额外检查 `shot_state.screen_direction` 与尾部 `end_state_lock / end_frame_prompt / 最后一条 timed_beats` 是否存在“靠近镜头 / 远离镜头”语义冲突；这类方向自相矛盾的合同会在结构化阶段直接失败重试
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
- 同一 scene 只要生成过母图，当前 scene 下未选中的其它 segment 任务也会同步更新母图状态，避免连续性报告误报 scene 内母图状态不一致
- 已接通 segment 级关键帧生成：
  - 首帧
  - 中段锚点帧
  - 尾帧
- 当片段满足中段锚点帧条件时，分段合同必须显式给出 `requires_mid_frame=true` 与 `mid_frame_characters`；当前硬触发条件只看 `时长 >= 8 秒`、`对白 >= 2 句` 或 `timed_beats >= 3 拍`，不再因为“双人段”本身而强制要求中段帧；运行时不对中段出镜角色做本地脑补，失败提示也会带出具体触发原因
- 场景图按帧选择角色参考图，不同帧只带当前出镜角色
- Seedream 单帧生图 prompt 已改成短版图片绑定风格：`图片1` 固定是 `scene_master_frame`，`图片2 / 图片3` 固定是当前帧角色参考，时间承接帧只作为追加连续性参考放在后面
- 已接通 Seedance 视频提交、轮询、下载与失败报告
- Seedance 默认提交策略已改为多模态参考图模式：首帧 / 中段 / 尾帧会按 `图片1 / 图片2 / 图片3` 写进同一个 prompt
- 视频阶段现已移除所有额外辅助参考图提交；Seedance 只吃首帧 / 中段 / 尾帧三张时间锚点图，避免母场景图或角色图继续干扰视频构图
- 中段锚点图现在是 Seedance 默认主路径的一部分，不再只是接口降级时才会带上的兜底参考图
- 视频基础 prompt 现在直接输出 `参考图片时间轴`：用 `图片1 / 图片2 / 图片3` 描述起步、中段、收束画面，不再堆 `scene_bible / shot_state / continuity_link` 的大段重复复述
- Seedance 提交层只补一小段 `实际提交图片绑定`，按本次请求的真实图片顺序说明哪一张是起步画面 / 中段状态 / 收束画面
- 简化后仍保留对白、旁白、角色音色、环境音、音乐和硬字幕要求，不会因为 prompt 变短而丢失音频和字幕约束
- 当片段采用 `mid_frame_mode=insert_cut` 时，视频 prompt 现在会额外声明 `图片1 / 图片3` 是主关系镜头、`图片2` 是插入镜头，并要求镜头必须先建立主关系、再切入插入镜头、最后切回主关系收束
- 当关键帧之间人数、角色集合或构图关系发生变化时，视频 prompt 现在会强制要求可见的入画 / 靠近 / 离场 / 景别重构过程，减少单人画面直接硬跳成双人定格
- 如果某段没有对白、旁白和字幕，Seedance prompt 现在会明确要求“无口播、无字幕、只保留环境音 / 拟音 / 音乐”，不再对静音片段追加硬字幕烧录指令
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
- 时间线现在可直接展开查看场景母图 prompt、每段图片 prompt、视频基础 prompt，以及视频提交后真实送往 Seedance 的最终 prompt / submit variant / 参考图绑定顺序
- 时间线现在还会展示场景母图、首帧、中段帧、尾帧和视频片段的真实提交参数 JSON，可直接核对当次到底用了哪些图、按什么顺序提交
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
