llm4orTT · 0.1.2 研究改进版

双击 llm4orTT.exe 启动。
默认打开普通对话，支持聊天记录、复制、重试、停止、重命名和导出。
点击顶部“逆优化工作台”，再点“运行三步重构”，即可体验内置排班示例。
默认使用本地数学检查，自动选择正则化强度并计算经验拟合范围，不调用大模型。
经验拟合范围不是真实价格的置信区间；范围很窄，也可能猜错。
新版增加独立的“误差相容与决策风险”检查：需要明确声明历史允许的绝对费用误差。
内置无噪合成示例声明误差为0；导入其他数据时不能照搬这个假设。
完整枚举能够处理的小型有界整数问题，可输出条件性风险保证、风险见证、未决或假设不相容。
连续规划、大规模整数问题、相对噪声暂不支持该新证书，原求解功能仍可使用。
不提供 deployment 时仅复查最后一个历史场景，不代表通过新场景测试。
证书只适用于结果中明确列出的方案、模型、参数框和误差假设。
0.1.2新增可选的较宽误差上限检查，始终检查同一个方案。
较宽上限出现风险时，综合结论会优先显示风险，原预算的条件结果仍保留。
没有填写较宽上限时，不自动猜测或填0；声明的误差、参数框和特征仍未获独立验证。
如勾选大模型补充规则，每次运行最多调用一次；已有回答会在本机复用。
已有规则能解释历史时自动跳过大模型；失败不会自动重试。
需要大模型时，在“设置”中填入密钥。

普通聊天与当前逆优化方向同时保留。内置排班示例是合成数据。

本次交付
outputs/followup-20261020/本轮改进与真实结果.txt：更强对照、新题目的误差敏感性检查及完整结果。
本轮新增1440次算法比较和180个双端点记录，条件数学核验全部通过。
主预算候选114/120，强对照118/120。
新敏感性题目未证明实际错误率下降：误差上限仍估小时新增1个假安全例；该失败完整保留。
任务.md：当前任务板（T0–T11），含每个任务的成本与验收。
research/noise_sensitivity_prior_work.txt：新增8篇原文核查，接续旧6篇。
research/deferred_model_protocol.json：其他模型实验待补，未运行指标为null。
../历史文件夹/llm4orTT升级前存档/before-certification-20261020-214544/：本轮修改前完整存档，4554文件核验通过。
outputs/comparison-20261020/贡献与比较实验结果.txt：后续五方法比较的完整结论、失败案例和下一阶段目标。
outputs/comparison-20261020/comparison.png：三个计算预算下的比较图。
上一轮完成2070次合成实验运行，60个独立正式实例；主比较112/120对106/120。
错误低估历史误差时出现真实损失超阈值案例。
research/comparison_prior_work.txt：六篇近邻方法的原文核验与贡献边界。
../历史文件夹/llm4orTT升级前存档/before-certification-20261020-210402/：上一轮实验前的完整0.1.1存档，2301文件核验通过。
实验\决策契约研究_2026-10-21_01\案例簿.md：公开题与四个对照臂的案例事实。
outputs/certification-20261020/：24项开发实验的冻结方案、输入、证书、完整结果。
tests/test_inverse_certified.py：独立机制和边界测试。
../历史文件夹/llm4orTT升级前存档/before-certification-20261020-204104/：修改前的完整程序与原研究证据存档，逐文件SHA256核验通过。
旧公开基准报告仍在 实验\原桌面完整研究报告_2026-10-20，未修改其数据或结果。

复核命令（在本文件所在目录运行）
resources\runtime\python\python.exe -m unittest discover -s tests -p test_inverse_certified.py -v
resources\runtime\python\python.exe research\run_certification_pilot.py
第二条为防止覆盖原始结果，输出目录已存在时会停止；复跑方法见研究说明。
后续比较的独立核验：
resources\runtime\python\python.exe research\verify_comparison.py outputs\comparison-20261020
resources\runtime\python\python.exe research\analyze_comparison.py
本轮独立核验与分析：
resources\runtime\python\python.exe tools\audit_followup.py
resources\runtime\python\python.exe research\analyze_followup.py

软件通过开发检查后可运行；本版为公开题与合成数据上的研究记录。
