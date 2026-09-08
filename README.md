# Toolkit

这是一个多工具集合。每个工具都放在独立目录中，并拥有自己的依赖、代码、
测试、说明和工作台，互相之间不共享运行环境。

## 工具列表

### Langfuse 工具包

目录：[langfuse-toolkit](./langfuse-toolkit/README.md)

通过 `.env` 和命令行自动化 Langfuse 项目发现、Prompt 版本发布、数据集维护、Trace / Session 查询、评分写回及实验记录查询，支持批量执行和 `--dry-run` 预览。
保留问题与画像生成、医生候选问诊材料两份 Chat Prompt 模板，以及输出 Schema、CSV 字段映射和页面操作指南。

### Output 收集器工具包

目录：[output-collector-toolkit](./output-collector-toolkit/README.md)

通过 Docker 部署为内部工作台，提供邮箱自助注册与登录、独立个人工作空间和服务器自动保存。分批粘贴 Langfuse 生成的问题画像与医生审核材料，按 case_id 合并并导出 CSV；支持 JSON 备份迁移。也可双击 [index.html](./output-collector-toolkit/index.html) 使用离线模式。部署说明见工具目录 README。

### Prompt Agent

目录：[prompt-agent](./prompt-agent/README.md)

填写 `.env` 和 `prompt-agent/prompt.md`，再执行：

~~~bash
cd prompt-agent
uv sync
uv run python run.py
~~~

它会并发运行 `workbench/cases.jsonl` 中的测试，并生成 JSONL 结果。

### 标注平台工具包

目录：[annotation-toolkit](./annotation-toolkit/README.md)

将审核 CSV 映射到 Argilla 等标注平台。当前支持 Cozie AI 安全分级的盲审和标签
对照流程：

~~~bash
cd annotation-toolkit
uv sync
uv run python run.py --profile cozie-safety --mode review --dry-run
~~~

### 审核 CSV 查询工具包

目录：[review-query-toolkit](./review-query-toolkit/README.md)

针对审核导出的 CSV 做概览、筛选、双人一致性分析、分歧查询和结果导出：

```bash
cd review-query-toolkit
uv sync
uv run python run.py summary
uv run python run.py agreement --completed-only
```

### XLSX 转 CSV

目录：[xlsx-to-csv](./xlsx-to-csv/README.md)

把 XLSX 文件放进 xlsx-to-csv/workbench，然后执行：

~~~bash
cd xlsx-to-csv
uv sync
uv run python run.py
~~~

每个工作簿的全部工作表都会转换，CSV 会生成到
xlsx-to-csv/workbench/output/工作簿名/。

## 目录约定

后续工具与 xlsx-to-csv 平级添加：

~~~text
toolkit/
├── output-collector-toolkit/
│   ├── index.html
│   └── README.md
├── langfuse-toolkit/
│   ├── prompts/
│   ├── schemas/
│   ├── docs/
│   └── README.md
├── annotation-toolkit/
│   ├── app/
│   │   ├── platforms/
│   │   └── profiles/
│   ├── tests/
│   ├── workbench/
│   └── pyproject.toml
├── prompt-agent/
│   ├── app/
│   ├── tests/
│   ├── workbench/
│   ├── prompt.md
│   └── pyproject.toml
├── xlsx-to-csv/
│   ├── app/
│   ├── tests/
│   ├── workbench/
│   ├── pyproject.toml
│   └── uv.lock
├── review-query-toolkit/
│   ├── app/
│   ├── tests/
│   ├── workbench/
│   ├── pyproject.toml
│   └── uv.lock
└── another-tool/
    └── ...
~~~
