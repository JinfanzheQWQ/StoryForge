# API 文档

这份文档描述 StoryForge 的 HTTP 接口。
默认服务基于 `FastAPI`，接口文档也可在运行时通过 Swagger 查看。

这里主要记录 HTTP contract，不重复安装、完整操作流程或系统分层：

- 安装与使用步骤：看 [usage.md](usage.md)
- 系统分层与模块边界：看 [architecture.md](architecture.md)
- 产品状态：看 [status.md](status.md)

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
- `llm_model` 会由后端和 bootstrap 返回，但页面中的模型 ID 为只读默认值，不允许手工编辑
- 同时会返回默认的 `continuity_review_mode`，默认值为 `auto`
- 同时会返回 `seedream_watermark` 与 `seedance_watermark` 默认值，供前端决定本次 run 是否保留图片 / 视频水印

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
  "llm_model": "deepseek-chat",
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

说明：

- `project_id = null` 时会自动新建项目
- 传入已有 `project_id` 时，会把本次运行挂到已有项目下
- Web 页面的 `llm_model` 为只读默认值；如通过 API 直调，仍可显式传入
- `continuity_review_mode` 可选 `off / auto / on`，用于控制后续 `continuity_report.json` 是否执行 LLM 软审校
- `seedream_watermark` 控制后续 Seedream 生图是否保留水印
- `seedance_watermark` 控制后续 Seedance 生视频是否保留水印

返回示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "task_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

#### `POST /v1/projects/scene-structure`

创建“生成场景结构”任务。

这一步会基于 `story_source.json` 生成：

- `novel_package.json`
- `novel_audit.json`
- `story_memory.json`
- `character_visual_bible.json`
- `scene_plan.json`

其中：

- `scene_plan.json` 在场景结构阶段保存 `chapter -> scene` skeleton、`scene_transition_contract`、`scene_bible` 和 `scene_master_frame` 相关字段
- 每个 scene 还会带 `covered_event_ids` 与紧凑版 `covered_event_summaries`，用于显式标记它覆盖了目标章节的哪些 must-cover 关键事件，以及后续 chunk planner 应聚焦的事件摘要
- 还不会生成正式 `segment contracts`、`segment_plan.json`、`scene_image_manifest.json` 或 `seedance_manifest.json`

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

说明：

- `continuity_review_mode` 会跟随任务记录保留下来，供后续 `project.segment_contracts`、`project.scenes`、`project.videos` 继承
- `seedream_watermark / seedance_watermark` 可选；如果不传，后续阶段会继承本次 run 根任务上的设置
- 幂等去重会按 `source_task_id + story_source_revision + continuity_review_mode + watermark 组合` 复用已有 queued / running / completed 任务

#### `PUT /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}`

保存工作台里人工修改后的媒体 prompt。接口只更新本次 run 的规划文件，不会自动提交 Seedream 或 Seedance 任务。

请求字段：

- `scene_master_frame_prompt`：场景母图 prompt；提交后会同步到同一 scene 的场景图任务
- `video_prompt`：Seedance 视频 prompt；修改后会清空该段旧视频提交状态和本地旧 mp4，下一次手动生成视频会使用新 prompt

落盘范围：

- `segment_plan.json`
- `scene_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`

响应会返回更新后的字段名、当前 prompt 和被同步的文件路径。

#### `POST /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset`

按当前 segment 合同重新生成默认 prompt。支持字段：

- `scene_master_frame_prompt`
- `video_prompt`

重置只回写 prompt，不自动提交媒体任务。

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
- 阶段任务会在提交时继承 `pipeline_root_task_id`，并通过 `payload.pipeline_root_task_id` 与 `result.pipeline_root_task_id` 指向同一条 story run。
- `result.story_source_revision` 用于判断场景结构、分段合同、图片和视频是否仍对应当前正文。
- `project.segment_contracts` 的 `result` 可能额外带 `segment_contract_progress_path` 与 `segment_contract_progress`
- `segment_contract_progress` 会包含 `status / total_chapters / total_scenes / total_chunks / completed_chapters / completed_scene_count / completed_chunk_count / failed_chapter_number / failed_scene_id / failed_chunk_id / resume_ready / chapters[]`
- `chapters[].scenes[]` 下会继续带 `chunks[]`、`running_chunk_id`、`failed_chunk_id`
- 分段合同失败时，`error` 会尽量带上 `chapter / scene_id / chunk_id` 上下文，前端可直接展示失败位置
- `project.scenes` 可带 `scene_id`，表示重跑该 scene 的场景母图；场景母图重生成任务会带 `master_only = true`
- `project.videos` 可直接带 `scene_id`，表示重跑该 scene 下全部视频片段
- `project.continuity_repair` 可带 `segment_id` 或 `scene_id`
- `project.continuity_repair_batch` 用于按风险优先级批量回写连续性合同，不会自动重跑媒体
- `project.continuity_repair` 当前是 `plan-only`；任务会停在 `continuity_repair_plan_completed`，随后由任务状态本身转为 `completed`
- `project.continuity_repair_batch` 当前也统一是 `plan-only`；任务会停在 `continuity_repair_batch_completed`，随后由任务状态本身转为 `completed`
- 如果目标没有问题可修，修复任务会以 `completed noop` 结束，不会报失败
- 修复任务的 `result` 会额外带 `repair_execution_mode`、`media_regeneration_required` 和 `pending_media_actions`
- `scene_id` 修复任务的 `result` 还会额外带 `selection_mode` 与 `affected_segment_ids`，用于解释本次修复是局部联动还是整 scene 方案
- `project.continuity_repair_batch` 的 `result` 还会额外带 `processed_unit_count`、`repaired_unit_count`、`noop_unit_count`、`failed_unit_count`、`remaining_repairable_count` 与 `has_more_batches`
- 如果任务或其根 run 开启了 LLM 软审校，`payload` / `result` 里会带 `continuity_review_mode`

