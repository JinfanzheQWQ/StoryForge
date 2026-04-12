# 工程状态

> 截至 `2026-04-12`

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
- 角色卡、章节蓝图、章节草稿、审校结果落盘
- `workflow_trace.json` 中间产物追踪
- 角色 `voice_profile` 输出并贯通后续视频 prompt

### 视频规划与媒体链路

- 角色视觉档案生成
- 角色定妆卡任务生成与真实调用
- 章节到视频段的拆分规划
- 场景首尾帧任务生成与真实调用
- Seedance manifest 生成
- Seedance 任务创建、轮询、下载
- `ffmpeg` 自动合并总片

### Web / API / 数据

- 四步式 Web 工作台
- FastAPI HTTP 接口
- 项目级 `project_id`
- 项目 / 任务元数据持久化
- 任务运行中增量展示已落盘产物
- 资产页视频预览轮询稳定性修复

### 代码结构

- 应用层已拆分为 container / runtime / handlers / support / persistence
- 视频域已拆分为 facade / prompting / repair / planning
- 小说域已拆分为 service / fallbacks / repair / rules

## 当前验证基线

最近一次本地校验结果：

- `uv run ruff check src/storyforge tests`
  - `All checks passed!`
- `uv run pytest`
  - `33 passed`

## 当前主要限制

### 基础设施

- 执行队列仍是内存态
- 还没有对象存储
- 还没有认证与权限系统
- 还没有 webhook / 回调机制

### 媒体质量

- 角色一致性仍以“参考图 + prompt 锁定”为主
- 声音一致性仍是 prompt 级，不是声纹级
- 硬字幕主要依赖模型生成，缺少稳定的后处理兜底

### 生产可用性

- Seedream / Seedance 的字段兼容性仍可能因账户环境不同而需要微调
- 缺少重试、幂等和失败恢复闭环
- 缺少配额、审计和多用户治理

## 推荐下一步

### 第一优先级

1. 把执行队列替换成持久化队列
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
