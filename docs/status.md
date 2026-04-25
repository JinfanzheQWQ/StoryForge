# 工程状态

> 截至 `2026-04-24`

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
- 视频域内部维护性拆分已继续推进：
  - `chapter_orchestration.py` 负责 chapter 级编排
  - `chapter_event_validation.py` 负责 chapter event coverage 校验
  - `chunk_orchestration.py` 负责 scene chunk / segment contract 编排
  - `segment_validation.py` 负责 segment 合同校验
  - `structure_validation.py` 负责 scene/chunk/transition 结构校验
  - `structured_generation.py` 负责结构化 LLM 执行与重试循环
  - `structured_retry_prompts.py` 负责结构化 retry 文案
  - `text_rules.py` 负责共用文本规则
  - `NovelToVideoService` 保留稳定公开入口
- `project.scene_structure` 先抽取章节 must-cover 关键事件，再生成 `scene skeleton`
- 已生成并落盘以下核心规划文件：
  - `story_memory.json`
  - `scene_plan.json`
  - `segment_plan.json`
  - `scene_structure_source.json`
  - `segment_contract_progress.json`
  - `continuity_report.json`
- `story_memory.json` 会保存章节级承接信息，包括角色关系、视觉延续和道具延续
- scene skeleton 带 `covered_event_ids`，用于把 scene 与章节关键事件做显式绑定
- scene skeleton 还会保留紧凑版 `covered_event_summaries`，供后续 chunk planner / repair / 边界校验复用
- 非首个 scene 带 `scene_transition_contract`，用于描述它如何从上一场进入当前场
- `scene skeleton -> 最终 scene_plan` 的 stage2 回写链路会保留 `scene_transition_contract` 与 `covered_event_summaries`，不会在重建 / 归一化时丢掉 scene 级边界信息
- 章节 scene 规划会强校验关键事件覆盖完整性：所有 `covered_event_ids` 拼接后必须与章节关键事件顺序完全一致，最后一个 scene 必须覆盖章节尾部落点
- 如果 scene 规划漏掉章节后半段事件，系统会直接失败重试，而不是静默产出只覆盖前半章的 `scene_plan.json`
- `Chapter Event Planner` 的尾部覆盖校验已经收紧到短章：不会只检查长章，较短章节如果最后一个 must-cover event 结束得过早，也会直接失败重试
- `scene_bible` 已进入主规划、场景图 prompt 与视频 prompt
- `shot_state` 已进入分段合同、场景图 prompt 与视频 prompt
- `motion_plan` 已进入分段合同与视频 prompt，用于约束 `图片1 -> 图片2 -> 图片3` 的可见运动；缺失时由后处理基于 `timed_beats / shot_state` 补齐
- `continuity_link` 已进入分段合同、首帧承接判断与视频 prompt
- `scene_master_frame` 已作为 scene 级空场景母图接入主链路
- `scene_prompt` 运行时字段不提交；当前只保留 `scene_master_frame_prompt` 与 `start/mid/end_frame_prompt`
- 场景图阶段会按当前帧真实出镜角色做 prompt 净化：自动剔除未出镜角色，以及 `scene_bible / shot_state / continuity_link` 里的服装、发型等造型覆盖描述
- 默认 `mid_frame_prompt` 优先取 `timed_beats` 的中间拍，不会回灌整段片段总述，避免中段锚点帧被未来状态污染
- `mid/end` 帧的 frame-level prompt 上下文已进一步收紧：不会直接注入整段 `shot_state.action_progression` 或 `continuity_link.allowed_changes`，而是只保留当前帧真正需要的 `blocking / framing / end_state_lock` 与通用承接语句
- `scene_master_frame` prompt 过滤已补强：`两人 / 双人 / 剪影 / 并肩 / 相对 / 接吻` 这类弱人物信号也会被判成人物内容并从母图 prompt 中移除
- `scene_master_frame` 会从 `scene_bible.spatial_layout / character_blocking / scene_anchor / 关键帧 prompt` 中提取环境版空间合同，尽量保留 `长椅 / 画架 / 步道 / 十米外 / 右后方` 这类真实空间关系，同时剔除角色名和人物动作词
- `scene_master_frame` 与 scene 级环境 prompt 还会过滤 `fixed_props` 里的随身 / 临时动作道具，例如手机、书包、雨伞、花束、信封，避免把人物携带物误画成空场景里的背景摆件
- segment 本地环境音生成只会消费过滤后的环境 `fixed_props`；手机、书包这类瞬时随身道具不会被自动扩写成 `手机相关细节声`
- Seedance prompt 在提交前会再次净化 `sound_effects`；如果某个道具音效只是瞬时随身道具，且 `prop_continuity` 并未明确跟踪它，就不会继续写进视频 prompt
- 分段合同支持 `scene + chunk` 级 checkpoint 与失败位置继续
- `scene chunk` 结构化阶段会拒绝相邻重复 chunk，并限制单个 scene 的预期 segment 总数，避免把同一事件层层嵌套成超长分段
- `chunk -> segment` 合同阶段会拒绝相邻重复 segment；如果只是重复同一拍动作、没有新增推进，会在结构化阶段直接失败
- `chunk -> segment` 合同要求每个 `segment` 显式输出非空 `timed_beats`；缺少该字段会在结构化 schema / 重试阶段直接失败，不会由后置阶段本地补节拍
- Seedance 前的 segment 归一化是幂等的；已拆出的 subsegment 不会在 checkpoint 合并或再次归一化时被重复拆分成 `seg01_01_01...` 级联结构
- segment 后处理与 Seedance 归一化会保留 scene 级元数据，不会因为按扁平 `segments` 重建 plan 而丢失 `covered_event_ids` 等 scene 级字段
- segment 后处理不提交工程化子段标记污染，不会把 `第1段`、`当前子片段` 等内部标签写入标题、字幕、`shot_state` 和 `continuity_link`
- scene chunk / segment contract prompt 显式禁止 scene 边界回放，并要求纯动作段不要把动作说明写成硬字幕
- scene 首个 chunk / 首个 segment 会显式消费 `scene_transition_contract`
  - 首个 chunk 必须先承接上一场尾部，再 reveal 当前场环境
  - 首个 segment 的 `opening_match` 与前 1-2 条 `timed_beats` 必须落地 `next_scene_entry_match / bridge_action`
