# API 文档

这份文档描述 StoryForge 当前可用的 HTTP 接口。  
默认服务基于 `FastAPI`，接口文档也可在运行时通过 Swagger 查看。

这里主要记录 HTTP contract，不重复安装、完整操作流程或系统分层：

- 安装与使用步骤：看 [usage.md](usage.md)
- 系统分层与模块边界：看 [architecture.md](architecture.md)
- 当前完成度与路线图：看 [status.md](status.md)

## 启动服务

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

默认入口：

- `http://127.0.0.1:8000/`：Web 控制台
- `http://127.0.0.1:8000/docs`：Swagger
- `http://127.0.0.1:8000/redoc`：ReDoc

说明：`--reload` 适合调前端和接口，不适合跑 Seedream / Seedance 长任务。长任务联调建议使用无热重载启动方式。
启动前必须保证 MySQL 已可连接，否则应用不会完成启动。

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

说明：

- 前端创建页只允许选择 `llm_provider`
- `llm_model` 仍会由后端和 bootstrap 返回，但页面中的模型 ID 为只读默认值，不允许手工编辑

### 项目

#### `GET /v1/projects`

列出所有项目摘要。

#### `GET /v1/projects/{project_id}`

返回单个项目详情，包括：

- 项目基础信息
- 项目 brief
- 关联任务
- 最近一次运行摘要

#### `DELETE /v1/projects/{project_id}`

删除项目元数据和该项目下的任务记录。

行为约定：

- 如果项目不存在，返回 `404`
- 如果项目下仍有 `queued` 或 `running` 任务，返回 `409`
- 删除成功后，`GET /v1/projects/{project_id}` 和相关 `GET /v1/tasks/{task_id}` 会返回 `404`
- 会同步删除任务结果记录过的 `output_dir`
- 文件删除有安全边界：只允许删除配置 `paths.output_dir` 下的项目产物目录，不会删除输出根目录本身或外部路径

返回示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "deleted": true,
  "deleted_task_count": 5,
  "deleted_output_count": 1,
  "deleted_output_paths": [
    "/path/to/StoryForge/outputs/story-title"
  ],
  "skipped_output_paths": []
}
```

#### `POST /v1/projects/novel`

创建“生成小说正文”任务。

这一步只会生成可编辑的 `story_source`，不会直接产出 `novel_package.json`。

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
  "use_llm": true,
  "llm_provider": "deepseek",
  "llm_model": "deepseek-chat"
}
```

说明：

- `project_id = null` 时会自动新建项目
- 传入已有 `project_id` 时，会把本次运行挂到已有项目下
- Web 页面的 `llm_model` 为只读默认值；如通过 API 直调，仍可显式传入

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
  "use_llm": true,
  "llm_provider": "openai",
  "llm_model": "gpt-5.4"
}
```

说明：

- 如果 `llm_provider = openai` 但你的 `OPENAI_BASE_URL` 背后平台没有 `gpt-5.4` 映射，任务会直接失败，并返回类似 `platform text model target not found`
- `Cast Analyzer` 的 `source_evidence` 仍必须能在正文中定位；当前后端会对“带修饰语的人名或稳定称呼”做容错匹配，但不会放过正文中根本不存在的人物
- 这一步依赖已经完成且未过期的 `project.story_analysis`
- 前端默认仍传入根 story task 的 `source_task_id`，因为分析结果会回写到同一条 run 根任务上

#### `POST /v1/projects/story-analysis`

创建“生成结构化信息”任务。

这一步会基于当前 `story_source.json` 生成：

- `novel_package.json`
- `novel_audit.json`

其中：

- `novel_package.json` 是运行态最小包
- `novel_audit.json` 保存 `review`、`workflow_trace` 和分析上下文

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
  "source_task_id": "story-task-id",
  "segment_id": "ch01_seg01"
}
```

说明：

- `segment_id` 可选
- 不传时表示沿用旧的整批执行方式
- 传入后表示只生成单个 segment 的首帧 / 中段锚点帧 / 尾帧
- 对同一 `source_task_id + segment_id`，如果已经有 queued / running 任务，后端会直接返回已有任务

#### `POST /v1/projects/videos`

创建“生成视频”任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "segment_id": "ch01_seg01"
}
```

说明：

- `segment_id` 可选
- `merge_only` 可选
- 传入 `segment_id` 后只会提交该片段对应的 Seedance clip
- 单段执行不会自动重新生成其它片段，也不会自动拼接总片
- 如果传 `merge_only = true`，则不会再向 Seedance 提交任务，而是把当前已生成的本地 mp4 片段按 manifest 顺序合并成 `rendered/full_story.mp4`

手动合并请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "merge_only": true
}
```

#### `POST /v1/projects/images`

兼容接口。会连续执行“角色图 + 场景图”两步。

#### `GET /v1/projects/{project_id}/story-source/{source_task_id}`

读取某个 story run 当前的可编辑小说正文。

#### `PUT /v1/projects/{project_id}/story-source/{source_task_id}`

更新某个 story run 的小说正文。

更新后会：

- 重写 `story_source.json`
- 清除旧的 `novel_package.json`、`novel_audit.json`、角色图、场景图、视频等派生产物
- 让前端把结构化信息与媒体阶段视为“待重新生成”

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
    "story_source_path": "/path/to/story_source.json",
    "story_source_revision": "2026-04-13T10:00:00+00:00"
  },
  "error": null
}
```

说明：

- `error` 为失败时的可展示原因，前端会直接展示它。
- 阶段任务会通过 `result.pipeline_root_task_id` 指向同一条 story run。
- `result.story_source_revision` 用于判断结构化信息、图片和视频是否仍对应当前正文。

#### `GET /v1/tasks/{task_id}/artifacts`

返回用于页面展示的产物索引，包括：

- 根目录文档文件
- 角色图
- 场景帧
- 视频片段
- 总片
- `planned_segments`

其中 `planned_segments` 会直接来自 `segment_plan.json`，并带上每个 segment 当前对应的：

- `start_frame`
- `mid_frame`
- `end_frame`
- `rendered_clip`
- `scene_ready`
- `video_ready`

前端会根据这份索引直接渲染逐段时间线，即使某个片段还没有实际产物，也会先展示出来等待单独触发。

## 任务状态

- `queued`
- `running`
- `completed`
- `failed`

服务启动时会扫描上次残留的 `running` 任务，并把它们重新放回 `queued` 等待执行；不会再因为一次服务重启直接写成失败。

## 当前约束

这里仅保留和 API 行为直接相关的运行约束：

- 执行队列目前仍是进程内异步队列
- 服务重启后，残留 `running` 任务会重新排回 `queued`
- 重启后的重新排队不是生产级幂等队列；真实生产环境仍应替换成 Redis / Celery / Arq / TaskIQ 等持久化队列

更完整的系统限制与生产路线图见：[status.md](status.md)

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [架构文档](architecture.md)
