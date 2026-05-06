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

## 生图

### `POST /v1/images/generations`

提交独立生图任务。前端可提交 `model = "gpt-image-2"` 或 `model = "doubao-seedream-4-5-251128"`；`text_to_image` 只需要 prompt，`image_to_image` 需要至少一张参考图 URL。

`size` 和 `aspect_ratio` 必须来自 `GET /v1/images/capabilities` 返回的当前模型能力。前端不需要写死尺寸规则，也不需要让用户选择后端通道。

文生图请求示例：

```json
{
  "mode": "text_to_image",
  "model": "gpt-image-2",
  "prompt": "清晨的玻璃图书馆中庭，薄荷绿植物墙，柔和天光，清新科技感商业插画。",
  "size": "1K",
  "aspect_ratio": "1:1"
}
```

图生图请求示例：

```json
{
  "mode": "image_to_image",
  "model": "gpt-image-2",
  "prompt": "保持参考图主体构图，改成清新科技感商业插画，低饱和薄荷绿与浅青蓝配色。",
  "reference_images": ["https://example.com/reference.png"],
  "size": "1K",
  "aspect_ratio": "1:1"
}
```

Seedream 4.5 请求示例：

```json
{
  "mode": "text_to_image",
  "model": "doubao-seedream-4-5-251128",
  "prompt": "傍晚的玻璃温室花园，薄荷绿与浅青蓝配色，柔和商业插画。",
  "size": "2K",
  "aspect_ratio": "9:16",
  "seedream_watermark": false
}
```

任务完成后，`GET /v1/tasks/{task_id}` 的 `result` 会包含：

- `image_url`：远程图片 URL。
- `output_url`：下载到本地后的 `/outputs/...` 访问地址，开启下载时可用。
- `output_path`：本地输出路径。
- `model / size / aspect_ratio`：本次选择的生图模型、分辨率档位和比例。
- `gpt_image_request` / `seedream_request` / `request_info`：真实提交 payload、endpoint、task id、响应摘要和参考图绑定。
- `seedream_watermark`：Seedream 4.5 请求的水印开关。

前端会通过 `GET /v1/images/capabilities` 读取当前后端配置下的可选分辨率和比例。Seedream 4.5 会把水印开关写入 `payload.watermark`。

独立生图结果写入 `outputs/images/{task_id}/generated.*`。Seedream 4.5 使用 `generated.png`；GPT Image 2 的后缀由 `[gpt_image].output_format` 决定。

生图任务完成后不会自动进入作品库。需要保存时调用：

### `POST /v1/images/generations/{task_id}/save`

把已完成的生图任务保存到作品库。保存后项目摘要才会出现在 `GET /v1/projects` 中。

```json
{
  "project_id": "image-project-id",
  "task_id": "image-task-id",
  "status": "completed"
}
```

### `GET /v1/images/capabilities`

返回当前后端配置下，生图页可展示的模型、分辨率和比例选项。

返回示例：

```json
{
  "models": [
    {
      "label": "GPT Image 2",
      "value": "gpt-image-2",
      "size_options": [
        {
          "label": "1K",
          "value": "1K",
          "aspect_ratios": ["1:1", "3:2", "2:3"]
        }
      ]
    },
    {
      "label": "Seedream 4.5",
      "value": "doubao-seedream-4-5-251128",
      "size_options": [
        {
          "label": "2K",
          "value": "2K",
          "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"]
        }
      ]
    }
  ]
}
```

## 项目

### `GET /v1/projects`

返回项目摘要列表。

项目摘要包含 `product_type`：

