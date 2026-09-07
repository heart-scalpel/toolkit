# 标注平台工具包

这是一个独立的标注平台对接工具。它把“标注任务定义”和“平台实现”分开：

~~~text
annotation-toolkit/
├── app/
│   ├── core/              # 平台无关的 TaskSpec / RecordSpec
│   ├── inputs/            # CSV 等通用输入读取器
│   ├── profiles/          # 业务校验、归一化、标签和审核阶段
│   ├── platforms/         # 将通用规格翻译到 Argilla 等平台
│   ├── sampling.py        # 顺序、均匀随机等选择策略
│   └── cli.py
├── docs/
├── tests/
├── workbench/
│   ├── input/             # 本地输入，不提交
│   └── output/            # 本地导出，不提交
├── run.py
└── pyproject.toml
~~~

当前内置：

- 平台：Argilla 2.8
- Profile：Cozie AI 安全分级复核
- 流程：第一轮模型辅助审核、第二轮标签合理性对照
- 双语选项：中文展示名 + 稳定英文值
- 多人审核：默认每条至少两份有效提交

## 母婴候选问诊材料审核

收集器导出的问题与画像先用 `prompt-agent/classify.py` 批跑，再通过独立 Profile
`cozie-medical-review` 创建全新数据集。它展示用户画像、候选分类、初步判断、可能
问诊回应、0—2 条追问和本次引擎分级；对照组信息仅保留在隐藏元数据中，不生成历史或预填人工答案。
医生单选人工安全分类，边界状态可多选，审核候选材料并填写必要修订。“是否需要专家裁决”中医生直接选择“否”，非医生才根据是否需要专家判断选择“是”或“否”。原有 `cozie-safety` 保持原流程。

~~~bash
uv run python run.py \
  --profile cozie-medical-review \
  --mode review \
  --input workbench/output/cases-2026-09-07T01-19-57-173Z_engine.csv \
  --dataset medical-case-review-100-20260907 \
  --min-submitted 1 \
  --dry-run
~~~

离线校验通过后移除 `--dry-run` 创建数据集；同名数据集已存在时会拒绝覆盖。
输入必须包含完整候选材料和明确的引擎运行结果。成功行需要合法分类和理由；失败行必须有错误信息且分类、理由均为空，原样进入人工审核，并通过 engine_status 标识，不补造分类。
统一使用[审核规范](docs/medical_case_review_guidelines.md)，随 Profile 默认写入数据集 Guidelines。
导出仍按记录与标注者分别保存，通过 case_id 关联原始结果 CSV；形成最终基线前
按规范检查修订内容和分歧，提交数达标不自动代表医生结论一致。

右侧只保留一次“安全分类医学逻辑”，不再单独收集“修订后的初步判断及依据”。
需要修订时，审核人在“问诊回应的修改意见”和“问诊追问修改”中直接填写普通文字；
不修改留空，删除全部追问写“无需追问”，并可在问诊回应的修改意见中记录材料问题或排除原因。
导出保留现有列名：`confirmed_consultation_response` 保存回复或问题说明原文，
`confirmed_follow_ups` 保存追问原文，不要求 JSON。整理最终基线时需区分完整回复
和问题说明，并把“无需追问”解释为清空追问；不能把这些原文直接当作已确认的结构化材料。
原始 CSV 中的 `confirmed_assessment` 列照常保留，但本版表单不再收集此项。

同类审核任务统一使用这份规范，导入时可以省略 `--guidelines`，也可显式指定下方路径。
以后需要使用其他规范时，可通过 `--guidelines` 覆盖，仅影响当次新建数据集。100 条批次示例：

~~~bash
uv run python run.py \
  --profile cozie-medical-review \
  --mode review \
  --input workbench/output/cases-2026-09-07T01-19-57-173Z_engine.csv \
  --guidelines docs/medical_case_review_guidelines.md \
  --dataset medical-case-review-100-20260907 \
  --min-submitted 1
~~~


平台操作一页说明：[Argilla 标注平台 · 一页操作说明](docs/argilla_annotation_platform_one_page_guide.png)

