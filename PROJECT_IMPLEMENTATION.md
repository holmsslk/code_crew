# 项目实现说明（code_crew）

本文档说明当前项目的实际实现结构与运行机制。

## 1. 项目定位

`code_crew` 是一个基于 CrewAI 的“单任务代码协作”系统，目标是在已有仓库上完成一次最小可行改动，并通过分角色流程给出可追溯结果。

技术栈与版本：
- Python `>=3.10,<3.14`
- `crewai[anthropic,tools]==1.11.1`

## 2. 目录结构（关键文件）

- `src/code_crew/main.py`：CLI 入口，负责接收用户请求并 kickoff
- `src/code_crew/crew.py`：核心编排（Agent、Task、Guardrail、Crew 配置）
- `src/code_crew/config/agents.yaml`：4 个角色定义
- `src/code_crew/config/tasks.yaml`：6 个任务定义与 JSON 协议
- `src/code_crew/tools/custom_tool.py`：3 个受控工具实现
- `knowledge/user_preference.txt`：项目知识文件（当前未在 crew.py 挂载到 knowledge_sources）

## 3. 多角色设计

在 `agents.yaml` 中定义 4 个角色：
- `product_agent`：把自然语言需求转成可执行规格
- `developer_agent`：进行最小改动实现与命令验证
- `qa_agent`：做验证与回归风险评估
- `lead_agent`：执行阶段门禁与最终发布决策

在 `crew.py` 中，4 个 Agent 都配置了：
- `llm="anthropic/claude-sonnet-4-6"`
- `inject_date=True`
- `reasoning=True`
- `respect_context_window=True`
- `allow_delegation=False`

## 4. 任务流水线（顺序执行）

`process=Process.sequential`，总共 6 个任务：
1. `product_spec_task`
2. `lead_scope_gate_task`
3. `developer_implementation_task`
4. `lead_quality_gate_task`
5. `qa_validation_task`
6. `lead_final_decision_task`

每个任务在 `tasks.yaml` 中都要求输出“严格 JSON 协议”，并通过 `context=[...]` 串联前序结果形成黑板式协作。

## 5. 输出模型与协议

`crew.py` 中用 Pydantic 定义了协议模型：
- `ProductOutput`
- `LeadGateOutput`
- `DeveloperOutput`
- `QAOutput`
- `LeadFinalOutput`
- `BlackboardSummary`

其中：
- 产品与门禁任务使用 `output_pydantic=...` 直接结构化解析
- 开发/QA/最终决策任务使用 guardrail 做协议与证据校验

## 6. Guardrail 机制

实现了 3 个关键 guardrail：

- `_developer_guardrail`
  - 要求 `files_to_change`、`commands_executed` 非空
  - 校验声明改动文件与 `git diff --name-only` 有交集
- `_qa_guardrail`
  - 要求 `executed_checks`、`evidence` 非空
  - 若 `verdict=pass`，必须包含至少一个与 `pytest` 相关的检查
  - 要求仓库存在实际 diff
- `_lead_final_guardrail`
  - 若 `release_recommendation=ship`，必须存在实际 diff

为提升鲁棒性，还实现了 JSON 提取与容错逻辑（从纯文本、代码块、嵌套字段里提取 JSON）。

## 7. 受控工具实现

`custom_tool.py` 提供 3 个安全工具：

- `ControlledWriteFileTool`
  - 限制只能写入 `repo_path` 内，阻断路径逃逸
  - 支持 `overwrite/append`
- `ControlledCommandTool`
  - 命令前缀白名单（如 `python/uv/pytest/git/...`）
  - 禁止 shell 链接与重定向（`&&`, `|`, `>` 等）
- `ControlledGitDiffTool`
  - 返回仓库 diff，可选 `--cached`、文件范围

## 8. 运行入口与环境变量

`main.py` 暴露了以下入口函数：
- `run()`：默认执行（支持从命令行参数拼接 `user_request`）
- `train()` / `test()` / `replay()`
- `run_with_trigger()`：接收 JSON trigger payload

关键运行参数：
- `inputs.user_request`：用户自然语言请求
- `inputs.repo_path`：目标仓库路径（默认 `.`）
- `TARGET_REPO_PATH`：运行时环境变量（供 guardrail 使用）

## 9. 当前行为特点

- 偏向“可验证交付”：任务协议、门禁和证据要求较严格
- 偏向“最小改动”：开发任务强调 architecture-aligned patch
- 明确避免无限讨论：Lead 任务限制反馈范围并要求收敛
