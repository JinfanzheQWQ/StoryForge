# 媒体生成管线

本文描述 StoryForge 当前媒体生成流程。媒体阶段以 scene 母图和角色定妆图作为视觉参考，视频 prompt 负责描述角色在同一场景空间里的连续运动、对白、环境声和收束状态。

## 核心原则

- 每个 scene 只生成一张场景母图，用于锁定地点、光线、空间透视、背景锚点和固定道具。
- 每个角色生成一张角色定妆图，用于锁定身份、体型、服装、发型和画风。
- 每个 segment 不生成独立图片锚点；segment 只生成视频合同和 Seedance prompt。
- Seedance 请求按固定顺序提交参考图：`图片1=场景母图`，`图片2` 及之后为当前 segment 实际出镜角色的定妆图。
- 视频 prompt 必须写清角色在场景中的运动轨迹、镜头路径、节拍推进、对白和收束状态。
- 页面展示真实提交 payload 和参考图绑定，让用户能判断问题来自场景图、角色图、prompt 还是 provider 执行。

## 规划合同

### `scene_bible`

`scene_bible` 是 scene 级环境基线，包含：

- 地点、时间、天气、光线。
- 主色调、背景锚点、固定道具。
- 空间布局、角色调度和连续性说明。

场景母图 prompt 只消费 scene 级环境基线，不把人物随身道具写成固定布景。

### `shot_state`

`shot_state` 是 segment 级镜头和动作状态，包含：

- `framing`：景别、构图和主体组织方式。
- `camera_motion`：镜头运动方式和推进节奏。
- `blocking`：角色站位、朝向、入画出画和相对关系。
- `action_progression`：从开场到收束的动作推进。
- `emotion_progression`：片段内情绪推进。
- `prop_continuity`：手部状态、持物、服装和关键道具连续性。
- `screen_direction`：运动方向、视线方向和反轴控制。
- `end_state_lock`：片段尾部状态，供下一段承接。

### `motion_plan`

`motion_plan` 是 Seedance 运动合同，包含：

- `scene_motion`：角色在场景母图空间中的整体运动轨迹。
- `beat_progression`：按 `timed_beats` 顺序展开的开场、推进和收束。
- `camera_path`：镜头路径，例如固定机位、轻微前推、跟拍、横移或关系镜头。
- `character_motion`：角色入画、靠近、转身、停步、递物、离场或站位变化。
- `continuity_guard`：防止换景、少人、换脸、动作跳变和方向漂移的要求。

## 生图阶段

### 角色图

角色图由 `character_visual_bible.json` 和 `character_image_manifest.json` 驱动。页面支持查看角色 prompt、真实 Seedream 请求、候选图和当前保留图。

角色图要求：

- 单角色白底三视图。
- 同项目画风、线条、上色方式和光照统一。
- prompt 可以人工编辑，重做后先产生候选图，用户确认后替换当前图。

### 场景母图

场景母图由 `scene_plan.json` 和 `scene_image_manifest.json` 驱动。场景母图优先表现环境、光线、空间和固定锚点，不承担 segment 的时间节点。

场景母图要求：

- 锁定同一 scene 的地点、光线、主色、空间透视和固定布景。
- 避免近景人像特写。
- 不出现对白字幕、说明文字、水印、Logo 或标题。
- 作为后续视频的空间基准，不替代视频里的角色运动描述。

## 生视频阶段

Seedance 请求使用：

- `图片1`：当前 scene 的场景母图。
- `图片2...n`：当前 segment 实际出镜角色的定妆图。
- `prompt`：视频剧情、运动轨迹、镜头路径、对白、字幕、环境声和音乐方向。

视频 prompt 写法：

- 先声明图片绑定关系，明确场景图和角色图的用途。
- 描述角色在图片1场景里的起始状态、运动过程和收束状态。
- 按秒数写 `timed_beats`，覆盖片段完整时长。
- 保留对白、旁白、字幕和音频约束。
- 禁止把角色图当成视频时间帧或画面目标。

## 前端审阅

分段审片台展示：

- 当前 segment 的场景母图。
- 当前 segment 的角色参考图。
- 当前视频。
- Prompt Editor。
- Request Inspector。
- Motion Plan。
- Seedance 最终推进 prompt。
- 真实提交 payload 与参考图绑定顺序。

用户可以只选择当前生成点查看 prompt 和请求参数，并按当前点保存、重做或检查差异。

## 风险校验

当前校验聚焦：

- scene 基线是否足够稳定。
- scene / chunk / segment 是否覆盖正确事件。
- segment 动作容量是否适配时长。
- `timed_beats` 是否覆盖完整时长。
- `continuity_link.opening_match` 是否承接上一段尾部状态。
- 多人同框时共享镜头是否错误写成单人特写。
- Seedance 请求是否携带场景母图和当前出镜角色图。

## 主要文件

- `character_visual_bible.json`：角色视觉设定。
- `character_image_manifest.json`：角色图任务清单。
- `scene_plan.json`：scene 与 segment 规划主文件。
- `segment_plan.json`：flat segment 执行索引。
- `scene_image_manifest.json`：场景母图任务清单。
- `seedance_manifest.json`：视频提交清单。
- `continuity_report.json`：连续性与执行风险报告。
