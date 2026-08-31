# Toolkit

这是一个多工具集合。每个工具都放在独立目录中，并拥有自己的依赖、代码、
测试、说明和工作台，互相之间不共享运行环境。

## 工具列表

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
├── xlsx-to-csv/
│   ├── app/
│   ├── tests/
│   ├── workbench/
│   ├── pyproject.toml
│   └── uv.lock
└── another-tool/
    └── ...
~~~
