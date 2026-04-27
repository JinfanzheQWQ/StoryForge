# 使用文档

这份文档说明如何配置、启动并完成一轮 StoryForge 制作流程。接口字段见 [api.md](api.md)，系统结构见 [architecture.md](architecture.md)。

## 环境要求

- Python `>= 3.11`
- `uv`
- `ffmpeg`
- MySQL 8+
- 可访问的 LLM provider
- 可访问的 Seedream / Seedance provider

## 安装

```bash
uv sync
```

## 环境变量

复制示例文件：

```bash
cp .env.example .env
```

常用变量：

```bash
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=your_deepseek_base_url
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
SEEDREAM_API_KEY=your_seedream_api_key
SEEDREAM_BASE_URL=your_seedream_base_url
SEEDANCE_API_KEY=your_seedance_api_key
SEEDANCE_BASE_URL=your_seedance_base_url
STORYFORGE_DB_PASSWORD=your_mysql_password
```

## 配置文件

默认配置文件：

- [`configs/storyforge.example.toml`](../configs/storyforge.example.toml)
- [`configs/storyforge.live.example.toml`](../configs/storyforge.live.example.toml)

关键配置项：

```toml
[llm]
enabled = true
provider = "deepseek"
model = "deepseek-chat"
available_providers = ["deepseek", "openai"]
max_tokens = 8192

[seedream]
enabled = true
model = "doubao-seedream-4-5-251128"
auto_submit = false
watermark = false

[seedance]
enabled = true
model = "doubao-seedance-2-0-260128"
auto_submit = false
watermark = false
with_audio = true
subtitle_mode = "burned_in"

[database]
host = "127.0.0.1"
port = 3306
user = "root"
password_env = "STORYFORGE_DB_PASSWORD"
database = "storyforge"
```

建议先关闭 `seedream.auto_submit` 和 `seedance.auto_submit`，确认规划、prompt 和请求参数都合理后，再提交真实图片或视频任务。

## 启动

```bash
uv run storyforge api serve --host 127.0.0.1 --port 8000
```

