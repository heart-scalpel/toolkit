# Langfuse 工具包

通过命令行操作 Langfuse 后台，按 `instance`（实例）、`org`（组织）、`project`（项目）、`workflow`（工作流）分层。支持 Prompt 维护、LLM 查询与 Playground、数据集、调用记录、评分和实验结果查询。

## 开始使用

需要 Python 3.12 和 uv。在本目录执行：

```bash
cp -n '.env.example' '.env'
uv sync
```

在 `.env` 填入 `LANGFUSE_BASE_URL`、`LANGFUSE_PROJECT_PUBLIC_KEY`、`LANGFUSE_PROJECT_SECRET_KEY`，查询密钥所属项目：

```bash
uv run python run.py project info
```

将返回的项目 ID 填入 `LANGFUSE_PROJECT_ID`，然后执行：

```bash
uv run python run.py project check
uv run python run.py project llms list --all
uv run python run.py project prompts list
```

项目 ID 与密钥不匹配时会停止项目操作。组织项目列表使用 `org projects list`，需另配 `LANGFUSE_ORG_PUBLIC_KEY` / `LANGFUSE_ORG_SECRET_KEY`；`instance health` 无需密钥。已有 `.env` 不必重建，旧的 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 仍作为项目密钥读取。

## 使用文档

- [命令说明](docs/commands.md)：各层的用途、配置和常用命令。
- [工作流](docs/automation.md)：组合多个操作，统一校验、顺序执行。
- [代码分层](docs/architecture.md)：模块职责与依赖方向。
- 其他参数：例如 `uv run python run.py project prompts save --help`。

命令已按上述四组重新设计，旧顶层命令不再保留；已有脚本请按命令说明迁移。`.env` 不提交 Git。

## 母婴用例提示词与流程

日常操作请看 [用 Langfuse 生成 Case：操作指南](docs/case-generation-guide.md)，按步骤完成生成、收集和导出；已预留截图位置。

一期标注对象：**用户输入＋画像 → 候选安全分类、初步判断及依据、可能问诊回应和必要追问**。所有材料供医生确认或修改。本期全部单轮，不生成历史对话、RAG/工具测试或被测系统真实回复，也不要求完整的App用户答复。

产品可在Langfuse页面或通过本工具包维护两个Chat Prompt。本目录保留初始模板与字段约定，直接复制模板不需要安装依赖。目标是参考旧340条的场景生成全新100条问题及画像，旧行内容与标签不直接继承。

## 接收生成结果

分批粘贴两个Output、复制整批问诊输入和导出CSV，使用独立的 [Output收集器工具包](../output-collector-toolkit/README.md)。

## 两个 Prompt

| Langfuse 名称 | System | User | 输出 Schema |
|---|---|---|---|
| medical/user-question-generator | [问题与画像生成规则](prompts/questions.system.txt) | [生成变量](prompts/questions.user.txt) | [问题与画像结构](schemas/question-output.schema.json) |
| medical/case-review-draft | [医生候选问诊规则](prompts/review.system.txt) | [审核输入](prompts/review.user.txt) | [问诊材料结构](schemas/review-output.schema.json) |

第一个System维护场景定义与生成要求，第二个System维护五类安全边界、问诊材料要求与妈妈体验原则。Prompt正文仅包含模型执行需要的任务、规则和输出格式；数据来源、批次配额、步骤衔接与版本维护说明放在本文。

## 使用步骤

1. 将上表System与User保存到对应Chat Prompt的新版本，在Playground配置对应输出Schema并选择可用模型。Schema支持范围取决于模型服务，第一次试跑需核对实际输出。
2. 第一个Prompt先填 `count=6`、`scenario=S01｜孕期与待产准备`、`requirements=按场景默认`；`source_materials`和`existing_questions`没有内容时都填 `[]`。人群、阶段、画像要求和对照条件可以写入requirements。
3. 用Output收集器接收问题后点「复制整批问诊输入」，把 `{"cases":[...]}` 粘贴到第二个Prompt的 `case_input`。每项仅含唯一case_id、原样的user_input和user_profile。第二个Prompt返回 `{"reviews":[...]}`，整段交回收集器按编号合并。
4. 医生查看问题与画像后，审核候选分类、初步判断及依据、可能问诊回应和必要追问。普通信息问题不强制列病因，未知信息通过必要追问补充。
5. 小样风格确认后固定两个Prompt版本及模型配置，按下表的18个场景配额完成100条计划，再按[CSV字段映射](docs/csv-fields.md)准备标注。模型不能替医生填写审定结论。

