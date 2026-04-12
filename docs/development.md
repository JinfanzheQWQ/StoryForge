# 开发文档

## 1. 当前代码组织原则

### 原则一：业务对象独立于框架

小说和视频的核心对象都放在 `domains` 中，不依赖 FastAPI。

### 原则二：模型调用独立于业务规则

DeepSeek / LangChain 相关调用都被隔离在：

- `agents/`
- `integrations/llm.py`

这样后面切 OpenAI、Claude、Moonshot 或本地模型时，不需要大改业务。

### 原则三：API 只做接入，不写业务

FastAPI router 只负责：

- 校验输入
- 提交任务
- 返回状态

真正的业务执行仍然在 application / pipeline / domain 里。

## 2. 结构化多 Agent 的实现要点

### 2.1 Schema-first

当前不是先写 prompt 再想怎么解析，而是先定义 schema：

- [src/storyforge/domains/novel/schemas.py](/Users/xy/StoryForge/src/storyforge/domains/novel/schemas.py)
- [src/storyforge/domains/video/schemas.py](/Users/xy/StoryForge/src/storyforge/domains/video/schemas.py)

这样做有两个好处：

1. Agent 输出可以直接验证
2. 下游节点不需要猜字段

### 2.2 Fallback-first

当前服务层里，每个结构化 Agent 都有 deterministic fallback。目的不是偷懒，而是为了：

- 无 API Key 也能跑通架构
- 测试时不依赖外部网络
- 更容易把系统先搭起来

### 2.3 多 Agent 是串联，不是混在一起

现在的多 Agent 是顺序协作：

1. Architect
2. Character Designer
3. Chapter Planner
4. Chapter Writer
5. Reviewer

这是第一阶段最稳妥的设计。等你后续要做更复杂的协作，再考虑引入真正的 handoff graph。

## 3. 队列层设计

当前队列文件：

- [src/storyforge/application/tasks.py](/Users/xy/StoryForge/src/storyforge/application/tasks.py)

这是一个轻量的内存队列。优点：

- 非常适合本地开发
- 易读
- 不需要外部中间件

缺点：

- 进程重启任务会丢
- 不适合多实例部署
- 不适合高并发生产环境

如果你下一步要上生产，我建议第一优先级是替换成 Redis-backed queue。

## 4. Seedance 接入建议

当前实现里，`SeedanceClient` 已经预留了：

- payload builder
- async submit
- manifest submission result

当前实现里，`SeedreamClient` 已经真正接入了：

- 角色图 API 调用
- 场景首帧 / 尾帧 API 调用
- URL 回填
- 可选本地下载

你真正落地时，需要重点确认四件事：

1. 你的 Seedance 部署路径是不是 `/video/generations`
2. 首帧和尾帧字段名是否一致
3. 是否支持本地路径、URL 还是对象存储 key
4. 任务创建后是同步返回还是异步回调

因此我把 provider contract 集中到一个地方：

- [src/storyforge/integrations/seedance.py](/Users/xy/StoryForge/src/storyforge/integrations/seedance.py)

## 5. 建议的下一步开发路线

### 第一批必须做

1. 图像生成 provider 抽象
2. Seedance 轮询 / 下载器
3. 输出素材的对象存储适配

### 第二批建议做

1. 任务持久化
2. 项目级数据库模型
3. 用户级工作区

### 第三批增强项

1. 角色一致性检查 Agent
2. 章节重写 Agent
3. 分镜精修 Agent
4. Clip 排版与封面生成

## 6. 本地测试

### 跑测试

```bash
uv run pytest
```

### 跑 CLI smoke test

```bash
uv run storyforge pipeline demo
```

### 跑 API

```bash
uv run storyforge api serve --reload
```

## 7. Git 与目录卫生

### 初始化 Git

如果当前目录还不是 Git 仓库：

```bash
git init -b main
```

### 提交前检查

```bash
scripts/check.sh
```

这个脚本当前会执行：

- `uv run ruff check`
- `uv run pytest`

### 清理本地产物

保守清理，只删除缓存、`.DS_Store`、`__pycache__`、测试临时目录：

```bash
scripts/clean-local-artifacts.sh
```

先看将要删除什么：

```bash
scripts/clean-local-artifacts.sh --dry-run
```

如果你确认要连 `outputs/`、`workspace/`、`.venv/` 一起清掉：

```bash
scripts/clean-local-artifacts.sh --deep
```
