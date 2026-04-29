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
  -> 分段视频
  -> 合并总片
```

## 已具备能力

- React + TypeScript + Vite 前端服务。
- FastAPI 后端服务和 Swagger 文档。
- MySQL 项目、任务、run 和产物索引。
- 异步任务队列。
- 小说正文生成、读取、编辑和保存。
- `chapter -> scene -> chunk -> segment` 结构化规划。
- 角色图生成、角色 prompt 保存、单角色重做、候选图选择。
- 场景母图生成、scene 级状态展示和引用关系展示。
- Seedance 分段视频生成。
- 上一段尾帧承接和真实参考图绑定说明。
- 分段审片台的视频 prompt 编辑、默认 prompt 恢复、连续性修复和重跑。
- 合并总片生成和前端展示。
- 项目删除保护，运行中任务会阻止删除。

## 当前约束

- Seedream 和 Seedance 的稳定性依赖外部 provider。
- 上一段尾帧承接依赖 provider 返回可用 `last_frame_url`。
- 跨 scene 连续性依赖规划阶段准确标记空间关系。
- 新地点会生成新的场景母图，同一地点才适合复用或承接。
- 前端不直接修改落盘 JSON，所有生产动作应通过 API 完成。

## 质量状态

已验证通过的检查：

```bash
uv run ruff check src/storyforge tests
uv run pytest tests/test_config.py tests/test_api.py -q
npm --prefix frontend run lint
npm --prefix frontend run test
npm --prefix frontend run build
git diff --check
```

当前全量 `uv run pytest -q` 仍有 5 个 pipeline 测试失败，集中在 Seedance prompt 断言、测试 mock 签名、scene repair changed fields 和 Seedream / Seedance 流程预期。它们需要单独修复，不属于本轮文档重写范围。

## 推荐下一步

- 修复 `tests/test_pipelines.py` 的 5 个失败点。
- 实现 scene repair 的 changed fields 收集。
- 继续补齐场景母图 prompt 编辑在前端的入口。
- 继续优化分段审片台的资源绑定展示和错误定位。
