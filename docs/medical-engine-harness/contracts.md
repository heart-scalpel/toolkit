# 闭环数据契约与验收状态

本文是待实施的契约规范，不声称相关数据库表或API已经存在。各工具保持独立依赖环境，通过版本化JSON/JSONL及命令/API交换，不跨仓库导入同名 `app.*` 包。

## 1. 标识与版本

`case_id` 表示业务编号，不足以唯一确定被审核内容。最小关联链为：

`CaseRevision → DraftRevision/EngineRun → ReviewResponse → FeedbackItem → Adjudication → EvalCaseRevision/AssetRevision → ExperimentRun → ReleaseBundle`

| 对象 | 必须字段 | 关键约束 |
| --- | --- | --- |
| GenerationRun | run_id、prompt name+resolved version+content hash、完整参数、模型、Schema revision、输入/输出artifact hash、时间、状态 | label只作当时的选择器，保存实际解析版本；未知历史版本为null+missing_reason，不补造 |
| CaseRevision | case_id、revision、canonical_input、input_sha256、source_artifact_ref、source_ids、scenario、pair_key、changed_factor、generation_run_ref | query、画像或关键事实变化即新revision；有意冲突需在测试元数据记录，模型输入不泄露期望标签 |
| DraftRevision | draft_id、case_revision_ref、四项原始候选输出、generation_run_ref、content_sha256 | 每次重生成保留新版本；不能覆盖已有医生审核所指向的版本 |
| EngineRun | run_id、case_revision_ref、bundle_ref、model_result、effective_policy、fallback_reason、input/output hash、tool/event refs、status | 未调用、调用失败、正常高约束分类、执行下限导致升级分开；失败也保留在总分母 |
| ReviewResponse | response_id、case_revision_ref、reviewed_artifact_ref、reviewer_id、submitted_at或缺失说明、原始标签/处置/意见 | 一条响应属于一个审核人和被审版本；不可用当前CSV覆盖早期响应 |
| FeedbackItem | feedback_id、response_ref、target_field、原文引用与摘要、gap_type、claim_kind、scope_candidate、hypothesis、work_item_ids | 观察、原因假设、建议分开；一段意见可拆成多项，每项必须指回原文 |
| Adjudication | adjudication_id、feedback_refs、decision、resolved_content或reason、reviewer/owner、适用条件、evidence_refs、版本与时间 | 不确定时pending；不默选模型或某位医生，不按“多人提交了”推定一致 |
| EvalCaseRevision | case_revision_ref、已确认分类、回复任务要求、追问要求、适用证据、独立状态、split、family_id | 可有有效分类而材料未定稿；不得把说明性批注直接塞入expected_response |
| AssetRevision | asset_id、kind、scope、owner、revision/hash、条件、依赖、证据、批准状态、positive/negative cases | proposed不得进入正式bundle；医生资产不覆盖公共策略和权限 |
| ExperimentRun | experiment_id、candidate/base bundle refs、evalset revision/hash、运行参数、RAG fixture/live模式、grader版本、逐条结果、汇总 | 同源实现回放；没有有效样本或必需结果缺失不能PASS；所有修复/退化可定位 |
| ReleaseBundle | bundle_id、精确资产与模型/Schema/知识版本、experiment_refs、批准记录、prior_bundle、deployment_receipt | 发布记录、实际加载版本与trace一致才算生效；rollback是切回确定的旧bundle |

推荐 input_sha256 对 `canonical_input` 使用UTF-8、排序JSON键、固定紧凑分隔符、不允许NaN计算。保留原始artifact摘要；显示层Markdown、CSV公式保护前缀不参与语义重建。canonical编码规则自身有版本，避免规范化变化造成隐式换题。

## 2. 规范咨询输入

目标合同保留原始问题和来源，公共机制只理解确定的字段，不自由推断医学事实。

```json
{
  "schema_version": "consultation-input/v1-proposed",
  "query": "原始问题",
  "normalized_query": null,
  "facts": [
    {
      "fact_id": "f1",
      "subject": "baby",
      "name": "age",
      "value": 25,
      "unit": "day",
      "status": "provided",
      "source_ref": "case-revision:user_profile.baby_age_days"
    }
  ],
  "user_goal": {"value": "用户原文中的目标", "source_ref": "case-revision:profile"},
  "unknowns": [],
  "conflicts": [],
  "short_memory": [],
  "platform_safety": null
}
```

这个示例是契约示意，不是医学建议，也不预设该日龄的处置。

迁移原则：

- 保留合成集的精确 baby_age_days；向现有业务契约添加对应字段或显式事实列表，不能直接塞给会忽略未知字段的模型。
- 只做能证明等价的映射。无法从stage/background可靠解析结构字段时保留原文事实，不由适配器猜值。
- subject未知、服药主体歧义、问题画像冲突应显式保留，不能自动“纠正”成生成器或医生看起来更合理的解释。
- 分类器和回答器从同一规范输入选择各自允许字段，选择结果都有hash和字段列表；不一定看到全部相同内容，但差异必须是明确的设计，并在离线/线上一致。
- 人工标签、批注、候选标签、期望答案不进入被测模型输入。图片/病历等未来扩展需单独Schema，不由本批文字数据外推。
- 离线运行通过独立进程适配或正式业务入口调用线上工厂/组件，不在两个使用 `app` 命名的项目间拼接sys.path运行生产服务。

