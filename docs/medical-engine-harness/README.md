# 以医生审核为核心的医疗引擎闭环

状态：技术梳理与实施方案，2026-09-08。范围包括合成用例、候选材料、医生审核、差距归因、公共能力与医生方法、线上咨询执行和回归发布。本文不表示列出的建设任务已经实施。

**建议把系统分成“离线改进链路”和“线上咨询链路”，共同使用版本化的输入、策略、知识、医生方法与评测契约。** 医生意见先形成有来源、适用条件和确认状态的反馈记录，再决定修改哪个组件。一次差评不应直接变成一条永久 System Prompt。

本次产出：

- [现状、DeerFlow 对照与目标架构](architecture.md)
- [医生方法与公共组件的提取规则和首批案例](doctor-components.md)
- [实施任务、依赖、验收证据与闭环](work-items.md)
- [数据契约与状态转换](contracts.md)
- [本次梳理的完成核对](completion-audit.md)

数据证据在本地忽略目录：`review-query-toolkit/workbench/output/harness-review-20260908/`，包含50条审核响应的来源关联、结构性差距与下一步任务映射。该证据包不修改医生标签，也不把医生修改说明当成最终答案。

本机可直接打开[证据包索引](../../review-query-toolkit/workbench/output/harness-review-20260908/README.md)。如需重建，在toolkit根目录执行下面的只读分析；三个工具的虚拟环境需已安装依赖，输出目录必须不存在：

```bash
python3 docs/medical-engine-harness/build_evidence.py --output /tmp/medical-harness-evidence-new
```

脚本通过各工具独立进程读取数据、调用现有画像渲染器和评估CLI，并复现导出CSV直接回放失败。它不调用模型或网络；本地证据文件包含审核原文，不作为公共运行资产发布。`--cozy`与`--deer`可指定两个源码仓库的位置。

本批关键基线：引擎分类命中39/50（78%），候选分类33/50（66%）；32/50材料需要修订；39条分类正确记录中仍有23条材料需修订。多数类也占78%，且审核时可见模型分类，因此单一分类准确率不足以衡量咨询质量，具体口径见[统计报告](../../review-query-toolkit/workbench/output/medical-review-50-20260908-statistics.md)。

## 先明确三件事

1. `langfuse-toolkit/prompts/questions.*` 生成测试输入；`review.*` 生成待审材料。两者都是数据生产资产，不能作为线上回复是否正确的独立裁判。
2. `prompt-agent/prompt.md` 是安全分类提示词，输出只有分类和简短理由。医生对回应、追问、共情的意见主要回到候选材料生成器和线上回复模块，而非全部回到分类器。
3. 单位医生的50条审核只能提供“这位医生表达过的方法与偏好”的证据，不能证明某概念为其独有，也不能自动把所有意见升为公共医学知识。医生方法与公共组件的边界必须同时看功能、适用条件、证据来源和验证结果。

## 最先做的四项

| 顺序 | 工作 | 为什么先做 |
| --- | --- | --- |
| 1 | W01/W02：冻结来源、建立可回放的规范输入 | 当前审核 CSV 的画像是 Markdown，分类器要求 JSON；已验证直接回放失败。不能把格式差异变成模型差异 |
| 2 | W03/W04：整理审核语义和确认状态 | 有 ACCEPT 加意见、边界冲突、引用上一版等情况；未确认的说明不能进入标准答案 |
| 3 | W05：对齐离线与线上分类输入和资产 | 线上与离线分类文本不同，线上分类载荷不含业务画像；目前78%不能直接代表线上表现 |
| 4 | W09/W10：验证一组公共问诊规则和一个医生方法候选 | 先用可比较案例证明组件有效，再决定扩大共享范围；保留撤回能力 |

后续按 [work-items.md](work-items.md) 的依赖推进。当前运行时已有 Gateway、SDK Agent、RAG、MCP、输出审核与追踪，不需要先重建这些系统。

## 参考范围

主要代码基准为本机 DeerFlow 提交 `99367100fbdddeaf7cec29aebbc9170cb5653def`（2026-09-07）。该副本是 `heart-scalpel/deer-flow` fork，工作区有文档和配置改动；本方案依据实际读取的 harness 源码与测试，并记录文件摘要，不假定 fork、未提交文档和官方 main 完全一致。

同时核对了官方 [Harness 核心概念](https://github.com/bytedance/deer-flow/blob/main/frontend/src/content/en/introduction/core-concepts.mdx)、[组件开关与扩展入口](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/agents/features.py)、[Harness/App 依赖约束测试](https://github.com/bytedance/deer-flow/blob/main/backend/tests/test_harness_boundary.py)。本方案借鉴其组件与证据组织方式，保留 Cozy Agent 的现有执行内核。
