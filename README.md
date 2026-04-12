# StoryForge

`StoryForge` 不再只是项目骨架，而是一套已经能真实跑通的小说生成与小说转视频工程。当前版本已经升级为：

- `Python >= 3.11`
- `uv` 管理依赖与运行
- `FastAPI` + 异步任务队列
- `LangChain >= 1.2` 结构化多 Agent 工作流
- DeepSeek 作为当前默认 LLM 接入
- Seedance 作为当前默认的视频生成接口目标
- 浏览器端四步手动工作台
- 项目 / 任务持久化
- 自动 `ffmpeg` 总片拼接

当前主交互已经是四步式：

1. 生成小说
2. 生成角色图
3. 生成场景图
4. 生成视频

底层仍然支持端到端“小说 -> 角色图 -> 场景首尾帧 -> 视频片段 -> 总片拼接”链路，但页面默认不再一键全跑。

## 这套代码算 Agent 吗

算，但要说准确：

- 小说生成部分是“结构化多 Agent 工作流”
- 视频规划部分是“Agent + 工作流混合架构”
- Seedream / Seedance / FastAPI / 队列这些本身不算 Agent，它们属于模型集成和基础设施层

更完整的技术说明见：

- [docs/tech-stack.md](/Users/xy/StoryForge/docs/tech-stack.md)
- [docs/status.md](/Users/xy/StoryForge/docs/status.md)

## 实现状态

### 已实现

- DeepSeek 真实 LLM 接入
- `LangChain >= 1.2` 结构化多 Agent 小说工作流
- FastAPI + 异步任务队列
- 内置浏览器 Web 控制台，可直接提交任务并预览产物
- Web 控制台前端已完成首轮模块化拆分
- 后端级 `project_id` 与项目 / 任务持久化，支持本地 JSON 或 MySQL
- Doubao Seedream 4.5 真实生图 client
- 角色定妆卡与场景首尾帧生图执行
- 角色定妆卡到场景图的参考图一致性链路
- 小说角色结构化音色卡输出，并贯通到视频片段 prompt
- 视频 prompt 侧的音色一致性、年龄感、体型、肩宽、四肢比例锁定
- 连续片段尾帧复用为下一片段首帧的视觉连续性链路
- Seedance 2.0 视频任务 manifest 生成
- Seedance 2.0 任务创建、状态查询与结果下载 client
- 资产页 / 队列页视频预览已修复“轮询时被重建打断”的问题
- 最小前端冒烟测试已接入项目测试基线

### 仍待你按真实环境补强

- Seedance 图像条件字段按你的账户环境微调
- Seedance 任务轮询、结果下载、重试
- 对象存储和公网素材 URL 管理
- 持久化队列、权限和多用户工作区

### 当前测试基线

- `uv run ruff check`
- `uv run pytest`
- 当前基线结果：`31 passed`

## 当前支持的业务链路

### 1. 小说生成

小说生成采用结构化多 Agent 工作流，当前按以下角色顺序执行：

1. `Story Architect`
   负责把 brief 提炼成故事引擎、世界设定、主题和视觉母题。

2. `Character Designer`
   负责生成角色卡、结构化音色卡，并产出可直接用于角色图生成的角色 prompt。

3. `Chapter Planner`
   负责把项目拆成章节蓝图，每章都保留后续可拆成视频片段的节拍。

4. `Chapter Writer`
   负责逐章生成 Markdown 草稿，并额外输出视觉抓手与连续性信息。

5. `Editorial Reviewer`
   负责统一审校结构、角色连续性和视频改编潜力。

## 2. 小说转视频

视频链路按你当前的需求拆成这几步：

1. 分析角色
2. 生成角色定妆卡
3. 把小说章节拆成多个片段视频
4. 基于角色定妆卡规划场景参考图生图
5. 为每个片段规划首尾帧、旁白、对白、音效、音乐方向和硬字幕文案
6. 把结构化角色音色卡编译进 Seedance 片段 prompt，锁定音色、语速和情绪基线
7. 生成 Seedance 片段视频任务清单与音视频 / 硬字幕 prompt
8. 生成可选的 `ffmpeg` 合并脚本

当前工程既支持只生成任务清单，也支持直接调用真实 `Seedream` / `Seedance` 服务完成图片、视频下载与总片合并。

现在当 `Seedance` 全部片段成功并且成片下载完成后，pipeline 还会自动执行 `ffmpeg`，直接产出总片 `rendered/full_story.mp4`。

## 技术总览

