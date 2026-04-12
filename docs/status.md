# 工程状态

> 截至 `2026-04-12`

## 当前定位

`StoryForge` 现在不是单纯的项目骨架，而是一套已经能真实跑通的四步式工程：

1. 生成小说
2. 生成角色图
3. 生成场景图
4. 生成视频

底层仍然能跑通“小说生成 -> 角色图 -> 场景首尾帧 -> 视频片段 -> 总片拼接”的端到端链路，但页面默认交互已经切到手动四步推进，不再一键全跑。

当前默认技术路线：

- 运行时：`Python >= 3.11`
- 依赖管理：`uv`
- API：`FastAPI`
- 数据建模：`Pydantic`
- Agent / 工作流：`LangChain >= 1.2` + 结构化多 Agent
- LLM：`DeepSeek`
- 生图：`Doubao Seedream 4.5`
- 生视频：`Seedance 2.0`
- 网络调用：`httpx`
- 拼接：`ffmpeg`

## 本轮问题记录与修复

用户本轮实际反馈的问题已经逐项进入代码和页面，本轮新增还包括“四步手动工作流”改造：

### 1. 页面在任务执行过程中不实时出现小说 / 文档 / 图片

原因：

- 任务以前只有整条 pipeline 跑完才写最终结果。
- 前端虽然在轮询任务，但文档 / 图片 / 视频 tab 仍然强制等待 `completed` 或 `failed`。

已修复：

- 任务在“小说阶段完成”后会先写入部分结果：
  - `output_dir`
  - `story_title`
  - `novel_package_path`
  - `pipeline_stage = story_completed`
- 前端在 `running` 状态下只要发现 `output_dir` 已存在，就会继续扫描产物目录。
- 文档、图片、视频 tab 现在不再死等任务完成；只要文件已经落盘，就会直接显示。
- 页面会显示阶段文案：
  - `小说生成中`
  - `小说已完成`
  - `角色图生成中`
  - `角色图已完成`
  - `场景图生成中`
  - `场景图已完成`
  - `视频生成中`
  - `视频已完成`

### 6. 页面改成更细的手动工作流，而不是一点开始全部执行

已修复：

- 新增更细的独立后端任务类型：
  - `project.story`
  - `project.characters`
  - `project.scenes`
  - `project.images`
  - `project.videos`
- 新增更细的阶段 API：
  - `POST /v1/projects/novel`
  - `POST /v1/projects/characters`
  - `POST /v1/projects/scenes`
  - `POST /v1/projects/images`
  - `POST /v1/projects/videos`
- Web 控制台现在只在发起页生成小说。
- 角色图、场景图、视频都必须在项目详情页手动点击下一步。
- 四个阶段共享同一个 story run 输出目录，不会把一个故事拆成四个孤立项目。
- 项目统计已按逻辑 run 聚合，不会把 `story / characters / scenes / videos` 误算成四次运行。
- 旧的 `POST /v1/projects/novel-to-video` 仍保留，用于兼容旧脚本和回归测试。
- 旧的 `POST /v1/projects/images` 也仍保留，用于兼容一口气生成全部图片的旧脚本。

### 2. LLM 解析小说拆视频时，对原小说情节复刻不够稳

原因：

- 原分段 prompt 对“必须严格复刻正文事件”的约束不够硬。
- 提供给分段 Agent 的章节正文摘录太短。
- 角色名漂移、对白参与方遗漏时，后处理不够强。

已修复：

- 分段 Agent prompt 已加入硬约束：
  - 必须严格复刻章节正文已发生事件
  - 不得改写关键关系和冲突
  - `dialogue_lines` 出现的角色必须进入 `involved_characters`
  - 告白 / 表白 / 对峙 / 谈判 / 双人对话必须覆盖双方
- 章节正文摘录长度已显著提高，给 LLM 更多原文上下文。
- 分段后处理现在会继续从以下位置补角色：
  - 标题
  - 摘要
  - 旁白
  - 场景 / 首帧 / 尾帧 prompt
  - 对白 speaker
  - 字幕
  - 时间节拍

说明：

- 这部分现在是“显著增强”，不是“100% 不会偏”。真正要做到生产级复刻，还要继续做事件抽取、对白对齐和自动回查。

### 3. 视频长度有时 5 秒，有时 12 秒，不稳定

当前规则已经明确：

