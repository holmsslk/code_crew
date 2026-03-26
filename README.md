# CodeCrew（基于 CrewAI 的多角色代码协作工作流）

本项目基于 **CrewAI** 框架实现，目标是在已有代码仓库中，以多角色协作方式完成一次可验证的最小改动交付。

对应实现说明文档见：
- `PROJECT_IMPLEMENTATION.md`

## 1. 这个项目做什么

本项目内置 4 个角色：
- Product Agent：把需求转成可执行规格
- Developer Agent：在代码库内做最小实现改动
- QA Agent：执行验证并给出证据
- Lead Agent：做阶段门禁与最终发布决策

整体是顺序工作流（sequential）：
1. 需求规格化
2. 需求门禁
3. 开发实现
4. 实现门禁
5. QA 验证
6. 最终决策

## 2. 环境要求

- Python `>=3.10,<3.14`
- `uv` 包管理器

## 3. 安装与准备

```bash
# 进入项目目录
cd /path/to/code_crew

# 安装依赖
uv sync
```

## 4. 必改配置：`.env`

在运行前，你必须按自己的模型服务修改 `.env` 中的以下信息：
- 模型名（model）
- 模型服务地址（base url）
- API Key

示例（请替换成你自己的值）：

```env
# 常见可选项
MODEL=anthropic/claude-sonnet-4-6
OPENAI_MODEL_NAME=gpt-4o

# 服务地址（如使用代理/兼容网关时）
OPENAI_BASE_URL=https://your-api-base-url/v1

# 密钥（按你使用的提供商填写）
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
```

注意：
- 当前代码中的 agent 模型在 `src/code_crew/crew.py` 里已写成 `anthropic/claude-sonnet-4-6`。
- 如果你要切换到别的模型，除了改 `.env`，也需要同步调整 `crew.py`（或改造为从环境变量读取）。

## 5. 使用教程

### 5.1 默认运行

```bash
uv run code_crew
```

### 5.2 带自然语言任务运行

```bash
uv run code_crew "请在当前项目中实现一个最小功能改动，并补充验证"
```

### 5.3 训练 / 回放 / 测试

```bash
# 训练
uv run train 3 training.json "Train coding-collaboration behavior."

# 回放
uv run replay <task_id>

# 测试
uv run test 2 gpt-4o-mini "Test coding-collaboration behavior."
```

### 5.4 触发式运行（JSON payload）

```bash
uv run run_with_trigger '{"user_request":"实现一个最小修复","repo_path":"."}'
```

## 6. 关键目录

- `src/code_crew/crew.py`：Crew、Agent、Task、Guardrail 核心逻辑
- `src/code_crew/config/agents.yaml`：角色定义
- `src/code_crew/config/tasks.yaml`：任务定义
- `src/code_crew/tools/custom_tool.py`：受控写文件/命令/diff 工具
- `PROJECT_IMPLEMENTATION.md`：实现细节说明

## 7. 重要警告（务必阅读）

`警告：该工作流 token 消耗速度极快。`

原因包括：
- 多角色串行执行（多次 LLM 调用）
- 每阶段都有结构化输出与门禁校验
- 开发与 QA 会读取代码、执行命令、生成证据

建议：
- 先用小任务、小仓库范围试跑
- 控制 prompt 长度和上下文范围
- 在非必要情况下关闭高成本调试日志

## 8. 常见问题

- 运行时报 key 错误：检查 `.env` 中对应 provider 的 API Key 是否正确
- 模型不可用：确认模型名、base url、账号权限是否匹配
- 成本过高：先降低任务复杂度，减少单次执行范围
