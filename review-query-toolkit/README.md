# Review Query Toolkit

这是一个独立的审核 CSV 查询工具包。默认输入是
`workbench/input/product-safety-review-v2-2p-full340_completed50_100rows_20260902.csv`，
也可以通过 `--input` 查询其他具有相同字段结构的审核导出文件。

它只读 CSV，不连接 Argilla，不修改原始文件。支持：

- 数据集概览、字段和空值检查
- 按 `case_id`、标注者、任意字段精确匹配或文本包含筛选
- 在多选字段中查找包含某个标签的记录
- 只查看双人完成的 case，或只查看存在双人分歧的 case
- 按 case 折叠查看、按字段分组计数
- 双人一致性统计
- 将任意筛选结果导出为新的 CSV
- `table`、`json`、`csv` 三种输出格式

## 快速开始

```bash
cd review-query-toolkit
uv sync
uv run python run.py summary
```

查看 50 个双人完成 case 的一致性：

```bash
uv run python run.py agreement --completed-only
```

对照参考引擎的结构化判断与人工审核标签：

```bash
uv run python run.py reference-agreement --completed-only --format json
```

默认使用 `predicted_safety_class` 对照 `medical_review_label`。当人工字段是多选时，
参考引擎标签包含在人工选择中即视为一致；`model_assessment` 可通过 `query` 的
`--contains`、`--search` 或 `--select` 查看完整参考回答。

查看指定 case 的两位标注结果：

```bash
uv run python run.py cases --case-id BF017
```

只看安全等级存在分歧的 case：

```bash
uv run python run.py disagreements --field medical_review_label
```

搜索用户问题，并只显示相关列：

```bash
uv run python run.py query \
  --search "吐奶" \
  --select case_id,annotator_username,medical_review_label,boundary_status,user_input
```

按能力统计唯一 case 数：

```bash
uv run python run.py group-by sub_capability --unit cases
```

查找标记需要专家裁决的响应：

```bash
uv run python run.py query \
  --where needs_expert_adjudication=YES \
  --format json
```

查找包含某个多选理由的响应：

```bash
uv run python run.py query \
  --has-label reason_codes=EMERGENCY
```

导出筛选结果。工具不会覆盖已有文件：

```bash
uv run python run.py export \
  --disagreement any \
  --output workbench/output/disagreements.csv
```

## 命令说明

```text
summary                         数据集、case、标注者和空值概览
agreement                       双人一致性统计
reference-agreement             参考引擎与人工标注的一致性统计
query                           一行一个响应的查询
cases                           一行一个 case 的查询
disagreements                   一行一个分歧 case；可用 --field 限定字段
group-by FIELD                  按字段计数；可用 --unit cases 和 --explode
fields                          字段、非空数、空值数和唯一值数
export                          将筛选后的原始响应行写入 CSV
```

通用筛选参数可组合使用：

```text
--case-id ID                    可重复
--annotator USER                可重复
--where FIELD=VALUE             精确匹配，可重复
--contains FIELD=TEXT           包含文本，可重复
--has-label FIELD=LABEL         多选标签包含，可重复
--missing FIELD                查找字段为空的行，可重复
--search TEXT                   搜索 case_id、用户输入和审核上下文
--completed-only                只保留至少两位标注者提交的 case
--disagreement FIELD            any 或四个审核问题字段之一
--select A,B,C                  指定输出列
--limit N --offset N            分页
```

`cases` 和 `disagreements` 会保留完整 case 的两位标注结果，便于直接比较；`query`
和 `export` 则按响应行工作。多选字段的比较会忽略 JSON 数组中的顺序。

## 开发检查

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
