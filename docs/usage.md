# 使用说明

StoryForge 的推荐使用方式是按阶段推进。每个阶段完成后先在页面审阅结果，再进入下一阶段，避免在错误规划上继续消耗生图和生视频成本。

## 启动服务

启动后端：

```bash
uv sync
cp .env.example .env
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

常用地址：

- 前端：`http://127.0.0.1:5173/`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

运行 Seedream 或 Seedance 长任务时，不建议给后端开启热重载。

## 创建项目

1. 打开首页，输入一句故事创意。
2. 点击开始创作，进入小说转视频页。
3. 填写项目名称、类型、气质、章节数和核心元素。
4. 创建视频项目。
5. 小说任务提交后，进入项目工作台等待任务完成。

## 工作台流程

### 1. 小说

小说页展示 `story_source.json` 的正文真源。可以编辑故事标题、章节标题、章节摘要和章节正文。

保存正文会更新 `story_source_revision`，后续结构、角色图、场景母图和视频需要基于新正文重新生成。

### 2. 结构化信息

结构化信息阶段分两步：

- 生成场景结构：得到章节、scene、角色视觉设定、空间合同和连续性报告。
- 生成分段合同：得到 chunk、segment、motion plan、场景母图任务和视频任务。

页面会展示 scene 和 segment 的蓝图，用于检查地点、人物、动作目标和承接关系。

### 3. 角色图

角色定妆墙用于检查每个角色的正式图和 prompt。

支持操作：

- 切换角色。
- 修改当前角色 prompt。
- 保存 prompt。
- 保存并重做当前角色。
- 对比当前正式图和新候选图。
- 使用候选图或保留当前图。

角色图用于锁定脸、发型、服装、体型和年龄感，不用于描述视频动作过程。

### 4. 场景母图

场景空间板按 scene 展示环境母图。重点检查：

- 是否是无人物空场景。
- 地点、时间、天气和光线是否正确。
- 空间透视、背景锚点和固定道具是否稳定。
- 该母图被多少个 segment 引用。

同一空间连续推进的 scene 可以复用母图；新地点或空间关系不确定时应生成新的母图。

### 5. 分段视频

分段审片台按 segment 展示视频生产状态。

每个 segment 可以查看：

- 当前视频或场景母图预览。
- segment 标题、摘要、时长和场景。
- 是否启用上一段尾帧承接。
- 当前片段命中的连续性问题。
- 提交资源图。
- 可编辑的视频 prompt。
- 含图片编号绑定的提交 prompt 预览。

未出片时按钮显示“生成当前视频”，已出片时显示“重新生成视频”。

### 6. 合并视频

合并视频页展示完整成片和片段资产。点击合并后，系统会把已完成的 segment 视频按顺序合成为 `rendered/full_story.mp4`。

## Prompt 编辑规则

- 角色 prompt 在角色定妆墙编辑。
- 视频 prompt 在分段审片台编辑。
- 场景母图 prompt 可通过 API 更新 segment 对应的 `scene_master_frame_prompt`。
- 保存 prompt 不会自动提交媒体任务。
- “保存并重做”只重做当前对象，不重新跑整个项目。

## 参考图绑定

Seedance 视频提交会根据真实资源顺序生成绑定说明。常见顺序：

- `图片1`：当前 scene 的场景母图，用于锁定地点、光线、透视、背景锚点和固定道具。
- `图片2`：上一段视频尾帧，仅在需要承接时出现，用于锁定开场构图、站位、动作停点和光线状态。
- 后续图片：实际出镜角色图，用于锁定角色身份、脸、发型、服装和体型。

如果没有上一段尾帧，角色图会前移。判断参考图用途时必须看提交 prompt 和 `submitted_reference_bindings`，不要假设固定编号。

## 常见问题

生成视频按钮不可用时，通常是当前 segment 缺少场景母图、角色图，或当前任务仍在运行。

视频不承接上一段时，检查上一段是否已有 `last_frame_url`，再检查当前 segment 是否把该尾帧作为参考图提交。

场景跳变明显时，检查 scene 是否被错误标记为同一空间；新地点应生成新场景母图。

角色换脸或年龄感变化时，优先重做角色图，再重跑相关视频片段。

合并视频没有展示时，先确认至少一个 segment 已完成视频生成，再提交合并任务。

## 输出目录

默认输出目录是 `outputs/projects/{project_id}/runs/{task_id}/...`。

常用文件：

- `story_source.json`
- `novel_package.json`
- `story_memory.json`
- `character_visual_bible.json`
- `scene_plan.json`
- `segment_plan.json`
- `character_image_manifest.json`
- `scene_image_manifest.json`
- `seedance_manifest.json`
- `continuity_report.json`

常用媒体目录：

- `assets/characters/`
- `assets/frames/`
- `rendered/`