- `continuity_report` 的 `V1` 规则审校会直接检查 scene 边界：
  - 会检查 `scene_transition_contract` 记录的上一场退出状态是否和上一场真实尾部漂移
  - 会检查 `next_scene_entry_match / bridge_action / visual_bridge` 是否过弱
  - 会检查当前 scene 首段的 `opening_match` 与前 1-2 拍是否真的消费了 scene 级过桥合同
- scene chunk / segment contract prompt 进一步收紧为“宁可少段，不可碎段”，告白 / 回应 / 双人对话类内容优先生成更少、更完整的 segment
- chapter event planner 会限制单个关键事件的粒度：一个 event 最多只保留 1-2 个紧密绑定推进点；如果一个 event 已经把“等待 -> 会面 -> 开口”或“试探 -> 告白 -> 回应”写成同一个 summary，会在 chapter 结构化阶段直接失败重试
- 多 event 章节的首尾 event 允许最多 3 个紧密绑定推进点，用来容纳常见的开场建立与章节收束；中间 event 与单 event 章节维持 2 点上限
- chapter event prompt / retry 会显式排除“只用于解释上下文的背景介绍、关系说明、回忆补叙”；中间 event 不能把问句、回答和动作结果三连塞进同一个 event
- chapter event 的粗粒度估算以 `summary` 为主判，不会把同一 event 的 `source_evidence` 碎片重复算成额外推进点；`source_evidence` 也被收口为当前 event 对应的 1-2 个相邻正文片段
- chapter event 如果第一次仍产出“过粗 event”，当前链路会自动进入 `video-chapter-event-repair` 定向修复，不会只依赖全量重试
- 如果整份 `video-chapter-event-repair` 仍然失败，当前链路会继续触发 `video-chapter-event-split-repair`：只拆当前那个过粗 event，再把 replacement events 合并回整章事件列表
- chapter event 粗粒度修复是迭代式的：如果同一章里连续存在多个粗 event，系统会在每轮 repair / split repair 合并后继续校验整章，并对新的粗 event 继续下一轮修复，而不是只修第一处
- `video-chapter-event-split-repair` 的本地校验只强校验当前 replacement events 本身，不会因为整章里另一个尚未处理的粗 event 而阻塞当前 targeted split
- chapter scene planner prompt 会显式提醒：不要把过多相邻关键事件一口吞进同一个 scene；如果事件块已经形成完整多阶段链路，应优先拆更多 scene，而不是把压力全留给 chunk planner
- scene chunk prompt 把 `expected_segment_count` 明确为保守上限而非目标值，并强调“一个 chunk = 一个连续事件目标”，减少把同一动作链拆成多个近义 chunk
- scene chunk prompt 还会显式写出当前 scene 绑定的 `covered_event_ids`，并要求最后一个 chunk 真正落到本 scene 的最后结果，不能只停在“即将发生”
- scene chunk prompt 与结构化校验会同时读取当前 scene 绑定的 `covered_event_summaries`；如果 chunk 偷偷写进后续 scene 才该发生的关键推进，会按 scene 边界越界直接失败重试
- scene chunk 结构化校验会前置检查动作容量：会按 `must_cover / transition_goal` 估算推进点数量；如果一个 chunk 明显已经包含多轮动作结果，但 `expected_segment_count` 仍过小，会直接失败重试并要求拆更多 segment 或更早拆 chunk
- 如果 scene chunk 的常规重试已经耗尽，但最后失败仍是“动作容量过载”，系统会自动追加一次 `video-scene-chunk-repair` 定向修复，只要求模型修当前失败 chunk 的段数预算，而不是整 scene 盲重跑
- segment contract prompt 明确 `expected_segment_count` 不必凑满，`title / summary` 禁止写 `第1段 / 继续 / 延续` 这类工程化标签或弱变化描述
- segment contract prompt 要求：如果当前 chunk 的 `must_cover / transition_goal` 已经是开口、回应、靠近、牵手、拥抱、亲吻或离开决定，最后一个 segment 必须真正落到这个结果，不要只写“准备做”
- `scene chunk -> segment contract` 会检查最后一个 segment 是否真正落到当前 chunk 的 `transition_goal`；这类“收束不够落地”的问题会优先走 repair，repair 失败时降级成 planner warning，不会默认卡死主链路
- 如果 scene segment planner 的常规重试已经耗尽，但最后失败仍是“某个 segment 的 `timed_beats` 尾部没有覆盖完整时长”，系统会自动追加一次 `video-scene-segment-timeline-repair`，只定向补该段尾部 beat，而不是整 chunk 直接失败
- 如果某个 segment 只是因为时长偏短导致轻微动作容量超载，合同校验会先把 `duration_seconds` 自动拉到可容纳动作的最小时长；扩秒时会同步把最后一条 `timed_beats` 延到新时长；如果仍未覆盖完整时长，再交给 `video-scene-segment-timeline-repair` 补尾部节拍
- 如果扩到 12 秒后动作容量仍然超载，系统才会追加 `video-scene-segment-action-repair`，只定向拆该段的动作链，而不是整 chunk 直接失败
- `video-scene-segment-action-repair` 会迭代消化后续失败：如果第一轮 repair 后仍残留过载子段，或 repair 拆出更多段后触发 chunk 段数上限，系统会继续拿最新失败 batch 再跑下一轮
- 多人同帧镜头冲突先由 schema normalize 兜底：共享 `shot_state.framing / shot_state.camera_motion` 会被改成多人同框关系镜头；如果后续仍残留冲突，系统会自动追加 `video-scene-segment-focus-repair` 定向修镜头字段
- segment contract prompt 明确 `mid_frame_characters` 必须跟随中段 beat 的真实出镜角色，不能直接照搬 scene cast，也不能把只在尾帧出现的人提前写进中段帧
- segment contract 包含 `mid_frame_mode`：
  - `continuous` 表示中段仍是主镜头连续推进
  - `insert_cut` 表示中段是从主镜头短促切入的单人 / 局部插入镜头
