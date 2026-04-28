# 当前状态

## 产品状态

StoryForge 当前是一套可运行的故事到视频工作台，主链路为：

```text
生成小说 -> 编辑正文 -> 生成场景结构 -> 生成分段合同 -> 生成角色图 -> 生成场景母图 -> 逐段生成视频 -> 合并视频
```

## 已具备能力

- Web 工作台和 FastAPI 接口。
- MySQL 项目、任务、run 和产物索引。
- LangChain 结构化规划、重试和修复。
- 小说正文可编辑并作为后续阶段真源。
- `chapter -> scene -> chunk -> segment` 视频结构规划。
- 角色定妆图生成、prompt 编辑、候选图确认和替换。
- 无人物场景母图生成、prompt 编辑和重做。
- Seedance 分段视频生成，支持场景母图、上一段视频尾帧和角色图参考绑定。
- 当前 segment 的 motion plan、Seedance prompt、提交请求和参考图绑定展示。
- 分段视频合并。
- Python lint、pipeline 测试和前端轻量测试。

## 当前约束

- Seedream / Seedance 长任务依赖外部 provider 稳定性和返回字段完整性。
- 跨 scene 连续性依赖 scene 规划准确标记空间关系；空间变化不明确时按新场景处理。
- 上一段视频尾帧只有在 provider 返回可用 `last_frame_url` 后才能用于下一段承接。
- 工作台以当前项目输出目录为产物来源，手工改动输出文件可能导致页面状态和任务状态不一致。

## 推荐验证

```bash
uv run ruff check src tests
uv run pytest
node tests/js/prompt_tools.test.mjs
node tests/js/segment_review.test.mjs
node tests/js/timeline_data.test.mjs
```
