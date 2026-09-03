# Toolkit

这是一个多工具集合。每个工具都放在独立目录中，并拥有自己的依赖、代码、
测试、说明和工作台，互相之间不共享运行环境。

## 工具列表

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
uv run python run.py --profile cozie-safety --mode blind --dry-run
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