- 工程管理：`Python 3.11+`、`uv`
- 服务层：`FastAPI`、`Pydantic`、异步任务队列
- Agent 层：`LangChain >= 1.2`、`create_agent`、`ToolStrategy`
- LLM：`DeepSeek`
- 生图：`Doubao Seedream 4.5`
- 生视频：`Seedance 2.0`
- 网络调用：`httpx`
- 元数据持久化：本地 JSON 或 MySQL
- 媒体拼接：`ffmpeg` 脚本生成与自动执行

## Web 控制台结构

当前前端已经不是单文件堆叠结构，而是三层拆分：

- HTML 模板层：`src/storyforge/api/templates/`
- JS 模块层：`src/storyforge/api/static/app/`
- CSS 模块层：`src/storyforge/api/static/styles/`

其中：

- `templates/console.html` 负责页面总布局
- `templates/partials/` 放页头、灯箱等共用结构
- `templates/panels/` 放首页 / 新建任务 / 故事资产 / 制作进度四个 panel
- `static/app/main.js` 只负责初始化
- `static/app/events.js`、`jobs.js`、`navigation.js`、`refresh.js` 分别负责事件、任务提交、导航、轮询
- `static/app/render/` 负责页面渲染
- `static/styles/` 按 `base / home / workbench / detail / responsive` 拆分

## 项目结构

```text
StoryForge/
├── configs/
│   └── storyforge.example.toml
├── docs/
│   ├── api.md
│   ├── architecture.md
│   ├── development.md
│   ├── status.md
│   ├── tech-stack.md
│   └── usage.md
├── examples/
│   └── briefs/
│       └── demo_story.toml
├── src/storyforge/
│   ├── agents/          # LangChain backend 与 orchestration
│   ├── api/             # FastAPI app 与 routers
│   ├── application/     # 异步任务队列与容器
│   ├── core/            # 配置、IO、公共工具
│   ├── domains/
│   │   ├── novel/       # 小说领域模型、结构化 schema、服务
│   │   └── video/       # 视频领域模型、分段规划、Seedance manifest
│   ├── integrations/    # LLM、Seedance、ffmpeg 适配层
│   ├── pipelines/       # story / video pipeline
│   └── cli.py           # CLI 入口
├── src/storyforge/api/templates/
│   ├── console.html
│   ├── partials/
│   └── panels/
├── src/storyforge/api/static/
│   ├── app/
│   └── styles/
├── scripts/
│   ├── check.sh
│   └── clean-local-artifacts.sh
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
└── uv.lock
```

## 安装

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

当前示例环境变量：

```bash
DEEPSEEK_API_KEY=...
SEEDREAM_API_KEY=...
SEEDANCE_API_KEY=...
STORYFORGE_DB_PASSWORD=...
SEEDREAM_BASE_URL=https://your-seedream-endpoint.example.com
SEEDANCE_BASE_URL=https://your-seedance-endpoint.example.com
```

如需启用 MySQL 项目/任务持久化，在配置文件里打开：

```toml
[database]
enabled = true
host = "127.0.0.1"
port = 3306
user = "root"
password = ""
password_env = "STORYFORGE_DB_PASSWORD"
database = "storyforge"
```

推荐做法：

- 把主机、端口、用户、库名写在配置文件
- 把数据库密码写进 `.env` 的 `STORYFORGE_DB_PASSWORD`

## 常用命令

### 启动 API / Web 控制台

```bash
uv run storyforge api serve --reload
```

启动后打开：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

### 初始化目录

```bash
uv run storyforge init
```

### 跑 demo

```bash
uv run storyforge pipeline demo
```

### 用自己的 brief 跑完整链路

```bash
uv run storyforge pipeline build \
  --brief examples/briefs/demo_story.toml \
  --config configs/storyforge.example.toml \
  --llm
```

### 从已生成小说包继续生成视频规划

```bash
uv run storyforge video plan \
  --novel-package outputs/雾港回声/novel_package.json \
  --config configs/storyforge.example.toml
```

### 跑检查

```bash
scripts/check.sh
```

### 清理本地产物

先看将删除什么：

```bash
scripts/clean-local-artifacts.sh --dry-run
```

保守清理缓存、`.DS_Store`、`__pycache__`：

```bash
scripts/clean-local-artifacts.sh
```

如果要连 `outputs/`、`workspace/`、`.venv/` 一起清掉：

```bash
scripts/clean-local-artifacts.sh --deep
```

## API 概览

### 四步手动工作流

```http
POST /v1/projects/novel
```

第一步只生成小说：