访问：

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/docs`

调前端样式或接口时可以使用 `--reload`。运行 Seedream / Seedance 长任务时不要使用热重载。

## 页面流程

### 1. 创建项目

在创建页填写 brief，并选择：

- LLM provider：`DeepSeek` 或 `ChatGPT 5.4`
- 连续性审校模式：`off / auto / on`
- Seedream 水印开关
- Seedance 水印开关

提交后会生成小说正文，并创建同一条 story run 的根任务。

### 2. 审阅正文

进入项目详情页的“小说”标签页：

- 阅读正文。
- 修改正文。
- 保存为新的 `story_source.json` 修订。

后续场景结构和视频规划都会以保存后的正文为准。

### 3. 生成场景结构

点击“生成场景结构”。这一步会生成：

- 角色和章节结构
- `story_memory.json`
- `character_visual_bible.json`
- scene skeleton
- scene 级过渡合同

完成后先检查 scene 切分是否覆盖了小说正文的主要推进。

### 4. 生成分段合同

点击“生成分段合同”。这一步会生成正式视频执行合同：

- `scene_plan.json`
- `segment_plan.json`
- `segment_contract_progress.json`
- `continuity_report.json`
- 媒体任务清单

页面会显示章、scene 和 chunk 进度。失败后可以从失败位置继续。

### 5. 生成角色图

点击“生成角色图”。生成后检查：

- 性别是否正确。
- 年龄感和体型是否稳定。
- 服装是否符合角色设定。
- 手部、肤色和三视图版式是否自然。
- 角色定妆图 Prompt 是否合理。

角色页会展示每个角色的定妆图、Prompt 和真实 Seedream 提交请求。可以直接修改单个角色的 Prompt，并选择只保存或“保存并重做该角色”。单角色重做只提交目标角色图，不会重跑其他角色、场景图或视频。重做后页面会同时展示当前图和新候选图。新图不会自动替换当前图，只有点击“使用新图”后才会写回正式角色图；点击“放弃新图”会删除候选图。

### 6. 生成场景母图

在场景工作台或分段审片台按 scene 生成场景母图。场景母图是无角色环境基准图，用来锁定地点、光线、空间透视、背景锚点和固定道具。

页面会展示场景母图真实提交给 Seedream 的 prompt、参考图和 payload。可以直接修改场景母图 prompt，保存后手动重做该 scene 的场景母图。

### 7. 生成视频

当某个 segment 的场景母图和角色图就绪后，可以生成该段视频。

Seedance 视频提交使用固定参考图顺序：

- `图片1`：当前 scene 的场景母图。
- `图片2...n`：当前 segment 实际出镜角色的定妆图。

视频 prompt 会描述角色在图片1场景中的运动轨迹、镜头路径、节拍推进、对白、字幕、环境声和收束状态。页面的 Request Inspector 会显示真实图片顺序、完整请求参数和最终 Seedance 推进 prompt。

### 8. 合并总片

至少有两个视频片段生成完成后，可以手动合并：

- 输出文件：`rendered/full_story.mp4`
- 合并顺序：按 `seedance_manifest.json` 中的片段顺序

## Prompt 编辑与重做

角色页支持单角色 Prompt 编辑；分段审片台支持在单个 segment 内选择当前生成点：

- 场景母图
- 视频

选择后页面只展示该点的 prompt 和请求参数。

可用操作：

- `保存 Prompt`：只保存当前点 prompt。
- `保存并重做当前点`：保存后只重做当前场景母图或当前视频。
- `重置当前点 Prompt`：按当前 segment 合同重新生成系统默认 prompt，不自动提交媒体任务。

## Request Inspector

Request Inspector 用于定位问题来源：

- 当前计划 prompt
- 实际提交 prompt
- Prompt Diff
- provider payload
- 参考图绑定
- Motion Plan
- Seedance 最终推进 prompt
- segment diagnostics

它可以帮助判断问题发生在规划、prompt 组装、参考图顺序、动作容量、时长预算、场景母图、角色图还是 provider 执行阶段。

## 智能修复

连续性报告会把风险落到 scene 或 segment。

可用修复入口：

- scene 级修复：重写 scene 基线合同和相关 segment 合同。
- segment 级修复：只重写目标 segment 的执行合同。
- 批量合同修复：按连续性报告集中修复风险合同。

修复任务只更新规划和修复报告，不自动重跑图片或视频。修复后需要根据页面提示手动重做对应媒体。

## 删除项目

项目详情页可以删除项目。删除会清理：

- 项目记录
- 任务记录
- 任务结果记录过的输出目录

后端只删除配置输出根目录内的项目产物目录，不删除输出根目录本身或外部路径。

## 输出产物

产物按用途分为几类，页面也按这些用途展示。

核心运行文件：

- `story_source.json`：正文真源。
- `novel_package.json`：结构化小说包。
- `story_memory.json`：视频规划记忆。
- `character_visual_bible.json`：角色视觉设定。
- `scene_plan.json`：scene 和 segment 主规划。
- `segment_plan.json`：扁平 segment 执行索引。

媒体任务清单：

- `character_image_manifest.json`：角色图任务清单。
- `scene_image_manifest.json`：场景图任务清单。
- `seedance_manifest.json`：视频提交清单。

恢复、风险和修复：

- `segment_contract_progress.json`：分段合同进度。
- `scene_structure_source.json`：场景结构恢复快照。
- `continuity_report.json`：连续性报告。
- `continuity_repair_<scene_id>.json`：scene 修复报告。
- `continuity_repair_<segment_id>.json`：segment 修复报告。

执行报告和审阅文件：

- `novel_audit.json`：审稿结果。
- `seedream_character_execution.json`：角色图执行报告。
- `seedream_scene_execution.json`：场景图执行报告。
- `seedance_execution.json`：视频执行报告。

媒体文件：

- `assets/characters/*.png`：角色图。
- `assets/frames/*.png`：场景母图。
- `rendered/*.mp4`：视频片段。
- `rendered/full_story.mp4`：合并总片。

## 联调顺序

### 只验证小说和结构

1. 配置 LLM 密钥。
2. 生成小说。
3. 修改并保存正文。
4. 生成场景结构。
5. 生成分段合同。
6. 检查 `scene_plan.json`、`segment_plan.json` 和页面诊断。

### 验证图片

1. 配置 Seedream。
2. 生成角色图。
3. 生成少量 scene 场景母图。
4. 检查角色、背景、场景母图和请求参数。
5. 只重做有问题的角色图或场景母图。

### 验证视频

1. 配置 Seedance。
2. 选择一个场景母图和角色图质量稳定的 segment。
3. 检查视频请求里的图片顺序和 prompt。
4. 生成单段视频。
5. 结果合理后再扩大生成范围。

## 失败处理

- 页面会展示任务级失败原因。
- LLM 结构化失败时，优先回到对应阶段重跑或从失败位置继续。
- 图片失败时，先检查参考图、prompt、provider 返回和内容安全响应。
- 视频失败时，先检查场景母图、角色图、图片顺序、视频 prompt 和 Seedance 返回。
- 任务进入 `failed` 后，推荐通过页面重新点击对应阶段按钮，不建议直接修改数据库。
- 长任务期间不要使用 `--reload`。

## 相关文档

- [README](../README.md)
- [API 文档](api.md)
- [架构文档](architecture.md)
- [开发文档](development.md)
- [产品状态](status.md)
