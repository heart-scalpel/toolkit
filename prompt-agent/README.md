# Prompt Agent

一个最小的 OpenAI Agents SDK 批量测试工具。你只需要改 `prompt.md`、填写 `.env`，
然后把测试输入放进 `workbench/cases.jsonl`，也可以直接传 Golden Set CSV。

## 安全分级批跑

当前 `prompt.md` 是 Cozie AI 健康咨询回复安全分级器的原始系统提示词。
针对工作台中的 Golden Set 批跑并只生成 CSV：

~~~bash
uv run python classify.py
~~~

指定其他 env 文件时：

~~~bash
uv run python classify.py --env /path/to/.env
~~~

结果写入 `workbench/output/safety_classifier_results.csv`，包含原始输入、期望分级、
模型分级、简短依据、是否匹配和错误信息。

批跑收集器导出的问诊 CSV 时，原始列（包括 case_id、画像、候选材料和空白人工字段）
全部保留。模型只读取用户问题和已提供的画像；若源文件含历史则传入 short_memory，
没有历史的单轮用例不补历史。候选分类、候选判断和人工答案不会进入模型输入。
人工标签为空时 matched 留空，准确率显示 n/a。旁边的 `.run.json` 记录实际模型、
输入和 prompt 的 SHA-256 及运行数量；批跑关闭 Agents tracing，仅调用配置的模型端点。
输出不能覆盖输入或已存在的结果，请每次使用新文件名。

~~~bash
uv run python classify.py \
  --cases ../annotation-toolkit/workbench/input/cases-2026-09-05T12-39-47-636Z.csv \
  --output ../annotation-toolkit/workbench/output/cases-2026-09-05T12-39-47-636Z_engine.csv \
  --concurrency 5
~~~

## 快速开始

需要 Python 3.12 和 uv。

~~~bash
cd prompt-agent
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY
uv sync
uv run python run.py
~~~

默认会并发执行 `workbench/cases.jsonl`，在终端打印摘要，并把完整结果写到
`workbench/output/results.jsonl`。

## 只改这三个地方

- `prompt.md`：Agent 的 system prompt / instructions。
- `.env`：API key 和模型，默认模型是 `gpt-5.6`。
- `workbench/cases.jsonl`：每行一条独立测试。

最简单的 case 可以直接写成 JSON 字符串：

~~~json
"你好，请介绍自己"
~~~

需要标识和最小断言时写成对象：

~~~json
{"id":"math","input":"2 + 2 等于几？","expected_contains":"4"}
~~~

`expected_contains` 可省略。填写后，输出不包含这段文字时该 case 会标为 `FAIL`，
命令退出码为 1；单个请求报错不会中断其他 case。

已有 CSV 时，默认读取 `case_id` 和 `user_input` 两列；允许表头前有一行标题。例如：

~~~bash
uv run python run.py --cases "workbench/004_02_黄金集.csv"
~~~

## 单条运行

~~~bash
uv run python run.py "用三句话解释什么是 Agent"
~~~

## 常用参数

~~~bash
uv run python run.py \
  --prompt prompt.md \
  --cases workbench/cases.jsonl \
  --output workbench/output/results.jsonl \
  --concurrency 10 \
  --model gpt-5.6
~~~

也可以在 `.env` 中设置 `PROMPT_AGENT_CONCURRENCY=10`。查看全部选项：

~~~bash
uv run python run.py --help
~~~

## 开发检查

~~~bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
~~~
