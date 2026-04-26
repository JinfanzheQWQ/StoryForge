# 产品状态

StoryForge 是一套分步式故事视频生产工作台。它强调阶段审阅、产物可追踪、prompt 可修改、请求参数可检查和小粒度重做，而不是把小说、图片和视频生成包装成不可检查的一键流程。

## 产品能力

### 小说与结构

- 根据 brief 创建项目并生成小说正文。
- 使用 `story_source.json` 作为正文真源，页面可直接编辑和保存。
- 生成结构化小说包，包括章节、角色、视觉设定和审稿结果。
- 基于当前正文生成场景结构。
- 基于场景结构生成分段合同。
- 分段合同生成带进度 checkpoint，可在失败后从失败位置继续。

### 视频规划

- 视频规划结构为 `chapter -> scene -> chunk -> segment`。
- scene 带 `covered_event_ids`、紧凑事件摘要、`scene_bible` 和 `scene_transition_contract`。
- segment 带 `shot_state`、`continuity_link`、首 / 中 / 尾帧角色集合、`timed_beats` 和 `motion_plan`。
- artifacts API 会返回 segment 诊断信息，包括动作预算、时长、`timed_beats` 覆盖、中段模式、拆段状态、风险类型、修复来源和规划告警来源。

### 图片与视频

- 使用 Seedream 生成角色图。
- 使用 Seedream 生成无角色场景母图。
- 使用 Seedream 生成 segment 首帧、中段帧和尾帧。
- 使用 Seedance 根据有序时间锚点图生成视频。
- 视频 prompt 使用 `图片1 / 图片2 / 图片3` 绑定首帧、中段帧和尾帧。
- 视频阶段不把场景母图或角色图作为 Seedance 参考图提交。
- Seedream / Seedance 水印选项按 run 保存。

### Web 工作台

- 项目列表、项目详情、任务时间线和产物浏览。
- 小说编辑页用于维护正文真源。
- 场景工作台用于查看 scene 分组、场景母图、过渡合同和 scene 级操作。
- 分段审片台用于查看关键帧、视频、prompt、请求参数、诊断信息和重做入口。
- Prompt Editor 支持修改单个首帧、中段、尾帧或视频 prompt。
- Request Inspector 支持查看真实提交 payload、Prompt Diff、参考图绑定和 provider 请求摘要。

### 持久化与恢复

- MySQL 保存项目、任务和 run 历史。
- 输出产物写入配置的输出根目录。
- 静态产物响应使用 `no-store`，减少浏览器缓存影响。
- 服务启动时，未完成任务会回到 `queued`。
- 删除项目会删除数据库记录和安全范围内的输出目录。

## 产品边界

- 正常运行需要 MySQL。
- 小说和视频规划需要可用的 LLM provider。
- 图片和视频生成需要可用的 Seedream / Seedance provider。
- 当前任务队列适合本地和单实例运行。
- Seedream / Seedance 长任务运行时不要使用 `--reload`。
- 媒体质量仍受 provider 能力、输入图、prompt、内容安全策略和素材质量影响。
- 连续性审校能发现并修复部分合同级风险，但不是完整的视频理解系统。
- 对象存储、账号体系、权限、多用户治理、计费和 webhook 不属于当前产品面。

## 工程重点

- prompt 合同保持短、明确，并只绑定当前阶段需要的数据。
- 媒体请求 payload 必须能在页面检查。
- 重做粒度优先控制在 frame、segment、scene 或 stage。
- validator 必须围绕当前生产 schema 工作，不维护并行规划模式。
- 前端 render 模块保持小边界，Prompt Editor、Request Inspector、时间线、场景工作台和分段审片台分别维护。

## 下一步重点

- 优化场景和片段风险展示，让页面直接提示下一步该做什么。
- 继续减少 prompt 重复，同时保留 schema 和 provider 必需指令。
- 补更多前端轻量测试，覆盖 prompt 修改、请求检查和单点重做按钮。
- 强化场景母图、关键帧角色集合和 Seedance 提交绑定的一致性检查。
- 在大批量并发任务前评估更持久的队列执行方案。
