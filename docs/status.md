# 工程状态

> 截至 `2026-04-17`

这份文档只回答三件事：

1. 现在已经完成了什么
2. 当前还缺什么
3. 下一步最值得做什么

这里不再重复接口示例、操作步骤或产物目录结构：

- 怎么使用：看 [usage.md](usage.md)
- 接口细节：看 [api.md](api.md)
- 模块边界：看 [architecture.md](architecture.md)

## 当前定位

StoryForge 当前是一个“结构化小说生成 + 小说转视频”的工程化工作流系统，而不是通用自治 Agent。
默认运行链路、模型入口和安装方式以 [README](../README.md) 与 [usage.md](usage.md) 为准；这里主要记录完成度、限制和路线图。

## 已完成

### 小说生成

- 结构化多 Agent 小说工作流
- 小说链路已拆成 `project.story` 与 `project.story_analysis`
- `project.story` 先生成整部小说草稿，并落为 `story_source.json`
- Web 端已经支持直接展示、编辑并保存小说正文
- `project.story_analysis` 再基于当前 `story_source` 做 cast / 角色 / 分章结构化
- `story_pipeline`、`video_planning`、`video_pipeline` 与 `orchestrator` 的运行入口默认值已统一为 `use_llm=True`
- `build_agent_backend()` 默认值也已统一为 `use_llm=True`；运行态代码里已没有 `use_llm=False` 默认入口残留
- 运行态 service 已移除 `DryRun` / 结构化静默兜底分支；live LLM 输出不合格时只会 retry / fail-fast
- `Story Architect`、`Story Drafter`、`Chapter Planner`、`Editorial Reviewer` 已补 step validator；缺标题、缺章、空正文、空 beats 会直接 structured retry / fail-fast
- `cast_analysis`、`character_roster`、`chapter_plan_set` repair 已收紧为字段规整、角色名归一化和顺序校正，不再在 repair 阶段补角色、补关系或补章节模板内容
- `Cast Analyzer` 角色层级与关系图解析阶段
- `novel_package.json` 已精简成运行态最小包，只保留图片与视频阶段真实消费的数据
- `novel_audit.json` 单独保存 `review`、`workflow_trace` 与分析上下文
- 角色 `voice_profile` 输出并贯通后续视频 prompt
- 角色结构约定已调整为“LLM Cast Analysis 优先，heuristics 只做规则校验与轻量 repair”
- cast slots 会尽量保留小说草稿中的角色指代和 `source_evidence`，复杂 brief 不再默认压成固定双人模板
- 角色正式名字唯一性已下沉到 `CharacterRosterSchema` 校验；一旦重名会触发 LLM structured retry，连续失败则显式报错
- `cast_slot_id` 唯一性已下沉到 `CharacterRosterSchema` 校验；重复槽位会触发 structured retry，避免两个角色共用 `lead_1`
- `Character Designer` prompt 已改成固定索引合同：会明确列出 `characters[0]`、`characters[1]` 分别必须对应哪个 `cast_slot_id`，数量不匹配时重试也会重复下发这份合同
- 如果 `Character Designer` 首次只返回了部分角色，系统会对缺失 slot 再发一次结构化补生请求，再合并回完整角色表
- LangChain structured output 已开启 raw 响应回收：如果 DeepSeek 没有触发 tool call 但返回了 JSON 文本，会提取 JSON 后再校验；如果返回空结构，会给出明确失败原因，不再暴露 Pydantic 的 `input_value=None`
- `Cast Analyzer` 输出现在要求 `source_evidence` 必须能在小说正文中定位，减少“正文没出现的人却被补进角色表”的情况；同时对“女学生林栀 / 年轻监考老师周骁”这类带修饰语证据增加了姓名 / 稳定称呼容错匹配，避免误判
- Web 创建页的 `模型 ID` 已改为只读默认值，不再允许手工输入，避免前端表单与后端支持矩阵脱节
- 已删除旧配置残留 `major_character_count` 与 `review_passes`，角色数量改由小说正文、cast slots 和结构化校验共同约束

### 视频规划与媒体链路