#### `GET /v1/tasks/{task_id}/artifacts`

返回用于页面展示的产物索引，包括：

- 根目录文档文件
- 角色图
- 场景帧
- 视频片段
- 总片
- `planned_segments`
- `continuity_report`
- `continuity_summary`
- `continuity_scene_groups`
- `continuity_segment_groups`

其中 `character_images` 除了基础的 `name / path / url / kind` 外，还会额外返回来自 `character_image_manifest.json` 的：

- `character_name`
- `prompt`
- `consistency_notes`
- `provider`
- `status`
- `image_kind`
- `error`

其中 `planned_segments` 会优先来自 `scene_plan.json`，并回落到 `segment_plan.json`。接口会带上每个 segment 对应的：

- `scene_id`
- `scene_title`
- `scene_summary`
- `scene_anchor`
- `scene_bible`
- `scene_transition_contract`
- `scene_master_frame_status`
- `scene_master_frame_error`
- `covered_event_ids`
- `covered_event_summaries`
- `scene_master_frame`
- `scene_master_frame_prompt`
- `video_prompt`
- `submitted_video_prompt`
- `submitted_prompt_variant`
- `submitted_reference_bindings`
- `motion_plan`
- `motion_contract`
- `seedance_motion_prompt`
- `scene_master_frame_request`
- `video_request`
- `diagnostics`
- `character_references`
- `rendered_clip`
- `scene_ready`
- `video_ready`

说明：

- `scene_master_frame` 是当前 scene 的环境参考图。
- `character_references` 是当前 segment 实际出镜角色的定妆图列表。
- `video_prompt` 是分段合同阶段落盘的基础视频 prompt。
- `motion_plan` 返回目标 segment 的画面推进合同，字段包括 `scene_motion / beat_progression / camera_path / character_motion / continuity_guard`。
- `seedance_motion_prompt` 返回最终 Seedance prompt 中的参考图绑定与画面推进摘录。
- `submitted_reference_bindings` 会返回实际送往 Seedance 的参考图绑定顺序，也就是 `图片1=场景母图，图片2+=角色图`。
- `scene_master_frame_request / video_request` 会返回真实提交时的 `provider / endpoint / variant / payload / reference_bindings`。
- `diagnostics` 由后端统一生成，用于前端展示规划状态，包含 `status / risk_type / risk_types / action_node_count / action_node_budget / duration_auto_expanded_from / duration_seconds / timed_beat_count / timed_beat_end_seconds / missing_tail_seconds / subsegment_index / subsegment_count / repair_source / planner_warning_source`。
- `duration_auto_expanded_from` 只有源计划真实记录扩秒前时长时才有值，否则为 `null`；接口不会推断或伪造扩秒前时长。
- `planner_warning_source` 可能为 `action_capacity / timed_beats / subsegment_split` 或空字符串。

前端会根据这份索引直接渲染逐段时间线，即使某个片段还没有实际产物，也会先展示出来等待单独触发。

如果某个片段执行过智能修复，`documents` 里还可能出现：

- `continuity_repair_{segment_id}.json`
- `continuity_repair_{scene_id}.json`

`continuity_summary` 会返回：

- `status`
- `report_version`
- `generated_at`
- `review_mode_requested`
- `review_mode_effective`
- `v2_review_status`
- `v2_issue_count`
- `v2_note`
- `issue_count`
- `high_risk_count`
- `medium_risk_count`
- `low_risk_count`
- `scene_issue_count`
- `segment_issue_count`
- `recommended_actions`
- `top_issues`

`continuity_scene_groups` 与 `continuity_segment_groups` 会把 `continuity_report.json` 里的问题明细按 `scene` / `segment` 聚合后返回。每组包含：

- `scope`
- `scene_id`
- `segment_id`
- `issue_count`
- `high_risk_count`
- `medium_risk_count`
- `low_risk_count`
- `recommended_actions`
- `issues`

其中 `issues` 里的每一项会带：

- `severity`
- `scope`
- `code`
- `message`
- `scene_id`
- `segment_id`
- `recommended_action`
- `recommended_action_label`
- `details`

## 任务状态

- `queued`
- `running`
- `completed`
- `failed`

服务启动时会扫描上次残留的 `running` 任务，并把它们重新放回 `queued` 等待执行；不会因为一次服务重启直接写成失败。

## 运行约束

这里仅保留和 API 行为直接相关的运行约束：

- 执行队列目前仍是进程内异步队列
- 服务重启后，残留 `running` 任务会重新排回 `queued`
- 重启后的重新排队不是生产级幂等队列；真实生产环境仍应替换成 Redis / Celery / Arq / TaskIQ 等持久化队列

更完整的系统限制见：[status.md](status.md)

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [架构文档](architecture.md)