- 现在改成由 LLM 在 `5-12` 秒之间自行判断每个片段时长
- `video.segment_duration_seconds` 仍保留，但只作为“模型拿不准时的偏好秒数 / fallback 秒数”
- 发送给 Seedance 前会做最终安全规整，确保不会超出接口上限

已修复：

- 已移除“先把所有片段统一强制对齐到配置秒数”的逻辑。
- 分段 prompt 现在明确要求 LLM 在 `5-12` 秒之间按剧情密度自行判断。
- 若 LLM 仍给出异常秒数，后处理会把过短片段抬到 `5s`，过长片段按 Seedance 规则拆分。

补充说明：

- 所以后面你会开始看到 `5s / 6s / 8s / 10s / 12s` 混合存在，而不是全部一刀切。

### 4. 双人告白场景只生成了一个角色

原因：

- 角色 Designer 有时会只给出一个核心角色。
- 分段 Agent 有时把双人关系场面只写成一个出镜角色。
- 场景 prompt 虽然有参考图，但对“多人必须同时出镜”的约束还不够硬。

已修复：

- 小说角色阶段新增“双人关系故事”修正规则：
  - 如果 brief 明显属于告白 / 表白 / 情感对手戏 / 双人对话驱动故事，至少保留 `2` 个核心角色
- 章节规划阶段会修复 `featured_characters`
  - 双人关系章节不能只保留一方
- 视频分段阶段会把告白 / 对话 / 对峙类场景自动补足到双方
- 场景图 prompt 和首尾帧 prompt 明确写入：
  - 如果 `involved_characters >= 2`，则这些角色必须同时出镜
  - 每个 involved character 都必须按对应参考设定图还原

### 5. 角色性别没有明确写出来，容易导致文生图偏差

已修复：

- `gender` 现在是小说角色卡、角色视觉卡、视频角色视觉档案里的一级结构化字段。
- 角色生成 prompt、角色定妆卡 prompt、场景 prompt、首尾帧 prompt 都会显式带出：
  - 性别
  - 年龄段
  - 体态
  - 服装轮廓
- 角色一致性说明里也会锁定：
  - 性别
  - 年龄感
  - 体型
  - 肩宽
  - 四肢比例
- 对“告白 / 恋爱 / 暧昧 / 情侣 / 前任 / 重逢”这类双人关系故事，若 brief 没明确写同性关系，角色阶段会默认把前两名核心角色修正为“一男一女”组合，避免又出现两个男主角或两个女主角。

## 当前新增行为

- 页面现在可以在任务 `running` 时直接看到已经生成好的章节和 JSON 文件。
- 角色图、场景帧、视频片段只要已经落盘，也会在轮询时尽快出现，不再等整条任务结束。
- 双人关系驱动故事会更倾向于自动保留双角色角色卡与双人场景。
- 视频片段时长现在由配置统一控制，并被严格约束在 Seedance 支持范围内。

## 已完成工程

### 1. 小说生成主链路

- 已支持从 TOML brief 或 API 请求体读取故事输入。
- 已实现结构化多 Agent 小说工作流。
- 当前多 Agent 角色包括：
  - `Story Architect`
  - `Character Designer`
  - `Chapter Planner`
  - `Chapter Writer`
  - `Editorial Reviewer`
- 已支持结构化中间结果落盘到 `workflow_trace.json`。
- 角色卡已包含结构化 `voice_profile`，并贯通到章节写作和视频生成。
- 已对单章短篇场景补充“短篇/短字数”写作约束，避免默认朝长篇开头扩写。

### 2. 视频规划主链路

- 已实现“章节”和“视频段”解耦。
- 现在的规则是：
  - 章节属于小说结构。
  - 段属于视频切片。
  - 一个章节拆成几段，由 LLM 根据正文内容自行判断。
- 已删除旧字段 `segment_target_per_chapter`，避免配置含义与实际行为不一致。
- 视频段已结构化输出：
  - `summary`
  - `narration`
  - `dialogue_lines`
  - `subtitle_lines`
  - `sound_effects`
  - `music_direction`
  - `timed_beats`
  - `scene_prompt`
  - `start_frame_prompt`
  - `end_frame_prompt`
  - `transition_hint`

### 3. 角色一致性与连续性链路

- 已实现角色定妆卡生成。
- 场景首帧、尾帧会引用角色定妆卡作为参考图。
- 场景 prompt 中已加入角色锁定要求：
  - 年龄感稳定
  - 体型稳定
  - 肩宽稳定
  - 头身比稳定
  - 四肢比例稳定
  - 脸型轮廓稳定