## 批次配额（产品使用）

每次在count中填写实际生成数量，在scenario中填写对应场景ID及名称。以下配额合计100条，全部单轮；它是测试覆盖安排，不代表用户需求发生率。少量试跑不代表完成整组或整批。

| 场景ID | 场景 | 数量 |
|---|---|---:|
| S01 | 孕期与待产准备 | 6 |
| S02 | 开奶与早期奶量 | 6 |
| S03 | 含接与抱姿 | 8 |
| S04 | 喂养规律与吐奶 | 6 |
| S05 | 奶量、追奶与目标 | 6 |
| S06 | 泵奶与日常管理 | 6 |
| S07 | 储奶与外出 | 6 |
| S08 | 返工与送托 | 8 |
| S09 | 喂养选择与心理压力 | 8 |
| S10 | 饮食、运动与补充剂 | 4 |
| S11 | 一般医学知识 | 4 |
| S12 | 个体医疗判断 | 5 |
| S13 | 药物与补充剂边界 | 4 |
| S14 | 母体高风险 | 5 |
| S15 | 婴儿高风险与数字边界 | 5 |
| S16 | 信息充分性与追问 | 4 |
| S17 | 画像信息使用与冲突 | 4 |
| S18 | 自然语言注入与隐私边界 | 5 |

## 画像和问诊材料

`user_profile`含 `stage`（阶段）、`locale`（提问语言地区）、`baby_age_days`（日龄）和 `background`（相关背景事实数组）。未知阶段/日龄填null，未出生的宝宝日龄为null；背景可包含喂养方式、目标、工作或支持条件。画像是问诊依据，无需把所有事实重复塞进问题。

第二个Prompt输出reviews数组；每个数组项只含四项标注材料，另带case_id用于关联：

| 字段 | 内容 |
|---|---|
| safety | 一个候选安全标签；有分类边界时补一句boundary_note，明确时留空 |
| initial_assessment | 2—3句话写初步判断，依据融入其中；有必要才提可能解释 |
| possible_consultation_response | 1—2句话表达可能的问诊回应方向，不重复判断 |
| follow_ups | 0—2条实际追问，每条仅有question和一句purpose |

候选解释不能作为确诊。未提供的信息只在确实影响判断或下一步时追问，不另列待确认清单、病因列表或验收要求。

妈妈心得融入目标尊重、减轻负担和有依据的安抚：不默认追奶或纯母乳优先，不将个人成功经历推广为医学规则；需要及时帮助时不等待追问完成。

## 本次版本变化

问题输出中的历史字段改为画像；审核输入改为 `case_id + user_input + user_profile`。原历史真实性场景S17改为“画像信息使用与冲突”，数量仍为4条，整个计划保持100条单轮。完整参考回复及回复理由改为初步判断、依据和可能问诊回应。

第一个Prompt及其v2.0.0 Schema保持不变。第二个输出Schema升级为v3.0.0：initial_assessment改为简短文本，移除重复的分类理由、独立待确认项、风险元数据和验收清单，追问最多2条。这个结构版本号与Langfuse自动分配的Prompt版本号无关。

当前第二个输出Schema为v4.0.0：在v3的单条材料外增加reviews数组，每条内容与长度要求不变。System和User同步支持逐条独立处理cases批次，变量名仍为case_input；单条输入也返回reviews数组。

在Langfuse更新第二个Prompt时，替换System、User和输出Schema三个位置。收集器兼容旧单条材料及浏览器暂存/JSON备份；本地文件更新不会自动同步线上Prompt。

本目录维护两个Prompt及字段约定。已有输出通过独立的Output收集器工具包组装CSV；模型调用仍在Langfuse完成，Argilla新增字段展示需另行适配。