```json
{
  "brief": {
    "title_hint": "黑潮档案",
    "idea": "一名记者发现每次台风登陆前，失踪名单都会提前出现在废弃气象站。",
    "genre": "悬疑 / 都市怪谈",
    "tone": "压抑、电影感",
    "target_audience": "成年悬疑读者",
    "chapter_count": 8,
    "total_word_target": 24000,
    "must_include": ["废弃气象站", "匿名电话", "封存档案"],
    "style_keywords": ["台风", "潮湿", "霓虹", "监控画面"]
  },
  "use_llm": true
}
```

第二步基于同一个 `project_id` + 第一步返回的 `task_id` 生成角色图：

```http
POST /v1/projects/characters
```

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

第三步继续基于同一个 story run 生成场景图：

```http
POST /v1/projects/scenes
```

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

第四步继续基于同一个 story run 生成视频：

```http
POST /v1/projects/videos
```

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

兼容接口仍保留：

```http
POST /v1/projects/novel-to-video
```

它用于旧脚本或测试，仍支持一条任务直接跑完整链路。

兼容图片接口也保留：

```http
POST /v1/projects/images
```

它会一口气执行“角色图 + 场景图”，主要用于兼容旧脚本。页面默认已经改成更细的四步。

### 查询任务

```http
GET /v1/tasks/{task_id}
```

## 产物说明

四步手动工作流会共享同一个 story run 输出目录。默认落在：

`outputs/projects/<project_id>/runs/<story_task_id>/`

小说阶段先生成：

- `outline.json`
- `novel_package.json`
- `editorial_review.json`
- `workflow_trace.json`

角色图阶段追加生成：

- `character_visual_bible.json`
- `character_image_manifest.json`
- `seedream_character_execution.json`

场景图阶段追加生成：

- `segment_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `video_workflow_trace.json`
- `seedream_scene_execution.json`
- `concat_list.txt`
- `ffmpeg_concat.sh`

视频阶段追加生成：

- `rendered/full_story.mp4`（当 Seedance 全部成功后自动生成）

## 当前实现边界

已经完成：

- 结构化多 Agent 小说工作流
- FastAPI 应用层
- 内存态异步任务队列
- 项目 / 任务元数据的 JSON / MySQL 双存储后端
- DeepSeek 接入配置
- Seedream 4.5 生图 client
- Seedance 2.0 manifest、任务提交、轮询与下载 client
- 四步手动推进的 Web 工作台：
  - 生成小说
  - 生成角色图
  - 生成场景图
  - 生成视频
- Web 控制台前端模板 / JS / CSS 已完成首轮模块化
- 角色定妆卡、场景图、视频片段的任务清单化
- 角色定妆卡到场景图的参考图一致性链路
- 结构化角色音色卡到 Seedance prompt 的贯通
- 连续片段首尾帧继承与更严格的角色年龄/体态锁定
- Seedance 成功后自动拼接总片 `full_story.mp4`
- 项目统计按逻辑 run 聚合，而不是把 story / characters / scenes / videos 四个阶段当成四次运行
- 最小前端冒烟测试已经接入基线：
  - 模板拼装输出测试
  - `renderInto()` 不重绘测试

仍然需要你后续根据自己的账号和接口实际情况补强：

- Seedance 硬字幕不稳定时的 ffmpeg 烧字兜底
- 视频预算控制，例如限制短篇不要拆出过多片段
- 多角色同屏时更强的人脸 / 服装锁定
- 真正的声纹级 voice cloning 或固定 speaker embedding
- 对象存储、持久化队列

## 文档

- [docs/architecture.md](/Users/xy/StoryForge/docs/architecture.md)
- [docs/tech-stack.md](/Users/xy/StoryForge/docs/tech-stack.md)
- [docs/usage.md](/Users/xy/StoryForge/docs/usage.md)
- [docs/api.md](/Users/xy/StoryForge/docs/api.md)
- [docs/development.md](/Users/xy/StoryForge/docs/development.md)
- [docs/status.md](/Users/xy/StoryForge/docs/status.md)

## Git 与目录卫生

当前仓库已经完成首轮卫生处理：

- 已初始化 Git 仓库
- `.env`、`.venv/`、`outputs/`、`workspace/`、缓存目录都已加入忽略规则
- 已提供提交前检查脚本 `scripts/check.sh`
- 已提供本地清理脚本 `scripts/clean-local-artifacts.sh`

说明：

- `outputs/`、`workspace/`、`.venv/` 默认只忽略，不会被保守清理误删
- 你可以随时用 `--deep` 做深度清理
