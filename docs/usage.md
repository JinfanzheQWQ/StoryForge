# 使用文档

这份文档面向“如何把 StoryForge 跑起来并完成一轮实际工作流”。
它是当前唯一的操作手册；README 不再重复这里的步骤细节，`status.md` 也不再重复这里的产物说明。

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
- StoryForge 现在要求 MySQL 必须可连接；没有数据库时不会以“内存态”降级运行

关键配置项：

```toml
[llm]
enabled = true
provider = "deepseek"
model = "deepseek-chat"
available_providers = ["deepseek", "openai"]

[seedream]
enabled = true
model = "doubao-seedream-4-5-251128"
auto_submit = false

[seedance]
enabled = true
model = "doubao-seedance-2-0-260128"
auto_submit = false
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
- 页面默认走 `DeepSeek`；如果要换成 `ChatGPT 5.4`，需要先配置 `OPENAI_API_KEY`
- 页面里的 `模型 ID` 现在是只读默认值，会随 provider 自动切换，不再支持手工输入
- 创建页默认会把 `V2 连续性软审校` 设为 `auto`
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

1. 创建项目并生成小说；在创建页可选 `DeepSeek` 或 `ChatGPT 5.4`，也可以预先设置 `V2 连续性软审校 = off / auto / on`
2. 在项目详情页的“小说”标签页检查并按需修改正文
3. 生成结构化信息；如需切换当前 run 的 `V2` 审校策略，可在项目详情页先改模式，再重新生成结构化信息
4. 生成角色图
5. 在项目详情页时间线里按 segment 逐段生成场景图
6. 在同一条时间线里按 segment 逐段生成视频
7. 如果某个 segment 被连续性审校标成高风险，可直接点“智能修复该段”，系统会只修这一个片段并自动重跑该段场景图与视频

这样可以逐阶段观察：

- 小说正文是否符合预期
- 结构化角色 / 分章 / 摘要是否符合预期
- 角色视觉是否稳定
- 场景关键帧是否合理，尤其是双人 / 多人片段的中段站位是否稳定
- 视频时长和字幕是否可接受

删除项目：

- 在故事资产页点击“删除项目”
- 会删除项目记录、任务记录，以及任务结果记录过的 `outputs` 项目产物目录
- 为避免误删，后端只允许删除配置输出根目录下的项目产物目录，不会删除输出根目录本身或外部路径
- 如果项目仍有排队中或运行中的任务，后端会拒绝删除并返回失败原因

## CLI

初始化目录：

```bash
uv run storyforge init
```

运行 demo brief。该命令同样需要真实 LLM provider 配置：

```bash
uv run storyforge pipeline demo
```

使用自己的 brief：

```bash
uv run storyforge pipeline build \
  --brief path/to/your_story.toml \
  --config configs/storyforge.example.toml \
  --llm
```

从已有小说包继续规划视频：

```bash
uv run storyforge video plan \
  --novel-package outputs/your-story/novel_package.json \
  --config configs/storyforge.example.toml \
  --llm
