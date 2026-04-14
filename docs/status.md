# 工程状态

> 截至 `2026-04-14`

这份文档只回答三件事：

1. 现在已经完成了什么
2. 当前还缺什么
3. 下一步最值得做什么

## 当前定位

StoryForge 当前是一个“结构化小说生成 + 小说转视频”的工程化工作流系统，而不是通用自治 Agent。

当前默认路径：

- 小说生成：DeepSeek
- 角色图 / 场景图：Seedream 4.5
- 视频片段：Seedance 2.0
- 服务层：FastAPI + 异步任务队列
- 元数据：本地 JSON 或 MySQL

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
- 场景首尾帧任务生成与真实调用
- Seedance manifest 生成
- Seedance 任务创建、轮询、下载
- Seedance pending / timeout 片段支持重跑恢复：复用 `remote_task_id` 查询远程状态，成功后补下载并继续合并总片
- `ffmpeg` 自动合并总片
- Seedance manifest 标题会继承真实小说标题，旧产物重载时会从 `novel_package.json` / `story_source.json` 恢复标题，避免显示成 `segment_video_manifest`

### Web / API / 数据

- 五阶段 Web 工作台
- FastAPI HTTP 接口
- 项目级 `project_id`
- 项目 / 任务元数据持久化
- 任务运行中增量展示已落盘产物
- 前端已展示任务和阶段级失败原因，不再只显示“异常”
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
  - `66 passed`

最近一次真实故障定位：

- 时间：`2026-04-14`
- 阶段：`project.story_analysis`
- 任务：`character-designer`
- 根因：DeepSeek OpenAI-compatible 接口在结构化链路中可能出现两类问题：`create_agent + ToolStrategy` 多轮工具消息不兼容，或 `with_structured_output` 没有返回 parsed tool 结果
- 修复：结构化输出改为 LangChain `ChatModel.with_structured_output(method="function_calling", include_raw=True)` 的单轮结构化调用；raw 内容如果是 JSON 会被回收解析，空结构会显式报错并进入 StoryForge 外层 structured retry

最近一次视频任务故障定位：

- 时间：`2026-04-14`
- 阶段：`project.videos`
- 现象：任务显示 `Task was interrupted by a service restart.`
- 根因：服务以 `--reload` 启动，代码改动触发热重载，中断 Seedance 长任务
- 修复：启动恢复逻辑从“把 running 改 failed”调整为“把 running 重新排回 queued”
- 使用建议：跑真实 Seedream / Seedance 长任务时不要用 `--reload`

最近一次真实 LLM 自测：

- 时间：`2026-04-13`
- 模型：`DeepSeek`
- 样例：`旧城回响`
- 结果：`Cast Analyzer` 真实拆出 `记者 / 昔日恋人 / 地下线人 / 地方势力继承人 / 退休警察 / 失踪父亲`
- 结果：故事形态被识别为 `single_lead_with_supporting_cast`
- 结果：`Character Designer` 产出了与这些 slot 对齐的正式角色卡

## 当前主要限制

### 基础设施

- 执行队列仍是内存态
- 重启恢复只是重新排队，不是严格幂等执行队列
- 还没有对象存储
- 还没有认证与权限系统
- 还没有 webhook / 回调机制

### 媒体质量

- 角色一致性仍以“参考图 + prompt 锁定”为主
- 角色定妆图已简化为 `SF-TURN-01` 横版 16:9 白底三视图 prompt，只保留角色姓名和人物描述，输出正面、左侧面、背面；不再要求信息格、色卡、材质块或灰底设计板
- 声音一致性仍是 prompt 级，不是声纹级
- 硬字幕主要依赖模型生成，缺少稳定的后处理兜底

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
