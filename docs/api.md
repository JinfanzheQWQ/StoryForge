# API 说明

默认后端地址：`http://127.0.0.1:8000`

FastAPI 只提供 API、健康检查和 `/outputs` 媒体访问。React 前端通过这些接口调度项目生产。

## 通用返回

阶段任务提交成功返回：

```json
{
  "project_id": "project-id",
  "task_id": "task-id",
  "status": "queued"
}
```

常见任务状态：

- `queued`
- `running`
- `completed`
- `failed`

## 健康检查

### `GET /health`

```json
{
  "status": "ok"
}
```

## 项目

### `GET /v1/projects`

返回项目摘要列表。

### `GET /v1/projects/{project_id}`

返回项目详情、brief、任务列表和 run 摘要。

### `DELETE /v1/projects/{project_id}`

删除项目记录、任务记录和项目输出目录。

如果项目不存在返回 `404`。如果项目存在排队中或运行中的任务返回 `409`。

## 小说任务

### `POST /v1/projects/novel`

创建小说正文任务。`project_id` 可以为空，后端会创建新项目。

请求示例：

```json
{
  "project_id": null,
  "brief": {
    "title_hint": "傍晚的花园",
    "idea": "大学校园里，一个男生在花田边准备向喜欢的人表白。",
    "genre": "校园情感",
    "tone": "清新、温柔、电影感",
    "target_audience": "年轻观众",
    "chapter_count": 1,
    "total_word_target": 1500,
    "must_include": ["花田", "信纸"],
    "style_keywords": ["青春", "傍晚", "微风"]
  },
  "use_llm": true,
  "llm_provider": "deepseek",
  "llm_model": "deepseek-chat",
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

## 正文真源

### `GET /v1/projects/{project_id}/story-source/{source_task_id}`

读取可编辑正文真源。

返回示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "task-id",
  "story_title": "傍晚的花园",
  "story_source_revision": "revision",
  "chapters": [
    {
      "number": 1,
      "title": "第一章",
      "summary": "章节摘要",
      "markdown": "章节正文"
    }
  ]
}
```

### `PUT /v1/projects/{project_id}/story-source/{source_task_id}`

保存正文真源。

请求示例：

```json
{
  "story_title": "傍晚的花园",
  "chapters": [
    {
      "number": 1,
      "title": "第一章",
      "summary": "章节摘要",
      "markdown": "章节正文"
    }
  ]
}
```

保存后会更新 `story_source_revision`，后续结构和媒体阶段需要基于新正文重新生成。

## 场景结构

### `POST /v1/projects/scene-structure`

基于正文真源生成小说包、故事记忆、角色视觉设定和 scene 结构。

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

## 分段合同

### `POST /v1/projects/segment-contracts`

基于 scene 结构生成 chunk、segment、motion plan 和媒体任务清单。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "scene-structure-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "resume_from_progress": false,
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

主要输出：

- `segment_plan.json`
- `segment_contract_progress.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`

`resume_from_progress=true` 只适用于分段合同阶段，用于从失败进度继续生成。

## 连续性修复

### `POST /v1/projects/continuity-repair`

修复单个 scene 或 segment 的连续性合同。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "segment_id": "ch01-sc01-seg01",
  "use_llm": true,
  "continuity_review_mode": "auto"
}
```

`segment_id` 和 `scene_id` 必须二选一。

### `POST /v1/projects/continuity-repair-batch`

批量修复连续性问题。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "severity_threshold": "medium",
  "max_units_per_batch": 4
}
```

## 角色图

### `POST /v1/projects/characters`

生成全部角色图，或重做指定角色。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "character_name": "林屿",
  "use_llm": true,
  "seedream_watermark": false
}
```

`character_name` 为空时生成全部角色图。

### `PUT /v1/projects/{project_id}/character-prompts/{source_task_id}/{character_name}`

保存单个角色图 prompt。

请求示例：

```json
{
  "prompt": "原创虚构角色白底三视图，单角色，非真人摄影。..."
}
```

### `POST /v1/projects/{project_id}/character-images/{source_task_id}/{character_name}/select`

选择正式图或候选图。

请求示例：

```json
{
  "version": "candidate"
}
```

`version` 可取 `current` 或 `candidate`。

## 场景母图

### `POST /v1/projects/scenes`

生成全部场景母图，或重做指定 scene 的母图。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "scene_id": "ch01-sc01",
  "master_only": true,
  "use_llm": true,
  "seedream_watermark": false
}
```

`scene_id` 为空时生成全部场景母图。

## 视频

### `POST /v1/projects/videos`

生成视频片段或合并总片。

生成单段视频：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "segment_id": "ch01-sc01-seg01",
  "use_llm": true,
  "seedance_watermark": false
}
```

合并视频：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "merge_only": true
}
```

视频提交前会检查场景母图、角色图和视频 prompt 是否可用。真实参考图顺序写入 `submitted_reference_bindings`。

## Segment Prompt

### `PUT /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}`

保存 segment 的媒体 prompt。

请求示例：

```json
{
  "scene_master_frame_prompt": "场景母图 prompt",
  "video_prompt": "Seedance 视频 prompt"
}
```

可以只提交其中一个字段。保存不会自动提交媒体任务。

### `POST /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset`

按当前合同恢复默认 prompt。

请求示例：

```json
{
  "field": "video_prompt"
}
```

`field` 可取 `scene_master_frame_prompt` 或 `video_prompt`。

## 任务

### `GET /v1/tasks`

返回任务列表。

### `GET /v1/tasks/{task_id}`

查询单个任务状态。

### `GET /v1/tasks/{task_id}/artifacts`

返回当前 run 的工作台聚合数据。前端项目工作台主要消费这个接口。

聚合内容包括：

- 小说、scene 和 segment 蓝图。
- 角色图、场景母图和视频资源。
- motion plan、prompt 和请求 payload。
- reference bindings。
- 连续性问题和失败原因。
- 合并总片。