## 快速开始

需要 Python 3.12、uv，以及一个正在运行的 Argilla Server。

~~~bash
cd annotation-toolkit
cp .env.example .env
uv sync
~~~

在 Argilla 的 **My Settings** 复制 API key 到 `.env`：

~~~dotenv
ANNOTATION_PLATFORM=argilla
ARGILLA_API_URL=http://localhost:6900
ARGILLA_API_KEY=你的本地API密钥
ARGILLA_WORKSPACE=default
~~~

把待审核 CSV 放进 `workbench/input/`，然后先执行离线校验：

~~~bash
uv run python run.py --profile cozie-safety --mode review --dry-run
~~~

创建第一轮模型辅助审核数据集：

~~~bash
uv run python run.py --profile cozie-safety --mode review
~~~

导入 CSV 时必须显式指定业务 Profile。`cozie-safety` 是当前的安全分级业务包，内部可
识别两类已知 CSV：

- annotation-ready：已有 `case_id` 以及完整或部分标注辅助字段；
- classifier-results：只有分类器输出时，会补充稳定的行号 ID、空用户画像和空历史消息，
  并将 `reasoning/error` 归一化为 `model_reasoning/classifier_error`。

两类输入最终都会转换为相同的内部记录；平台适配器不读取原始 CSV，也不包含业务字段名。
不符合这两类结构的文件会报错；新业务应实现并注册新的 Profile，而不是由框架猜测。

只导入 CSV 中前 5 条做联调时，使用独立数据集名称，避免和正式数据集混淆：

~~~bash
uv run python run.py \
  --profile cozie-safety \
  --mode review \
  --limit 5 \
  --dataset cozie_safety_review_smoke_v1
~~~

`--limit` 按 CSV 原始顺序取前 N 条，不会修改源 CSV。联调确认后再创建正式数据集。

跳过前 20 条、取第 21～40 条时，将 `--offset` 和 `--limit` 组合使用：

~~~bash
uv run python run.py \
  --profile cozie-safety \
  --mode review \
  --offset 20 \
  --limit 20 \
  --dataset cozie_safety_review_21_40_v1
~~~

`--offset` 从 0 开始计数，表头不计入记录；只使用 `--offset` 时会取从该位置到
CSV 末尾的所有记录。

需要随机且尽量均匀地抽取不同场景和分类时，增加 `--random`：

~~~bash
uv run python run.py \
  --profile cozie-safety \
  --mode review \
  --offset 20 \
  --limit 20 \
  --random \
  --dataset cozie_safety_review_random_20_v1
~~~

`--random` 必须和 `--limit` 一起使用。候选范围从 `--offset` 指定的位置开始到 CSV
末尾。抽样字段由 Profile 声明；`cozie-safety` 使用 `sub_capability` 和
`predicted_safety_class`。缺少任一字段值的记录不参与随机抽样；如果没有任何有效候选，
命令会明确报错，不会创建空数据集。算法根据全局
分布预先拆分轮次，使数量较多的类型均匀分散；每轮中两个字段都分别不重复，轮次
交界处也会尽量避免重复。抽样会持续到达到 `--limit` 或有效候选耗尽。

第一轮完成后创建标签对照数据集：

~~~bash
uv run python run.py --profile cozie-safety --mode comparison
~~~

默认数据集名称分别是：

- `cozie_safety_review_v1`
- `cozie_safety_review_comparison_v1`

可使用 `--dataset` 指定新的数据集名称，使用 `--limit` 限制导入条数，使用
`--min-submitted` 调整每条需要的有效提交数。完整参数：

~~~bash
uv run python run.py --help
~~~

## 删除指定数据集

删除只接受完整、精确的数据集名称。默认会要求再次输入完整名称确认：

~~~bash
uv run python run.py --delete-dataset cozie_safety_review_v1
~~~

自动化环境可以显式使用 `--yes` 跳过交互确认：

~~~bash
uv run python run.py \
  --delete-dataset cozie_safety_review_v1 \
  --yes
