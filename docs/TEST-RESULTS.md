# Submission verification — 21 October 2026

Team: Dotopia  
Project: DOT — Cross-border & Student Finance Assistant  
Date: 21 October 2026, Australia/Sydney

This record accompanies the source revision that adds the bilingual submission README and configuration bootstrap tests. Use the commit containing this file to reproduce this run. Subsequent GitHub Actions results are separate evidence.

## Results

| Check | Result | Environment / scope |
|---|---|---|
| Full Python suite | **425 passed, 0 failed, 0 skipped** | Windows, Python 3.12 virtual environment; 152.18 seconds |
| Same suite in the built backend image | **425 passed, 0 failed, 0 skipped** | Linux, Python 3.12, locked dependencies, network disabled; 102.98 seconds |
| Docker deployment | Passed | Fresh isolated Compose project; frontend starts, backend healthy, `/api/health` reports local simulation and no EVM provider |
| Browser smoke test | Passed | Compare, draft, hold-to-authorise, asynchronous settlement, receipt, audit trail, lost-response recovery, agent refusal and mobile layout |
| Browser layout sweep | Passed | 13 views × 6 languages × desktop/mobile; no reported JavaScript errors, raw translation keys or horizontal overflow |
| Offline CLI demonstration | Passed | Agent submission refused; owner submission, duplicate protection and lost-response recovery complete |
| Configuration bootstrap | Included in the 425 | Random distinct tokens, simulation defaults, no printed secrets, preservation of existing values and repeat-run stability |

The 159 security regression cases and 23 hardening cases are subsets of the Python total. They are not additional tests. The previous application-only run had 423 cases; this submission adds two configuration tests.

Both full Python runs produced two dependency deprecation warnings, concerning `websockets.legacy` and the Starlette/httpx TestClient integration. No test failed. These warnings are not a dependency vulnerability assessment.

## Reproduce

Install `requirements.lock.txt` in a Python 3.12 virtual environment, then:

```bash
python -m pytest tests -q --junitxml=artifacts/test-results.xml
python -m finance.demo
```

The backend image includes the locale files required by the parameterised language tests, so a container run collects the same suite as the source checkout:

```bash
docker build -t dot-test .
docker run --rm --network none -e FINANCE_DB=/tmp/dot-tests.sqlite3 -e ENABLE_WORKER=false dot-test python -m pytest tests -q -o cache_dir=/tmp/pytest-cache
```

For browser acceptance, follow the running-app instructions in [README.md](../README.md#9-test-cases-and-results). The verification used a separate Compose project, fresh demo workspaces and fictional data. It did not change the developer's existing application volume.

## What this proves—and what it does not

The checks exercise the recorded service, API, permission, privacy, finance and UI cases. Python tests use fixed or simulated inputs and do not need a real model key. The browser checks exercise the deployed UI but are not a live-model red-team evaluation.

The results do not certify regulatory compliance, the absence of every vulnerability, forecast accuracy, bank settlement or production capacity. Current limits are recorded in the [security self-assessment](DOT-Security-Self-Assessment-Report-v2.md).

## 中文说明

2026 年 10 月 21 日，在 Windows 虚拟环境及 Linux Docker 镜像中分别运行完整测试，均为 **425 项通过、0 失败、0 跳过**。两次运行均有 2 条依赖弃用提示。

另完成隔离 Docker 启动、浏览器模拟支付流程，以及 13 个页面 × 6 种语言 × 桌面/手机布局验收。159 项安全回归及 23 项加固测试已包含在 425 项中，不重复计数。本次增加的 2 项测试验证配置脚本。

这些结果说明已记录用例通过，不代表真实模型、真实银行付款或公网生产环境已获安全认证。
