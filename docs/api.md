# API 文档

这份文档描述 StoryForge 当前可用的 HTTP 接口。  
默认服务基于 `FastAPI`，接口文档也可在运行时通过 Swagger 查看。

## 启动服务

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000 --reload
```

默认入口：

- `http://127.0.0.1:8000/`：Web 控制台
- `http://127.0.0.1:8000/docs`：Swagger
- `http://127.0.0.1:8000/redoc`：ReDoc

## 接口分组

### 健康检查

#### `GET /health`

返回：

```json
{
  "status": "ok"
}
```

### UI

#### `GET /`

返回浏览器端工作台页面。

#### `GET /ui`

与 `/` 相同。

#### `GET /v1/ui/bootstrap`

返回前端启动所需的默认配置和模型名。

### 项目

#### `GET /v1/projects`

列出所有项目摘要。

#### `GET /v1/projects/{project_id}`

返回单个项目详情，包括：

- 项目基础信息
- 项目 brief
- 关联任务
- 最近一次运行摘要

#### `POST /v1/projects/novel`

创建“生成小说”任务。

请求示例：

```json
{
  "project_id": null,
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
  "use_llm": true
}
```

说明：

- `project_id = null` 时会自动新建项目
- 传入已有 `project_id` 时，会把本次运行挂到已有项目下

返回示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

#### `POST /v1/projects/characters`

创建“生成角色图”任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "use_llm": true
}
```

#### `POST /v1/projects/scenes`

创建“生成场景图”任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

#### `POST /v1/projects/videos`

创建“生成视频”任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

#### `POST /v1/projects/images`

兼容接口。会连续执行“角色图 + 场景图”两步。

#### `POST /v1/projects/novel-to-video`

兼容接口。会一口气执行整条链路。

### 任务

#### `GET /v1/tasks`

列出所有任务。

#### `GET /v1/tasks/{task_id}`

查询单个任务状态。

返回示例：

```json
{
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_type": "project.story",
  "status": "completed",
  "created_at": "2026-04-12T00:00:00+00:00",
  "started_at": "2026-04-12T00:00:01+00:00",
  "finished_at": "2026-04-12T00:00:03+00:00",
  "result": {
    "output_dir": "/path/to/output",
    "novel_package_path": "/path/to/novel_package.json"
  },
  "error": null
}
```

#### `GET /v1/tasks/{task_id}/artifacts`

返回用于页面展示的产物索引，包括：

- 根目录文档文件
- 章节 Markdown
- 角色图
- 场景帧
- 视频片段
- 总片

## 任务状态

- `queued`
- `running`
- `completed`
- `failed`

## 当前约束

- 执行队列目前仍是内存态
- 认证和权限尚未接入
- 对象存储尚未接入
- `Seedream` / `Seedance` 的 provider contract 仍可能因账户环境不同而需要微调

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [架构文档](architecture.md)