~~~

删除只作用于 Argilla 中指定的数据集，不会删除本地 CSV，也不接受通配符或部分名称。

## 创建标注账号与查看逐人进度

批量创建 10 个独立的医学标注账号，并加入配置的 workspace：

~~~bash
uv run python run.py --create-users 10 --user-prefix medical_reviewer
~~~

默认创建 `medical_reviewer_01` 到 `medical_reviewer_10`，角色固定为 `annotator`。
随机初始密码不会打印到终端，而是保存到 `workbench/output/` 下带时间戳的凭据 CSV。
该文件权限设为 `0600` 且不会被 Git 提交。CSV 预留了 `assigned_to`、
`distributed_at` 和 `notes`，用于本地记录账号分配情况。

如任一目标用户名已经存在，命令会在创建前停止，不覆盖已有账号。查看指定数据集的
逐人提交、草稿和丢弃数量：

~~~bash
uv run python run.py \
  --progress-dataset cozie_safety_review_smoke_v1
~~~

## 导出已提交标注

按“每条记录 × 每位标注者”一行导出 submitted 响应：

~~~bash
uv run python run.py \
  --export-dataset cozie_safety_review_single_smoke_v1
~~~

默认输出到 `workbench/output/` 下带时间戳的 UTF-8 BOM CSV。文件包含原始字段、
隐藏审核元数据、标注用户名和用户 ID、响应状态及各个问题的回答。多人审核时同一
`case_id` 会出现多行，以保留每位标注者的独立判断。草稿和丢弃响应不会导出。

可以指定输出路径：

~~~bash
uv run python run.py \
  --export-dataset cozie_safety_review_single_smoke_v1 \
  --export-out workbench/output/smoke_review.csv
~~~

日常停用某个账号时，优先只移出 workspace；账号不会被删除：

~~~bash
uv run python run.py --remove-user medical_reviewer_01
~~~

永久删除单个账号时，必须提供完整用户名并再次确认：

~~~bash
uv run python run.py --delete-user medical_reviewer_01
~~~

永久删除同前缀、固定编号的整批账号：

~~~bash
uv run python run.py --delete-users 10 --user-prefix medical_reviewer
~~~

批量删除会先解析并显示 `medical_reviewer_01` 到 `medical_reviewer_10`，且只允许删除
`annotator`，不会删除 owner/admin。确认时必须输入终端提示的完整确认短语。
删除用户前建议先导出标注结果；Argilla 官方文档只保证删除后账号不能再登录，未承诺
历史响应一定保留。凭据 CSV 不会随账号自动删除，便于保留本地分配审计记录。

## 框架、Profile 与平台适配器

框架层只处理 CSV 读取、Profile 注册、offset/limit、抽样、导入导出和命令编排。
`TaskSpec` 与 `RecordSpec` 是框架和平台之间的稳定中间模型，不依赖 Argilla SDK。

`app/profiles/cozie_safety.py` 只负责审核任务本身：

- 不同来源 CSV 到标准记录的归一化
- 业务必需字段和默认值
- 五级中英双语标签
- 边界状态和理由码
- 医学逻辑 / `medical_rationale`
- 模型辅助审核与标签对照的数据展示方式

`app/platforms/argilla.py` 只负责 Argilla：

- 把通用 TaskSpec、RecordSpec 映射到 Argilla Settings、Record
- 创建数据集和上传记录
- 设置多人提交数
- 解析 workspace

以后增加其他任务时实现并注册新的 Profile；同一任务增加新的 CSV 结构时，只扩展该
Profile 的输入归一化；增加其他标注平台时新增 platform adapter。三者无需互相导入。

## 数据与密钥

- `.env` 不提交。
- `workbench/input/` 与 `workbench/output/` 中的文件不提交，只保留 `.gitkeep`。
- 第一轮审核会向标注员展示模型标签和模型理由，原标签仍作为隐藏元数据保存。
- 医学审核人和提交时间由 Argilla 自动记录。

## 开发检查

~~~bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
~~~
