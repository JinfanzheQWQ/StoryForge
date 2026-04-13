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
uv run storyforge api serve --host 127.0.0.1 --port 8000 --reload
```

访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

推荐使用方式：

1. 创建项目并生成小说
2. 在项目详情页生成角色图
3. 检查角色图后生成场景图
4. 检查场景图后生成视频

这样可以逐阶段观察：

- 小说结构是否符合预期
- 角色视觉是否稳定
- 场景首尾帧是否合理
- 视频时长和字幕是否可接受

## CLI

初始化目录：

```bash
uv run storyforge init
```

运行 demo：

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

## 四步工作流说明

### 第一步：生成小说

产出：

- `outline.json`
- `novel_package.json`
- `editorial_review.json`
- `workflow_trace.json`
- `chapters/*.md`

### 第二步：生成角色图

产出：

- `character_visual_bible.json`
- `character_image_manifest.json`
- `assets/characters/*.png`
- `seedream_character_execution.json`

### 第三步：生成场景图

产出：

- `segment_plan.json`
- `scene_image_manifest.json`
- `assets/frames/*_start.png`
- `assets/frames/*_end.png`
- `seedream_scene_execution.json`

### 第四步：生成视频

产出：

- `seedance_manifest.json`
- `seedance_execution.json`
- `rendered/*.mp4`
- `rendered/full_story.mp4`
- `ffmpeg_concat.sh`

## 输出目录

CLI 直接运行时，默认输出到：

```text
outputs/<story-slug>/
```

典型目录结构：

```text
outputs/<story-slug>/
├── chapters/
├── assets/
│   ├── characters/
│   └── frames/
├── rendered/
├── outline.json
├── novel_package.json
├── editorial_review.json
├── workflow_trace.json
├── character_visual_bible.json
├── character_image_manifest.json
├── segment_plan.json
├── scene_image_manifest.json
├── seedream_execution.json
├── seedance_manifest.json
├── seedance_execution.json
├── concat_list.txt
└── ffmpeg_concat.sh
```

## 推荐联调顺序

### 阶段一：只验证结构

1. 不开真实 LLM
2. 跑小说阶段
3. 检查 JSON 和 Markdown 是否符合预期

### 阶段二：打开 DeepSeek

1. 配好 `DEEPSEEK_API_KEY`
2. 只跑小说阶段
3. 看角色、章节和语气是否稳定

### 阶段三：接入真实图像与视频

1. 生成角色图
2. 生成场景图
3. 最后再提交 Seedance 视频任务

## 最佳实践

- 先看中间产物，再扩大真实调用范围
- 先把角色图和场景图调稳，再追求视频一致性
- 不要一开始就依赖一键全链路
- 让每个视频片段尽量短，便于失败重跑
- 保持 `workflow_trace.json` 和 manifest 可审计

## 相关文档

- [README](../README.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [工程状态](status.md)
