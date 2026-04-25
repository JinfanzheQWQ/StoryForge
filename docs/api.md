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
- `llm_model` 会由后端和 bootstrap 返回，但页面中的模型 ID 为只读默认值，不允许手工编辑
- 同时会返回默认的 `continuity_review_mode`，当前默认值为 `auto`
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
- `continuity_review_mode` 可选 `off / auto / on`，用于控制后续 `continuity_report.json` 是否执行 `V2` LLM 软审校
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

这一步会基于当前 `story_source.json` 生成：

- `novel_package.json`
- `novel_audit.json`
- `story_memory.json`
- `character_visual_bible.json`
- 第一版 `scene_plan.json`

其中：

- `scene_plan.json` 这时只保存 `chapter -> scene` skeleton、`scene_transition_contract`、`scene_bible` 和 `scene_master_frame` 相关字段
- 每个 scene 还会带 `covered_event_ids` 与紧凑版 `covered_event_summaries`，用于显式标记它覆盖了当前章节的哪些 must-cover 关键事件，以及后续 chunk planner 应聚焦的事件摘要
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
- `seedream_watermark / seedance_watermark` 可选；如果不传，后续阶段会继承当前 run 根任务上的设置
- 幂等去重会按 `source_task_id + story_source_revision + continuity_review_mode + watermark 组合` 复用已有 queued / running / completed 任务

#### `PUT /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}`

保存工作台里人工修改后的媒体 prompt。接口只更新当前 run 的规划文件，不会自动提交 Seedream 或 Seedance 任务。

请求字段：

- `start_frame_prompt`：首帧生图 prompt
- `mid_frame_prompt`：中段锚点帧生图 prompt
- `end_frame_prompt`：尾帧生图 prompt
- `video_prompt`：Seedance 视频 prompt；修改后会清空该段旧视频提交状态和本地旧 mp4，下一次手动生成视频会使用新 prompt
- `scene_master_frame_prompt`：场景母图 prompt；提交后会同步到同一 scene 的场景图任务

落盘范围：

- `segment_plan.json`
- `scene_plan.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`

响应示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "task-id",
  "segment_id": "ch01-sc01-seg01",
  "updated_fields": ["start_frame_prompt", "video_prompt"]
}
```

#### `POST /v1/projects/{project_id}/segment-prompts/{source_task_id}/{segment_id}/reset`

重置当前 segment 的单个媒体 prompt。接口会基于当前 segment 合同重新组装系统默认 prompt 并回写计划文件，不会自动提交 Seedream 或 Seedance。

请求字段：

- `field`：只能是 `start_frame_prompt / mid_frame_prompt / end_frame_prompt / video_prompt`

落盘规则：

- 图片 prompt 会回写 `segment_plan.json` 与 `scene_image_manifest.json`
- 视频 prompt 会回写 `segment_plan.json` 与 `seedance_manifest.json`，并清空该段旧视频提交状态和本地旧 mp4

响应示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "task-id",
  "segment_id": "ch01-sc01-seg01",
  "updated_fields": ["video_prompt"],
  "reset_field": "video_prompt",
  "prompt": "请生成带原生音频的中文剧情短视频片段..."
}
```

#### `POST /v1/projects/segment-contracts`

创建“生成分段合同”任务。

这一步依赖已经完成且未过期的 `project.scene_structure`，并会在已有 scene skeleton 的基础上继续生成：

- `character_image_manifest.json`
- `scene_structure_source.json`
- 最终版 `scene_plan.json`
- `segment_plan.json`
- `segment_contract_progress.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `continuity_report.json`

其中：

- 最终版 `scene_plan.json` 是场景级主规划文件，保存 `chapter -> scene -> segment`
- stage2 把 scene skeleton 重建成最终 `scene_plan.json` 时，会保留 scene 级 `scene_transition_contract` 与 `covered_event_summaries`
- 每个 scene 的首个 chunk / 首个 segment 都会消费 `scene_transition_contract`，把跨 scene 承接落到 `opening_match / timed_beats`
- `Scene Chunk Planner` 的 prompt 与结构化校验都会读取当前 scene 绑定的 `covered_event_summaries`，提前拦截把后续 scene 关键推进写进当前 scene 的越界 chunk
- `segment_plan.json` 是 flat 执行索引，供逐段生成、重试和任务映射使用；每个 segment 会继承所属 scene 的 `scene_bible`，并带 `shot_state`、`continuity_link` 与 `motion_plan`
- `continuity_report.json` 的 `V1` 还会直接输出 scene 边界风险，例如 `scene_transition_exit_state_drift / scene_transition_entry_weak / scene_transition_bridge_not_consumed`
- `scene_structure_source.json` 是恢复专用的原始 scene skeleton 快照
- `segment_contract_progress.json` 会按 `chapter -> scene -> chunk` 记录进度、失败位置和恢复状态；每完成一个 chunk 就会回写一次 checkpoint

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "use_llm": true,
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false,
  "resume_from_progress": false
}
```