- `novel_to_video`：小说转视频项目。
- `image_generation`：独立生图产品。

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
    "style_keywords": ["青春", "傍晚", "微风"],
    "video_mode": "grid_storyboard",
    "image_model": "doubao-seedream-4-5-251128",
    "image_size": "2K",
    "image_aspect_ratio": "16:9"
  },
  "use_llm": true,
  "llm_provider": "deepseek",
  "llm_model": "deepseek-chat",
  "continuity_review_mode": "auto",
  "seedream_watermark": false,
  "seedance_watermark": false
}
```

`video_mode` 可选：

- `grid_storyboard`：先生成九宫格分镜图，再用九宫格生成视频。
- `direct_motion`：直接用场景母图、角色图和运动 prompt 生成视频。

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

## 小说转视频阶段任务

后续阶段共用 `project_id` 和 `source_task_id` 定位项目与生产 run。局部重做时使用 `segment_id`、`scene_id`、`character_name`、`master_only` 或 `merge_only` 缩小范围。角色图、场景母图和九宫格分镜图阶段可在每次提交时选择本次生图模型：

- `video_mode`
- `image_model`
- `image_size`
- `image_aspect_ratio`

`image_model` 可选择 `doubao-seedream-4-5-251128` 或 `gpt-image-2`。`image_size` 和 `image_aspect_ratio` 必须符合当前模型能力；前端会通过能力接口限制可选组合。

同一正文版本重复提交场景结构或分段合同任务时，接口会复用已有排队、运行中或已完成任务；如果复用已完成任务，返回前会把该任务产物同步回根小说任务，确保工作台刷新后能直接读取结构产物。

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
  "seedance_watermark": false,
  "video_mode": "grid_storyboard",
  "image_model": "doubao-seedream-4-5-251128",
  "image_size": "2K",
  "image_aspect_ratio": "16:9"
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
- `storyboard_grid_manifest.json`
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
  "image_model": "gpt-image-2",
  "image_size": "2K",
  "image_aspect_ratio": "16:9",
  "seedream_watermark": false
}
```

`character_name` 为空时生成全部角色图。选择 `gpt-image-2` 时角色定妆图由 GPT Image 2 生成；选择 `doubao-seedream-4-5-251128` 时由 Seedream 4.5 生成。

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
  "image_model": "doubao-seedream-4-5-251128",
  "image_size": "2K",
  "image_aspect_ratio": "16:9",
  "seedream_watermark": false
}
```

`scene_id` 为空时生成全部场景母图。场景母图也按本次提交的 `image_model` 选择 GPT Image 2 或 Seedream 4.5。

## 九宫格分镜

### `POST /v1/projects/storyboards`

生成全部、单个 scene 或单个 segment 的九宫格分镜图。九宫格模式下，当前 segment 的视频生成前必须先完成九宫格。

请求示例：

```json
{
  "project_id": "project-id",
  "source_task_id": "segment-contract-task-id",
  "segment_id": "ch01-sc01-seg01",
  "video_mode": "grid_storyboard",
  "image_model": "gpt-image-2",
  "image_size": "2K",
  "image_aspect_ratio": "16:9",
  "seedream_watermark": false
}
```

任务会读取当前 segment 的场景母图、角色图、timed beats 和对白，生成一张 3x3 连续分镜图。九宫格 prompt 会固定展开格1到格9；如果当前视频需要承接上一段，Seedance 视频提交阶段会继续绑定尾帧。

主要输出：

- `storyboard_grid_manifest.json`
- `assets/storyboards/{segment_id}_grid.*`

任务完成后会同步 `seedance_manifest.json` 中对应 clip：

- `video_mode = grid_storyboard`
- `storyboard_grid_url`
- `storyboard_grid_prompt`
- `storyboard_grid_status`
- `storyboard_grid_request_info`
- `storyboard_scene_descriptions`

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

九宫格模式下，视频提交固定以 `图片1：九宫格分镜图` 为主参考图；如果需要尾帧承接，会额外提交 `图片2：上一段视频尾帧`，并设置 `first_frame`。连续表演模式下，视频提交场景母图、可用上一段尾帧和实际出镜角色图。真实参考图顺序写入 `submitted_reference_bindings`。

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
- 角色图、场景母图、九宫格分镜图和视频资源。
- motion plan、prompt 和请求 payload。
- reference bindings。
- `segment_contract_progress`，用于展示分段合同生成进度、失败位置、错误详情和是否可从失败位置继续。
- 连续性问题和失败原因。
- 合并总片。

`image.generate` 任务会把生成图放在 `scene_frames` 中，供作品库作为图片封面展示。
生图作品详情页通过项目详情读取当前作品下的 `image.generate` 任务，再通过 artifacts 展示生成图和请求参数。
