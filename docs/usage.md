# 使用文档

这份文档面向“如何把 StoryForge 跑起来并完成一轮实际工作流”。

如果你只想先快速体验，优先看 [`README.md`](../README.md)。  
如果你需要 HTTP 接口示例，配合阅读 [`api.md`](api.md)。

## 环境要求

- Python `>= 3.11`
- `uv`
- `ffmpeg`
- 可访问的 DeepSeek / Seedream / Seedance 接口
- 可选：MySQL 8+

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
SEEDREAM_API_KEY=your_seedream_api_key
SEEDANCE_API_KEY=your_seedance_api_key
STORYFORGE_DB_PASSWORD=your_mysql_password
SEEDREAM_BASE_URL=https://your-seedream-endpoint.example.com
SEEDANCE_BASE_URL=https://your-seedance-endpoint.example.com
```

示例见：[`.env.example`](../.env.example)

### 配置文件

默认配置文件：

- [`configs/storyforge.example.toml`](../configs/storyforge.example.toml)

关键配置项：

```toml
[llm]
enabled = true
provider = "deepseek"
model = "deepseek-chat"

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
enabled = true
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

1. 创建项目并生成小说
2. 在项目详情页的“小说”标签页检查并按需修改正文
3. 生成结构化信息
4. 生成角色图
5. 检查角色图后生成场景图
6. 检查场景图后生成视频

这样可以逐阶段观察：

- 小说正文是否符合预期
- 结构化角色 / 分章 / 摘要是否符合预期
- 角色视觉是否稳定
- 场景首尾帧是否合理
- 视频时长和字幕是否可接受

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

说明：

- `novel_package.json` 是运行态最小包，只保留图片与视频阶段真正要消费的字段
- `novel_audit.json` 保存 `review`、`workflow_trace`，以及从运行包剥离出来的分析上下文
- `Cast Analyzer` 现在要求每个角色槽位都提供可在小说正文中定位的 `source_evidence`
- `Character Designer` 只允许覆盖本次目标 slots，不能重复 `cast_slot_id`，也不能凭空补出正文里没有证据的人

### 第三步：生成角色图

产出：

- `character_visual_bible.json`
- `character_image_manifest.json`
- `assets/characters/*.png`
- `seedream_character_execution.json`

### 第四步：生成场景图

产出：

- `segment_plan.json`
- `scene_image_manifest.json`
- `assets/frames/*_start.png`
- `assets/frames/*_end.png`
- `seedream_scene_execution.json`

### 第五步：生成视频

产出：

- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`
- `rendered/full_story.mp4`

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
- `segment_plan.json`
  视频片段规划，定义每个片段的参与角色、对白、字幕、时长、首尾帧 prompt 和分段关系。
- `scene_image_manifest.json`
  场景首尾帧任务清单，记录每个片段的首帧、尾帧、参考图和输出位置。
- `seedream_character_execution.json`
  角色图执行报告，只用于确认角色图阶段是否成功以及失败原因。
- `seedream_scene_execution.json`
  场景图执行报告，只用于确认场景图阶段是否成功以及失败原因。
- `seedance_manifest.json`
  最终视频提交清单，Seedance 会按这里的每个 clip 去生成视频。
  `title` 应继承真实小说标题，不再使用 `segment_video_manifest` 这类文件用途名；旧产物重载时也会优先从 `novel_package.json` / `story_source.json` 恢复标题。
- `seedance_execution.json`
  视频执行报告，记录提交状态、完成数量、失败数量和下载结果。
- `assets/characters/*.png`
  实际生成出来的角色图文件。
- `assets/frames/*.png`
  实际生成出来的场景首帧和尾帧文件。
- `rendered/*.mp4`
  各个视频片段的下载结果。
- `rendered/full_story.mp4`
  条件满足时自动拼出的总片。

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
3. 再生成场景首尾帧
4. 检查场景图是否引用同一组角色图

### 阶段三：提交真实视频

1. 确认 `seedance_manifest.json` 里的片段数量、时长、字幕和首尾帧路径
2. 确认没有使用 `--reload` 启动服务
3. 最后再提交 Seedance 视频任务

## 失败与重试

- 所有任务都会在接口和页面上返回 `error` 字段，前端会展示任务级和阶段级失败原因。
- LLM 结构化输出失败会由 StoryForge 外层最多重试 3 次；仍失败会显式标记任务失败。
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
