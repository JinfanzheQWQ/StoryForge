# 小说转视频九宫格分镜模式

九宫格分镜模式把每个视频 segment 先生成一张 3x3 连续分镜图，再把这张分镜图作为 Seedance 的主要视频参考图。需要承接上一段时，视频提交会额外绑定上一段尾帧作为开场锚点。它适合商业化剧情短视频生产：用户可以在视频生成前审阅角色站位、动作推进、镜头节奏和收束状态。

## 创作流程

```text
输入一句故事创意
  -> 生成小说正文
  -> 生成场景结构
  -> 生成分段合同
  -> 生成角色图
  -> 生成场景母图
  -> 生成 segment 九宫格分镜图
  -> 根据九宫格分镜图生成 segment 视频
  -> 合并总片
```

创建小说转视频项目时可选择：

- `grid_storyboard`：九宫格分镜模式。
- `direct_motion`：连续表演模式。

前端默认使用九宫格分镜模式。角色图、场景母图和九宫格分镜图每次生成前都可以选择生图模型、分辨率和比例；九宫格使用同一组生图配置。

## 九宫格生成

每个 segment 的九宫格图由 `project.storyboards` 任务生成。生成输入包括：

- 当前 scene 的场景母图。
- 当前 segment 实际出镜角色的角色图。
- 当前 segment 的标题、摘要、motion plan、timed beats 和对白。
- 如果上一段视频已有可用尾帧，并且当前片段需要连续承接，尾帧不参与九宫格生图；它会在 Seedance 视频生成阶段作为第二张参考图和 `first_frame` 提交。

尾帧只参与 Seedance 视频承接，不参与九宫格生图。场景母图和角色图不直接进入九宫格模式的视频提交。

九宫格画面规则：

- 按项目选择的比例生成，一张图内固定 3x3。
- 九格按从左到右、从上到下表示连续动作推进。
- prompt 必须固定描述格1到格9，把稀疏 timed beats 展开成起始、推进、结果关键帧；每个格子都有不同的站位、动作、视线、景别或构图变化。
- 九宫格生图描述不使用上一段尾帧措辞；当前片段开场只写成当前片段自身的开场状态。
- 不出现编号、字幕、说明文字、水印、Logo、色卡或信息板。
- 保持同一场景、同一角色身份、同一服装、同一光线方向和同一画风。
- 不把角色白底三视图版式带入分镜图。

支持的生图模型：

- `gpt-image-2`
- `doubao-seedream-4-5-251128`

## Seedance 提交

九宫格模式的视频提交固定以九宫格为主参考图：

```text
图片1：九宫格分镜图，是当前片段主要视频参考图。
图片2：上一段视频尾帧，可选，只在规划判断当前段需要承接上一段时提交。
```

Seedance prompt 会按 segment 的 timed beats 生成场景时间描述：

```text
格1 (0-0.9秒): 建立开场构图和初始站位。
格2 (0.9-1.8秒): 动作开始，角色视线或手部位置发生变化。
格3 (1.8-2.7秒): 角色移动到下一状态。
格4 (2.7-3.6秒): 空间关系继续推进。
格5 (3.6-4.4秒): 进入片段中点，互动关系发生转折。
格6 (4.4-5.3秒): 延续中点动作。
格7 (5.3-6.2秒): 进入收束前状态。
格8 (6.2-7.1秒): 接近最终状态。
格9 (7.1-8秒): 停在本段结尾状态；对白：林屿：苏晚。
```

对白直接写入对应场景描述中，不再单独生成音频规则块。

## 产物

九宫格分镜任务写入：

```text
storyboard_grid_manifest.json
assets/storyboards/{segment_id}_grid.png
```

`storyboard_grid_manifest.json` 每项包含：

- `segment_id`
- `scene_id`
- `model`
- `size`
- `aspect_ratio`
- `prompt`
- `reference_images`
- `reference_bindings`
- `scene_descriptions`
- `uses_previous_last_frame`
- `previous_last_frame_url`
- `generated_url`
- `output_path`
- `request_info`
- `status`
- `error`

`seedance_manifest.json` 的 clip 会记录：

- `video_mode`
- `storyboard_grid_url`
- `storyboard_grid_path`
- `storyboard_grid_prompt`
- `storyboard_grid_status`
- `storyboard_grid_request_info`
- `storyboard_scene_descriptions`

## 前端行为

小说转视频创作页提供模式选择。九宫格模式下，分段审片台的操作顺序是：

1. 场景母图和角色图准备完成后，生成当前 segment 九宫格。
2. 九宫格完成后，生成或重新生成当前 segment 视频。
3. 提交资源图区域展示九宫格；需要承接上一段时同时展示尾帧。
4. 提交 prompt 预览写清 `图片1：九宫格分镜图` 和可选 `图片2：上一段视频尾帧`，不展示场景母图或角色图绑定。

生成视频按钮在九宫格未完成前不可用。
