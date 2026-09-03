# 标注平台工具包

这是一个独立的标注平台对接工具。它把“标注任务定义”和“平台实现”分开：

~~~text
annotation-toolkit/
├── app/
│   ├── profiles/          # 字段、标签、数据映射和审核阶段
│   ├── platforms/         # Argilla 等平台适配器
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

只导入 CSV 中前 5 条做联调时，使用独立数据集名称，避免和正式数据集混淆：

~~~bash
uv run python run.py \
  --mode review \
  --limit 5 \
  --dataset cozie_safety_review_smoke_v1
~~~

`--limit` 按 CSV 原始顺序取前 N 条，不会修改源 CSV。联调确认后再创建正式数据集。

跳过前 20 条、取第 21～40 条时，将 `--offset` 和 `--limit` 组合使用：

~~~bash
uv run python run.py \
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
  --mode review \
  --offset 20 \
  --limit 20 \
  --random \
  --dataset cozie_safety_review_random_20_v1
~~~

`--random` 必须和 `--limit` 一起使用。候选范围从 `--offset` 指定的位置开始到 CSV
末尾。空的 `sub_capability` 或 `predicted_safety_class` 不参与随机抽样。算法根据全局
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

## Profile 与平台适配器

`app/profiles/cozie_safety.py` 只负责审核任务本身：

- CSV 必需字段
- 五级中英双语标签
- 边界状态和理由码
- 医学逻辑 / `medical_rationale`
- 模型辅助审核与标签对照的数据展示方式

`app/platforms/argilla.py` 只负责 Argilla：

- 把字段和问题映射到 Argilla Settings
- 创建数据集和上传记录
- 设置多人提交数
- 解析 workspace

以后增加其他任务时新增 profile；增加其他标注平台时新增 platform adapter，不需要修改
Prompt Agent。

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
