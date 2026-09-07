# Output 收集器

用浏览器打开 [Output 收集器](index.html)，无需安装依赖或启动服务。

1. 左侧填编号前缀（如 `S01`），粘贴第一个 Output，点「收下问题与画像」。`Q001` 会变成 `S01-Q001`；同场景新批次用 `S01-B02` 等新前缀。
2. 点输入框下方的「复制整批问诊输入」。默认选择刚收下的编号前缀，也可切到「全部问题」。一次复制 `{"cases":[...]}`，每条的编号、问题和画像一起带上，粘贴到第二个Prompt的 `case_input`。
3. 第二个Prompt一次返回 `{"reviews":[...]}`。整段粘贴到右侧，点「收下医生审核材料」，按完整case_id逐条匹配。也兼容旧的单条输出、多段JSON和Playground `{}` 视图中的input/output包装。
4. 点「下载 CSV」得到一条问题一行的标注表；点「下载 JSON 备份」保留完整原文，之后可恢复。

接收后会自动暂存到当前浏览器。重复内容跳过；同编号问题冲突时整批不写入；问诊材料更新需勾选替换。未关联的问诊材料会暂存并阻止 CSV 导出；缺少问诊材料的问题仍可导出并标记 `missing_review`，配齐后为 `draft_ready`，医生审核栏保持空白。

CSV 内画像、来源及追问保存为 JSON 单元格；对照 pair_key 加编号前缀，避免跨批次碰撞。CSV 对可能被表格解释为公式的开头加文本前缀；JSON 备份与复制问诊输入保持原文。浏览器暂存不替代备份，换浏览器或电脑时使用 JSON 备份恢复。本工具不调用模型、不上传数据。

## Langfuse配置

第二个Prompt使用批量版 [System](../langfuse-toolkit/prompts/review.system.txt)、[User](../langfuse-toolkit/prompts/review.user.txt) 和 [输出Schema](../langfuse-toolkit/schemas/review-output.schema.json)。变量名保持 `case_input`。输入支持包含cases数组的对象或单条case，输出统一为reviews数组；每条材料仍只有原来的四项内容及case_id。

例如S01收下5条问题，复制后传入5条，返回5条，右侧一次接收。数据多时可按编号前缀分批操作；如果模型输出被截断，减少该次批量，不接收不完整JSON。工具会显示实际配齐数和待补数，不能仅凭模型返回成功判定整批完成。

## 包内文件

- `index.html`：独立离线工具，双击或用浏览器打开。
- `README.md`：使用与维护说明。

本包与 [langfuse-toolkit](../langfuse-toolkit/README.md) 平级。提示词与场景规则在该包和Langfuse中维护；这里接收已有Output并导出表格。

当前内嵌QuestionOutput v2.0.0和ReviewOutput v4.0.0，结构定义见 [问题Schema](../langfuse-toolkit/schemas/question-output.schema.json) 和 [问诊Schema](../langfuse-toolkit/schemas/review-output.schema.json)。运行时不读取其他包，后续结构升级时同步更新HTML中的两份Schema和字段映射。

CSV字段与标注约定见 [字段映射](../langfuse-toolkit/docs/csv-fields.md)。JSON备份可用于更换浏览器、电脑或工具文件位置后恢复已收集内容。
