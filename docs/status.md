# 工程状态

> 截至 `2026-04-15`

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

当前默认路径：

- 小说生成：DeepSeek
- 角色图 / 场景图：Seedream 4.5
- 视频片段：Seedance 2.0
- 服务层：FastAPI + 异步任务队列
- 元数据：MySQL 必选；没有数据库不允许运行

## 已完成

### 小说生成

- 结构化多 Agent 小说工作流
- 小说链路已拆成 `project.story` 与 `project.story_analysis`
- `project.story` 先生成整部小说草稿，并落为 `story_source.json`
- Web 端已经支持直接展示、编辑并保存小说正文
- `project.story_analysis` 再基于当前 `story_source` 做 cast / 角色 / 分章结构化
- `Cast Analyzer` 角色层级与关系图解析阶段
- `novel_package.json` 已精简成运行态最小包，只保留图片与视频阶段真实消费的数据
- `novel_audit.json` 单独保存 `review`、`workflow_trace` 与分析上下文
- 角色 `voice_profile` 输出并贯通后续视频 prompt
- 角色结构约定已调整为“LLM Cast Analysis 优先，heuristics 只做 fallback / repair”
- cast slots 会尽量保留小说草稿中的角色指代和 `source_evidence`，复杂 brief 不再默认压成固定双人模板
- 角色正式名字唯一性已下沉到 `CharacterRosterSchema` 校验；一旦重名会触发 LLM structured retry，连续失败则显式报错
- `cast_slot_id` 唯一性已下沉到 `CharacterRosterSchema` 校验；重复槽位会触发 structured retry，避免两个角色共用 `lead_1`
- `Character Designer` prompt 已改成固定索引合同：会明确列出 `characters[0]`、`characters[1]` 分别必须对应哪个 `cast_slot_id`，数量不匹配时重试也会重复下发这份合同
- 如果 `Character Designer` 首次只返回了部分角色，系统会对缺失 slot 再发一次结构化补生请求，再合并回完整角色表
- LangChain structured output 已开启 raw 响应回收：如果 DeepSeek 没有触发 tool call 但返回了 JSON 文本，会提取 JSON 后再校验；如果返回空结构，会给出明确失败原因，不再暴露 Pydantic 的 `input_value=None`
- `Cast Analyzer` 输出现在要求 `source_evidence` 必须能在小说正文中定位，减少“正文没出现的人却被补进角色表”的情况
- fallback 角色卡已改为只覆盖目标 slots，不再按旧的补位策略自动多塞一个核心角色
- 已删除旧配置残留 `major_character_count` 与 `review_passes`，角色数量改由小说正文、cast slots 和结构化校验共同约束

### 视频规划与媒体链路

- 角色视觉档案生成
- 视频规划文件已前移到 `project.story_analysis` 阶段生成，不再等到角色图阶段才拆分视频
- 角色定妆卡任务生成与真实调用
- 章节到视频段的拆分规划
- 视频分段 prompt 已加入中文口播字数预算，要求对白、旁白、硬字幕和 `duration_seconds` 匹配
- 视频分段归一化层会在 LLM 塞入过量对白时自动拉长到最多 12 秒或拆成多个子片段
- 视频分段现在会显式输出 `requires_mid_frame` / `mid_frame_prompt`
- 视频分段现在会显式输出 `start_frame_characters` / `mid_frame_characters` / `end_frame_characters`
- 对多人同框、长时长、动作推进明显的片段，会额外生成中段锚点帧
- 场景关键帧任务生成与真实调用
- 场景图阶段改为按帧选择角色参考图，不再按整段 `involved_characters` 把所有角色图都塞进首帧、尾帧和中段
- 帧级角色归一化会优先参考对应时间节拍：如果中段节拍只是“男主等待女主”，中段帧只绑定男主参考图，不会因为整段涉及两人就把女主塞进画面
- 场景生图 prompt 现在显式禁止任何字幕、对白字卡、聊天气泡、旁白框和其它可见文字；对白与硬字幕只留到视频阶段烧录
- 即使上游分镜 prompt 混入“林远说：……”或“字幕：……”这类文本，场景生图阶段也会先清洗成纯视觉动作描述，再发给 Seedream
- 场景图与视频阶段现在支持 `segment_id` 单段执行，不再只能整批跑完
- Seedance manifest 生成
- Seedance 提交层现在会优先尝试“角色参考图 + 中段锚点图（如有）+ 首尾帧”的完整上下文；若接口返回 400，会自动降级重试为“中段锚点图 + 首尾帧”，最后再退到“仅首尾帧”
- Seedance 任务创建、轮询、下载
- Seedance pending / timeout 片段支持重跑恢复：复用 `remote_task_id` 查询远程状态，成功后补下载
- 总片合并已改成手动触发；用户可在页面点击“合并已生成片段”，由 ffmpeg 生成 `full_story.mp4`
- Seedance manifest 标题会继承真实小说标题，旧产物重载时会从 `novel_package.json` / `story_source.json` 恢复标题，避免显示成 `segment_video_manifest`

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
- 小说域已拆分为 service / prompts / schemas / fallbacks / repair / rules

## 当前验证基线

最近一次本地校验结果：

- `uv run ruff check src/storyforge tests`
  - `All checks passed!`
- `uv run pytest`
  - `74 passed`
- `uv run pytest tests/test_config.py tests/test_mysql_store.py tests/test_api.py`
  - `18 passed`

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
- 角色定妆图已简化为 `SF-TURN-01` 横版 16:9 白底三视图 prompt，只保留角色姓名和人物描述，输出正面、左侧面、背面；不再要求信息格、色卡、材质块或灰底设计板
- 声音一致性仍是 prompt 级，不是声纹级
- 硬字幕主要依赖模型生成，缺少稳定的后处理兜底
- 虽然已经支持按 segment 逐段重跑，但暂时还没有“按 segment 自动生成后再异步串行下一段”的工作流编排

### 小说理解

- cast 解析已经从 heuristics 主导改为 LLM 主导，但仍然没有审校后自动回改闭环

### 内容与上下文

- 内容合规当前完全依赖接入的 LLM / Seed 模型供应商策略，后端不再做本地规则拦截
- 长篇上下文仍主要依赖阶段输入和最近章节摘要，不是长期记忆式写作

### 生产可用性

- Seedream / Seedance 的字段兼容性仍可能因账户环境不同而需要微调
- 缺少生产级重试、幂等和失败恢复闭环
- 缺少配额、审计和多用户治理

## 推荐下一步

### 第一优先级

1. 把执行队列替换成生产级持久化队列
2. 补 Seedance 下载器 / 重试 / 超时恢复
3. 接入对象存储和公网素材 URL 管理

### 第二优先级

1. 增加硬字幕 ffmpeg 兜底
2. 增加失败任务重放与手动重试
3. 增加更强的角色一致性检查

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