说明：

- 如果缺少 scene structure 产物，接口会直接返回 `400`
- `continuity_review_mode` 可选 `off / auto / on`
- `auto` 只在更值得花成本的 run 上触发 `V2`，例如多角色同框、同 scene 多 segment、存在对白/字幕、存在连续承接，或 `V1` 已发现中高风险
- 如果不传，后端会继承当前 run 上次使用的模式，默认回退为 `auto`
- `seedream_watermark / seedance_watermark` 如果不传，后端会继承当前 run 根任务上的设置
- `resume_from_progress = true` 时，会复用 `segment_contract_progress.json` 里已落盘的 chunk 规划与失败位置，只继续未完成 chunk / scene / chapter，不能和 `segment_id / scene_id / master_only / merge_only` 混用
- `resume_from_progress = true` 要求 checkpoint 包含 `scene/chunk` 级进度结构
- 幂等去重会按 `source_task_id + story_source_revision + continuity_review_mode + watermark 组合` 复用已有 queued / running / completed 任务

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

- `Cast Analyzer` 的 `source_evidence` 仍必须能在正文中定位；当前后端会对“带修饰语的人名或稳定称呼”做容错匹配，但不会放过正文中根本不存在的人物
- 这一步依赖已经完成且未过期的 `project.segment_contracts`
- 前端默认仍传入根 story task 的 `source_task_id`，因为分析结果会回写到同一条 run 根任务上
- `seedream_watermark / seedance_watermark` 可选；不传则继承当前 run 根任务上的设置

#### `POST /v1/projects/scenes`

创建“生成场景图”任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "segment_id": "ch01_seg01",
  "frame_kind": "start"
}
```

重生成单个 scene 的场景母图：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "scene_id": "ch01-sc01",
  "master_only": true
}
```

说明：

- `segment_id` 可选
- `scene_id` 可选
- `frame_kind` 可选，只能和 `segment_id` 一起使用，取值为 `start / mid / end`
- `master_only` 可选
- 不传时表示对当前 run 执行整批场景图任务
- 传入后表示只生成单个 segment 的首帧 / 中段锚点帧 / 尾帧
- 传入 `segment_id + frame_kind` 时，只重做该 segment 对应的一张图片，并保留该 segment 内其它图片状态
- 传入 `scene_id + master_only = true` 时，只会重生成该 scene 的 `scene_master_frame`
- `master_only = true` 不能与 `segment_id` 同时提交，也必须配合 `scene_id`
- 该模式会重新调用 Seedream 并把结果回写到 `scene_plan.json` 与 `scene_image_manifest.json`
- `seedream_watermark / seedance_watermark` 可选；不传则继承当前 run 根任务上的设置
- 对同一 `source_task_id + segment_id`，如果已经有 queued / running 任务，后端会直接返回已有任务
- 对同一 `source_task_id + scene_id + master_only`，如果已经有 queued / running 任务，后端也会直接返回已有任务

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
- `scene_id` 可选
- `merge_only` 可选
- 传入 `segment_id` 后只会提交该片段对应的 Seedance clip
- 传入 `scene_id` 后会提交该 scene 下全部 segment 的 Seedance clip
- 单段执行不会自动重新生成其它片段，也不会自动拼接总片
- `merge_only = true` 不能与 `segment_id` 或 `scene_id` 同时提交
- 如果传 `merge_only = true`，则不向 Seedance 提交任务，而是把当前已生成的本地 mp4 片段按 manifest 顺序合并成 `rendered/full_story.mp4`
- `seedance_watermark` 可选；不传则继承当前 run 根任务上的设置

手动合并请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "merge_only": true
}
```

#### `POST /v1/projects/continuity-repair`

创建“连续性智能修复”任务。

当前支持两种 scope：

- `segment_id`：片段级智能修复。会重写目标片段合同，并返回后续建议执行的媒体动作
- `scene_id`：场景级智能修复。会重写目标 scene 的 `scene_anchor / scene_bible`，并返回 `selection_mode`、`affected_segment_ids` 与后续建议执行的媒体动作

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "segment_id": "ch01-sc01-seg01_01",
  "use_llm": true,
  "continuity_review_mode": "on"
}
```