- 已支持连续片段复用上一段尾帧作为下一段首帧。
- 已支持 `transition_hint` 与连续性规则联合判断。

### 4. Seedream 真实接入

- 已接入 `Doubao Seedream 4.5` 真实 API client。
- 已支持：
  - 角色定妆卡生成
  - 场景首帧生成
  - 场景尾帧生成
- 已支持将返回 URL 回填到任务清单。
- 已支持把图片下载到本地输出目录。

### 5. Seedance 真实接入

- 已接入 `Seedance 2.0` 任务创建。
- 已接入 `Seedance 2.0` 状态查询。
- 已接入 `Seedance 2.0` 成片下载。
- 已支持把以下信息编译进视频 prompt：
  - 旁白
  - 角色对白
  - 硬字幕文案
  - 环境音
  - 音乐方向
  - 时间节拍
  - 角色音色锁定说明
  - 禁止变化项
- 已启用 `with_audio = true` 路线，不再依赖单独 TTS。

### 6. ffmpeg 自动拼接

- 已生成：
  - `concat_list.txt`
  - `ffmpeg_concat.sh`
- 现在当 Seedance 全部片段成功且本地文件都下载完成后，`run_video_pipeline()` 会自动执行 ffmpeg 拼接，产出：
  - `rendered/full_story.mp4`
- CLI 输出和 API 返回里都已能拿到 `full_story_path`。

### 7. API 与任务系统

- 已有 `FastAPI` 应用。
- 已有异步任务队列。
- 已接入后端级 `project_id`。
- 已接入项目 / 任务元数据持久化，支持两种后端：
  - 本地 JSON：
    - 项目元数据落到 `workspace/state/projects.json`
    - 任务元数据落到 `workspace/state/tasks.json`
  - MySQL：
    - 自动建库 `storyforge`
    - 自动建表 `projects` / `tasks`
- 已支持“同项目多次运行”归属到真实项目，而不是前端按标题临时聚合。
- 已支持“一个 run 拆成 story / characters / scenes / videos 四个阶段任务，但项目统计仍按一次 run 计算”。
- 已内置浏览器 Web 控制台：
  - 可直接在页面填写 brief
  - 可先提交小说任务
  - 可在项目详情页继续提交角色图任务
  - 可在项目详情页继续提交场景图任务
  - 可在项目详情页继续提交视频任务
  - 可基于已有项目再次发起新 run
  - 可自动轮询任务状态
  - 可直接预览章节文件、角色图、场景帧、片段视频和总片
- 已有任务状态接口。
- 已有项目列表接口与项目详情接口。
- API 任务返回目前已包含：
  - `project_id`
  - `output_dir`
  - `novel_package_path`
  - `seedream_execution_path`
  - `seedance_manifest_path`
  - `seedance_execution_path`
  - `segment_plan_path`
  - `rendered_clips`
  - `full_story_path`

## 已真实验证的结果

### 2026-04-10 实跑 1：`戏院残响`

输出目录：

- [outputs/live-short3-rerun-20260410-v2/戏院残响](/Users/xy/StoryForge/outputs/live-short3-rerun-20260410-v2/戏院残响)

确认结果：

- 小说生成成功
- 角色图生成成功
- 场景首尾帧生成成功
- `Seedance` 视频片段成功下载
- 共生成 `3` 条视频片段

这次主要验证了：

- 分段不再因为时长预处理被意外二次拆片
- 角色名与章节覆盖修复逻辑有效
- 3 段目标链路可以真实落盘

### 2026-04-10 实跑 2：`最后一班摆渡车`

输出目录：

- [outputs/live-oneshot-micro-20260410-v2/最后一班摆渡车](/Users/xy/StoryForge/outputs/live-oneshot-micro-20260410-v2/最后一班摆渡车)

确认结果：

- 单章短篇小说生成成功
- 角色图生成成功
- 场景首尾帧生成成功
- `Seedance` 视频片段成功下载
- 共生成 `6` 条视频片段
- 总片文件存在：
  - [full_story.mp4](/Users/xy/StoryForge/outputs/live-oneshot-micro-20260410-v2/最后一班摆渡车/rendered/full_story.mp4)

这次主要验证了：

- 单章短篇也能走完整视频链路
- “章节归章节，段归段”的新规则已生效
- `Seedream` 与 `Seedance` 真实 API 调用可完整跑通

## 当前产物结构