- 如果首帧和尾帧是同一组双人 / 多人，而中段只拍其中一人的反应特写，系统允许这种 `双人 -> 单人 -> 双人` 结构，但必须显式写 `mid_frame_mode=insert_cut`，并把运镜写成“从主镜头切入，再切回主镜头收束”
- segment contract prompt 把这条规则进一步压成“二选一”决策句，并显式给出非法反例，减少模型输出“首尾整组 / 中段单人 / 仍是 continuous”的半对半错结构
- segment contract prompt 明确 `opening_match` 必须写成可拍到的开场状态，并给出 `start / continue` 两类简短示例；这类开场承接偏弱问题会优先 repair，必要时只记 warning
- segment contract prompt 明确 `timed_beats` 密度要求：5-6 秒通常 1-2 条，8-12 秒通常 2-3 条，避免用单条泛描述覆盖整段
- segment contract prompt 明确 `narration` 只在存在真实旁白 / 心声 / 画外音时填写；已有 `dialogue_lines` 时，不允许再用 `narration` 或 `subtitle_lines` 复述动作和对白
- `expected_segment_count` 是严格执行上限，不会默认放宽 `+1`
- `continuity_link.opening_match / allowed_changes / transition_reason` 会在 segment 合同阶段被强校验
- 无中段片段会做 `start -> end` 关键帧语义距离检查；如果首尾只是“停在原地 / 保持等待 / 姿态几乎不变”的近义改写，会优先触发 repair，失败时降级成 warning
- 跨 chunk 首段必须在结构化阶段就写成 `continue / cut`，不能把后续 chunk 首段重新写成 `start`
- 跨 chunk 首段会显式继承上一 chunk 尾部状态摘要：`visible_tail_state`、`carry_over_elements`、`opening_match_seed` 会一起进入 prompt、校验和重试，减少“同一 scene 像重新开演”的情况
- segment 合同阶段会直接校验对白 / 字幕与时长预算是否匹配，超预算会进入结构化重试
- segment 合同阶段会直接校验动作容量：5-6 秒片段最多允许 1-2 个可见推进点，8-9 秒最多 3 个，10-12 秒最多 4 个；轻微超载优先自动扩秒，扩到 12 秒仍装不下时才触发 chunk 内拆段重试
- 如果某个 segment 的对白预算仍在单段 12 秒上限内，但 LLM 把 `duration_seconds` 写短了，合同校验会直接把该段时长补到所需秒数，而不是因为 `9 秒 / 12 秒` 这种预算错配直接失败
- 如果某个 segment 的对白预算已经超过单段 12 秒上限，当前 chunk 会在结构化阶段自动触发“重拆段”重试：临时提高该 chunk 的 segment 上限，并要求模型把这轮对白拆成多个正式 segment，而不是直接整批失败
- 动作容量过载也已接入同一条结构化重试链：系统会临时提高当前 chunk 的 `effective_expected_segment_count`，并在 retry prompt 中直接写明“至少拆成 N 个 segment”
- chapter event 过粗也已接入结构化重试链：系统会明确要求把粗事件拆成更细的相邻 `event_id`，而不是继续把多轮动作和关系结果合并进同一个关键事件
- 如果整 chunk 的常规重试已经耗尽，但最后失败仍然是“某个 segment 超过 12 秒”，系统还会追加一次专门的 overflow repair：把上一轮失败 batch JSON 连同超长 segment 信息一起回喂模型，要求它只修当前 chunk 的超长对白拆分
- `subtitle_lines` 不提交 `timed_beats` 本地兜底，不会把动作 beat 自动回填成硬字幕
- Segment 归一化不提交 `summary -> narration` 的本地兜底；对白段里的描述性 `narration` 会在进入 Seedance 时长预算前被剔除，减少本地重复拆出的 `_01/_02` 子段
- `SceneSegmentContractSchema.timed_beats` 要求非空，空数组会在 schema 阶段直接失败
- 结构化重试提示会针对 `mid_frame_characters`、`opening_match` 和相邻重复事件给出更具体的修正指令
- 结构化重试提示会单独指出“首尾双人 / 中段少人”的错误，并要求 LLM 要么保留整组角色，要么显式使用 `mid_frame_mode=insert_cut` 的中段插入镜头
- 这类重试提示还会回填具体角色名，直接给出“改回整组 + continuous”或“保留子集 + insert_cut + 双人 -> 单人 -> 双人运镜”的修正模板
- segment 合同校验会额外检查 `shot_state.screen_direction` 与尾部 `end_state_lock / end_frame_prompt / 最后一条 timed_beats` 是否存在“靠近镜头 / 远离镜头”语义冲突；这类方向自相矛盾的合同会在结构化阶段直接失败重试
- 连续性系统支持：
  - `V1` 规则审校
  - `V2` 可选 LLM 软审校
  - `segment` 级修复
  - `scene` 级修复
  - 批量合同修复