```

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

### 2. 生成结构化信息

- 这一步会生成 `novel_package.json`、`novel_audit.json`、角色视觉档案、`scene_plan.json`、`segment_plan.json` 和各类 manifest
- 同一份 `story_source` 已经有 queued / running / completed 的结构化任务时，后端会直接复用已有任务
- `Cast Analyzer` 要求每个角色槽位都带可在正文中定位的 `source_evidence`
- `source_evidence` 仍然必须来自正文，但对带修饰语的人名或稳定称呼会做容错匹配
- `Character Designer` 必须严格覆盖目标 slots，不能重复 `cast_slot_id`，也不能凭空补正文里没有证据的人
- 视频规划也在这一步完成，后续角色图、场景图和视频阶段都只消费这些规划结果
- 视频 segment 规划在 live LLM 模式下会最多自动重试 3 次；如果模型返回的是分析备注、伪分镜或空结构，而不是可执行的正式场景计划，这一步会直接失败并把原因写入任务，而不会静默生成坏掉的 `scene_plan.json`
- 小说结构化主链路同样不再依赖本地模板静默兜底：如果 `Story Architect`、`Story Drafter`、`Chapter Planner` 或 `Editorial Reviewer` 返回空标题、缺章、空正文或空 beats，这一步会直接重试 / 失败
- 这一步还会按 `continuity_review_mode` 写出连续性审校结果：
  - `off`：只保留 `V1` 规则校验
  - `auto`：按 run 复杂度与风险自动决定是否触发 `V2`
  - `on`：强制追加 `V2` LLM 软审校
- `scene_plan.json` 是当前场景级主规划文件，保存 `chapter -> scene -> segment`，每个 scene 都带 `scene_bible`
- `scene_bible` 用来锁定地点、时间、天气、光线、背景锚点、固定道具、空间布局和角色调度，后续场景图与视频都会直接消费它
- 每个 scene 还会带 `scene_master_frame_prompt / path / status / url`，用于同场景母图生成与复用
- 如果旧 run 或弱规划里的 `scene_bible` 环境字段过空，主链路会先从该 scene 的 `scene_prompt / start_frame_prompt / mid_frame_prompt / end_frame_prompt` 里自动提炼无角色环境锚点，再回填到 `scene_bible` 后生成母图 prompt
- `segment_plan.json` 是执行索引，供逐段生成场景图、视频和失败重试使用；每个 segment 会继承所属 scene 的 `scene_bible`，并额外带 `shot_state` 与 `continuity_link`
- `shot_state` 用来锁定该片段的景别、镜头推进、人物调度、动作推进、道具连续性和尾部承接状态
- `continuity_link` 用来显式描述当前片段是否承接上一段、开场要对齐什么状态、哪些元素必须延续、哪些变化被允许
- 同一步还会生成 `continuity_report.json`，其中包含 `V1` 规则审校，以及按模式决定是否追加 `V2` 软审校；它会检查场景母图、关键帧承接、帧级角色、对白时长预算和视频执行风险

### 3. 生成角色图

- 对应执行报告是 `seedream_character_execution.json`
- 角色定妆图会统一使用白底三视图模板，只显示角色姓名，不再允许手工往模板里塞更多面板文字

### 4. 生成场景图

- 对应执行报告是 `seedream_scene_execution.json`
- 页面会先按 `scene_plan.json` 展示按 scene 分组的时间线，再允许你按 segment 单独生成
- 同一 scene 会先生成一张 `scene_master_frame`，再基于它继续生成该 scene 下各个 segment 的首帧 / 中段 / 尾帧
- 时间线里每个 scene 头部都可以单独“重生成场景母图”；这个入口只会重跑该 scene 的 `scene_master_frame`，不会连带重跑其它 scene 或 segment
- 时间线头部现在会直接显示最近一次连续性校验时间、总体状态和 top issues
- 时间线头部还会显示本次 run 请求的 `V2` 模式，以及 `V2` 是否实际执行
- 每个 scene 头部和每个 segment 卡片都会显示连续性风险；如果某个问题建议“重生成场景母图 / 场景图 / 视频”，对应按钮会被高亮
- 如果某个 segment 已被判定为连续性高风险，时间线卡片还会放出“智能修复该段”入口；这一步会先让 LLM 重写该段执行合同，再只重跑该段场景图和视频
- `scene_master_frame` 现在是无角色空场景参考图，只负责锁背景环境、光线、固定道具和空间透视，不负责承载人物
- 即使上游 `scene_bible` 很弱，`scene_master_frame` 也会优先回填地点、时间、光线、空间布局和背景锚点，避免母图退化成泛化场景
- 单段生成只更新该片段对应的首帧 / 中段锚点帧 / 尾帧，不会重跑其它片段
- 同一 scene 下的多个 segment 会共享同一套 `scene_bible` 基线，场景图 prompt 会显式带入这组约束
- 同时也会显式带入该段自己的 `shot_state`，保证景别、调度和动作推进不只靠自然语言 prompt 碰运气
- 如果 `continuity_link` 判定当前段应承接上一段，首帧会优先按这份承接关系复用或对齐上一段尾部状态
- 当前帧生成时还会优先引用 `scene_master_frame + 当前帧角色图`；连续承接段的首帧会再额外带上上一段尾帧
- 场景生图阶段只负责纯画面关键帧，不允许把对白、字幕、聊天气泡或任何可见文字直接画进图片

### 5. 生成视频

- 对应执行报告是 `seedance_execution.json`
- 视频阶段也是按 segment 单独触发
- 视频 prompt 会复用同一段所属 scene 的 `scene_bible`，把场景连续性约束直接写进 Seedance 请求
- 视频阶段会把同一 scene 的 `scene_master_frame` 当作额外参考图一起送入 Seedance
- 视频 prompt 也会复用该段 `shot_state`，把镜头景别、镜头推进、动作承接和尾部状态直接写进 Seedance 请求
- 视频 prompt 还会复用该段 `continuity_link`，把它与上一段的开场承接要求直接写进 Seedance 请求
- 只有对应片段场景关键帧已就绪时，时间线里的“生成视频”按钮才会放开
- 如果视频来自“智能修复该段”任务，系统只会把目标 segment 的视频合同重置为 `planned` 后重跑，不会重置其它片段

### 6. 手动合并总片

- 总片不再自动合并
- 页面会提供单独的“合并已生成片段”按钮
- 至少需要 2 个已生成片段，才能拼成 `rendered/full_story.mp4`

## 输出目录

CLI 直接运行时，默认输出到：

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
├── character_visual_bible.json
├── character_image_manifest.json
├── scene_plan.json
├── segment_plan.json
├── scene_image_manifest.json
├── seedream_character_execution.json
├── seedream_scene_execution.json
├── seedance_manifest.json
├── continuity_repair_<segment_id>.json
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
  角色图 prompt 会统一追加固定 `SF-TURN-01` 横版 16:9 白底三视图模板，只保留角色姓名和人物描述，要求正面、左侧面、背面三栏全身站姿一致。不再要求信息格、色卡、材质块或灰底设计板；性别、身份和职业只作为造型参考，不允许作为画面文字。
- `segment_plan.json`
  视频片段规划，定义每个片段的参与角色、对白、字幕、时长、首帧 / 中段锚点帧 / 尾帧 prompt，以及分段关系。
  其中 `requires_mid_frame = true` 表示该片段会额外生成中段锚点帧；常见于双人 / 多人同框、8 秒以上片段、动作推进明显或中段关系变化明显的镜头。
  页面时间线会直接读取这份规划来展示完整片段列表，即使某个片段还没有生成任何图片或视频，也会先显示出来等待单独触发。
- `scene_image_manifest.json`
  场景关键帧任务清单，记录每个片段的首帧、中段锚点帧（如有）、尾帧、每一帧实际出镜角色、角色参考图和输出位置。
- `seedream_character_execution.json`
  角色图执行报告，只用于确认角色图阶段是否成功以及失败原因。
- `seedream_scene_execution.json`
  场景图执行报告，只用于确认场景图阶段是否成功以及失败原因。
- `seedance_manifest.json`
  最终视频提交清单，Seedance 会按这里的每个 clip 去生成视频。
  StoryForge 会优先用“角色定妆图 + 中段锚点图（如有）+ 首尾帧”的完整组合提交；若 Seedance 对该组合返回 400，会自动降级到更保守的图片组合继续重试。
  `title` 应继承真实小说标题，不再使用 `segment_video_manifest` 这类文件用途名；旧产物重载时也会优先从 `novel_package.json` / `story_source.json` 恢复标题。
- `seedance_execution.json`
  视频执行报告，记录提交状态、完成数量、失败数量和下载结果。
- `continuity_repair_<segment_id>.json`
  单段智能修复报告，记录本次修复针对哪个 segment、修复摘要、触发它的连续性问题、修复前后差异和被改写的关键字段。
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
4. 再跑结构化信息阶段
5. 检查 `novel_package.json` 和 `novel_audit.json` 是否符合预期

### 阶段二：验证角色和场景

1. 生成角色图
2. 检查角色外观、性别、体态和服装是否稳定
3. 再到项目详情时间线里按 segment 逐段生成场景关键帧
4. 检查场景图是否引用同一组角色图；若是双人 / 多人片段，重点检查中段锚点帧是否把所有角色都稳定画出
   现在首帧 / 中段 / 尾帧会按各自的 `*_frame_characters` 和对应时间节拍选参考图；如果首帧或中段明明是单人等待镜头，就不会因为整段 `involved_characters` 有两个人而自动喂入另一位角色图
5. 优先重跑具体有问题的 segment，不要默认整批重跑
6. 如果连续性风险明确落在某个 segment，可以优先点击“智能修复该段”，让系统先重写该段合同，再观察重跑结果

### 阶段三：提交真实视频

1. 确认 `seedance_manifest.json` 里的片段数量、时长、字幕，以及角色参考图 / 中段锚点图 / 首尾帧路径
2. 确认没有使用 `--reload` 启动服务
3. 在项目详情时间线里按 segment 单独提交 Seedance 视频任务
4. 当至少已有 2 个片段生成完成后，再手动点击“合并已生成片段”

## 失败与重试

- 所有任务都会在接口和页面上返回 `error` 字段，前端会展示任务级和阶段级失败原因。
- Seedance 视频任务如果提交阶段就被接口拒绝，`seedance_execution.json` 会记录真实响应体、请求摘要和各次降级尝试，不再只显示 `failed_count=1`。
- LLM 结构化输出失败会由 StoryForge 外层最多重试 3 次；仍失败会显式标记任务失败。
- LangChain structured output 会优先读取 parsed tool 结果；如果模型没有触发 tool call 但 raw 文本里有 JSON，会自动提取 JSON 校验；如果返回空结构，会显示“模型没有返回结构化对象”这类明确原因。
- 视频 segment 规划还会额外拒绝带有 `当前片段聚焦`、`结尾要保留`、`当前小段聚焦` 这类分析模板话术的伪分镜；看到这类错误时，应直接重跑“生成结构化信息”，不要继续拿该 run 去生成场景图和视频。
- 服务重启时，残留的 `running` 任务会重新回到 `queued`，启动后会重新执行。
- 如果任务已经进入 `failed`，推荐在页面重新点击对应阶段按钮，而不是手动修改数据库。
- 视频长任务执行期间不要用 `--reload`。热重载会中断当前进程，即使现在会重排队，也可能造成重复提交或等待时间变长。

## 相关文档

- [README](../README.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