- 角色视觉档案生成
- 视频规划文件已前移到 `project.story_analysis` 阶段生成，不再等到角色图阶段才拆分视频
- 视频结构已经从纯 `chapter -> segment` 升级为 `chapter -> scene -> segment`
- 已新增 `scene_plan.json` 作为场景级主规划文件
- 视频 segment 结构化规划在 live LLM 模式下已改为 fail-fast：坏结构最多自动重试 3 次，仍失败就显式终止，不再静默回退成伪规划
- 视频 segment 规划已增加模板污染校验：如果 `summary / narration / prompt / timed_beats` 混入 `当前片段聚焦`、`结尾要保留`、`当前小段聚焦` 等分析话术，会直接触发 structured retry
- `video-character-bible` 与 `video-segment-planner` 现在都要求完整覆盖小说角色表与章节；缺角色、缺章节或缺片段会直接 retry / fail-fast
- `scene_bible` 已接入结构化规划主链路，并真实进入场景图 / 视频 prompt
- `scene_master_frame` 已接入结构化规划、运行时合同、场景图执行链路、Seedance 参考图链路和前端时间线索引
- `scene_master_frame` 现在是严格的无角色空场景参考图，只锁环境与空间，不再允许人物、背影或角色调度进入母图 prompt
- 当 `scene_bible` 太弱时，`scene_master_frame` 现在会自动从同一 `scene` 的 `scene_prompt / start_frame_prompt / mid_frame_prompt / end_frame_prompt` 中提炼无角色环境锚点，回填地点、时间、光线、空间布局和背景锚点，再生成母图 prompt
- `shot_state` 已接入结构化规划主链路，并真实进入场景图 / 视频 prompt
- `continuity_link` 已接入结构化规划主链路，并真实进入首帧承接判断、场景图 prompt 与 Seedance prompt
- 已新增规则型连续性校验器 `V1`
- 已新增可选的 `V2` 连续性软审校层
- 当前会自动落盘 `continuity_report.json`
- `continuity_report.json` 目前会基于 `scene_plan.json`、`scene_image_manifest.json`、`seedance_manifest.json` 和本地视频输出，输出 `V1` 规则审校以及按模式触发的 `V2` LLM 软审校，检查场景母图状态、关键帧缺失、跨段承接、帧级角色、对白时长预算和视频执行状态
- `segment_plan.json` 现在保留为执行层 flat 索引，便于逐段生成与重试
- 角色定妆卡任务生成与真实调用
- 章节到视频段的拆分规划
- 视频分段 prompt 已加入中文口播字数预算，要求对白、旁白、硬字幕和 `duration_seconds` 匹配
- 视频分段归一化层会在 LLM 塞入过量对白时自动拉长到最多 12 秒或拆成多个子片段
- 视频分段现在会显式输出 `requires_mid_frame` / `mid_frame_prompt`
- 视频分段现在会显式输出 `start_frame_characters` / `mid_frame_characters` / `end_frame_characters`
- 对多人同框、长时长、动作推进明显的片段，会额外生成中段锚点帧
- 场景关键帧任务生成与真实调用
- 同一 scene 现在会先生成一张 `scene_master_frame`，再派生该 scene 下所有 segment 的首帧 / 中段 / 尾帧
- segment 关键帧现在会优先基于 `scene_master_frame + 当前帧角色图 + 条件承接帧` 派生，而不是每段都从零起图
- `project.scenes` 现在支持 `scene_id + master_only`，可以只重生成单个 scene 的 `scene_master_frame`
- 同一 scene 下的片段现在共享 `scene_bible`，repair 会在字段缺失时自动补齐地点、时间、天气、光线、背景锚点和连续性说明
- 每个 segment 现在共享正式 `shot_state`，repair 会在字段缺失时自动补齐景别、镜头推进、调度、动作推进、道具连续性和尾部承接状态
- 每个 segment 现在共享正式 `continuity_link`，repair 会在字段缺失时自动补齐上一段承接关系、开场匹配要求、延续元素与允许变化
- 场景图阶段改为按帧选择角色参考图，不再按整段 `involved_characters` 把所有角色图都塞进首帧、尾帧和中段
- 帧级角色归一化会优先参考对应时间节拍：如果中段节拍只是“男主等待女主”，中段帧只绑定男主参考图，不会因为整段涉及两人就把女主塞进画面
- 场景生图 prompt 现在显式禁止任何字幕、对白字卡、聊天气泡、旁白框和其它可见文字；对白与硬字幕只留到视频阶段烧录
- 即使上游分镜 prompt 混入“林远说：……”或“字幕：……”这类文本，场景生图阶段也会先清洗成纯视觉动作描述，再发给 Seedream
- 场景图与视频阶段现在支持 `segment_id` 单段执行，不再只能整批跑完
- 同一 scene 内的连续 segment 现在优先按 `scene_id` 判定是否复用上一段尾帧
- Seedance manifest 生成
- Seedance 提交层现在会优先尝试“角色参考图 + 中段锚点图（如有）+ 首尾帧”的完整上下文；若接口返回 400，会自动降级重试为“中段锚点图 + 首尾帧”，最后再退到“仅首尾帧”
- Seedance 任务创建、轮询、下载
- Seedance pending / timeout 片段支持重跑恢复：复用 `remote_task_id` 查询远程状态，成功后补下载
- 总片合并已改成手动触发；用户可在页面点击“合并已生成片段”，由 ffmpeg 生成 `full_story.mp4`
- Seedance manifest 标题会继承真实小说标题，旧产物重载时会从 `novel_package.json` / `story_source.json` 恢复标题，避免显示成 `segment_video_manifest`
- 已新增 `project.continuity_repair` 首版自动回改闭环：会基于 `continuity_report.json` 里的 `segment` 级问题，让 LLM 只重写目标片段合同，再只重跑该段场景图与视频
- 智能修复阶段会额外落盘 `continuity_repair_{segment_id}.json`，保存修复摘要、触发问题、前后差异和改动字段