- 连续性修复会更新合同与报告，并返回后续建议的媒体动作
- 对白、旁白、硬字幕与时长预算已纳入 segment 合同约束

### 媒体生成链路

- 支持角色定妆图生成
- 角色图采用统一白底三视图模板，只展示角色姓名
- 支持 scene 级母图生成
- 同一 scene 只要生成过母图，当前 scene 下未选中的其它 segment 任务也会同步更新母图状态，避免连续性报告误报 scene 内母图状态不一致
- 支持 segment 级关键帧生成：
  - 首帧
  - 中段锚点帧
  - 尾帧
- 当片段满足中段锚点帧条件时，分段合同必须显式给出 `requires_mid_frame=true` 与 `mid_frame_characters`；当前硬触发条件只看 `时长 >= 8 秒`、`对白 >= 2 句` 或 `timed_beats >= 3 拍`，不会因为“双人段”本身而强制要求中段帧；运行时不对中段出镜角色做本地脑补，失败提示也会带出具体触发原因
- 场景图按帧选择角色参考图，不同帧只带当前出镜角色
- Seedream 单帧生图 prompt 使用短版图片绑定风格：`图片1` 固定是 `scene_master_frame`，`图片2 / 图片3` 固定是当前帧角色参考，正文只描述当前帧动作，时间承接帧只作为追加连续性参考放在后面
- 非首个 scene 的首段首帧会额外带上一场最后一段的尾帧作为 temporal anchor，用来帮助跨场过桥；但不会跨 scene 直接复用上一场尾帧成图
- 支持 Seedance 视频提交、轮询、下载与失败报告
- Seedance 默认提交策略使用多模态参考图模式：首帧 / 中段 / 尾帧会按 `图片1 / 图片2 / 图片3` 写进同一个 prompt
- 视频阶段不提交母场景图或角色图；Seedance 只吃首帧 / 中段 / 尾帧三张时间锚点图，避免额外参考图干扰视频构图
- 中段锚点图是 Seedance 默认时间锚点的一部分，按 `图片2` 明确参与画面推进
- 视频基础 prompt 直接输出 `参考图绑定`：用 `图片1 / 图片2 / 图片3` 描述首帧、中段帧、尾帧，再按开场 / 中段 / 收束分阶段写 `画面推进`；推进细节优先消费 `motion_plan`，并结合 `timed_beats` 里的秒数与动作描述
- 如果当前段存在 `dialogue_lines / narration`，视频 prompt 会把真实发生的旁白 / 对白直接挂到对应的 `画面推进` 阶段里，而不只是在后面单独列一份台词清单
- 上游 `scene segment planner` 与 `segment continuity repair` prompt 会显式要求：只要当前段存在 `dialogue_lines / narration`，`timed_beats` 就必须直接写出哪一秒谁说了哪句，不能只写“他开口 / 她回应”
- Seedance 提交层只补一小段 `提交素材绑定`，按本次请求的真实图片顺序说明哪一张是首帧 / 中段 / 尾帧
- 如果某段是非首个 scene 的首段，Seedance prompt 还会追加一小段跨 scene 承接指令：先长成 `next_scene_entry_match`，再执行 `bridge_action / visual_bridge`，并按 `audio_bridge` 保持开场音频尾韵
- 简化后保留对白、旁白、角色音色、环境音、音乐和硬字幕要求，不会因为 prompt 变短而丢失音频和字幕约束
- 当片段采用 `mid_frame_mode=insert_cut` 时，视频 prompt 会额外声明 `图片1 / 图片3` 是主关系镜头、`图片2` 是插入镜头，并要求镜头必须先建立主关系、再切入插入镜头、最后切回主关系收束
- 当关键帧之间人数、角色集合或构图关系发生变化时，视频 prompt 会强制要求可见的入画 / 靠近 / 离场 / 景别重构过程，减少单人画面直接硬跳成双人定格
- 如果某段没有对白、旁白和字幕，Seedance prompt 会明确要求“无口播、无字幕、只保留环境音 / 拟音 / 音乐”，不会对静音片段追加硬字幕烧录指令
- 视频基础 prompt 不包含 `片段标题 / 场景与基线 / 镜头与动作` 这类大段重复栏目，结构为“参考图绑定 + 画面推进 + 音频字幕约束”
- 视频片段支持单段生成
- 支持手动合并总片 `full_story.mp4`
- `scene_id`、`segment_id` 级局部重跑已接入后端任务入口

