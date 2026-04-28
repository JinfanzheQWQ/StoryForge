# API 说明

默认服务地址：`http://127.0.0.1:8000`

## 健康检查

### `GET /health`

返回：

```json
{
  "status": "ok"
}
```

## UI

### `GET /`

返回 Web 工作台。

### `GET /ui`

返回 Web 工作台。

### `GET /v1/ui/bootstrap`

返回前端启动配置，包括默认 LLM provider、模型名、水印默认值和连续性审阅模式。

## 项目

### `GET /v1/projects`

返回项目摘要列表。

### `GET /v1/projects/{project_id}`

返回项目详情、brief、任务列表和最近 run 摘要。

### `DELETE /v1/projects/{project_id}`

删除项目、任务记录和该项目输出目录。

如果项目不存在返回 `404`。如果存在排队中或运行中的任务返回 `409`。

## 生成小说

### `POST /v1/projects/novel`

创建小说正文任务。

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
  "llm_model": "deepseek-chat",
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

返回：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

## 生成场景结构

### `POST /v1/projects/scene-structure`

基于 `story_source.json` 生成小说包、故事记忆、角色视觉设定和 scene 结构。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "story-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

主要输出：

- `novel_package.json`
- `story_memory.json`
- `character_visual_bible.json`
- `scene_plan.json`
- `continuity_report.json`

## 生成分段合同

### `POST /v1/projects/segment-contracts`

基于 `scene_plan.json` 生成 chunk、segment、motion contract 和媒体任务清单。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "scene-structure-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

主要输出：

- `segment_plan.json`
- `segment_contract_progress.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`

## 角色图

### `POST /v1/projects/characters`

生成全部角色图，或根据请求重做指定角色。

常用请求：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "use_llm": true,
  "seedream_watermark": false
}
```

### `PUT /v1/projects/{project_id}/character-prompts/{source_task_id}/{character_name}`

保存单个角色的角色图 prompt。

请求示例：

```json
{
  "portrait_prompt": "原创虚构角色白底三视图，单角色，非真人摄影。..."
}
```

保存 prompt 不会自动重做图片。

## 场景母图

### `POST /v1/projects/scenes`

生成全部场景母图，或根据请求重做指定 scene / segment 对应的场景母图。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "use_llm": true,
  "seedream_watermark": false
}
```

场景母图请求会使用当前 prompt 和可用的空间连续性参考图。输出写入 `scene_image_manifest.json` 和相关 scene / segment 字段。

## 视频

### `POST /v1/projects/videos`

生成全部视频，或根据请求生成指定 segment 的视频。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "segment_id": "ch01-sc01-seg01",
  "use_llm": true,
  "seedance_watermark": false
}
```

提交前系统会检查：

- 当前 segment 有可用场景母图。
- 当前 segment 实际出镜角色都有可用角色图。
- 当前 segment 有可提交的视频 prompt。

Seedance 请求中的参考图顺序写入 `submitted_reference_bindings`。如果上一段视频返回了可用尾帧，且当前片段需要承接，绑定列表会包含该尾帧作为开场时间锚点。

## Prompt

### `PUT /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}`

保存当前 segment 的媒体 prompt。

请求字段：

```json
{
  "scene_master_frame_prompt": "场景母图 prompt",
  "video_prompt": "Seedance 视频 prompt"
}
```

可以只提交其中一个字段。保存后会同步相关规划文件和 manifest；不会自动提交媒体任务。

### `POST /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset`

按当前合同重新生成默认 prompt。

请求示例：

```json
{
  "fields": ["scene_master_frame_prompt", "video_prompt"]
}
```

## 任务

### `GET /v1/tasks/{task_id}`

查询任务状态。

返回字段包含：

- `task_id`
- `project_id`
- `stage`
- `status`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `error`
- `result`

### `GET /v1/tasks/{task_id}/artifacts`

返回当前 run 的工作台聚合数据。

主要内容：

- 小说正文。
- scene 列表。
- segment 列表。
- 角色图。
- 场景母图。
- 视频状态和预览地址。
- motion plan。
- prompt。
- request payload。
- reference bindings。
- 风险和失败原因。

前端项目详情页主要消费这个接口。

## 合并视频

### `POST /v1/projects/{project_id}/merge-videos`

合并当前 run 已完成的视频片段。

返回合并任务 `task_id`。合并结果写入 `rendered/full_story.mp4`。