### Web / API / 数据

- 五阶段 Web 工作台
- FastAPI HTTP 接口
- 项目级 `project_id`
- 项目 / 任务元数据持久化
- 已删除运行时内存版项目 / 任务 store，生产路径只保留 MySQL 实现
- 任务运行中增量展示已落盘产物
- 前端已展示任务和阶段级失败原因，不再只显示“异常”
- Seedance 提交失败时会把真实 HTTP 响应体、所用 payload 变体和 segment 级错误摘要写入 `seedance_execution.json`，任务页也会直接显示具体失败原因
- 任务产物接口已输出 `planned_segments`，前端时间线会先展示完整片段列表，再允许逐段生成场景图和视频
- 任务产物接口现在会把 `scene_id` / `scene_title` / `scene_summary` / `scene_master_frame` 一起下发，前端时间线按 scene 分组展示 segment
- 任务产物接口现在还会返回 `continuity_report` 与 `continuity_summary`
- 任务产物接口现在还会返回按 `scene` / `segment` 聚合的连续性问题明细，供时间线直接消费
- `continuity_summary` 当前会额外返回 `review_mode_requested / review_mode_effective / v2_review_status / v2_issue_count / v2_note`
- 前端时间线现在可在 scene 头部单独触发“重生成场景母图”，并直接展示该任务的状态与失败原因
- 前端时间线现在会直接展示连续性风险：
  - 时间线头部显示最近一次校验时间、总体状态和 top issues
  - scene 头部显示 scene 级风险摘要
  - segment 卡片显示 segment 级风险列表，并把推荐重跑的按钮高亮
- 前端时间线现在可对高风险 segment 直接触发“智能修复该段”
- 创建页和项目详情页现在都可以为当前 run 选择 `V2` 软审校模式：`off / auto / on`
- 前端已提供手动合并总片入口，不再在视频任务完成后自动生成 `full_story.mp4`
- 资产页视频预览轮询稳定性修复
- 故事正文保存后自动清理旧的结构化和媒体派生产物
- 支持删除项目：删除项目元数据、任务记录和安全范围内的关联输出目录；项目有 queued / running 任务时返回 409
- 服务启动时残留的 `running` 任务会重新排回 `queued`，不再因为一次重启直接标记为失败
- `project.story_analysis` 已增加后端幂等保护：同一故事正文修订已经存在 queued / running / completed 结构化任务时，不再重复创建新任务
- 任务详情页已按 `pipeline_root_task_id` 聚合同一版本阶段状态，结构化完成后按钮会禁用；提交按钮逻辑已抽成共用 helper，避免重复 try/catch 和双击重复提交

### 代码结构

- 应用层已拆分为 container / runtime / handlers / support / persistence
- 视频域已拆分为 facade / prompting / repair / planning
- 小说域已拆分为 service / prompts / schemas / repair / rules；测试侧 deterministic 夹具已迁出运行时源码

## 当前验证基线

最近一次本地校验结果：

- `uv run ruff check src/storyforge tests`
  - `All checks passed!`
- `uv run pytest`
  - `74 passed`
- `uv run pytest tests/test_config.py tests/test_mysql_store.py tests/test_api.py`
  - `18 passed`
- `uv run pytest tests/test_pipelines.py tests/test_api.py -k 'continuity or bootstrap or openai_selection or artifacts or scene_master or master_only or selected_segment or selected_scene'`
  - `17 passed`
- `uv run pytest tests/test_pipelines.py -k 'runtime_fallback or does_not_resolve_fallback or build_default_segment_plan or deterministic_character_roster or deterministic_cast_analysis or missing_chapters or dual_lead_chapter_repair_does_not_append_missing_counterpart or dual_lead_repair_does_not_synthesize_missing_second_character'`
  - `9 passed`
- `uv run ruff check src/storyforge/domains/novel/service.py src/storyforge/domains/video/planning.py src/storyforge/domains/video/repair.py src/storyforge/domains/video/prompting.py src/storyforge/domains/video/schemas.py src/storyforge/api/artifacts.py tests/_deterministic_novel_builders.py tests/test_pipelines.py`
  - `All checks passed!`

本轮针对视频规划污染问题补充校验：

