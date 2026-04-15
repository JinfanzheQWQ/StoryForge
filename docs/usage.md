# 使用文档

这份文档面向“如何把 StoryForge 跑起来并完成一轮实际工作流”。
它是当前唯一的操作手册；README 不再重复这里的步骤细节，`status.md` 也不再重复这里的产物说明。

如果你只想先快速体验，优先看 [`README.md`](../README.md)。  
如果你需要 HTTP 接口示例，配合阅读 [`api.md`](api.md)。

## 环境要求

- Python `>= 3.11`
- `uv`
- `ffmpeg`
- 可访问的 DeepSeek / Seedream / Seedance 接口
- 如果要切换到 ChatGPT 5.4，还需要可访问的 OpenAI 接口
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
- 如果 `OPENAI_BASE_URL` 指向第三方平台，而该平台没有 `gpt-5.4` 映射，会返回 `platform text model target not found`
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

1. 创建项目并生成小说；在创建页可选 `DeepSeek` 或 `ChatGPT 5.4`
2. 在项目详情页的“小说”标签页检查并按需修改正文
3. 生成结构化信息
4. 生成角色图
5. 在项目详情页时间线里按 segment 逐段生成场景图
6. 在同一条时间线里按 segment 逐段生成视频

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

运行 demo brief。该命令同样需要真实 DeepSeek 配置：

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

## 五阶段工作流说明

### 第一步：生成小说

产出：

- `story_source.json`

说明：

- 这一步只生成可编辑正文
- 页面会先展示这份正文，让你决定是否修改

### 审阅窗口：审阅并编辑小说正文

可做的事情：

- 直接查看生成后的章节标题、摘要和正文
- 手动修改标题、摘要、正文
- 保存后让后续结构化 / 图片 / 视频阶段按新正文重跑

### 第二步：生成结构化信息

产出：

- `novel_package.json`
- `novel_audit.json`
- `character_visual_bible.json`
- `character_image_manifest.json`
- `segment_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`

说明：

- `novel_package.json` 是运行态最小包，只保留图片与视频阶段真正要消费的字段
- `novel_audit.json` 保存 `review`、`workflow_trace`，以及从运行包剥离出来的分析上下文
- 同一故事正文修订已经存在 queued / running / completed 结构化任务时，后端会直接返回已有任务 ID，不会重复创建结构化任务
- `Cast Analyzer` 现在要求每个角色槽位都提供可在小说正文中定位的 `source_evidence`
- `source_evidence` 的校验仍然是“必须来自正文”，但对“女学生林栀”“年轻监考老师周骁”这类带修饰语证据，后端会允许通过人名或稳定称呼做容错匹配，避免误杀
- `Character Designer` 只允许覆盖本次目标 slots，不能重复 `cast_slot_id`，也不能凭空补出正文里没有证据的人
- `Character Designer` 现在会给出固定索引合同，明确 `characters[0]`、`characters[1]` 等条目分别必须对应哪个 `cast_slot_id`；如果模型漏人，structured retry 会重复下发这份合同
- 如果首轮角色表仍然缺失某些 slot，系统会额外发起一次“只补缺失角色”的结构化补生请求，再把结果合并回完整角色表
- 视频规划在本阶段同步生成，后续角色图、场景图和视频阶段只读取这些规划文件，不再等到生成角色图时才拆分视频片段
- `segment_plan.json` 会要求 LLM 按中文自然口播语速估算时长；对白、旁白或硬字幕超过当前时长可说完的字数时，必须拆成下一个片段
- `segment_plan.json` 现在还会显式规划 `requires_mid_frame` 与 `mid_frame_prompt`；多人同框、长时长、动作推进明显的片段会在首尾帧之外额外生成中段锚点帧
- `segment_plan.json` 现在还会显式规划 `start_frame_characters`、`mid_frame_characters`、`end_frame_characters`。`involved_characters` 只表示这个片段剧情涉及谁，不再等同于每一帧都必须同框
- 帧级角色会按首帧 / 中段 / 尾帧对应的 `timed_beats` 与画面 prompt 二次归一化；“等待某人”“想起某人”这类未实际入镜的提及不会自动绑定该角色参考图
- 场景生图阶段只负责纯画面关键帧，不允许把对白、硬字幕、聊天气泡、旁白框或任何可见文字直接画进图片；字幕只在视频阶段烧录

### 第三步：生成角色图

产出：

- `assets/characters/*.png`
- `seedream_character_execution.json`

### 第四步：生成场景图

产出：

- `assets/frames/*_start.png`
- `assets/frames/*_mid.png`
- `assets/frames/*_end.png`
- `seedream_scene_execution.json`

说明：

- Web 端会根据 `segment_plan.json` 先把所有片段列在时间线里
- 场景图不再默认一口气生成全部片段
- 你可以针对单个 segment 单独点击“生成场景图”或“重生成场景图”
- 单段生成只会更新该 segment 对应的首帧 / 中段锚点帧 / 尾帧，不会把其它片段重跑

### 第五步：生成视频

产出：

- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`

说明：

- 视频阶段也改成按 segment 单独触发
- 只有某个 segment 的场景关键帧已就绪时，时间线里的“生成视频”按钮才会放开
- 单段视频任务不会自动把全部 segment 再生成一遍

### 第六步：手动合并总片

产出：

- `rendered/full_story.mp4`

说明：

- 总片不再自动合并
- 页面会提供单独的“合并已生成片段”按钮
- 合并时会按 `seedance_manifest.json` 的片段顺序，把当前已经存在本地 mp4 的片段拼成 `full_story.mp4`
- 至少需要 2 个已生成片段才能执行合并

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
├── segment_plan.json
├── scene_image_manifest.json
├── seedream_character_execution.json
├── seedream_scene_execution.json
├── seedance_manifest.json
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
- 服务重启时，残留的 `running` 任务会重新回到 `queued`，启动后会重新执行。
- 如果任务已经进入 `failed`，推荐在页面重新点击对应阶段按钮，而不是手动修改数据库。
- 视频长任务执行期间不要用 `--reload`。热重载会中断当前进程，即使现在会重排队，也可能造成重复提交或等待时间变长。

## 最佳实践

- 先看中间产物，再扩大真实调用范围
- 先把角色图和场景图调稳，再追求视频一致性
- 不要一开始就依赖一键全链路
- 让每个视频片段尽量短，便于失败重跑
- 保持 `novel_audit.json` 里的 `workflow_trace` 与各阶段 manifest 可审计

## 相关文档

- [README](../README.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
