# 当前状态

## 产品定位

StoryForge 当前定位为中文剧情短视频创作工作台。它不是单次生成工具，而是分阶段的视频生产系统，重点是可审阅、可修改、可重做和可追踪。

## 主链路

```text
小说转视频
  -> 编辑正文
  -> 场景结构
  -> 分段合同
  -> 角色图
  -> 场景母图
  -> 九宫格分镜图
  -> 分段视频
  -> 合并总片
```

## 已具备能力

- React + TypeScript + Vite 前端服务。
- FastAPI 后端服务和 Swagger 文档。
- MySQL 项目、任务、run 和产物索引。
- 异步任务队列。
- Chat-first Agent 创作入口：支持创建 Agent Session、发送创意消息、返回生产计划、确认后自动创建小说转视频项目，并通过前端轮询推进普通阶段任务。
- 前端已接入 `/console/agent` 聊天页，包含消息流、计划确认、阶段进度、最近事件、工作台入口和最终成片预览。
- Agent 计划确认前支持补充修改：再次发送普通消息会保留上一轮创意上下文，只覆盖最新消息明确修改的部分，避免把“改成 500 字”这类参数当成全新故事题材。
- Agent 支持历史会话：`GET /v1/agent-sessions` 返回最近会话，前端 Agent 页面左侧历史栏可切换老会话。
- Agent 支持暂停和继续：发送 `暂停/pause` 或点击“暂停”后进入 `paused`，发送 `继续/resume` 或点击“继续”后从当前进度接着跑。
- Agent 支持独立重新跑当前阶段：暂停或失败后可通过按钮/API 重新提交当前生产阶段，不会和“继续”混用。
- Agent 支持终止创作：发送 `停止/终止/取消/stop/cancel` 或点击前端“终止”后，Session 进入 `canceled`，不可恢复，Runner 不再推进后续阶段。
- 小说正文生成、读取、编辑和保存。
- `chapter -> scene -> chunk -> segment` 结构化规划。
- 角色图生成、角色 prompt 保存、单角色重做、候选图选择。
- 场景母图生成、scene 级状态展示和引用关系展示。
- 小说转视频支持九宫格分镜模式，按 segment 生成 3x3 连续分镜图，把 timed beats 展开为 9 个起始/推进/结果关键帧，再把九宫格作为 Seedance 主参考图；需要承接上一段时额外提交尾帧。
- 角色图、场景母图和九宫格分镜图每次提交前可选择 Seedream 4.5 或 GPT Image 2；九宫格任务结果写入 `storyboard_grid_manifest.json` 和 `assets/storyboards/`。
- 独立生图，单入口内支持 GPT Image 2 / Seedream 4.5 的文生图和基于参考图 URL 的图生图；前端通过能力接口只展示当前模型支持的分辨率和比例；Seedream 4.5 支持水印开关；生成结果必须保存后才会进入作品库。
- 作品库按产品类型展示小说转视频和生图产品，生图卡片使用生成图作为封面，并进入生图作品详情页查看 Prompt、参数和请求 payload。
- Seedance 分段视频生成。
- 上一段尾帧承接和真实参考图绑定说明。
- 分段审片台的视频 prompt 编辑、默认 prompt 恢复、连续性修复和重跑。
- 合并总片生成和前端展示。
- 项目删除保护，运行中任务会阻止删除。

## 当前约束

- Seedream、GPT Image 2 和 Seedance 的稳定性依赖外部模型服务。
- 上一段尾帧承接依赖视频服务返回可用 `last_frame_url`。
- 九宫格分镜质量依赖场景母图和角色图是否已经稳定；跨段开场连续性依赖上一段尾帧是否可用。
- 跨 scene 连续性依赖规划阶段准确标记空间关系。
- 同一 scene 内共用场景母图；跨 scene 同空间推进会参考上一场母图生成新母图；新地点会生成新的场景母图。
- 前端不直接修改落盘 JSON，所有生产动作应通过 API 完成。
- 图生图当前使用可被生图服务访问的参考图 URL；本地上传需要接入对象存储或可公网访问的上传服务。
- Agent 需求理解已改为 LLM-only：规划阶段调用现有 LLM backend 的结构化输出，LLM 不可用或结构化失败会进入 failed，不使用关键词规则兜底。
- Agent Runner 通过 Session API 轮询推进，不是后台常驻扫描器；如果前端或外部 Agent 不轮询，Session 不会继续提交下一阶段。
- Agent 前端当前只做第一版 `novel_to_video / auto_full_pipeline`，不做长期记忆或自由工具调用。
- Agent 自动生产开始后，普通聊天消息不会重写生产计划；具体修改应进入项目工作台操作。
- Agent 暂停和终止都是会话级控制；已经进入底层执行的单个长任务不保证立即中断。暂停后任务完成也不会自动推进，继续后才会接着跑；终止后不可恢复。

## 质量状态

已验证通过的检查：

```bash
uv run ruff check src/storyforge tests
uv run pytest tests/test_storyboard_grid.py tests/test_seedance.py -q
uv run pytest tests/test_api.py -q
npm --prefix frontend run lint
npm --prefix frontend run test -- --run
npm --prefix frontend run build
git diff --check
```

## 推荐下一步

- 为独立生图补充本地上传能力。
- 做 Agent 自动创作真实端到端长链路验证，覆盖小说到合并成片。
- 为 Agent 自动创作补更细的失败恢复入口和阶段级重跑结果展示。
- 补充九宫格分镜图的局部重做和失败状态视觉细节。
- 实现 scene repair 的 changed fields 收集。
- 继续补齐场景母图 prompt 编辑在前端的入口。
- 继续优化分段审片台的资源绑定展示和错误定位。
