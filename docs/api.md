# API 文档

## 1. 服务启动

```bash
uv run storyforge api serve --host 0.0.0.0 --port 8000 --reload
```

启动后默认接口文档地址：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

其中：

- `/` 是浏览器 Web 控制台
- `/docs` 是 Swagger 文档
- `/redoc` 是 ReDoc 文档

## 2. 路由概览

### `GET /health`

健康检查。

返回：

```json
{
  "status": "ok"
}
```

### `POST /v1/projects/novel`

提交第一步“生成小说”任务。

现在支持两种模式：

- 不传 `project_id`：后端自动新建项目，并返回新的 `project_id`
- 传 `project_id`：把这次运行挂到已有项目下，作为该项目的新一轮 run

请求体：

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

返回：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_id": "f1b7e7ba-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

### `POST /v1/projects/characters`

提交第二步“生成角色图”任务。这个阶段会基于已有小说 run 调用 Seedream，生成角色定妆图，并写回后续场景图所需的参考图状态。

请求体：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

### `POST /v1/projects/scenes`

提交第三步“生成场景图”任务。这个阶段会复用同一个 story run 输出目录，并要求角色图已经存在，随后生成场景首尾帧与更新后的 Seedance manifest。

请求体：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

### `POST /v1/projects/videos`

提交第四步“生成视频”任务。这个阶段会复用同一个 story run 的输出目录，要求场景首尾帧已齐备，然后调用 Seedance 生成片段并在成功后尝试 ffmpeg 合并总片。

请求体：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id"
}
```

### `POST /v1/projects/novel-to-video`

兼容旧的一键全链路接口。

它仍然可用，主要给旧脚本或测试使用。新的 Web 控制台默认改成四步手动推进。

### `POST /v1/projects/images`

兼容旧的“图片一口气生成”接口。

它会连续执行角色图和场景图两步，主要给旧脚本或测试使用。新的 Web 控制台默认改成更细的四步手动推进。

### `GET /v1/projects`

列出所有持久化项目。

### `GET /v1/projects/{project_id}`

返回单个项目详情，包括：

- 项目基础信息
- 项目级 `brief`
- 属于该项目的全部历史任务
- 最近一次运行状态
- 总运行次数、完成次数、失败次数、总片次数

### `GET /v1/tasks`

列出所有任务。

### `GET /v1/tasks/{task_id}`

查询指定任务状态。

返回示例：

```json
{
  "task_id": "f1b7e7ba-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_type": "project.story",
  "status": "completed",
  "created_at": "2026-04-09T00:00:00+00:00",
  "started_at": "2026-04-09T00:00:01+00:00",
  "finished_at": "2026-04-09T00:00:03+00:00",
  "result": {
    "output_dir": "/path/to/outputs/雾港回声",
    "novel_package_path": "/path/to/novel_package.json",
    "pipeline_root_task_id": "f1b7e7ba-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "task_stage": "story"
  },
  "error": null
}
```

### `GET /v1/tasks/{task_id}/artifacts`

返回页面预览所需的结构化产物索引，包括：

- 根目录文档文件
- 章节 Markdown
- 角色图
- 场景首尾帧
- 视频片段
- 总片 `full_story.mp4`

### `GET /v1/ui/bootstrap`

返回 Web 控制台默认表单值，以及当前启用的模型名。

## 3. 任务生命周期

### `queued`

任务已入队，等待 worker 执行。

### `running`

任务执行中。

### `completed`

任务执行完成，结果路径在 `result` 中。

### `failed`

任务执行失败，错误信息在 `error` 中。

## 4. 当前实现限制

- 项目与任务元数据现在支持两种持久化方式：
  - 本地 `workspace/state/`
  - MySQL `projects` / `tasks`
- 真正的分布式队列还没有接入。
- 还没有认证。
- 新的四步接口会在第二步、第三步、第四步分别直接尝试真实调用 Seedream / Seedance。
- 旧的 `/v1/projects/novel-to-video` 仍支持用 `submit_seedance` 控制是否只跑到 manifest。

## 5. 建议的生产化改造

1. 给任务系统加真正的持久化执行队列
2. 给 API 加认证和项目隔离
3. 加 webhook / 回调机制
4. 给 Seedance 增加更稳的失败重试、超时恢复和字幕兜底
