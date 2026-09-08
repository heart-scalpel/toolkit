# 工作流

把多个命令写进一个 JSON 文件，按顺序执行。命令用途见 [命令说明](commands.md)。

## 运行

在 `langfuse-toolkit` 目录执行：

```bash
uv run python run.py workflow validate --file 'examples/workflow.json'       # 离线校验全部步骤
uv run python run.py workflow run --file 'examples/workflow.json' --dry-run  # 离线预览
uv run python run.py workflow run --file 'examples/workflow.json'            # 实际执行
```

[workflow.json](../examples/workflow.json) 创建或更新数据集、写入样本，再查询结果。移除 `--dry-run` 后会写入目标项目。

[discovery-workflow.json](../examples/discovery-workflow.json) 只查询实例、组织项目、当前项目和 LLM 连接，演示跨层组合；实际运行需同时配置组织密钥、项目密钥和项目 ID。

## 文件格式

```json
{
  "commands": [
    ["project", "datasets", "upsert", "--file", "dataset.json"],
    ["project", "items", "upsert", "--file", "item.json"],
    ["project", "items", "list", "--dataset", "automation/smoke", "--all"]
  ]
}
```

每行是一条命令的参数，从 `instance`、`org` 或 `project` 开始。`--file` 路径相对于工作流 JSON 所在目录。不支持嵌套工作流或单步 `--env`；同一份配置可同时保存组织和项目密钥，各步骤按层选择。

执行前检查全部参数、输入文件和所需凭据，并核对项目 ID。删除步骤需显式加 `--yes`；Playground 实际执行还需登录 Cookie。单步仍可使用自己的 `--dry-run`。

## 结果与失败

| 字段 | 含义 |
|---|---|
| `success` | 是否全部成功 |
| `completed` | 已完成步骤数 |
| `failedStep` / `error` | 执行失败的步骤和原因 |
| `results` | 各步骤的结构化结果 |

校验失败时不会开始执行；执行中遇错立即停止，返回已完成的结果。预览完全离线，不解析后台 Prompt 或检查远端权限；本地凭据检查也不保证后续远端请求一定成功。

已完成步骤不自动回滚，写请求不自动重试。重跑前检查结果：固定样本/评分 ID 可重复更新，Prompt 保存会新增版本，Playground 会再次调用模型。
