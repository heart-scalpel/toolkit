# Review Query Toolkit

这是一个独立的审核 CSV 查询工具包。默认输入是
`workbench/input/product-safety-review-v2-2p-full340_completed50_100rows_20260902.csv`，
也可以通过 `--input` 查询医生单人审核导出，兼容 `expected_safety_class`、
`material_review`、回应/追问修改意见及多选 `boundary_status`。

它只读 CSV，不连接 Argilla，不修改原始文件。支持：

- 数据集概览、字段和空值检查
- 按 `case_id`、标注者、任意字段精确匹配或文本包含筛选
- 在多选字段中查找包含某个标签的记录
- 只查看双人完成的 case，或只查看存在双人分歧的 case
- 按 case 折叠查看、按字段分组计数
- 双人一致性统计
- 医生审核多维评估：分类、素材质量、场景分组、对照组覆盖与填写问题
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

默认使用 `predicted_safety_class` 对照人工字段，优先 `medical_review_label`，否则
使用 `expected_safety_class`。逐审核人指标使用所有已提交响应，支持单人审核；
`--completed-only` 仍表示只看至少两位审核人提交的用例，单人数据不要加此参数。
空预测或空人工标签单列为跳过，不将两个空值算作一致。该命令报告原始响应一致性，
重复提交、待裁决筛选和失败预测的完整统计请使用 `evaluate`。当人工字段是多选时，
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
evaluate                        医生单选审核的多维评估；默认输出可读 Markdown
review-issues                   医生审核填写问题与待裁决清单，一行一个问题
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
--disagreement FIELD            any 或审核字段之一（含 expected_safety_class、material_review）
--select A,B,C                  指定输出列
--limit N --offset N            分页
```

`cases` 和 `disagreements` 会保留完整 case 的两位标注结果，便于直接比较；`query`
和 `export` 则按响应行工作。多选字段的比较会忽略 JSON 数组中的顺序。
`group-by --explode` 的比例分母为响应数（或 `--unit cases` 的唯一用例数），
每条同一标签只计一次；多个标签占比之和可以超过 100%。空筛选结果返回空统计。

## 医生审核多维评估

```bash
uv run python run.py evaluate \
  --input ../annotation-toolkit/workbench/output/medical-case-review-50-20260907_submitted_20260908_142539.csv \
  --format markdown --output workbench/output/medical-evaluation.md

uv run python run.py evaluate \
  --input /path/to/doctor-review.csv \
  --group-by id_prefix,expected_safety_class --format json

uv run python run.py review-issues \
  --input /path/to/doctor-review.csv --format csv \
  --output workbench/output/review-issues.csv
```

`evaluate` 支持通用行筛选，读取医生审核完整字段结构。它按已提交的审核响应统计，
不会把多位审核人的意见自动合并为最终答案。同一用例与审核人重复提交时，全部暂缓；
未提交、匿名及重复响应数均单列。两种分类口径同时报告：

- 全量对照：具有有效人工单选标签的审核响应，包括暂定或待裁决标签。
- 分类筛选集：人工标签有效、边界仅 `CLEAR`、专家裁决 `NO`、素材 `ACCEPT/REVISE`、
  分类要点有效，同用例审核人无分类分歧、原始输入及模型结果一致。

筛选集是明确规则下的统计子集，不表示最终基线已验收；素材修订与分类有效性分别处理。
报告包含准确率、各类 precision/recall/F1、混淆明细、限制医疗类误升/漏分、候选与引擎
变化、多数类基线，以及素材处置、意见填写率、分类与素材的交叉统计、按场景/类别/审核人
分组和对照组完整性。零分母返回 `null`/`n.a.`；缺失、非法或失败的引擎输出计入未命中，
同时报告输出覆盖率和有效输出准确率。主表宏平均 F1、平衡准确率在人工有样本的类别上
取平均，两模型使用相同类别；JSON 的 `macro_f1_union` 另按人工或预测出现的类别取平均。

填写检查包括：`CLEAR` 与其他边界同时选择、`ACCEPT` 有修改意见、`REVISE` 无修改意见、
排除原因未填入指定字段、引用“同上/上一版”等不完整上下文、删除追问的非标准表达和
专家裁决请求。保留医生原文，不把修改说明自动替换成最终回复，不自动修正医疗判断。
`review-issues` 每行是一项问题，所以同一响应可能出现多行。

多选理由是分类依据，不是回复缺陷标签。对照组的两条标签相同也不代表材料正确处理了
画像差异。场景样本数较小时请结合编号逐条检查；仅一位审核人无法衡量医生间一致性。

## 开发检查

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```
