# 使用文档

这份文档面向“如何把 StoryForge 跑起来并完成一轮实际工作流”。
它聚焦安装、配置、页面操作顺序和核心产物说明。

如果你只想先快速体验，优先看 [`README.md`](../README.md)。  
如果你需要 HTTP 接口示例，配合阅读 [`api.md`](api.md)。

## 环境要求

- Python `>= 3.11`
- `uv`
- `ffmpeg`
- 至少一组可访问的 LLM provider 接口，以及可访问的 Seedream / Seedance 接口
- 当前内置 LLM provider 为 `DeepSeek` 与 `ChatGPT 5.4`
- MySQL 8+

## 安装

```bash
uv sync
```

## 配置

### 环境变量

复制示例文件：

```bash
cp .env.example .env
```

常用变量：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
OPENAI_API_KEY=your_openai_api_key
SEEDREAM_API_KEY=your_seedream_api_key
SEEDANCE_API_KEY=your_seedance_api_key
STORYFORGE_DB_PASSWORD=your_mysql_password
OPENAI_BASE_URL=https://api.openai.com/v1
SEEDREAM_BASE_URL=https://your-seedream-endpoint.example.com
SEEDANCE_BASE_URL=https://your-seedance-endpoint.example.com
```

示例见：[`.env.example`](../.env.example)

### 配置文件

默认配置文件：

- [`configs/storyforge.example.toml`](../configs/storyforge.example.toml)
- [`configs/storyforge.live.example.toml`](../configs/storyforge.live.example.toml)

说明：

- `storyforge.example.toml`：主配置，默认开发与日常运行使用
- `storyforge.live.example.toml`：真实提交模板，默认打开真实媒体提交相关开关
- StoryForge 要求 MySQL 可连接

关键配置项：

```toml
[llm]
enabled = true
provider = "deepseek"
model = "deepseek-chat"
available_providers = ["deepseek", "openai"]
max_tokens = 8192

[seedream]
enabled = true
model = "doubao-seedream-4-5-251128"
auto_submit = false
watermark = false

[seedance]
enabled = true
model = "doubao-seedance-2-0-260128"
auto_submit = false
watermark = false
with_audio = true
subtitle_mode = "burned_in"

