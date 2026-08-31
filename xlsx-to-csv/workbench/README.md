# XLSX 工作台

把需要转换的 XLSX 文件直接放在当前目录，然后回到 xlsx-to-csv 工具目录执行：

~~~bash
uv run python run.py
~~~

生成的 CSV 文件会出现在 output/工作簿名 目录中。

每个 XLSX 的全部工作表都会转换，每张工作表生成一个带序号的 CSV；
再次执行会更新同名 CSV。