## 3. 审核语义：四条状态分别管理

| 状态轴 | 建议值 | 含义 |
| --- | --- | --- |
| source_status | valid / needs_clarification / superseded / invalid | 输入是否可作为同一用例被理解 |
| label_status | pending / confirmed / disputed / withheld | 分类能否用于标签评测 |
| material_status | pending / accepted / revise_required / confirmed_revision / excluded | 材料是否完成修改与确认 |
| asset_status | not_extracted / proposed / evidence_pending / reviewed / approved / revoked | 从反馈提取的规则或方法是否可执行 |

当前CSV的 ACCEPT/REVISE/EXCLUDE 和 YES/NO 是**原始观察字段**，保留不改。新增状态来自另一个确认记录。比如 ACCEPT+意见先标记需确认意见范围；不能默默改成REVISE，也不能默默忽略意见。

新的编辑操作应使用 `edit_type = replace / amend / delete / comment / reference_previous`。其中 delete显式表示删除追问；空值表示未修改，不表示删除；reference_previous必须有具体版本引用才能完成。

现有字段筛选得到42条的结果，仅称 `rule_filtered_classification_set`。它没有解决S13-Q003等语义问题，不能命名为 final_gold。未来真正发布的评测集由各状态轴和批准证据共同决定。

## 4. 反馈路由：何时修改什么

| gap_type | 默认工作项 | 不应自动发生的转换 |
| --- | --- | --- |
| source_integrity / input_contract | W01、W02、W04 | 改输入后沿用旧审核 |
| safety_classification | W04、W05、W06 | 用未裁决的低风险标签自动降级线上安全策略 |
| response_relevance / follow_up_quality | W08、W09、W12 | 全部归因于分类Prompt，或把原文说明直接作为回答 |
| domain_knowledge | W11 | 直接写入公共System Prompt或医生风格 |
| doctor_method | W10 | 单次观察直接认作该医生独有且普遍有效 |
| annotation_consistency | W03、W04 | 自动覆盖医生原始响应 |
| tool_evidence / output_lifecycle | W12、W14、W15 | 有调用日志就声称任务或医学验证成功 |

结构检查可自动提出路由；语义归因由分析者或模型提出假设，并保存来源。本文12个候选主题均为 `proposed`，没有自动执行的权限。

## 5. 可验收的实验，而不是单一准确率

| 评测层 | 指标/证据 | 失败情况 |
| --- | --- | --- |
| 输入与关联 | 每条源数据、被审版本、模型输入、输出可连接；字段等价断言 | 缺失/重复版本、事实丢失、对照被拆、标签泄漏 |
| 分类 | 全量/有效人工集、混淆矩阵、分类支持数、macro指标、误升/漏分、错误/回退率 | 用成功子集遮蔽服务失败；把策略回退混入模型分类准确率 |
| 回应任务完成 | 主问题是否回应、用户目标是否遵守、关键要求是否满足 | 分类正确但未回答、违背明确目标 |
| 追问 | 是否必要、中性、未重复已知、是否有改变决定的目的 | 机械凑问题、无依据引导疾病、先问完才处理明确风险 |
| 知识与工具证据 | request/doc/chunk/version引用、适用条件、实际成功结果 | 引用不存在、证据无关、只有检索次数没有支持关系 |
| 医生方法 | 公共基线 vs 加载医生方法的盲评、反例和禁用实验 | 偏好变化导致事实或安全约束退化 |
| 运行与流式输出 | 延迟、费用、token、工具失败、撤回、最终结果、版本追踪 | 只检查最终文本却漏掉已经显示的受限内容；已终止Run继续输出 |

最低确定性验收建议：版本/输入关联和泄漏检查必须全部通过；没有有效样本时不判通过；指定修复案例按已确认要求完成；已确认高约束回归不得新增漏分或绕过策略。连续质量指标以试验前登记的阈值与配对比较评估，W12负责把阈值、样本量和裁判责任明确写入实验协议，不能看到结果后改门槛。

## 6. 闭环状态与回执

工作项状态建议为 `open → ready → running → awaiting_review → validated → released → observed_closed`，也可以 `rejected/superseded` 明确关闭。

- awaiting_review：持久化待医生问题与artifact，结束当前模型Run；用户回复后开启新的Run并关联同一工作项。
- validated：保存测试输出、人工确认、基线与候选差异；不等于已上线。
- released：有实际部署/配置读取回执；不等于已经验证线上效果。
- observed_closed：线上记录确实使用该bundle，指定检查通过或无线上变更的任务明确标为offline_only。
- rejected/superseded：记录理由及替代任务；不能把无法解释的问题直接丢弃。

采用DeerFlow“执行记录与自述分开”的思路，但领域审核需另外提供审定证据。工具回执证明写过文件或跑过实验，医生的审定记录与适用证据证明相应内容获准使用。
