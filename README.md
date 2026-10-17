# 药品稳定性研究管理与分析系统

[English](README_en.md) | **中文**

本地运行的药品稳定性研究管理与分析工具，适用于化学药（原料药、制剂）与生物制品。覆盖研究方案规划、检测数据录入、降解趋势回归、有效期推算、报告导出，以及审计与权限管理。

> **免责声明**：本系统是研究辅助工具，**尚未经过 GxP 计算机化系统验证（CSV）**。用于受监管用途前，须由企业质量部门按 GAMP 5 / CSV 流程完成评估与验证，并结合全部质量属性、包装、批次等因素由授权人员判定有效期。程序中的限度、时间点等均为示例或参考值，须以现行法规原文和产品方案为准。

## 主要功能

| 模块 | 说明 |
|------|------|
| 研究管理 | 创建研究（化药/生物制品、临床阶段、全检/括号法/矩阵法设计），按 ICH 推荐条件自动生成取样时间点计划；内置生物制品方案模板 |
| 数据录入 | 按样品 × 条件 × 时间点录入检测值；支持 CSV 批量导入；录入时实时校验 |
| 分析与时序图 | 线性回归（斜率、年降解率、R²、p 值），交互式趋势图，限度线叠加 |
| 有效期推算 | 依据 ICH Q1E 的 95% 置信限推算有效期；多模型（线性 / 指数 / 逻辑斯蒂）AIC/BIC 选择；Bootstrap 置信区间；留一法稳健性分析 |
| 质量告警 | 离群值（稳健 MAD 法）、缺失观测、显著变化判定、数据质量扫描 |
| 生物制品 (ICH Q5C) | 原液（DS）/制剂（DP）关联、强制降解确证、冻融、使用中稳定性、运输应力、CQA 分析（效价、聚集体、片段、电荷异质体等） |
| 光稳定性 | 依据 ICH Q1B 的光照暴露量判定 |
| 可比性研究 | 变更前后或类似药 CQA 对比，等效区间判定 |
| 导出报告 | Excel（多表）与 PDF 报告，含跨研究汇总 |
| 教学指南 | 法规术语表、阶段合规清单、常见误区 |
| 权限与审计 | 管理员 / 研究负责人 / 分析员 / 只读四种角色；仅追加的审计日志（含哈希链校验）；登录失败锁定；bcrypt 口令哈希 |
| 系统维护 | 整库 JSON 备份与恢复；合规自检（DS-DP 关联、限度缺失、审计覆盖率） |
| 界面语言 | 中文 / English 切换（英文译文覆盖界面文字与教学内容；分析叙述文字与报告暂为中文） |

## 快速开始

### Windows：一键启动（推荐）

1. 安装 [Python 3.9 或更新版本](https://www.python.org/downloads/)，安装时勾选 **Add python.exe to PATH**。
2. 双击项目根目录的 **`start.bat`**。
   - 首次运行会在 `.venv\` 中创建独立环境并安装依赖（需要网络），不改动系统 Python。
   - 浏览器会自动打开 http://localhost:8501 。
   - 如果没有设置 `STAB_ADMIN_PASSWORD`，首次启动时控制台会输出 `admin` 账号的一次性口令，请记录并在登录后立即修改。
   - 关闭控制台窗口即停止服务。端口可用环境变量 `PORT` 修改。

### 手动启动（所有平台）


环境要求：Python 3.9 及以上。

```bash
pip install -r requirements.txt

# 首次启动前设置初始管理员口令（可选；未设置则在控制台输出一次性随机口令）
# Windows PowerShell:  $env:STAB_ADMIN_PASSWORD = "请设置一个强口令"
# Linux/macOS:          export STAB_ADMIN_PASSWORD="请设置一个强口令"

python tools/seed_example.py     # 可选：生成化药与生物制品示例数据（仅用于体验）
streamlit run app.py             # 浏览器打开 http://localhost:8501
```

默认管理员用户名为 `admin`。首次登录后请立即修改口令。

运行测试（每个测试脚本使用临时数据库，不会改动正式数据）：

```bash
python tests/run_all.py
```

更多说明见 [使用手册](docs/zh/使用手册.md)、[法规依据](docs/zh/法规依据.md)、[法规符合性差距分析](docs/zh/法规符合性差距分析.md)、[架构与测试](docs/zh/架构与测试.md)，以及 [更新日志](CHANGELOG.md)。

## 项目结构

```
.
├── app.py                 # Streamlit 应用入口（页面、交互、权限）
├── src/                   # 核心库
│   ├── models.py          # 数据模型、CQA 限度方向、取值校验
│   ├── planner.py         # 取样时间点计划（ICH Q1A / Q1D / Q5C）
│   ├── analysis.py        # 回归、有效期推算、模型选择、异常检测、生物制品评价
│   ├── db.py              # 数据库访问（SQLite 默认，PostgreSQL 可选）、备份恢复
│   ├── auth.py            # 用户、角色、口令、锁定、审计日志
│   ├── report.py          # Excel / PDF 导出
│   ├── teaching.py        # 教学指南内容
│   ├── importers.py       # 批量 CSV 导入（UTF-8 / GBK）
│   ├── ui_theme.py        # 界面主题、样式与图表模板
│   └── fonts.py           # matplotlib 中文字体配置
├── tools/
│   ├── seed_example.py    # 示例数据
│   └── backup.py          # 命令行备份
├── .streamlit/config.toml # Streamlit 主题配置
├── tests/                 # 测试脚本（python tests/run_all.py）
└── docs/
    ├── zh/                # 中文文档
    └── en/                # English documentation
```

## 配置（环境变量）

| 变量 | 作用 | 默认 |
|------|------|------|
| `STAB_ADMIN_PASSWORD` | 首次创建管理员 `admin` 时使用的口令 | 未设置则生成随机口令并输出到控制台 |
| `STAB_DATA_DIR` | SQLite 数据库所在目录 | 项目根目录 |
| `DATABASE_URL` | 设为 `postgresql://...` 时使用 PostgreSQL（需 `psycopg2-binary`） | 未设置则使用 SQLite |

## 许可与贡献

本项目采用 [Apache License 2.0](LICENSE) 许可，版权声明见 [NOTICE](NOTICE)。贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题报告方式见 [SECURITY.md](SECURITY.md)。

> 本软件不是经过验证的 GxP 系统，按“现状”提供，不附带任何担保。