一次完整运行后，典型输出包括：

- `outline.json`
- `novel_package.json`
- `editorial_review.json`
- `workflow_trace.json`
- `character_visual_bible.json`
- `character_image_manifest.json`
- `segment_plan.json`
- `scene_image_manifest.json`
- `seedream_execution.json`
- `seedance_manifest.json`
- `seedance_execution.json`
- `video_workflow_trace.json`
- `concat_list.txt`
- `ffmpeg_concat.sh`
- `rendered/*.mp4`
- `rendered/full_story.mp4`

## 还需要做的事情

### 当前体检结论

2026-04-12 重新检查了一遍工程现状，当前主链路能跑通，测试基线已恢复。

- `uv run pytest` 当前结果为 `31 passed`
- `uv run ruff check` 当前结果为 `All checks passed!`
- 前端首页已从内部控制台方向调整为更偏商业展示页
- 首页首轮废代码清理已完成，已删除下线模块残留的 DOM 分支、渲染函数和一批未使用样式
- 前端已完成首轮模块化拆分：
  - `src/storyforge/api/static/app.js` 现在只保留薄入口
  - `src/storyforge/api/static/app/` 已拆出 `api / events / form / jobs / lightbox / navigation / refresh / render / state / utils`
  - `src/storyforge/api/static/app.css` 现在只保留样式入口
  - `src/storyforge/api/static/styles/` 已拆出 `base / home / workbench / detail / responsive`
  - `/` 页面不再直接返回 `static/index.html`，而是改为后端模板拼装
  - `src/storyforge/api/templates/` 已拆出 `console / partials / panels`
  - 资产页/队列页媒体预览已加入“内容未变化不替换 DOM”的渲染缓存，避免轮询时把正在播放的视频重建掉
- 小说、角色图、场景图、视频片段、总片合并链路已有基础实现
- 但项目还没有达到生产级稳定性，下一阶段应优先补“可靠任务执行、媒体质量控制、前端维护性”

### 1. 硬字幕兜底

当前虽然已把“硬字幕”要求写进 `Seedance` prompt，但模型是否真的把字幕烧进画面，还不稳定。

后续需要：

- 增加 ffmpeg 字幕兜底后处理
- 当 Seedance 未可靠烧字时，使用本地字幕轨再次生成硬字幕版总片

### 2. 视频预算控制

现在段数完全交给 LLM 判断，逻辑上是对的，但缺少“预算”层约束。

后续需要：

- 新增“每章最多几段”之类的视频预算参数
- 新增“单次项目最大总片段数”
- 新增“单章短篇优先 2-4 段”之类的软约束，而不是回到旧的章节=段

### 3. 更强角色一致性

当前的一致性仍然是“参考图 + prompt 锁定”级别，不是生产级角色锁定。

后续需要：

- 多角色同屏一致性增强
- 更稳定的人脸/服装 anchor 机制
- 姿态、年龄感、体态漂移检测
- 必要时引入局部重绘、分层合成或更强控制模型

### 4. 更强声音一致性

当前的音色一致性仍然是 prompt 级控制，不是声纹级控制。

后续需要：

- 角色级固定 speaker ID
- speaker embedding / voice cloning
- 多角色对白轮次控制
- 更细粒度的对白切句与配音编排

### 5. 短篇长度控制仍需更硬

虽然已经对单章短篇加了收紧 prompt，但“目标 500 字”并不等于模型一定精准命中。

后续需要：

- 写作后自动统计篇幅
- 超长时自动触发压缩重写
- 让短篇长度控制从“prompt 约束”升级为“生成后校正”

### 6. 队列持久化

当前任务元数据已经可持久化到 JSON 或 MySQL，但真正的执行队列仍是内存态。

后续需要：

- Redis / 真正的持久化执行队列
- 重试机制
- 幂等控制
- 多 worker 消费
- 进程重启后恢复任务

### 7. 存储与素材管理

当前素材默认只落本地目录。

后续需要：

- TOS / S3 / OSS 接入
- 外网可访问 URL 管理
- 素材生命周期管理
- 链接刷新与鉴权

### 8. 生产级治理

还未完成：

- 用户鉴权
- 项目隔离
- 审计日志
- 配额限制
- 管理后台
- 失败任务告警

### 9. ffmpeg 拼接稳健性

当前 `-c copy` 拼接已经可用，但在实际合并时出现过 `Non-monotonic DTS` 警告。

后续需要：