或：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "scene_id": "ch01-sc01",
  "use_llm": true,
  "continuity_review_mode": "on"
}
```

说明：

- `segment_id` 与 `scene_id` 必须二选一
- 这一步要求输出目录里已经存在 `continuity_report.json`
- 传 `segment_id` 时，目标片段必须在报告里至少有一条 `segment` 级问题
- 传 `scene_id` 时，目标 scene 必须在报告里至少有一条 `scene` 级问题，或该 scene 下至少有一条可定位的 `segment` 级问题
- `segment_id` 模式会先让 LLM 重写该段执行合同，再只回写目标片段对应的 `segment_plan.json / scene_image_manifest.json / seedance_manifest.json`
- `scene_id` 模式会让 LLM 重写该 scene 的 `scene_anchor / scene_bible`，回写 `scene_plan.json`、受影响片段的 `segment_plan.json`，并把对应 `scene_image_manifest.json / seedance_manifest.json` 目标片段重置为待重新执行
- 两种模式当前都只更新修复合同与修复报告，不会自动重跑场景母图、场景图或视频
- 如果目标当前没有可修复问题，任务会直接以 `completed` 结束，并返回：
  - `repair_execution_mode = "noop"`
  - `media_regeneration_required = false`
  - `pending_media_actions = []`
- 如果目标存在可修复问题，任务结果会返回：
  - `repair_execution_mode = "plan_only"`
  - `media_regeneration_required = true`
  - `pending_media_actions`
- `scene_id` 模式会额外落盘 `continuity_repair_{scene_id}.json`，其中包含 `selection_mode` 与 `affected_segment_ids`
- 修复报告文件名统一为 `continuity_repair_<segment_id|scene_id>.json`
- 对同一 `source_task_id + segment_id` 或 `source_task_id + scene_id`，如果已经有 queued / running 的修复任务，后端会直接返回已有任务
- `seedream_watermark / seedance_watermark` 可选；不传则继承当前 run 根任务上的设置

#### `POST /v1/projects/continuity-repair-batch`

创建“批量连续性合同修复”任务。

这一步只会按 `continuity_report.json` 里的风险优先级，分批回写 `scene` / `segment` 合同与连续性报告，不会自动重跑场景母图、场景图、视频或合并任务。

请求示例：

```json
{
  "project_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "source_task_id": "story-task-id",
  "use_llm": true,
  "continuity_review_mode": "on",
  "seedream_watermark": false,
  "seedance_watermark": false,
  "severity_threshold": "medium",
  "max_units_per_batch": 4
}
```

说明：

- `severity_threshold` 可选 `high / medium / low`
- `max_units_per_batch` 默认 `4`，范围 `1-12`
- 当前批次会优先处理更高风险目标；同风险下优先 `scene`，再处理 `segment`
- 每次只处理一小批目标；如果结果里 `has_more_batches = true`，表示还有剩余风险可继续发下一批
- 任务结果会额外返回：
  - `repair_execution_mode`
  - `pending_media_actions`
  - `processed_unit_count`
  - `repaired_unit_count`
  - `noop_unit_count`
  - `failed_unit_count`
  - `repaired_scene_ids`
  - `repaired_segment_ids`
  - `remaining_repairable_count`
  - `has_more_batches`
- 这个接口不会新建任何媒体任务；它只更新合同与报告，后续是否重跑 `project.scenes` / `project.videos` 仍由用户手动决定
- `seedream_watermark / seedance_watermark` 可选；不传则继承当前 run 根任务上的设置

#### `GET /v1/projects/{project_id}/story-source/{source_task_id}`

读取某个 story run 当前的可编辑小说正文。

#### `PUT /v1/projects/{project_id}/story-source/{source_task_id}`

更新某个 story run 的小说正文。

更新后会：

- 重写 `story_source.json`
- 清除当前 `novel_package.json`、`novel_audit.json`、角色图、场景图、视频等派生产物
- 清除当前 `continuity_repair_*.json`
- 让前端把场景结构、分段合同与媒体阶段视为“待重新生成”

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
- 阶段任务会在提交时继承 `pipeline_root_task_id`，并通过 `payload.pipeline_root_task_id` 与 `result.pipeline_root_task_id` 指向同一条 story run。
- `result.story_source_revision` 用于判断场景结构、分段合同、图片和视频是否仍对应当前正文。
- `project.segment_contracts` 的 `result` 可能额外带 `segment_contract_progress_path` 与 `segment_contract_progress`
- `segment_contract_progress` 会包含 `status / total_chapters / total_scenes / total_chunks / completed_chapters / completed_scene_count / completed_chunk_count / failed_chapter_number / failed_scene_id / failed_chunk_id / resume_ready / chapters[]`
- `chapters[].scenes[]` 下会继续带 `chunks[]`、`running_chunk_id`、`failed_chunk_id`
- 分段合同失败时，`error` 会尽量带上 `chapter / scene_id / chunk_id` 上下文，前端可直接展示失败位置
- `project.scenes` 的单段任务会带 `segment_id`；场景母图重生成任务会带 `scene_id` 和 `master_only = true`
- `project.scenes` 可直接带 `scene_id`，表示重跑该 scene 下全部关键帧；内部连续性修复链路还可进一步附带受影响 `segment_ids`，把重跑范围缩小到 scene 内局部片段
- `project.videos` 可直接带 `scene_id`，表示重跑该 scene 下全部视频片段
- `project.continuity_repair` 可带 `segment_id` 或 `scene_id`
- `project.continuity_repair_batch` 用于按风险优先级批量回写连续性合同，不会自动重跑媒体
- `project.continuity_repair` 当前是 `plan-only`；任务会停在 `continuity_repair_plan_completed`，随后由任务状态本身转为 `completed`
- `project.continuity_repair_batch` 当前也统一是 `plan-only`；任务会停在 `continuity_repair_batch_completed`，随后由任务状态本身转为 `completed`
- 如果目标没有问题可修，修复任务会以 `completed noop` 结束，不会报失败
- 修复任务的 `result` 会额外带 `repair_execution_mode`、`media_regeneration_required` 和 `pending_media_actions`
- `scene_id` 修复任务的 `result` 还会额外带 `selection_mode` 与 `affected_segment_ids`，用于解释本次修复是局部联动还是整 scene 方案
- `project.continuity_repair_batch` 的 `result` 还会额外带 `processed_unit_count`、`repaired_unit_count`、`noop_unit_count`、`failed_unit_count`、`remaining_repairable_count` 与 `has_more_batches`
- 如果任务或其根 run 开启了 `V2` 软审校，`payload` / `result` 里会带 `continuity_review_mode`

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

其中 `planned_segments` 会优先来自 `scene_plan.json`，并回落到 `segment_plan.json`。接口会带上每个 segment 当前对应的：

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
- `start_frame_prompt`
- `mid_frame_prompt`
- `mid_frame_mode`
- `end_frame_prompt`
- `video_prompt`
- `submitted_video_prompt`
- `submitted_prompt_variant`
- `submitted_reference_bindings`
- `scene_master_frame_request`
- `start_frame_request`
- `mid_frame_request`
- `end_frame_request`
- `video_request`
- `start_frame`
- `mid_frame`
- `end_frame`
- `rendered_clip`
- `scene_ready`
- `video_ready`

说明：

- `video_prompt` 是分段合同阶段落盘的基础视频 prompt；画面推进会消费 `motion_plan` 并绑定 `图片1 / 图片2 / 图片3`
- `motion_plan` 返回当前 segment 的画面推进合同，`seedance_motion_prompt` 返回最终 Seedance prompt 中的参考图绑定与画面推进摘录
- `submitted_video_prompt`、`submitted_prompt_variant`、`submitted_reference_bindings` 只有该段真正提交过视频后才会有值
- `mid_frame_mode` 当前取值为 `continuous` 或 `insert_cut`；当前者表示中段仍是主镜头推进，后者表示中段是从主镜头短促切入的单人 / 局部插入镜头
- `submitted_reference_bindings` 会返回当前实际送往 Seedance 的时间锚点图绑定顺序和用途说明，也就是 `图片1 / 图片2 / 图片3` 对应的首帧 / 中段帧 / 尾帧
- `scene_master_frame_request / start_frame_request / mid_frame_request / end_frame_request / video_request` 会返回真实提交时的 `provider / endpoint / variant / payload / reference_bindings`
- 如果某段首帧没有重新调用 Seedream，而是直接复用上一段尾帧，`start_frame_request.payload.mode` 会标成 `reuse_previous_end_frame`
- 如果某段是非首个 scene 的首段，且上一场尾帧已经可用，`start_frame_request.reference_bindings` 里还会多一张 `temporal` 参考图，对应上一场最后一段尾帧
- 接口返回 manifest 中记录的请求视图；当 manifest 只包含产物文件时，会基于当前 manifest 和产物文件提供 `derived_from_manifest` 请求视图

前端会根据这份索引直接渲染逐段时间线，即使某个片段还没有实际产物，也会先展示出来等待单独触发。

如果某个片段执行过智能修复，`documents` 里还可能出现：

- `continuity_repair_{segment_id}.json`
- `continuity_repair_{scene_id}.json`

`continuity_summary` 当前会返回：

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

`continuity_scene_groups` 与 `continuity_segment_groups` 会把 `continuity_report.json` 里的问题明细按 `scene` / `segment` 聚合后返回。每组当前包含：

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
