# Langfuse 命令说明

以下命令在 `langfuse-toolkit` 目录执行，连接配置见 [快速开始](../README.md#开始使用)。查询结果显示为 JSON；写命令可先加 `--dry-run` 预览。

## 命令分层

| 层 | 入口 | 用途与凭据 |
|---|---|---|
| 实例 | `instance health` | 服务状态和版本；无需密钥 |
| 组织 | `org projects list` | 列出组织内项目；组织 API Key |
| 项目 | `project info/check` | 查询密钥所属项目、校验目标 ID；项目 API Key |
| 项目资源 | `project <资源> <操作>` | 维护下表资源；项目 API Key 和目标 ID |
| 工作流 | `workflow validate/run` | 组合各层操作；各步骤分别使用对应凭据 |

`project` 下支持的资源：

| 资源 | 操作 | 用途 |
|---|---|---|
| `llms` | `list` | 查看已配置连接、适配器、地址和自定义模型名 |
| `playground` | `validate/run` | 校验输入，使用后台模型连接执行消息或 Prompt |
| `prompts` | `list/get/validate/save/label/delete` | 查询、保存版本、发布或回滚、删除版本 |
| `datasets` | `list/get/create/upsert` | 查询、创建或更新数据集 |
| `items` | `list/get/upsert/delete` | 维护测试样本 |
| `traces` / `observations` / `sessions` | `list/get`；Trace 另有 `delete` | 查询调用、节点和会话 |
| `scores` | `list/get/create/delete` | 查询、写回或删除评分 |
| `score-configs` | `list/get/create/update` | 维护评分类型、范围及归档状态 |
| `experiments` / `experiment-items` | `list` | 查询实验和结果条目 |
| `runs` / `run-items` | `list/get/delete` / `list/create` | 维护旧版 Langfuse v3 Dataset Run |

表中的 `/` 表示任选一个操作。完整参数例如：`uv run python run.py project datasets get --help`。

## 1. 配置、查询项目

```bash
uv run python run.py instance health     # 服务健康状态，无需 API Key
uv run python run.py org projects list   # 使用组织密钥列出项目
uv run python run.py project info        # 查看项目密钥所属项目，不需要先填 ID
uv run python run.py project check       # 校验密钥与目标 ID 是否匹配
```

| 配置项 | 用途 |
|---|---|
| `LANGFUSE_BASE_URL` | 实例地址 |
| `LANGFUSE_ORG_PUBLIC_KEY` / `LANGFUSE_ORG_SECRET_KEY` | 组织密钥，仅用于 `org` |
| `LANGFUSE_PROJECT_PUBLIC_KEY` / `LANGFUSE_PROJECT_SECRET_KEY` | 项目密钥，仅用于 `project` |
| `LANGFUSE_PROJECT_ID` | 目标项目 ID，从 `project info` 或项目页面 URL 获取 |
| `LANGFUSE_SESSION_COOKIE` | Playground 实际执行所需的登录会话 |

组织与项目密钥独立配置，不互相替代。旧的 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 仍兼容为项目密钥；同一来源中显式项目变量优先，不混用两套名称的公钥和私钥。

切换配置用 `uv run python run.py --env '/path/to/.env' project info`，环境变量优先于文件。离线 `validate` 和工作流预览不需要连接配置。

## 2. 查看 LLM 和运行 Playground

```bash
uv run python run.py project llms list --all  # 查看当前项目配置了哪些模型连接
uv run python run.py project playground validate --file 'examples/playground.json'  # 离线检查输入
uv run python run.py project playground run --file 'examples/playground.json' --dry-run  # 读取连接并预览请求
uv run python run.py project playground run --file 'examples/playground.json'  # 实际调用模型
```

先把 [输入示例](../examples/playground.json) 的 `modelParams.provider` 改为列表中的连接名、`model` 改为模型名。`customModels` 是自定义模型列表；`withDefaultModels` 仅表示是否启用默认模型列表，不代表返回了全部可用模型。查询不会显示完整密钥。

实际运行还需在 `.env` 设置 `LANGFUSE_SESSION_COOKIE`：填入已登录浏览器的 **Cookie 请求头值，包含 Cookie 名称**。工具只转发其中的会话 Cookie；过期或无执行权限时会报错。模型密钥沿用后台配置，无需再填。`--dry-run` 只需项目 API Key，会读取连接和 Prompt，但不调用模型。

运行已保存的 Prompt 参考 [playground-prompt.json](../examples/playground-prompt.json)：通过 `prompt.name` 和 `version` / `label` 选版本（默认 latest），`variables` 填入字符串变量，`placeholders` 填入消息数组。参数以输入文件的 `modelParams` 为准，不自动继承 Prompt 的自由格式 `config`。可传 `structuredOutputSchema` 或 `tools`；当前支持文本消息和一次模型调用，工具调用结果会返回，工具本身不自动执行。

## 3. 维护 Prompt

```bash
uv run python run.py project prompts list  # 查看所有 Prompt 的名称、版本和标签
uv run python run.py project prompts get 'medical/case-review-draft' --label production  # 读取线上版本
uv run python run.py project prompts validate --file 'definitions/review.json'  # 检查本地定义
uv run python run.py project prompts save --file 'definitions/review.json' --dry-run  # 查看与后台的差异
uv run python run.py project prompts save --file 'definitions/review.json'  # 保存为新版本
uv run python run.py project prompts label 'medical/case-review-draft' --version 3 --label production  # 发布版本 3
uv run python run.py project prompts delete 'medical/case-review-draft' --version 1 --dry-run  # 预览删除版本 1
```

`project prompts get` 不指定版本或标签时读取 `latest`；也可用 `--version 2`。发布时把 `--version` 改为旧版本号即可回滚。

定义文件可参考 [review.json](../definitions/review.json)：`name` 是 Prompt 名称，`type` 为 `chat` 或 `text`，`prompt` 是正文；`contentFile` / `promptFile` 可引用相对路径的文本文件。模型参数、输出 Schema 放入 `config`，或由 `configFile` 引用完整配置。

每次 `save` 都创建新版本。未填写的 `config`、`tags` 继承最新版本；填写 `config` 会整体替换配置。默认不移动 `production`；显式填写 `labels` 才会把对应标签移到新版本。`label` 保留其他已有标签，`latest` 由后台管理。

## 4. 维护数据集和样本

```bash
uv run python run.py project datasets upsert --file 'examples/dataset.json'  # 按名称创建或更新数据集
uv run python run.py project items upsert --file 'examples/item.json'        # 按 ID 新增或更新样本
uv run python run.py project items list --dataset 'automation/smoke' --all   # 查看该数据集的全部样本
```

文件格式见 [数据集示例](../examples/dataset.json) 和 [样本示例](../examples/item.json)。数据集可设置 `inputSchema`、`expectedOutputSchema`；样本使用 `input`、`expectedOutput`，设 `status: "ARCHIVED"` 可归档。同一个样本 ID 不可跨数据集复用。`project datasets create` 与 `upsert` 相同，同名时也会更新。

## 5. 查询调用记录

```bash
uv run python run.py project traces list --user-id 'user-123' --limit 10      # 查询某用户的调用
uv run python run.py project observations get 'obs-id' --trace-id 'trace-id'  # 读取调用中的一个节点
uv run python run.py project sessions get 'session-id'                       # 查看会话中的调用节点
```

默认查询最近 24 小时，可加 `--from '2026-09-01T00:00:00Z' --to '2026-09-08T00:00:00Z'` 指定范围。Trace / Session 从 Observation 汇总，`complete=false` 表示还没读完分页；窗口内查不到不代表整个项目不存在。旧部署的这些读命令可加 `--legacy`。

## 6. 写回评分

```bash
uv run python run.py project scores list --trace-id 'trace-id'                         # 查看某次调用的评分
uv run python run.py project scores create --file 'examples/score.json' --dry-run       # 预览评分写入
uv run python run.py project score-configs create --file 'examples/score-config.json'  # 新建评分规则
```

先把 [评分示例](../examples/score.json) 中的 `traceId` 换成实际调用 ID，`id` 换成该项评分的稳定 ID，再移除 `--dry-run` 写入。重复使用同一评分 ID 会更新评分。布尔评分值填数字 `0` 或 `1`。评分可能异步生效，`accepted=true` 表示已受理，可用 `project scores get 'score-id'` 查询；旧部署的评分查询可加 `--legacy`。

## 7. 查询实验和运行批量任务

```bash
uv run python run.py project experiments list  # 查看最近 24 小时的实验，可用 --from / --to 改范围
uv run python run.py project experiment-items list --experiment-id 'experiment-id' --all  # 查看实验结果
uv run python run.py workflow run --file 'examples/workflow.json' --dry-run  # 预览整批步骤
```

批量文件格式和执行方法见 [批量任务](automation.md)，可加入 `project playground run` 步骤。模型执行通过 Playground 完成；批量实验的评估算法仍由应用或 SDK 执行。

## 通用规则

- **预览**：`--dry-run` 不写入、不调用模型。单独的 Prompt / Playground 预览会读取后台；工作流预览完全离线。
- **分页**：资源列表默认 50 条，`--all` 读取全部页；最多 100 页，可用 `--max-pages` 调整。Prompt 列表默认读取全部页。
- **删除**：执行时需输入目标确认；脚本中显式加 `--yes`。删除可能异步生效。
- **失败**：写请求不自动重试。重跑前检查是否已写入，尤其是创建 Prompt 版本；命令成功退出码为 0，失败为非零。

## 旧命令迁移

旧顶层 `health` 改为 `instance health`；`projects` 改为 `project info`；`projects --scope organization` 改为 `org projects list`；`check` 改为 `project check`。资源命令前加 `project`，`batch` 改为 `workflow run`。工作流文件内的命令也需加对应层级。