### Web / API / 数据

- 已提供六阶段 Web 工作台
- 已提供项目列表页、详情页和生产工作台视图
- 项目详情已按 `生产总览 / 正文与结构 / 场景工作台 / 分段审片台 / 请求与调试` 组织
- 分段审片台已提供左侧 segment 列表、基础筛选和右侧当前 segment 详情
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
  - 单独重做首帧 / 中段 / 尾帧
  - 单段生成视频
  - 手动合并总片
- 分段审片台把 Prompt Editor 和 Request Inspector 分离，并按当前选择的首帧 / 中段 / 尾帧 / 视频单点展示 prompt、实际 payload、图片顺序和提交记录
- Prompt Editor 支持显式“保存并重做当前点”：先保存当前首帧 / 中段 / 尾帧 / 视频 prompt，再只提交当前点对应的单图或单段视频任务
- Prompt Editor 支持重置当前点 prompt：重新按当前合同组装系统默认 prompt 并回写计划，不自动提交媒体任务
- Request Inspector 已提供 Prompt Diff，用于对比当前计划 prompt 与真实提交 prompt 的长度和差异片段
- 场景工作台已提供 scene 级修复 / 重生成母图入口，并展示场景基准、过渡合同、母图状态以及同一 scene 下各 segment 的首帧、中段、尾帧、视频和风险状态
- Request Inspector 已展示规划诊断，包括动作点 / 动作预算、时长、timed_beats 覆盖、中段触发、子段拆分和 continuity_report 来源
- 只读 prompt 和实际请求 JSON 支持一键复制，便于排查 Seedream / Seedance 实际提交内容
- 时间线还会展示场景母图、首帧、中段帧、尾帧和视频片段的真实提交参数 JSON，可直接核对当次到底用了哪些图、按什么顺序提交
- 项目、任务、任务结果已持久化到 MySQL
- 删除项目支持，会同步清理安全范围内的输出目录
- 服务重启后，未完成任务会重新回到 `queued`
- 静态资源响应已设置 `no-store`，避免浏览器缓存影响前端模块加载

