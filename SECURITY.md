# Security Policy / 安全策略

[中文](#中文) | [English](#english)

## English

This system is a single-machine or lab-LAN research tool. It is **not** a validated GxP system out of the box.

### Reporting a vulnerability
Please do not open a public issue for a security problem. Report it privately to the maintainer:
**<CONTACT — fill in before publishing>**. Include steps to reproduce. We aim to acknowledge reports within 7 days.

### Deployment notes
- Run on a trusted network only. Do not expose the port to the internet; if remote access is needed, use a reverse proxy with TLS and authentication.
- Change the initial administrator password at first login. Set `STAB_ADMIN_PASSWORD` before the first start, or change the one-time password printed to the console.
- Back up the database regularly (`tools/backup.py`). Backups contain password hashes and the audit trail.
- Never commit `stability.db`, backups, `.env` files or any credential file. `.gitignore` covers the common cases.

## 中文

本系统是单机或实验室局域网的研究工具，**开箱即用时并非经过验证的 GxP 系统**。

### 报告安全问题
请勿为安全问题公开提交 issue。请私下联系维护者：**<联系方式——发布前填写>**，并附上复现步骤。我们力争在 7 天内回复。

### 部署注意事项
- 仅在可信网络中运行。请勿把端口直接暴露到互联网；如需远程访问，请使用带 TLS 与身份验证的反向代理。
- 首次登录后立即修改管理员口令。首次启动前可设置环境变量 `STAB_ADMIN_PASSWORD`，或更换控制台输出的一次性口令。
- 定期备份数据库（`tools/backup.py`）。备份文件包含口令哈希与审计记录。
- 切勿提交 `stability.db`、备份文件、`.env` 或任何凭据文件。`.gitignore` 已覆盖常见情况。
