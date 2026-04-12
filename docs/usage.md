# 使用文档

## 1. 环境准备

### Python

项目要求：

- `Python >= 3.11`

### 依赖安装

```bash
uv sync
```

## 2. 配置

示例配置文件：

- [configs/storyforge.example.toml](/Users/xy/StoryForge/configs/storyforge.example.toml)

### LLM 配置

当前默认是 DeepSeek：

```toml
[llm]
enabled = false
provider = "deepseek"
model = "deepseek-chat"
temperature = 0.7
api_key_env = "DEEPSEEK_API_KEY"
base_url = "https://api.deepseek.com/v1"
timeout_seconds = 120
```

### Seedream 配置

```toml
[seedream]
enabled = true
base_url = ""
api_key_env = "SEEDREAM_API_KEY"
model = "doubao-seedream-4-5-251128"
auto_submit = false
image_size = "2K"
response_format = "url"
download_outputs = true
```

### Seedance 配置

```toml
[seedance]
enabled = true
base_url = ""
api_key_env = "SEEDANCE_API_KEY"
model = "doubao-seedance-2-0-260128"
auto_submit = false
with_audio = true
subtitle_mode = "burned_in"
subtitle_style = "底部居中中文硬字幕，白字黑边，电影感，无额外花字"
watermark = false
download_outputs = true
```

建议一开始先：

- `auto_submit = false`
- 先确认 `.env` 中的 `SEEDREAM_*`、`SEEDANCE_*` 已配置
- 首次联调可以保留 `auto_submit = false`，先检查 manifest 和图片结果

当前工程已经支持真实生图、真实视频任务提交、结果下载和自动 `ffmpeg` 合并；保留 `auto_submit = false` 只是为了在联调阶段降低成本和失败排查难度。

### 数据库配置

如果要把项目和任务元数据从本地 JSON 切到 MySQL，在配置文件里增加或打开：

```toml
[database]
enabled = true
host = "127.0.0.1"
port = 3306
user = "root"
password = ""
password_env = "STORYFORGE_DB_PASSWORD"
database = "storyforge"
charset = "utf8mb4"
connect_timeout_seconds = 5
auto_create_schema = true
```

推荐把密码放进 `.env`：

```bash
STORYFORGE_DB_PASSWORD=root
```

这样服务启动时会自动：

- 连接 MySQL
- 自动创建数据库 `storyforge`
- 自动创建 `projects` / `tasks` 两张表

如果 `database.enabled = false`，系统会继续回退到本地：

- `workspace/state/projects.json`
- `workspace/state/tasks.json`

## 3. 准备 brief

示例 brief：

- [examples/briefs/demo_story.toml](/Users/xy/StoryForge/examples/briefs/demo_story.toml)

你自己的 brief 最少需要：

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

## 4. CLI 使用

### 初始化目录

```bash
uv run storyforge init
```

### 跑 demo

```bash
uv run storyforge pipeline demo
```

### 跑自己的故事

```bash
uv run storyforge pipeline build \
  --brief path/to/your_story.toml \
  --config configs/storyforge.example.toml
```

### 开启真实 LLM

```bash
uv run storyforge pipeline build \
  --brief path/to/your_story.toml \
  --config configs/storyforge.example.toml \
  --llm
```

### 从已有小说包生成视频任务清单

```bash
uv run storyforge video plan \
  --novel-package outputs/your-story/novel_package.json \
  --config configs/storyforge.example.toml
```

### 启动 API

```bash
uv run storyforge api serve --host 0.0.0.0 --port 8000 --reload
```

启动后建议直接打开页面控制台：

- `http://127.0.0.1:8000/`

这个页面支持：

- 直接填写 brief
- 勾选是否启用 DeepSeek
- 第一步只生成小说
- 在项目详情页手动点击“生成角色图”
- 在项目详情页手动点击“生成场景图”
- 在项目详情页手动点击“生成视频”
- 自动查看任务队列
- 直接预览输出目录里的 JSON、章节、角色图、场景帧、视频片段和 `full_story.mp4`
- 任务还在 `running` 时，也会尽量实时显示已经落盘的文档、图片和视频
- 页面会显示当前阶段：
  - `小说生成中`
  - `小说已完成`
  - `角色图生成中`
  - `角色图已完成`
  - `场景图生成中`
  - `场景图已完成`
  - `视频生成中`
  - `视频已完成`

### 运行时长规则

- 现在是由 LLM 在 `5-12` 秒之间自行判断每个片段时长
- `video.segment_duration_seconds` 仍然保留，但只作为模型拿不准时的偏好秒数
- 发送给 Seedance 之前，代码会做最终安全规整，避免超出接口允许范围

### 双角色与性别规则