### 代码结构与验证

- 应用层已拆分为 container / runtime / handlers / support / persistence
- 小说域已拆分为 service / prompts / schemas / repair / rules
- 视频域已拆分为 service / chapter_event_validation / chapter_orchestration / chunk_orchestration / segment_validation / structure_validation / structured_generation / structured_retry_prompts / text_rules / prompting / repair / planning
- 前端详情页已开始拆分：Prompt Editor / Request Inspector / Prompt Diff 已从 `render/detail_assets.js` 抽到 `render/prompt_tools.js`
- 前端已新增轻量 Node 渲染测试，覆盖当前点 prompt 面板、Request Inspector 和保存并重做按钮属性
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

1. 请求调试 Inspector：继续补充 API 错误归类。
2. Prompt 编辑器增强：补充计划 prompt 与默认 prompt 的差异提示。
3. 场景工作台：继续增强 scene 级筛选、批量操作和母图重跑后的状态解释。

### 第二优先级

1. Prompt 编辑器增强：默认 prompt 对比和重置确认体验。
2. 保存并重跑：保存 prompt 后可选择直接重生成对应图片或视频。
3. 批量筛选和批量操作：按 scene、风险、图片状态、视频状态、prompt 是否人工修改过滤。
4. 为 `scene_master_frame` 增加更强的评估与重生成闭环。
5. 接入持久化任务队列、对象存储与公网素材 URL 管理。
