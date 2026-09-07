# 一期CSV字段映射

参考旧340条的场景、画像和人工审核栏位。第一步生成用户输入及画像；第二步生成供医生审核的候选问诊材料。通过 [Output 收集器](../../output-collector-toolkit/index.html) 接收两份已有输出，按case_id组装CSV。第二个Prompt的批量输出为reviews数组，下表字段从每个reviews项映射，一项对应一个case；也兼容旧的单条Output。

| 内容 | CSV字段 | 一期填写方式 |
|---|---|---|
| 用户输入 | user_input | 第一步全新生成 |
| 画像依据 | user_profile | 第一步生成stage、locale、baby_age_days、background；随问题原样传给第二步，医生与模型都能看到 |
| 场景特征 | case_id、capability、sub_capability、priority、difficulty、turn_type | 组装时填写；turn_type统一为单轮，其余依选定场景和实际内容，不复制旧行值 |
| 候选安全分类 | candidate_safety_class | 第二步safety.candidate_class，待医生确认 |
| 初步判断及依据 | initial_assessment | 第二步2—3句话的文本，依据融入判断，不再拆出summary或病因列表 |
| 信息充分性 | info_sufficient | 若保留旧栏位则留空待审核，本次不由模型填；必要的未知信息通过follow_ups表达 |
| 可能问诊回应 | possible_consultation_response | 第二步输出的简短候选回应方向，供医生修订；不映射为被测系统的真实答复 |
| 追问 | follow_ups | 第二步0—2条question及purpose，不再输出priority；不需要时为[]，不模拟用户作答 |
| 分类边界 | boundary_note | 映射safety.boundary_note；仅有边界或五类无法表达时写一句说明，否则为空 |
| 其他分类与风险栏位 | classification_note、label_clarity、boundary_classes、risk_flags、urgency | 若保留旧栏位则留空待审核，不从短文本擅自推导；关键风险在初步判断和问诊方向中表达 |
| 标注要求 | required_behaviors、forbidden_behaviors、expected_final_points | 若保留旧栏位则留空，由后续评测设计或人工确认填写；第二个Prompt不再生成acceptance |
| 其他测试设计 | expected_intent、expected_action、judge_type、critical_assertions、pass_rule | 保留字段含义，后续组装时按实际需要填写；本期不填工具/RAG任务，不让模型自判通过 |
| 旧审核栏位 | conflict_pair、boundary_precheck、review_route、medical_review_label、non_medical_transfer、label_reasonableness、boundary_status、reason_codes、short_rationale | 保留原接口含义；预检查/路由可给建议，人工判断栏留空待审核 |
| 审核与裁决 | reviewer_name、reviewed_at、needs_expert_adjudication、adjudication_note、adjudicated_safety_class、review_status、medical_review_status | 审核人和结论由人工填写；可初始化待审核状态，不能由生成模型标为已批准 |
| 人工审定材料 | expected_safety_class、confirmed_assessment、confirmed_consultation_response、confirmed_follow_ups | 医生确认或修订后填写；与候选材料分别保存 |
| 被测系统结果 | predicted_safety_class、model_reasoning、classifier_matched、classifier_error | 保留为后续真实运行的字段，本次生成阶段不填写 |
| 版本与来源 | dataset_version、case_revision、scene_id、pair_key、changed_factor、source_ids、两个Prompt的实际版本及模型配置 | 由组装/运行记录，不让模型编造版本、来源链接或trace |

user_profile是明确提供的合成背景，不是目标标签或标准答案。问题与画像应一致；有意测试冲突时两者都原样展示，供医生确认。未知画像项保留null/空数组，不按“没有问题”处理。priority表示测试优先级，不等同于安全分类。

## 本期不用

- `conversation_history`不进入生成输出、审核输入或新基线。原CSV如因旧导入接口必须保留此列，仅在导入适配时填 `[]`，不能据此生成历史。
- `rag_required`、`expected_rag_behavior`、`expected_tool`、`expected_args_json`、`tool_mock_response`、`system_state`、`expected_card`不纳入本期；无时间依赖时不填current_datetime/timezone。
- 上版的 `draft_response`、`reference_response`、`response_reason`、`confirmed_response`不纳入本期，用初步判断和可能问诊回应表达医生标注材料；旧值不直接改名搬入。

initial_assessment保存普通文本；follow_ups等数组或对象可序列化为JSON单元格。旧的结构化initial_assessment、to_confirm和acceptance不直接搬入本版，notes只记录真实说明。现有Argilla Profile不会自动展示新增问诊字段，本目录没有实现导入适配，也没有替医生填写结论。

## 收集器的精简导出

[Output 收集器](../../output-collector-toolkit/index.html) 输出20列：case_id、id_prefix、local_id、user_input、user_profile、source_ids、pair_key、changed_factor、candidate_safety_class、boundary_note、initial_assessment、possible_consultation_response、follow_ups、draft_status、expected_safety_class、confirmed_assessment、confirmed_consultation_response、confirmed_follow_ups、reviewer_name、review_status。

case_id由填写的id_prefix和local_id拼接；pair_key有值时加同一前缀，原始值保留在JSON备份。draft_status仅表示材料是否配齐：draft_ready或missing_review，不表示医生批准。人工审核字段留空，不推导其余旧CSV栏位，也不虚构Prompt版本或场景标签。CSV使用UTF-8 BOM和标准引号转义；可能以公式开头的文本增加单引号前缀，完整原文以JSON备份为准。

独立收集器内嵌本目录当前两个输出Schema以支持离线使用。后续结构升级时，需要同步更新HTML中的question-schema和review-schema，并核对字段映射。