- `uv run pytest tests/test_pipelines.py -k "story_and_video_pipeline or video_segment_plan_meta_template_phrases_trigger_retry or video_segment_planner_live_failure_raises_clear_error or load_video_planning_artifacts_restores_story_title_from_novel_package"`
  - `4 passed`
- `uv run ruff check src/storyforge/domains/video src/storyforge/pipelines tests/test_pipelines.py`
  - `All checks passed!`

当前已知运行建议：

- 跑真实 Seedream / Seedance 长任务时不要使用 `--reload`
- 生产路径现在是 MySQL-only；没有可连接数据库时不会降级为本地内存运行

## 当前主要限制

### 基础设施

- 执行队列仍是进程内异步队列
- 重启恢复只是重新排队，不是严格幂等执行队列
- 还没有对象存储
- 还没有认证与权限系统
- 还没有 webhook / 回调机制

### 媒体质量

- 角色一致性仍以“参考图 + prompt 锁定”为主
- `V2` 连续性软审校已经上线，且已补上首版 `segment` 级自动回改闭环；但 `scene_master_frame` / scene 级自动修复还没做
- `scene_master_frame` 的环境回填目前仍是规则型环境推导，不是独立的环境一致性评估器；输入文本特别弱时，仍可能拿不到足够细的固定道具与空间布局
- Seedream 场景帧默认参考图策略已显式固定：优先 `时间承接帧 -> scene anchor / scene_master_frame -> 当前帧实际出镜角色图`，单帧总参考图最多 4 张，角色参考图最多 2 张，不再把未出镜角色硬塞进单人帧
- 最近一次 4 样本真实批量对比也支持这条默认策略：单人帧以 `3 refs` 最稳，额外塞入未出镜角色会直接污染画面；双人帧则明显更适合 `4 refs`
- 角色定妆图已简化为 `SF-TURN-01` 横版 16:9 白底三视图 prompt，只保留角色姓名和人物描述，输出正面、左侧面、背面；不再要求信息格、色卡、材质块或灰底设计板
- 声音一致性仍是 prompt 级，不是声纹级
- 硬字幕主要依赖模型生成，缺少稳定的后处理兜底
- 虽然已经支持按 segment 逐段重跑，但暂时还没有“按 segment 自动生成后再异步串行下一段”的工作流编排
- 连续性问题已经接到前端时间线，且已支持“发现问题 -> 单段生成修复方案 -> 局部回改”的首版闭环；但还没有覆盖 `scene_master_frame`、scene 级结构漂移和跨段批量协同修复

### 小说理解

- cast 解析已经从 heuristics 主导改为 LLM 主导，但仍然没有审校后自动回改闭环

### 内容与上下文

- 内容合规当前完全依赖接入的 LLM / Seed 模型供应商策略，后端不再做本地规则拦截
- 长篇上下文仍主要依赖阶段输入和最近章节摘要，不是长期记忆式写作

### 生产可用性

- Seedream 已补 `image` / `reference_images` 多 payload 兼容回退，以及多参考图失败时的保守降级策略；当前 `ark` 网关已实测通过 1-4 张参考图和 `reference_images` 的 `string / list / objects` 形式，但不同账户环境下的最佳字段和顺序仍可能需要联调微调
- 已补真实质量探针对比脚本，可基于现有 run 直接生成单人帧 / 双人帧的 2/3/4 refs 对比样例
- 批量对比脚本现在也支持从已有批次目录直接重建 `summary.json / summary.md`，不必为补汇总重新消耗外部接口
- 缺少生产级重试、幂等和失败恢复闭环
- 缺少配额、审计和多用户治理

## 推荐下一步

### 第一优先级

1. 把执行队列替换成生产级持久化队列
2. 补 Seedance 下载器 / 重试 / 超时恢复
3. 接入对象存储和公网素材 URL 管理

### 第二优先级

1. 把当前 `segment` 级智能修复扩展到 `scene_master_frame` / scene 级自动修复
2. 给 `V2` 增加更细的触发阈值、成本控制与 reviewer prompt 迭代
3. 在已打通的 1-4 图兼容基础上，继续用更大样本校准 `Seedream 4.5` 的最佳参考图顺序、图数上限与画质稳定性
4. 增加硬字幕 ffmpeg 兜底
5. 增加失败任务重放与手动重试

### 第三优先级

1. 认证与项目隔离
2. 配额和审计日志
3. 更强的声音一致性控制

## 是否适合直接上生产

当前更适合：

- 原型验证
- 单团队内部使用
- 模型联调
- 内容工作流验证

当前还不适合：

- 多租户 SaaS
- 高并发生产环境
- 对稳定性和成本控制要求很高的商业发布

## 相关文档

- [README](../README.md)
- [使用文档](usage.md)
- [架构文档](architecture.md)
- [开发文档](development.md)
