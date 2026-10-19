<div align="center">

[English](README.md) · **简体中文**

# ◉ DOT · AI 跨境汇款助手

**一个会「理解 · 规划 · 安全执行」的金融 Agent —— 比较方案、预测汇率、提醒你何时换汇，并把日常开销理清楚。**

![Python](https://img.shields.io/badge/Python-3.12-111?style=flat-square) ![FastAPI](https://img.shields.io/badge/FastAPI-backend-111?style=flat-square) ![Vanilla JS](https://img.shields.io/badge/Vanilla%20JS-ES%20modules-111?style=flat-square) ![Tests](https://img.shields.io/badge/tests-138%20passed-111?style=flat-square) ![i18n](https://img.shields.io/badge/i18n-EN%20·%20简%20·%20繁%20·%20VI%20·%20JA%20·%20KO-111?style=flat-square)

![总览](docs/screenshots/overview.png)

</div>

---

## 这是什么

跨境汇款时，人们要同时考虑汇率、手续费、可用资金、收款人和到账时间。**参考汇率算出的金额 ≠ 扣费后真正到账的金额**，最低手续费也不一定到账最多。

DOT 是一个自然语言 AI Agent，帮你：

- 🔍 **看懂汇率**：真实的 ECB 日参考汇率，带来源与时间；按你的汇款方向解读历史高低位
- ⚖️ **比较方案**：参考计算、模拟方案、沙盒报价三者严格区分，按到账金额或速度排序
- 📝 **准备支付**：固定发送额，或按“对方要收到多少”反算
- 🛡️ **安全执行**：13 项风控检查 + 你的明确授权，Agent 永远不能批准自己的支付
- ⏰ **挑好时机换汇**：比较之后设置提醒——目标汇率、“有利水平”（近 90 天最好的 10–30%）或最晚换汇日；可选浏览器通知
- 🧾 **理清日常开销**：导入银行 CSV、扫描小票、文字或语音快速记账（“午饭 35元”）；自动建议分类、标记疑似重复、周期开销、一键批量审核
- 🎓 **学生理财**：“我买得起吗？”判断、按学期的现金流规划（学费、生活费、收入）、奖学金与助学金跟踪（截止日期与材料清单）、带具体建议的周/月消费洞察，以及邮件报告
- 🧾 **全程可追溯**：谁授权了什么、跑了哪些检查、之后发生了什么，一条审计轨迹全部回答

> 本项目实现了课程/产品文档《AI Cross-Border Remittance Assistant》v4.0 中的全部功能模块（4.1–4.15），对照表见[下文](#-文档需求对照)。

---

## ✨ 亮点

### 1. 理解 → 规划 → 执行，每一步都看得见

Agent 每轮对话先调用 `record_plan` 记录**意图、提取的金额币种收款人、缺失信息、计划步骤**，再按权限等级调用工具。三个阶段通过 SSE 实时流式呈现，工具结果以卡片展示（汇率、比较、草稿、记账），并标注数据类型——参考数据、模拟还是账本记录。

![AI 助手](docs/screenshots/agent.png)

- 未配置大模型时，由**离线规则规划器**驱动同一条流水线（明确标注“不是 AI”），支持 6 种语言的常见意图，缺信息会追问并在下一句补全
- 配置任意 **OpenAI 兼容**、支持 function calling 的模型后即为真 AI
- 模型工具里**没有**“批准”“提高额度”——说“好的”永远不等于授权

### 2. 先比较，再汇款

![方案比较](docs/screenshots/compare.png)

输入金额实时比较：参考汇率基准、三种模拟方案（银行电汇 / 在线汇款 / 即时取现）与可执行的沙盒报价，列出固定费、百分比费、适用汇率、价差、时效、较参考损失和**未包含的费用**。

### 3. 授权必须是一个刻意的动作

![授权](docs/screenshots/authorize.png)

授权屏显示环境标签、精确金额、费率来源、报价倒计时、状态时间线和逐项风控检查。勾选确认后需要**长按圆环**才能授权；授权绑定详情摘要（SHA-256），任何改动都会使其失效。

### 4. 规划换汇时机，到点提醒

「汇款」页新增第三步：**换汇时机与提醒**。它展示今天的参考汇率、90 天位置和实验性 7 天预测区间，然后让你设置提醒——目标汇率（默认取预测区间上沿）、有利水平，以及到账截止前几天的最晚换汇日。后台每十分钟检查一次；提醒出现在铃铛里，你允许的话还会弹出浏览器通知。我们不假装知道哪天最好——只是替你盯着汇率。

### 5. 看得清的开销

「记账」页为留学生设计：把银行导出的 CSV 拖进来（自动识别逗号/分号、支出/收入分列、日在前的日期和 GBK 编码），每一行都以**待审核**状态进入，附带建议分类和疑似重复标记（同商家同金额 ±2 天内，含重复导入的账单）。勾选、批量改分类、确认——你的修改会按商家学习。小票由视觉模型识别，保存前一定给你核对。快速记账能理解 `午饭 35元`、`bus pass 40`、`昨天 打车 23元` 和语音输入。周期开销（房租、话费、订阅）会提前一周生成**预计**条目等你确认或调整。AI 助手也能记账（`log_expense`），但同样进入审核队列。

### 6. 学生理财

「学生理财」页用你自己的数字规划整个学期：

- **我买得起吗？**——输入价格，对照现有现金（账本 + 你填写的持有资金）、学期计划、即将到期的学费和其他支出、安全垫，以及本月预算剩余，给出“可以买 / 可以但偏紧 / 现在不建议”，附带数字、买前买后余额曲线和更稳妥的日期。
- **学期现金流**——添加学期（起止日期、学费及截止日、每月生活费和收入）。每月金额按天平摊，学费按日期计入，已获得的奖学金按发放日计为收入，学期以外的月份按你已确认开销的平均值估算。结果包括期初现金、每月月末余额、最低点和首次缺口。
- **奖学金与助学金**——从“了解中”到“已获得”的状态、截止倒计时、材料清单（成绩单、简历、个人陈述、推荐信……），材料未齐时在截止前 14/7/3/1 天提醒；学费截止日同样提醒。
- **消费洞察**（在「记账」页）——最近 7 天或 30 天与上一期及平时水平对比，给出建议：哪类开销上升、频繁的小额消费、订阅总额、学期预算进度、即将到期的学费和计划缺口，并估算能省多少。
- **邮件报告**——每周（周一）或每月（1 号）的报告和重要提醒，通过你自己的 SMTP 服务器只发给你保存的那一个地址；没配置 SMTP 也能预览。

这里的一切都是基于你的计划和已确认开销的估算，不构成理财建议，也不会动用任何资金。

### 7. 工具与记忆

**工具**在 [`finance/tools.py`](finance/tools.py)。每个工具用 `@tool(名称, 说明, 参数, 等级)` 在实现旁边声明一次；Agent 统一做参数校验、权限等级检查（T1 查看 / T2 准备 / T3 提交）并逐次写审计。共 33 个工具，包括 `afford_check`、`cashflow_plan`、`spending_insights`、`track_scholarship`、`log_expense`、`remember_note`——并且刻意没有“批准支付”“提高额度”“修改收款人”。新增工具只需写一个带装饰器的函数。

**记忆**在 [`finance/memory.py`](finance/memory.py)，分三层：

| 层 | 内容 | 用法 |
| --- | --- | --- |
| 对话 | 每个会话最近 12 轮 | 每次请求一并发送，便于理解追问 |
| 笔记 | 你让它长期记住的事实：人物、习惯、偏好 | 每轮把最相关的笔记作为**数据**注入；Agent 用 `remember_note` 保存，你可以在「记忆」页查看和删除 |
| 经历 | 每轮一条：请求、意图、调用（及被阻止）的工具、涉及的支付、结果 | 可用 `recall_memory` 检索；最近经历让 Agent 保持连续性 |

检索支持多语言（拉丁文字按词、中日韩按字符二元组）。记忆拒绝保存密码、密钥和完整账号/卡号，从不授予权限，也从不作为余额或支付的证据。

![记忆](docs/screenshots/memory.png)

### 6. 黑白点线圆 · 会动的极简

| 拉近推远 · 景深模糊 | 深色模式 |
| --- | --- |
| ![缩放](docs/screenshots/zoom.png) | ![深色](docs/screenshots/dark.png) |

- 点阵背景随鼠标形成**放大镜**，点线圆星群缓慢漂移、随滚动视差
- 页面切换的**景深过渡**：前进时旧页推远模糊、新页拉近；手机**左右滑动**切页
- 旅程轨道图与汇率图支持**滚轮/双指缩放、拖拽平移**，点击节点拉近并让背景层虚化
- 弹窗从点击处缩放展开、背景模糊；滚动揭示、3D 卡片倾斜、磁吸按钮、数字滚动、绘线动画
- 尊重 `prefers-reduced-motion`；零外部依赖，严格 CSP（仅 `'self'`）

### 7. 六种语言

English · 简体中文 · 繁體中文 · Tiếng Việt · 日本語 · 한국어 —— 数字、日期、地区名均用 `Intl` 本地化，后端错误码由前端翻译。

| 한국어 | Tiếng Việt |
| --- | --- |
| <img src="docs/screenshots/mobile-ko.png" width="300"> | <img src="docs/screenshots/mobile-vi.png" width="300"> |

---

## 🏗 架构

```mermaid
flowchart LR
    U[用户 · 6 种语言 UI] -->|会话 cookie / SSE| N[Nginx]
    N --> API[FastAPI]
    API --> AG[Agent<br/>理解 → 规划 → 执行]
    AG -->|白名单工具 · 权限等级| S[Finance 服务]
    API --> S
    S --> G[13 项风控检查]
    G --> SB[沙盒提供方<br/>本地模拟 · 异步结算]
    S --> R[参考汇率<br/>ECB / Frankfurter]
    S --> DB[(SQLite<br/>账本 · 追加式审计)]
    W[后台 worker] -->|对账 · 提醒 · 汇率提醒| S
```

| 模块 | 文件 |
| --- | --- |
| Agent 编排（模型循环、流式事件、经历记录） | `finance/agent.py` |
| **工具注册表**——每个工具的参数、权限等级与实现 | `finance/tools.py` |
| **记忆**——对话、笔记、经历、检索 | `finance/memory.py` |
| 离线规则规划器 | `finance/agent_rules.py` |
| 支付核心、风控、授权、路线 | `finance/service.py` |
| 比较、情景、目标预算、建议与提案 | `finance/planning.py` |
| 付款习惯、提醒去重、汇率提醒 | `finance/habits.py` |
| 参考汇率、历史分析、回测预测 | `finance/rates.py` |
| 沙盒提供方 | `finance/providers.py` |
| 记账：CSV 导入、分类、去重、审核、周期、快速记账 | `finance/expenses.py` |
| 学生理财：奖学金、学期、现金流、买得起判断、洞察、邮件报告 | `finance/student.py`、`finance/student_i18n.py`、`finance/mailer.py` |
| API、SSE、独立服务 | `finance/api.py`, `finance/web.py`, `finance/worker.py` |
| 前端（原生 ES modules） | `frontend/dist/js/**` |

---

## 👥 组员：从 GitHub 下载后如何运行

**需要：** 本私有仓库的访问权限（请仓库所有者把你加为 Collaborator）、[Git](https://git-scm.com/)、[Python 3.10+](https://www.python.org/downloads/)、[Docker Desktop](https://www.docker.com/products/docker-desktop/)（保持运行）。

```bash
git clone https://github.com/ytan0008/dot-remittance-agent.git
cd dot-remittance-agent
python scripts/configure.py          # 生成你自己的 .env（令牌和密码），不会显示任何密钥
docker compose up --build -d --wait  # 第一次构建需要几分钟
```

打开 **http://localhost:8787** —— 会自动以本机 Owner 身份进入。

- **接入 AI 模型（可选）：** 在 `.env` 中填写*你自己的* Key：`OPENAI_API_KEY=sk-...`（已预设 `gpt-6-luna`），保存后执行 `docker compose up -d --force-recreate backend`。不填 Key 时 Agent 以标注清楚的离线规则模式运行。不要提交 `.env`，也不要在聊天里分享 Key。
- **数据互不影响：** 每个人的副本都有独立的数据库和测试资金。
- **端口被占用？** 在 `.env` 加一行 `FRONTEND_PORT=8799`，改用这个端口打开。
- **更新到最新代码：** `git pull`，然后 `docker compose up --build -d --wait`。
- **停止 / 启动：** `docker compose stop` / `docker compose up -d`。清空本地全部数据：`docker compose down -v`。
- **不用 Docker 跑测试：** `python -m venv .venv`，再 `.venv\Scripts\pip install -r requirements.lock.txt`（macOS/Linux 用 `.venv/bin/pip`），然后 `python -m pytest -q`。

## 🚀 快速开始

### Docker（推荐）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock.txt
.\.venv\Scripts\python scripts/configure.py      # 生成 .env：令牌和密码（不输出密钥）
docker compose up --build -d --wait
```

打开 **http://localhost:8787**。本机演示模式会自动以 Owner 身份登录。

### 不用 Docker

```powershell
$env:ENABLE_DEMO_LOGIN = 'true'
.\.venv\Scripts\python -m finance.cli serve       # UI: http://127.0.0.1:8000  · API 文档: /api/docs
```

### 接入大模型（可选）

在 `.env` 设置 `OPENAI_API_KEY`、`OPENAI_MODEL`，可选 `OPENAI_BASE_URL`（任意 OpenAI 兼容服务），然后 `docker compose up -d --force-recreate backend`。

### 邮件报告（可选）

在 `.env` 中填写 SMTP（`SMTP_HOST`、`SMTP_PORT`、`SMTP_SECURITY`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM`），然后运行 `docker compose up -d --force-recreate backend`，再到「学生理财 → 邮件报告」保存你的邮箱。Gmail / Outlook 请使用应用专用密码。

### 试试新功能

1. 「汇款」→ 输入金额 → 在第 ③ 步勾选“目标汇率”和/或“有利水平”→ **设置提醒**
2. 「记账」→ 拖入银行 CSV → 审核待确认的行（疑似重复默认不勾选）→ **确认**
3. 「学生理财」→ 添加学期 → 输入价格问“我买得起吗？”；跟踪一个奖学金并勾选材料
4. 「记账」→ 输入 `午饭 35元`（或点麦克风）→ **保存**；或 **扫描小票**（需要支持图像的模型，否则手动填写）

### 沙盒测试金额

| 金额小数 | 结果 |
| --- | --- |
| 普通金额 | 提交 → 处理中 → 约 8 秒后完成，结算一次 |
| `.13` 结尾 | 服务商拒绝 → 失败，释放预留资金 |
| `.57` 结尾 | 响应丢失 → “结果待核对”，按自身 ID 查回原交易，**绝不新建第二笔** |

---

## 📋 文档需求对照

| 模块 | 实现要点 |
| --- | --- |
| 4.1 资金与转账需求 | 固定发送额或目标到账额（反算保证不少于目标）、用途、到账日期、关联目标；缺失信息先追问 |
| 4.2 地区与 APEC 路线 | 21 个 APEC 经济体（币种/语言/时区）；路线增删启停；支付需单独开启且服务商支持；参考数据验证能力 |
| 4.3 最新汇率 | ECB 优先，缺失时用 Frankfurter 混合源并标注；来源、方向、观测日、频率、变化、交叉推导；**不编造** |
| 4.4 历史分析 | 30/90/365 天最低最高平均、百分位、高中低位、新高新低、覆盖率；按方向解读 |
| 4.5 预测与情景 | 实验性 7 天模型 + 滚动回测，与“不变汇率”基线对比、留出数据检验区间覆盖；情景计算器 |
| 4.6 方案比较 | 参考计算 / 模拟方案 / 沙盒报价三类区分；按到账或速度排序并说明依据；未计费用披露 |
| 4.7 多币种资金 | 分币种总额/可用/预留；参考等值注明来源且“并非兑换”；确认后才结算，失败才释放 |
| 4.8 目标与预算 | 已完成与已计划分离；收入/支出/安全缓冲/自填持有；一次性 vs 分期与资金缺口 |
| 4.9 自然语言 Agent | 首步强制记录计划；SSE 流式三阶段；数据类型标注；聊天与界面共享状态 |
| 4.10 权限与风控 | T1 查看 / T2 准备 / T3 提交；13 项检查在授权前与提交前各跑一次，逐项入审计 |
| 4.11 端到端沙盒转账 | 报价 → 风控 → 授权屏 → 长按授权 → 幂等提交 → 异步跟踪 → 结算 → 回执；失败与超时恢复 |
| 4.12 授权与历史 | 接受建议 / 确认修改 / 授权支付 三类独立记录；修改即作废旧授权 |
| 4.13 审计 | 时间、执行者、动作、结果、关联 ID、请求 ID；拒绝也记录；敏感信息打码；触发器禁止改删 |
| 4.14 信用习惯 | 应付项目与每月重复、按时/逾期、内部指标（显著标注“不是信用评分”）、信用知识 |
| 4.15 提醒与回执 | 截止、报价过期、未决交易、资金不足、目标汇率、有利水平、换汇日、预计开销、奖学金与学费截止；指纹去重；浏览器通知与邮件；可打印回执 |
| 扩展：记账 | 银行 CSV 导入（建议分类、重复检测、审核步骤）、小票扫描、文字/语音快速记账、周期开销、批量审核 |
| 扩展：学生理财 | “我买得起吗？”、学期现金流规划、奖学金与助学金跟踪、带建议的周/月洞察、邮件报告与提醒 |

---

## 🔐 安全模型

- **角色分离**：Owner / Agent / Viewer 令牌由后端区分；浏览器使用 HttpOnly + SameSite=Strict 会话，写请求要求同源头
- **授权绑定**：沙盒支付需 Owner 对报价摘要逐笔授权；字段、收款人变化或报价过期即失效
- **未确认不计入**：导入、扫描和 AI 记下的开销都保持待审核，直到你确认；小票照片在浏览器里先压缩，且不会被保存
- **精确金额**：后端一律最小单位整数，超过 2^53 以字符串传输，前端 BigInt 格式化
- **模型约束**：工具白名单、参数校验、轮数上限；疑似私钥/API key 的消息直接拒绝

---

## 🧪 测试

```powershell
.\.venv\Scripts\python -m pytest -q        # 138 项：服务、风控、记账、学生理财、邮件、提醒、API、规则规划器、6 种语言
.\.venv\Scripts\python -m finance.demo     # 离线演示：未授权被拒 → 授权 → 执行 → 幂等 → 超时恢复

docker build -f tests/browser/Dockerfile -t remittance-agent-browser-test .
docker run --rm --network remittance-agent_default --mount "type=bind,source=$PWD/artifacts,target=/artifacts" remittance-agent-browser-test
```

浏览器验收：完整支付流程 + 11 个页面 × 6 种语言 × 桌面/手机全量巡检（无 JS 错误、无漏翻、无横向溢出）。

---

## ⚠️ 已知边界

- 文档要求的“服务商沙盒”需真实服务商凭据，当前以**带标注的本地模拟**代替；接入时实现 `quote / submit / find / status` 即可
- 链上支付已暂停：界面和 Agent 提供方案、预测和提醒，不做加密货币转账。直连银行取决于各地监管，因此记账从 CSV 导出开始。
- 预测为实验性功能；付款习惯指标不是信用评分，沙盒记录不构成信用历史
- 单用户开发原型。正式上线还需 HSM/KMS 签名、身份与 MFA、多租户、限流、备份与合规审查

<div align="center"><sub>◉ DOT — every action has a clear boundary.</sub></div>
