# XLSX 转 CSV 工具

这是一个使用 uv 管理的轻量 Python 工具，用于把 XLSX 工作簿转换为 CSV。
它既可以在代码中调用，也提供了直接可用的命令行入口。

工具目录独立管理自己的代码、依赖、测试和工作台，不包含发布到 PyPI
所需的打包配置：

~~~text
xlsx-to-csv/
├── app/
│   ├── cli.py
│   └── xlsx_to_csv.py
├── tests/
├── workbench/
├── .python-version
├── pyproject.toml
└── uv.lock
~~~

## 功能

- 工作台默认转换每个工作簿中的全部工作表
- 单文件命令支持转换第一张、指定工作表或全部工作表
- 支持按工作表名称或从 1 开始的序号进行选择
- 支持一次转换全部工作表，包括隐藏工作表
- 默认输出 UTF-8 BOM，Excel 打开中文 CSV 时不容易乱码
- 正确处理逗号、双引号和单元格内换行
- 使用 openpyxl 只读模式，适合处理较大的工作簿
- 默认保护已有文件，需要明确指定 force 才会覆盖

## 快速开始

需要 Python 3.12 和 uv。

~~~bash
cd xlsx-to-csv
uv sync
~~~

最简单的使用方式是把 XLSX 文件放进 xlsx-to-csv/workbench，然后执行：

~~~bash
cd xlsx-to-csv
uv run python run.py
~~~

CSV 会自动生成到 xlsx-to-csv/workbench/output/工作簿名。每张工作表生成
一个带序号的 CSV，例如 001_Data.csv、002_Summary.csv；再次执行会更新已有输出。

转换第一张工作表：

~~~bash
uv run python -m app.cli ../report.xlsx
~~~

指定输出文件和工作表：

~~~bash
uv run python -m app.cli ../report.xlsx \
  --sheet "Sales" \
  --output ../sales.csv
~~~

按序号选择工作表：

~~~bash
uv run python -m app.cli ../report.xlsx --sheet-index 2
~~~

转换全部工作表：

~~~bash
uv run python -m app.cli ../report.xlsx \
  --all-sheets \
  --output ../report_csv
~~~

覆盖已有文件：

~~~bash
uv run python -m app.cli ../report.xlsx --force
~~~

保留公式表达式，而不是读取公式缓存值：

~~~bash
uv run python -m app.cli ../report.xlsx --formulas
~~~

查看全部命令参数：

~~~bash
uv run python -m app.cli --help
~~~

## Python 调用

在 xlsx-to-csv 目录中运行代码时，可以直接导入转换函数：

~~~python
from app.xlsx_to_csv import convert_xlsx

results = convert_xlsx(
    "../report.xlsx",
    "../report_csv",
    all_sheets=True,
)

for result in results:
    print(result.sheet_name, result.output_path)
~~~

常用参数：

| 参数 | 说明 |
| --- | --- |
| source | XLSX 文件路径 |
| output | CSV 文件或输出目录；不传时自动生成 |
| sheet | 工作表名称，或从 1 开始的工作表序号 |
| all_sheets | 是否转换全部普通工作表 |
| encoding | 输出编码，默认 utf-8-sig |
| delimiter | CSV 分隔符，默认逗号 |
| data_only | 为 true 时读取公式缓存值，为 false 时保留公式 |
| overwrite | 是否覆盖已有输出文件 |

## 输出规则

- 单工作表且未指定 output：report.xlsx 会生成同目录的 report.csv。
- 多工作表且未指定 output：会创建 report_csv 目录。
- output 以 .csv 结尾时，它会作为单个输出文件，只能转换一张工作表。
- 其他 output 路径会作为目录。
- 目录中的文件名包含工作表序号，例如 001_Data.csv、002_Sales.csv。

## 数据处理说明

- 日期、日期时间和时间统一输出为 ISO 格式。
- 布尔值输出为 TRUE 或 FALSE。
- 会保留数据前部和中间的空行，删除末尾的空行与每行末尾的空单元格。
- CSV 不保留颜色、字体、边框、合并样式、图片、图表和宏。
- 数字显示格式不会保留。例如 Excel 中显示为 001 的数值，CSV 中可能是 1。
- 合并单元格通常只有左上角单元格包含值。

openpyxl 不会计算公式。默认模式读取的是工作簿上次保存时的公式缓存值；
如果原文件没有缓存或缓存已经过期，CSV 中对应字段可能为空或不是最新值。
使用 formulas 参数可以改为导出原始公式表达式。

转换器会忠实保留以 =、+、- 或 @ 开头的文本。打开来源不可信的 CSV
之前，请先评估电子表格公式注入风险。

目前只支持 XLSX，不支持旧版 XLS、XLSB 或加密工作簿。

## 开发

~~~bash
cd xlsx-to-csv

uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
~~~

代码中的模块名、变量、注释、帮助信息和错误信息统一使用英文；面向使用者的说明使用中文。

## 许可证

MIT