[database]
host = "127.0.0.1"
port = 3306
user = "root"
password_env = "STORYFORGE_DB_PASSWORD"
database = "storyforge"
```

联调建议：

- 先把 `seedream.auto_submit = false`
- 先把 `seedance.auto_submit = false`
- 先确认 `.env` 里的密钥和 `base_url` 已正确配置
- `llm.max_tokens` 当前默认建议保留 `8192`；如果结构化视频规划经常报 `finish_reason='length'`，不要再往下调
- 页面默认走 `DeepSeek`；如果要换成 `ChatGPT 5.4`，需要先配置 `OPENAI_API_KEY`
- 页面里的 `模型 ID` 是只读默认值，会随 provider 自动切换
- 创建页默认会把 `V2 连续性软审校` 设为 `auto`
- 创建页可以分别决定 `Seedream` 和 `Seedance` 是否保留水印；勾选关闭时，接口会提交 `watermark=false`
- 在看懂 manifest 和图片产物之前，不要一开始就跑真实视频生成

## Web 控制台

启动服务：

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

如果只是改前端样式或调接口，可以临时加 `--reload`。如果要生成角色图、场景图或视频，建议不要使用 `--reload`，因为保存代码会触发热重载，中断正在运行的长任务。

推荐使用方式：

1. 创建项目并生成小说；在创建页可选 `DeepSeek` 或 `ChatGPT 5.4`，也可以预先设置 `V2 连续性软审校 = off / auto / on`，以及本次 run 的 `Seedream / Seedance` 水印开关
2. 在项目详情页的“小说”标签页检查并按需修改正文
3. 先生成场景结构；如需切换当前 run 的 `V2` 审校策略，可在项目详情页先改模式，再继续下一步
4. 检查 `chapter -> scene` 拆分后，再生成分段合同
   - 分段合同运行中会显示 `章 + scene` 进度；如果中途失败，直接点“从失败位置继续”即可
5. 生成角色图
   - “图像资产 -> 角色定妆图”卡片可以直接展开查看该角色的生成 prompt 和一致性备注，不用再手动打开 `character_image_manifest.json`
6. 在项目详情页时间线里按 segment 逐段生成场景图
7. 在同一条时间线里按 segment 逐段生成视频
   - 每个 scene 和 segment 卡片都可以展开查看当前图片 / 视频 prompt
   - 场景母图、首帧、中段帧、尾帧、视频片段都会展示真实送往 Seedream / Seedance 的请求参数 JSON，以及本次实际使用图片顺序
   - 页面展示 manifest 中记录的请求视图，方便直接核对用了哪些图、按什么顺序提交
8. 如果某个 scene 被连续性审校标成高风险，可先点 scene 头部的“智能修复场景”，系统会回写该 scene 的场景基线合同并刷新连续性报告，再提示你后续手动决定是否重生成场景母图、场景图和视频
9. 如果某个 segment 被连续性审校标成高风险，可再点“智能修复该段”，系统会只更新这一段的修复合同；如果该段当前没有需要修的风险，会直接返回已完成的 `noop`

这样可以逐阶段观察：

- 小说正文是否符合预期
- 结构化角色 / 分章 / 摘要是否符合预期
- 角色视觉是否稳定
- 场景关键帧是否合理，尤其是双人 / 多人片段的中段站位是否稳定
- 视频时长和字幕是否可接受

说明：

- 媒体水印当前按 run 级别管理
- 你在创建页为 `Seedream` / `Seedance` 选择的水印设置，会默认继承到后续角色图、场景图、视频与批量修复相关阶段
- 如果需要换一套水印策略，建议从创建页重新发起一条新 run，或通过 API 在单个阶段请求里显式覆盖

删除项目：

- 在故事资产页点击“删除项目”
- 会删除项目记录、任务记录，以及任务结果记录过的 `outputs` 项目产物目录
- 为避免误删，后端只允许删除配置输出根目录下的项目产物目录，不会删除输出根目录本身或外部路径
- 如果项目仍有排队中或运行中的任务，后端会拒绝删除并返回失败原因

## CLI

CLI 提供启动 Web / API 的入口：

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

当前推荐工作流统一走 Web 页面分步执行。

## brief 编写

示例：

- [`examples/briefs/demo_story.toml`](../examples/briefs/demo_story.toml)

最小字段示例：

```toml
title_hint = "黑潮档案"
idea = "一名记者发现每次台风登陆前，失踪名单都会提前出现在废弃气象站。"
genre = "悬疑 / 都市怪谈"
tone = "压抑、电影感"
target_audience = "成年悬疑读者"
chapter_count = 8
total_word_target = 24000
must_include = ["废弃气象站", "匿名电话", "封存档案"]
style_keywords = ["台风", "潮湿", "霓虹", "监控画面"]
```

## 工作流说明

### 1. 生成小说

- 这一步只生成可编辑正文，对应核心文件是 `story_source.json`
- 页面会先展示标题、摘要和正文，你可以先人工改稿，再继续后续阶段

### 2. 生成场景结构

- 这一步会生成 `novel_package.json`、`novel_audit.json`、`story_memory.json`、`character_visual_bible.json` 与第一版 `scene_plan.json`
- 这一版 `scene_plan.json` 只保存 `chapter -> scene` 结构、`scene_bible` 和 scene 母图相关字段，还不包含正式 `segment contracts`
- `project.scene_structure` 会先从当前章节正文抽取 must-cover 关键事件，再生成 scene skeleton；第一版 `scene_plan.json` 里的每个 scene 都会带 `covered_event_ids` 与紧凑版 `covered_event_summaries`
- 从第二个 scene 开始，第一版 `scene_plan.json` 里的每个 scene 还会带 `scene_transition_contract`，用于描述它如何从上一场进入当前场
- 同一份 `story_source` 已经有 queued / running / completed 的 `project.scene_structure` 任务时，后端会直接复用已有任务
- `Cast Analyzer` 要求每个角色槽位都带可在正文中定位的 `source_evidence`
- `source_evidence` 仍然必须来自正文，但对带修饰语的人名或稳定称呼会做容错匹配
- `Character Designer` 必须严格覆盖目标 slots，不能重复 `cast_slot_id`，也不能凭空补正文里没有证据的人
- `story_memory.json` 会在这一步初始化并逐章回写，用来把上一章退出状态、角色摘要和 continuity state 传给后续规划
- 如果模型返回 `finish_reason='length'`，系统会自动保留更高的 completion token 预算、缩短章节摘录，并优先把规划收缩到更小的 `scene structure / segment contracts` 粒度，再在后续 retry 里强制要求更紧凑的 JSON 输出
- 小说结构化主链路采用 fail-fast：如果 `Story Architect`、`Story Drafter`、`Chapter Planner` 或 `Editorial Reviewer` 返回空标题、缺章、空正文或空 beats，这一步会直接重试 / 失败
- `scene_plan.json` 是当前场景级主规划文件；在这一步里它主要保存 `chapter -> scene` skeleton、`scene_bible` 与 `scene_master_frame` 相关字段
- `covered_event_ids` 会把每个 scene 显式绑定到章节关键事件；如果 scene 没覆盖到章节后半段事件，或覆盖顺序与正文不一致，这一步会直接失败重试
- `scene_bible` 用来锁定地点、时间、天气、光线、背景锚点、固定道具、空间布局和角色调度，后续场景图与视频都会直接消费它
- 每个 scene 还会带 `scene_master_frame_prompt / path / status / url`，用于同场景母图生成与复用
- 如果 `scene_bible` 环境字段过空，主链路会先从该 scene 的 `start_frame_prompt / mid_frame_prompt / end_frame_prompt` 与 `scene_anchor` 里自动提炼无角色环境锚点，并补充固定道具 / 主色调线索，再回填到 `scene_bible` 后生成母图 prompt
- `story_memory.json` 是项目级结构化状态文件，不是自由文本聊天记忆；当前主要用于章节级视频规划承接

### 3. 生成分段合同

- 这一步依赖已经完成且未过期的 `project.scene_structure`
- 它会在已有 scene skeleton 的基础上，补齐正式 `segment contracts`，并写出：
  - `character_image_manifest.json`
  - `scene_structure_source.json`
  - 最终版 `scene_plan.json`
  - `segment_plan.json`
  - `segment_contract_progress.json`
  - `scene_image_manifest.json`
  - `seedance_manifest.json`
  - `continuity_report.json`
- 同一份 `story_source` 已经有 queued / running / completed 的 `project.segment_contracts` 任务时，后端会直接复用已有任务
- 视频规划内部已拆成四段式：
  - 先按章节正文抽取 must-cover 关键事件，再生成 `scene structure`
  - 再按单个 `scene` 生成 1-4 个连续 chunk
  - 再按单个 `chunk` 生成 `segment contracts`
  - 最后本地富化并统一重编成正式 `scene_plan.json / segment_plan.json`
- planner 不会把整份 `story_memory` 和整章长摘录原样喂给每个 scene / chunk
- 当前实际传给 LLM 的是“当前章批次视图 + 最近已规划章节摘要 + 焦点角色摘要 + 当前 scene / chunk 聚焦摘录”
- chapter event 规划会先拦截“事件过粗”的情况：如果一个关键事件 summary 已经同时包含多轮动作、对白或关系结果，这一步会直接失败重试，并要求拆成更细的相邻 event
- 多 event 章节的 chapter 首尾 event 允许最多 3 个紧密绑定推进点，用来容纳常见的开场建立和结尾收束；中间 event 与单 event 章节仍按 2 个推进点收口
- 背景介绍、关系说明、回忆补叙如果只是解释上下文，不会被当成 must-cover event；中间 event 也要求更窄，不允许把问句、回答、动作结果三连塞进一条
- chapter event 的 `source_evidence` 要求只截当前 event 对应的 1-2 个相邻正文片段；系统不会把同一 event 里的证据碎片重复算成多个推进点
- 如果首次 chapter event 抽取仍出现“过粗 event”，系统会自动触发一次 `video-chapter-event-repair`，把失败的 event plan 连同失败原因交给 LLM 做定向修复，而不是只重跑同一个全量抽取 prompt
- 如果整份 `video-chapter-event-repair` 仍然连续失败，系统还会进一步触发一次只针对单个粗 event 的 `video-chapter-event-split-repair`，把那一个 event 直接拆成更细的相邻 replacement events，再并回整章事件清单
- 这条链路是迭代式的：如果同一章里连续还有别的粗 event，系统会在合并后继续校验整章并自动进入下一轮 repair，而不是修完第一个就直接退出
- `video-chapter-event-split-repair` 的本地校验只要求当前 replacement events 自己合法，不会因为整章里另一个还没处理到的粗 event 而卡死当前 targeted split
- 最终版 `scene_plan.json` 仍是场景级主规划文件，保存 `chapter -> scene -> segment`
- `scene_plan.json` 保留 scene 级 `scene_transition_contract` 与 `covered_event_summaries`，并保持 scene 边界信息
- scene 级字段保留在 scene 层；segment 层聚焦执行合同与承接信息
- `start_frame_prompt / mid_frame_prompt / end_frame_prompt` 由本地 prompt 组装阶段统一补齐
- scene 首个 chunk / 首个 segment 会显式消费 `scene_transition_contract`：首段 `opening_match` 先建立 entry state，前 1-2 条 `timed_beats` 负责 bridge action 和 reveal
- scene chunk planner 会同时看到当前 scene 绑定的 `covered_event_summaries`；如果 chunk 提前写进后续 scene 才该发生的 `回应 / 告白 / 亲吻 / 明确关系落点` 之类关键推进，会在结构化阶段直接失败重试
- scene 内 chunk 合并时，系统会把上一 chunk 尾部压缩成 `visible_tail_state / carry_over_elements / opening_match_seed` 传给下一 chunk 首段，再结合 `previous_segment_id / opening_match` 做结构化校验与重试，减少“同一 scene 里像重新开演”
- chapter scene planner prompt 会显式提醒：如果相邻关键事件已经形成完整多阶段链路，应优先拆更多 scene，而不是把整串事件都压进同一个 scene
- scene chunk 规划还会前置检查动作容量：如果 `must_cover + transition_goal` 已经明显包含多轮推进，但 `expected_segment_count` 仍过小，这一步会直接失败重试，而不是把压力留到后面的 segment planner
- 如果 scene chunk 在常规重试后仍然卡在“动作容量过载”，系统会自动触发一次 `video-scene-chunk-repair`，把失败 chunk、失败原因和最低所需 segment 数再次交给 LLM 定向修复
- 如果 scene segment planner 在常规重试后仍然卡在“`timed_beats` 最后一拍过早结束、尾部缺少收束 beat”，系统会自动触发一次 `video-scene-segment-timeline-repair`，把失败 batch、失败原因和出错 `segment_id` 再交给 LLM 定向补尾部节拍
- 如果某个 segment 只是因为时长偏短导致轻微动作容量超载，系统会先自动扩秒到可容纳动作的最小时长；扩秒时会同步把最后一条 `timed_beats` 延到新时长；如果仍未覆盖完整时长，会先触发 `video-scene-segment-timeline-repair` 补尾部节拍
- 如果扩到单段 12 秒上限后仍然动作过载，系统才会触发 `video-scene-segment-action-repair`，把失败 batch、出错 `segment_id`、推进点数量和最低所需 segment 数再交给 LLM 定向拆动作链
- `video-scene-segment-action-repair` 是迭代式的：如果 repair 第一轮后还有新的过载子段，或 repair 拆出更多段但触发 chunk 段数上限，系统会继续基于最新失败 batch 再跑下一轮修复
- 多人同帧镜头冲突会先在 schema normalize 阶段兜底清理：共享 `shot_state.framing / shot_state.camera_motion` 会被改成多人同框关系镜头；如果实际帧 prompt 或 repair 输出仍残留冲突，系统会自动触发 `video-scene-segment-focus-repair` 定向修镜头一致性
- `segment_plan.json` 是执行索引，供逐段生成场景图、视频和失败重试使用；每个 segment 会继承所属 scene 的 `scene_bible`，并额外带 `shot_state`、`continuity_link` 与 `motion_plan`
- `scene_structure_source.json` 是恢复用的原始 scene skeleton 快照，供失败后从当前位置继续时读取，不参与图片和视频执行
- `segment_contract_progress.json` 会按 `chapter -> scene -> chunk` 持续回写进度、失败章节、失败 scene 和失败 chunk；如果前端看到“从失败位置继续”，底层依赖的就是这份 checkpoint
- 视频 segment 规划在 live LLM 模式下会最多自动重试 3 次；如果模型返回的是分析备注、伪分镜或空结构，而不是可执行的正式场景计划，这一步会直接失败并把原因写入任务，而不会静默生成坏掉的 `scene_plan.json`
- 如果这一步在中途失败，再次调用 `project.segment_contracts` 并带 `resume_from_progress=true` 时，会先复用已落盘的 chunk 规划，只继续失败 scene 内剩余 chunk，再继续后续 scene / chapter，不会重跑已完成部分
- `resume_from_progress` 使用当前 chunk 级 checkpoint；`segment_contract_progress.json` 需要包含 `scene/chunk` 结构
- 这一步还会按 `continuity_review_mode` 写出连续性审校结果：
  - `off`：只保留 `V1` 规则校验
  - `auto`：按 run 复杂度与风险自动决定是否触发 `V2`
  - `on`：强制追加 `V2` LLM 软审校
- `shot_state` 用来锁定该片段的景别、镜头推进、人物调度、动作推进、道具连续性和尾部承接状态
- `continuity_link` 用来显式描述当前片段是否承接上一段、开场要对齐什么状态、哪些元素必须延续、哪些变化被允许
- `motion_plan` 用来描述 `图片1 -> 图片2 -> 图片3` 的镜头路径、角色运动和防硬跳要求；结构化输出缺失时会由后处理基于 `timed_beats / shot_state` 补齐
- 同一步还会生成 `continuity_report.json`，其中包含 `V1` 规则审校，以及按模式决定是否追加 `V2` 软审校；它会检查场景母图、场景基线强度、关键帧承接、帧级角色、对白时长预算和视频执行风险
- `V1` 当前还会额外提示三类动作承接问题：`opening_match_weak`、`action_progression_stalled`、`adjacent_segment_duplicate`
- `V1` 还会直接提示 scene 边界风险：`scene_transition_exit_state_drift`、`scene_transition_entry_weak`、`scene_transition_bridge_weak`、`scene_transition_opening_not_consumed`、`scene_transition_bridge_not_consumed`
- `segment contracts` 会检查 scene 首段是否消费 `scene_transition_contract`、无中段片段的 `start -> end` 关键帧语义是否过平，以及当前 chunk 的最后一个 segment 是否真正落到 `transition_goal`
- 其中“动作容量 / 开场承接 / 关键帧过平 / 收束不够落地”这类质量问题，当前链路会优先 repair；repair 失败时会记入 `planner_warnings` 后继续规划，默认不整 chunk 卡死
- 如果动作容量超载，系统不会直接整批失败：先尝试自动扩秒；扩秒仍装不下时，会在当前 chunk 内自动重试，并临时提高该 chunk 的可输出 segment 上限，要求模型把这轮动作链拆成更合理的正式片段

### 4. 生成角色图

- 对应执行报告是 `seedream_character_execution.json`
- 角色定妆图会统一使用白底三视图模板，只显示角色姓名

### 5. 生成场景图

- 对应执行报告是 `seedream_scene_execution.json`
- 页面会先按 `scene_plan.json` 展示按 scene 分组的时间线，再允许你按 segment 单独生成
- 同一 scene 会先生成一张 `scene_master_frame`，再基于它继续生成该 scene 下各个 segment 的首帧 / 中段 / 尾帧
- 时间线里每个 scene 头部都可以单独“重生成场景母图”；这个入口只会重跑该 scene 的 `scene_master_frame`，不会连带重跑其它 scene 或 segment
- 每个 scene 头部都可以展开查看 `scene_master_frame` 的实际生图 prompt
- 如果某个问题已经被判定为 scene 级连续性风险，scene 头部还会放出“智能修复场景”入口；这一步会额外落盘 `continuity_repair_<scene_id>.json`，回写该 scene 的 `scene_anchor / scene_bible`、刷新 `continuity_report.json`，并写出 `selection_mode`、`affected_segment_ids` 与待执行媒体动作，但不会自动重跑 `scene_master_frame`、场景图或视频
- 时间线头部会直接显示最近一次连续性校验时间、总体状态和 top issues
- 时间线头部还会显示本次 run 请求的 `V2` 模式，以及 `V2` 是否实际执行
- 时间线头部提供“一键修复风险合同”；它会按连续性报告里的风险优先级，分批只回写 `scene` / `segment` 合同与报告，不会自动开始场景图或视频任务
- 每个 scene 头部和每个 segment 卡片都会显示连续性风险；如果某个问题建议“重生成场景母图 / 场景图 / 视频”，对应按钮会被高亮
- 如果某个 segment 已被判定为连续性高风险，时间线卡片还会放出“智能修复该段”入口；这一步会先让 LLM 重写该段执行合同，并提示你后续手动继续场景图或视频阶段
- 如果你点了修复，但目标当前其实没有问题，这次修复任务会直接完成并显示 `noop`，不会把“无事可修”当成失败
- 智能修复卡片会实时根据你后续手动提交的场景图 / 视频任务，更新“剩余待执行动作”；如果动作已经手动提交或完成，提示会自动收敛
- 批量合同修复同样只更新合同：它会返回本批修了多少个 scene / segment、还有多少风险留待下一批，但不会代替你自动执行媒体重跑
- 如果某个 scene 正在执行场景修复，或该 scene 的母图正在重生成，前端会暂时锁住该 scene 下的局部修复、场景图、视频按钮，避免并发提交互相覆盖
- `scene_master_frame` 是无角色空场景参考图，只负责锁背景环境、光线、固定道具和空间透视，不负责承载人物
- `scene_master_frame` prompt 会显式加入“场景基线锁定”，要求后续关键帧复用同一地点、时间、光线、主色、背景锚点、固定道具和空间透视
- 如果 `scene_bible` 里仍混入了 `两人 / 双人 / 剪影 / 并肩 / 相对 / 接吻` 这类弱人物信号，母图阶段会在运行时剔除，避免空场景母图被这类描述带人
- 如果 `scene_bible.fixed_props` 里混入了手机、书包、雨伞、花束、信封这类人物随身或临时动作道具，母图与 scene 级环境上下文会在运行时剔除，避免把这类道具误画成地上的环境摆件
- 即使上游 `scene_bible` 很弱，`scene_master_frame` 也会优先回填地点、时间、光线、空间布局和背景锚点，并尽量补固定道具与主色调，避免母图退化成泛化场景
- 单段生成只更新该片段对应的首帧 / 中段锚点帧 / 尾帧，不会重跑其它片段
- 分段审片台支持在首帧 / 中段 / 尾帧 / 视频之间切换当前生成点；Prompt Editor、Request Inspector 和重做按钮只作用于当前选择的一个点
- `保存 Prompt` 只保存当前计划；`保存并重做当前点` 会先保存当前点 prompt，再只提交当前图片或当前视频任务
- Request Inspector 会显示当前生成点的 Prompt Diff，对比计划 prompt 与真实提交 prompt，帮助判断问题发生在计划、提交组装还是模型执行阶段
- 单图重做会通过 `frame_kind=start|mid|end` 只生成当前图片，并保留同一 segment 里的其它图片状态
- 但如果这次单段生成触发了当前 scene 的 `scene_master_frame`，系统会把同 scene 其它片段任务上的母图状态一起同步，避免后续连续性报告把同一 scene 误判成母图状态不一致
- 同一 scene 下的多个 segment 会共享同一套 `scene_bible` 基线，场景图 prompt 会显式带入这组约束
- 当前帧 prompt 会按 `start_frame_characters / mid_frame_characters / end_frame_characters` 做 frame-scoped 净化：未出镜角色、错误服装 / 发型覆盖描述会在运行时被剔除，避免把别的角色或错误定妆带进单帧
- 默认 `mid_frame_prompt` 只保留当前拍的角色、动作停点和空间关系，不会回灌整段片段总述
- 如果首帧和尾帧是同一组双人 / 多人，而中段只拍其中一人的反应特写或局部动作，必须显式写 `mid_frame_mode=insert_cut`
- `mid_frame_mode=insert_cut` 的真实含义是：首帧先建立双人 / 多人主关系，中段短促切入单人 / 局部插入镜头，尾帧再回到主关系镜头收束；它不是“少人版主镜头”
- scene 级连续性风险还会额外标记“场景基线过弱”，用于提示你先重生成 `scene_master_frame`
- 同时也会显式带入该段自己的 `shot_state`，保证景别、调度和动作推进不只靠自然语言 prompt 碰运气
- 如果 `continuity_link` 判定当前段应承接上一段，首帧会优先按这份承接关系复用或对齐上一段尾部状态
- 连续承接段的 repair 会自动补强更具体的 `opening_match` 和 `allowed_changes`，减少“只是写了承接，但画面还是像重开一段”的情况
- 当前帧生成时还会优先引用 `scene_master_frame + 当前帧角色图`；连续承接段的首帧会再额外带上上一段尾帧
- 如果当前段是非首个 scene 的首段，首帧还会额外带上上一场最后一段的尾帧作为 temporal anchor；它只用于跨 scene 过桥，不会直接复用成当前首帧
- 场景生图阶段只负责纯画面关键帧，不允许把对白、字幕、聊天气泡或任何可见文字直接画进图片
- 每个 segment 卡片都可以展开查看 `start_frame_prompt / mid_frame_prompt / end_frame_prompt`

### 6. 生成视频

- 对应执行报告是 `seedance_execution.json`
- 视频阶段也是按 segment 单独触发
- 视频 prompt 使用已生成的首帧 / 中段 / 尾帧作为时间锚点；场景连续性在关键帧生成前由 `scene_bible / shot_state / continuity_link` 消化
- 视频阶段默认按多模态参考图模式提交：首帧 / 中段 / 尾帧会作为有顺序的 `reference_image` 一起送入 Seedance，并在 prompt 里显式绑定成 `图片1 / 图片2 / 图片3`
- 视频阶段不提交 `scene_master_frame` 或角色图；Seedance 只接收首帧 / 中段 / 尾帧三张时间锚点图
- `scene_bible / shot_state / continuity_link` 的约束会先被压缩进关键帧描述里，视频基础 prompt 不逐段复述这些大段合同原文
- 视频基础 prompt 会直接输出 `参考图绑定`：`图片1 / 图片2 / 图片3` 分别描述首帧、中段帧、尾帧，再按开场 / 中段 / 收束分阶段写 `画面推进`；推进细节优先来自 `motion_plan`，并结合 `timed_beats` 的秒数与动作
- 如果某段有真实旁白或对白，`画面推进` 里也会直接写出该时间段的口播内容，方便你直接看到“哪一秒谁说什么”
- 上游结构化阶段会明确要求：有旁白或对白的 segment，`timed_beats` 本身就要写出对应时间段里的真实口播内容
- 如果当前段是非首个 scene 的首段，视频 prompt 还会额外追加一小段跨 scene 承接指令：前几秒先长成 `next_scene_entry_match`，再执行 `bridge_action / visual_bridge`，并按 `audio_bridge` 保持开场音频尾韵
- Seedance 提交前会再补一层 `提交素材绑定`，只说明本次真实提交里的 `图片1 / 图片2 / 图片3`
- 视频短版 prompt 保留对白、旁白、角色音色、环境音、音乐和硬字幕要求，并避免复述 scene_bible / shot_state / continuity_link 合同原文
- 视频短版 prompt 不包含 `片段标题 / 场景与基线 / 镜头与动作` 这些重复栏目
- 如果某段使用 `mid_frame_mode=insert_cut`，视频 prompt 会再额外写明：`图片1 / 图片3` 是主关系镜头，`图片2` 是插入镜头，必须先建立主关系、再自然切入插入镜头、最后切回主关系
- 如果关键帧之间角色人数、角色集合或构图关系发生变化，视频 prompt 会明确要求可见的入画 / 靠近 / 离场 / 景别重构过程，避免直接硬跳
- 如果某个 segment 没有对白、旁白和字幕，视频 prompt 会明确声明“无口播、无字幕、只保留环境音 / 拟音 / 音乐”，不会对静音动作段追加硬字幕烧录指令
- 只有对应片段场景关键帧已就绪时，时间线里的“生成视频”按钮才会放开
- 智能修复本身不会自动重跑视频；修复完成后需要你手动点击对应 segment 或 scene 的“生成视频”
- 修复任务会继续归在当前制作版本下展示，不会额外长出一个新的版本块
- 连续性修复器会更严格检查对白 / 旁白 / 硬字幕是否装得进当前时长；超预算时会优先压缩文本，而不是直接保留一份说不完的修复合同
- 当前链路默认不用 `summary` 补 `narration`；如果本段已经有 `dialogue_lines`，运行时还会清掉复述动作 / 对白的描述性 `narration`，减少本地重复拆段和告白节奏被打碎
- 视频提交后，segment 卡片会额外展示 `motion_plan`、最终 Seedance prompt 的参考图绑定 / 画面推进摘录、submit variant、真实请求 payload 和参考图绑定顺序，便于排查视频跳帧原因

### 6. 手动合并总片

- 总片采用手动合并
- 页面会提供单独的“合并已生成片段”按钮
- 至少需要 2 个已生成片段，才能拼成 `rendered/full_story.mp4`

## 输出目录

项目任务默认输出到：

```text
outputs/<story-slug>/
```

典型目录结构：

```text
outputs/<story-slug>/
├── assets/
│   ├── characters/
│   └── frames/
├── rendered/
├── story_source.json
├── novel_package.json
├── novel_audit.json
├── story_memory.json
├── character_visual_bible.json
├── character_image_manifest.json
├── scene_plan.json
├── segment_plan.json
├── scene_image_manifest.json
├── seedream_character_execution.json
├── seedream_scene_execution.json
├── seedance_manifest.json
├── continuity_repair_<segment_id>.json
├── continuity_repair_<scene_id>.json
└── seedance_execution.json
```

## 核心产物说明

- `story_source.json`
  小说正文真源。用户在页面里编辑的就是这份内容；后续结构化分析也直接读取它。
- `novel_package.json`
  小说运行总包。里面只保留后续图片与视频阶段真正要消费的字段，例如角色卡、章节规划、视觉母题和正文摘录。
  其中角色卡阶段已强制执行：
  `source_evidence` 必须来自小说正文、角色名唯一、`cast_slot_id` 唯一、角色数量与目标 slots 一致。
- `novel_audit.json`
  小说分析审计包。里面保存 `review`、`workflow_trace`，以及从运行包剥离出来的 `outline_context`、`chapter_context`，主要用于排错和人工审阅。
- `character_visual_bible.json`
  视频角色视觉设定，用来约束角色外观、服装、色彩和角色定妆 prompt。
- `character_image_manifest.json`
  角色定妆图任务清单，记录每个角色要怎么生成、输出到哪里、当前状态是什么。
  角色图 prompt 会统一追加固定 `SF-TURN-01` 横版 16:9 白底三视图模板，只使用角色姓名、性别、外观和服装；其中 `gender` 只作为内部造型约束保留，不会作为画面文字显示。最终 prompt 不会把 `role / portrait_prompt` 额外拼进角色图生成。
- `segment_plan.json`
  视频片段规划，定义每个片段的参与角色、对白、字幕、时长、首帧 / 中段锚点帧 / 尾帧 prompt，以及分段关系。
  其中 `requires_mid_frame = true` 表示该片段会额外生成中段锚点帧；常见于双人 / 多人同框、8 秒以上片段、动作推进明显或中段关系变化明显的镜头。
  其中 `mid_frame_mode` 当前支持：
  - `continuous`：中段仍是主镜头连续推进
  - `insert_cut`：中段是从主镜头短促切入的单人 / 局部插入镜头
  如果 `start_frame_characters` 与 `end_frame_characters` 是同一组双人 / 多人，而 `mid_frame_characters` 只保留了其中一人，就必须把 `mid_frame_mode` 写成 `insert_cut`，并在节拍与运镜里明确“切入再切回”。
  页面时间线会直接读取这份规划来展示完整片段列表，即使某个片段还没有生成任何图片或视频，也会先显示出来等待单独触发。
- `scene_image_manifest.json`
  场景关键帧任务清单，记录每个片段的首帧、中段锚点帧（如有）、尾帧、每一帧实际出镜角色、角色参考图和输出位置。
  单帧生图按短版图片绑定语义生成：`图片1` 是 `scene_master_frame`，`图片2 / 图片3` 是当前帧角色参考，prompt 正文只描述当前帧动作；若运行时追加上一帧连续性参考，也只会放在后面辅助衔接，不会覆盖 `图片1` 的场景主参考语义。
- `seedream_character_execution.json`
  角色图执行报告，只用于确认角色图阶段是否成功以及失败原因。
- `seedream_scene_execution.json`
  场景图执行报告，只用于确认场景图阶段是否成功以及失败原因。
- `seedance_manifest.json`
  最终视频提交清单，Seedance 会按这里的每个 clip 去生成视频。
  StoryForge 默认会用“首帧 + 中段锚点图（如有）+ 尾帧”的多模态组合提交，并在 prompt 里用 `图片1 / 图片2 / 图片3` 明确绑定时间顺序。
  clip 里会同时保存基础视频 prompt，以及提交后回写的 `submitted_prompt / submit_variant / submitted_reference_bindings`，用于还原真实送审内容。
  `title` 应继承真实小说标题，不使用 `segment_video_manifest` 这类文件用途名；读取产物时会优先从 `novel_package.json` / `story_source.json` 恢复标题。
- `seedance_execution.json`
  视频执行报告，记录提交状态、完成数量、失败数量和下载结果。
- `continuity_repair_<segment_id>.json`
  单段智能修复报告，记录本次修复针对哪个 segment、修复摘要、触发它的连续性问题、修复前后差异和被改写的关键字段。
- `continuity_repair_<scene_id>.json`
  单场景智能修复报告，记录本次修复针对哪个 scene、触发它的 scene 级连续性问题、`selection_mode`、`affected_segment_ids`，以及后续建议执行的媒体动作。
  批量合同修复不会新增新的文件类型，仍然只会回写既有的 `continuity_repair_<scene_id>.json` 或 `continuity_repair_<segment_id>.json`。
- `assets/characters/*.png`
  实际生成出来的角色图文件。
- `assets/frames/*.png`
  实际生成出来的场景关键帧文件，包含首帧、必要时的中段锚点帧和尾帧。
- `rendered/*.mp4`
  各个视频片段的下载结果。
- `rendered/full_story.mp4`
  用户手动触发合并后生成的总片。

## 推荐联调顺序

### 阶段一：只验证小说和结构

1. 配好 `DEEPSEEK_API_KEY`
2. 先跑小说正文阶段
3. 在页面检查并按需修改 `story_source.json`
4. 依次跑“生成场景结构”和“生成分段合同”
5. 检查 `novel_package.json` 和 `novel_audit.json` 是否符合预期

### 阶段二：验证角色和场景

1. 生成角色图
2. 检查角色外观、性别、体态和服装是否稳定
3. 再到项目详情时间线里按 segment 逐段生成场景关键帧
4. 每个 segment 的 prompt 面板支持直接修改首帧 / 中段 / 尾帧 / 视频 prompt；保存视频 prompt 后该段旧视频会失效，需要用户再手动重跑视频
5. 检查场景图是否引用同一组角色图；若是双人 / 多人片段，重点检查中段锚点帧是否把所有角色都稳定画出
   首帧 / 中段 / 尾帧会按各自的 `*_frame_characters` 和对应时间节拍选参考图；如果中段是 `mid_frame_mode=insert_cut` 的单人反应镜头，就只会喂该帧真实出镜角色，不会因为整段 `involved_characters` 有两个人而自动喂入另一位角色图
6. 优先重跑具体有问题的 segment，不要默认整批重跑
7. 如果连续性风险明确落在某个 segment，可以优先点击“智能修复该段”，让系统先重写该段合同，再观察重跑结果

### 阶段三：提交真实视频

1. 确认 `seedance_manifest.json` 里的片段数量、时长、字幕，以及角色参考图 / 中段锚点图 / 首尾帧路径
2. 确认没有使用 `--reload` 启动服务
3. 在项目详情时间线里按 segment 单独提交 Seedance 视频任务
4. 当至少已有 2 个片段生成完成后，再手动点击“合并已生成片段”

## 失败与重试

- 所有任务都会在接口和页面上返回 `error` 字段，前端会展示任务级和阶段级失败原因。
- Seedance 视频任务如果在提交阶段被接口拒绝，`seedance_execution.json` 会记录真实响应体、请求摘要和本次提交尝试。
- LLM 结构化输出失败会由 StoryForge 外层最多重试 3 次；失败会显式标记任务失败。
- LangChain structured output 会优先读取 parsed tool 结果；如果模型没有触发 tool call 但 raw 文本里有 JSON，会自动提取 JSON 校验；如果第一次 structured 调用返回空结构，还会再走一次 LangChain 普通 JSON 回收；两次都拿不到合法 JSON 时，才会显示“模型没有返回结构化对象”这类明确原因。
- 视频 segment 规划还会额外拒绝带有 `当前片段聚焦`、`结尾要保留`、`当前小段聚焦` 这类分析模板话术的伪分镜；看到这类错误时，应直接重跑“生成分段合同”；如果上游 scene skeleton 也已失效，再先重跑“生成场景结构”。
- 服务重启时，残留的 `running` 任务会重新回到 `queued`，启动后会重新执行。
- 如果任务已经进入 `failed`，推荐在页面重新点击对应阶段按钮，而不是手动修改数据库。
- 视频长任务执行期间不要用 `--reload`。热重载会中断当前进程，即使会重排队，也可能造成重复提交或等待时间变长。

## 相关文档

- [README](../README.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