- 如果 brief 明显是告白 / 表白 / 双人关系驱动故事，角色生成阶段会至少保留 2 个核心角色
- 如果这类故事没有明确写同性关系，系统会默认优先修正成“一男一女”双核心角色，避免又生成两个男角色或两个女角色
- `gender` 已经贯通到小说角色卡、角色视觉卡、角色图 prompt、场景图 prompt 和视频 prompt
- 双人或多人场景会尽量把所有 `involved_characters` 都带入同一张场景图，而不是只画一个人

## 5. API 使用

### 第一步：提交小说任务

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/novel \
  -H "Content-Type: application/json" \
  -d '{
    "brief": {
      "title_hint": "雾站档案",
      "idea": "一名调查员在暴雨夜追查失踪列车。",
      "genre": "悬疑",
      "tone": "压迫、电影感",
      "target_audience": "成年读者",
      "chapter_count": 6,
      "total_word_target": 18000,
      "must_include": ["失踪列车"],
      "style_keywords": ["暴雨", "车站", "霓虹"]
    },
    "use_llm": false
  }'
```

返回：

```json
{
  "project_id": "xxxx",
  "task_id": "xxxx",
  "status": "queued"
}
```

### 第二步：基于已有小说任务生成角色图

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/characters \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "xxxx",
    "source_task_id": "story-task-id"
  }'
```

### 第三步：基于同一个 story run 生成场景图

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/scenes \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "xxxx",
    "source_task_id": "story-task-id"
  }'
```

### 第四步：基于同一个 story run 生成视频

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/videos \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "xxxx",
    "source_task_id": "story-task-id"
  }'
```

### 兼容旧接口

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/novel-to-video ...
```

兼容图片接口也仍可用：

```bash
curl -X POST http://127.0.0.1:8000/v1/projects/images ...
```

它会一口气执行“角色图 + 场景图”。现在页面默认工作流是更细的四步手动推进。

### 查询任务状态

```bash
curl http://127.0.0.1:8000/v1/tasks/<task_id>
```

## 6. 输出文件说明

### 小说产物

- `outline.json`
  大纲、角色、结构化音色卡、章节蓝图

- `novel_package.json`
  小说中间产物总包

- `editorial_review.json`
  审校结果

- `workflow_trace.json`
  多 Agent 工作流的结构化 trace

- `chapters/chapter-01.md`
  单章草稿

### 视频产物

- `character_visual_bible.json`
  角色视觉设定。角色图阶段开始时就会生成。

- `character_image_manifest.json`
  角色定妆卡任务清单

- `segment_plan.json`
  按章节拆出来的视频片段规划，包含旁白、对白、硬字幕、音效、音乐和时间节拍

- `scene_image_manifest.json`
  场景首尾帧与参考图任务清单，包含角色锁定 prompt 和连续片段尾帧复用信息

- `seedream_execution.json`
  Seedream 聚合执行结果与统计

- `seedance_manifest.json`
  片段视频任务清单，包含编译后的 Seedance 音视频 prompt、角色音色锁定与硬字幕要求。场景图阶段完成后即可拿到。

- `seedream_character_execution.json`
  Seedream 角色图阶段执行结果与统计

- `seedream_scene_execution.json`
  Seedream 场景图阶段执行结果与统计

- `video_workflow_trace.json`
  视频规划阶段 trace

- `concat_list.txt`
  `ffmpeg concat` 列表

- `ffmpeg_concat.sh`
  用来合并总片的脚本

- `rendered/full_story.mp4`
  当第四步“生成视频”成功且片段全部下载完成后，pipeline 会自动执行 ffmpeg 生成总片

## 7. 推荐工作流

### 阶段一：先验证结构

1. 不开真实 LLM
2. 先只跑“生成小说”
3. 再单独跑“生成角色图”
4. 看输出目录和 JSON 结构是否符合你的生产流程

### 阶段二：打开 DeepSeek

1. 配好 `DEEPSEEK_API_KEY`
2. 用页面第一步或 `--llm` 跑小说链路
3. 重点观察结构化输出是否稳定

### 阶段三：接真实素材与视频生成

1. 角色图模型接到 `character_image_manifest.json`
2. 场景图模型接到 `scene_image_manifest.json`
3. Seedance 接 `seedance_manifest.json`

## 8. 最佳实践

- 先把角色图 prompt 和首尾帧 prompt 固化好，再接真实视频模型。
- 当前音色一致性是 prompt 级控制；如果你后面接到支持 speaker embedding 的接口，再把 `voice_profile` 升级成固定 speaker ID。
- 让每个片段尽量短，便于失败重跑。
- 不要把所有逻辑都压在一个 prompt 里，保持中间产物可审计。