- 增加“copy 失败或时间戳异常时自动转码”的兜底策略
- 提高拼接结果在不同播放器上的兼容性

### 10. 前端清理与模块拆分

首轮前端废代码清理已经完成：

- 已清理首页下线模块对应的旧 DOM 引用
- 已清理首页旧渲染函数
- 已清理一批不再使用的首页样式和点击分支
- 已重新确认 `node --check src/storyforge/api/static/app.js`、`uv run ruff check`、`uv run pytest`

前端模块化首轮也已经完成：

- `app.js` 已降为薄入口文件
- 页面状态、DOM、API、表单、轮询、导航、任务提交、灯箱、渲染器、主控制流已拆到独立 JS 模块
- 样式已按全局、首页、工作台、详情、响应式拆到独立 CSS 文件
- HTML 已按布局、页头、灯箱、首页 panel、新建任务 panel、项目 panel、队列 panel 拆到模板目录
- 资产页和队列页渲染改成“markup 未变化则不替换 DOM”，已修复视频预览被轮询打断的问题
- 测试已更新为适配新的静态文件结构
- 已补最小前端冒烟测试：
  - Python 侧验证 UI 模板拼装输出
  - Node 侧验证 `renderInto()` 的“相同内容不重绘”行为

后续仍需要：

- 再做一轮样式与结构命名收敛，减少长期迭代中的选择器漂移
- 再继续收敛渲染层，把 `detail.js` 这种大模块继续按文档/图片/视频/概览拆小
- 继续补更高层的前端交互测试，例如切 tab、开灯箱、轮询期间播放不中断
- 如后续页面再变复杂，可以再引入正式模板引擎或前端构建链，但当前阶段还没必要

### 11. 实时状态与增量刷新

当前前端仍主要依赖轮询 `/v1/tasks`、`/v1/projects` 和任务 artifacts。任务和项目数量增加后，这种方式会越来越重。

后续需要：

- 增加 SSE 或 WebSocket，用于任务状态实时推送
- 增加按项目、按状态、按时间分页的任务列表接口
- artifacts 查询改为按选中任务或版本懒加载，而不是对所有任务批量拉取
- 前端显示更细粒度的阶段进度，例如故事、角色、场景、视频、合并

### 12. Seedance 执行效率与恢复能力

当前 Seedance 视频片段执行是串行提交、串行轮询、串行下载。视频片段一多，整体等待时间会明显变长。

后续需要：

- 改成并发提交 Seedance clip
- 并发轮询远端任务状态
- 单片失败后支持重试，不影响已完成片段
- 将远端 task id 和片段状态持续写回数据库，进程重启后可继续恢复轮询
- 为单片设置独立超时和错误记录，避免一个片段拖住整条故事

### 13. Git 与项目目录卫生

这一项已完成。

当前已处理为：

- 已初始化或确认当前工程根目录的 Git 工作区
- 已补充 `.gitignore`，确保以下目录不会进入版本管理：
  - `.env`
  - `.venv/`
  - `.uv-cache/`
  - `outputs/`
  - `workspace/`
  - `__pycache__/`
  - `.pytest_cache/`
  - `.ruff_cache/`
  - `tests/.tmp*/`
- 已清理明确无价值的本地产物：
  - `.DS_Store`
  - `__pycache__`
  - pytest / ruff / uv 缓存
  - 测试临时目录
- 已增加提交前检查脚本：
  - `scripts/check.sh`
- 已增加本地清理脚本：
  - `scripts/clean-local-artifacts.sh`

说明：

- `outputs/`、`workspace/`、`.venv/` 默认只忽略，不会在这一步直接删除，避免误删你的运行成果或开发环境。
- 如果后续你想做深度清理，可以执行：
  - `scripts/clean-local-artifacts.sh --deep`

## 下一步建议顺序

1. 继续做前端模块拆分和最小冒烟测试，把这轮清理结果固化下来。
2. 再做“可靠任务执行层”，补重试、取消、幂等、多 worker 和进程重启恢复。
3. 然后做“实时状态推送”和“增量刷新”，让页面能稳定显示长任务进度。
4. 接着做“硬字幕兜底”“视频预算控制”“角色一致性增强”“声音一致性增强”。
5. 再做“Seedance 并发执行”和“ffmpeg 拼接兜底”，降低长视频等待时间并提高总片成功率。
6. 最后补存储、鉴权、配额、审计日志、告警、多用户项目隔离和管理后台。
