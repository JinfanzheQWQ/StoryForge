# 使用说明

StoryForge 的主入口是 Web 工作台。推荐按阶段推进，每完成一个阶段先在页面审阅结果，再进入下一阶段。

## 启动

```bash
uv sync
cp .env.example .env
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

打开：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

运行 Seedream / Seedance 长任务时不要使用 `--reload`。

## 项目流程

1. 在创建页输入 brief，生成小说正文。
2. 在小说页审阅正文，必要时直接修改并保存。
3. 生成场景结构，检查 scene 是否覆盖章节事件、地点和空间关系是否合理。
4. 生成分段合同，检查每个 segment 的动作容量、对白长度、镜头关系和收束状态。
5. 生成角色图，必要时编辑单个角色 prompt 后重做。
6. 生成场景母图，检查是否为无人物空场景，地点、光线、背景锚点和固定道具是否稳定。
7. 逐段生成视频，检查当前 segment 的画面推进、声音、字幕和参考图绑定。
8. 合并已完成视频片段。

## 角色图

角色图用于锁定角色身份和外观。每个角色单独生成白底三视图，画面只包含同一角色的正面、侧面和背面。

页面支持：

- 查看当前正式角色图。
- 查看真实 Seedream 请求。
- 编辑单角色 prompt。
- 生成候选图。
- 保存候选图并替换正式图。
- 放弃候选图。

角色图不是视频时间帧，不用于描述动作过程。

## 场景母图

场景母图用于锁定 scene 的环境基准。它必须是无人物、无文字的空场景参考图。

场景母图 prompt 应包含：

- 地点。
- 时间、天气、光线。
- 空间布局。
- 主色调。
- 背景锚点。
- 固定道具。
- 无人物、无文字、无 Logo、水印和说明性排版的约束。

同一地点连续推进的 scene 可以共用或承接上一 scene 的场景母图。新地点或空间关系不确定时应生成新的场景母图。

## 视频生成

每个 segment 独立提交 Seedance。提交内容包括：

- 当前 scene 的场景母图。
- 需要承接时的上一段视频尾帧。
- 当前 segment 实际出镜角色的角色图。
- 当前 segment 的 motion prompt。

参考图顺序以 Request Inspector 中的实际提交为准。prompt 会明确说明每张图的用途：场景母图锁定空间，上一段视频尾帧锁定开场状态，角色图锁定人物身份。

视频 prompt 负责描述：

- 时长。
- 角色运动轨迹。
- 动作状态。
- 镜头调度。
- 开场状态和收束状态。
- 对白、角色音色、环境音、音乐和硬字幕。
- 连续性保护。

## Prompt 编辑

分段审片台只编辑当前选中的 segment。

可编辑项：

- 场景母图 prompt。
- Seedance 视频 prompt。

保存 prompt 不会自动提交媒体任务。保存后需要手动重做对应的场景母图或视频。

## 请求查看

Request Inspector 展示当前媒体任务真实提交内容：

- provider。
- model。
- prompt。
- size / duration / resolution / watermark 等请求参数。
- reference images。
- submitted reference bindings。
- provider request summary。
- 失败原因和诊断信息。

当页面结果和预期不一致时，优先检查 Request Inspector 中的实际 payload。

## 输出文件

常用文件：

- `story_source.json`：正文真源。
- `novel_package.json`：小说包。
- `story_memory.json`：故事记忆。
- `character_visual_bible.json`：角色视觉设定。
- `scene_plan.json`：scene 结构和场景母图字段。
- `segment_plan.json`：segment 合同和 prompt。
- `character_image_manifest.json`：角色图任务和结果。
- `scene_image_manifest.json`：场景母图任务和结果。
- `seedance_manifest.json`：视频任务、参考图绑定、提交 prompt 和结果。
- `continuity_report.json`：风险诊断。

媒体目录：

- `assets/characters/`：角色图。
- `assets/frames/`：场景母图。
- `rendered/`：分段视频和合并视频。

## 常见判断

生成视频按钮禁用时，通常说明当前 segment 缺少可用场景母图、角色图或视频任务仍在运行。

视频报缺少 scene master 时，先检查当前 scene 是否已有场景母图 URL；同地点连续推进的 scene 再检查是否正确继承了上一 scene 的场景母图。

视频不承接上一段时，先检查上一段是否已有 `last_frame_url`，再检查当前 segment 的提交请求是否包含上一段视频尾帧绑定。

场景母图偏移明显时，先检查 scene 的空间连续性字段和场景母图 prompt；新地点应生成新母图，同一地点应保持地点、光线、锚点和固定道具一致。
