# 开发与贡献

TG2Cloud 以 Linux、Python 主体和 Bash 轻量入口维护。两 Edition 共享 Bot，独立 Compose 与一键脚本分别管理实例；源码构建不依赖本地归档或私有配置。

v1.5.10 fork 入口固定辅助 A `60862325931197915ea8058261cca0f5f74599b3`，80 个宿主 helper；业务仍取正式稳定 Release。实际发布进度、A/B、CI、镜像与资产结果见[当前发布记录](https://github.com/jiajiaxd/TG2Cloud/blob/main/docs/development/V1510-ACCEPTANCE.md)。

## 获取主项目源码

复现当前正式版本使用对应 Tag，开发再切换 main 并记录实际提交：

```bash
git clone https://github.com/jiajiaxd/TG2Cloud.git
cd TG2Cloud
git checkout v1.5.10
git rev-parse HEAD
```

开发使用 `git switch main`；保留完整 Git 历史以运行固定旧版本兼容夹具。克隆仓库或更新文档不会更新正在运行的 VPS。

## 关键目录与入口

| 路径 | 职责 |
| --- | --- |
| `src/tg2cloud/deployment/profiles.py` | 两 Edition 标识与载荷 |
| `src/tg2cloud/deployment/resources.py` | 主机资源预检与预算 |
| `src/tg2cloud/version.py` | 唯一产品版本源 |
| `src/tg2cloud/cli/` | 标准库宿主 CLI 和管理菜单 |
| `src/tg2cloud/telegram/`、`transfer/`、`storage/` | Telegram 接入、共享任务与后端差异 |
| `src/tg2cloud/persistence/` | 数据库事务、迁移、路径与备份 |
| `src/tg2cloud/compose/` | 独立初始化、部署包和宿主 HTTPS |
| `packaging/` | Docker 资源、钩子及必要兼容入口 |

代码组装为实例 `app/tg2cloud/`，外层薄入口、Session 和持久化目录保持兼容；数据库新旧文件名见[配置参考](/reference/config/)。

## 执行自动测试

宿主 CLI 使用 Python 3.10+ 标准库；Bot 镜像 Python 3.12，完整本地测试使用 Python 3.12 / 3.13：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements/dev.lock.txt
python -m pip install --no-deps -e .
python -B .github/scripts/check_python.py all
```

依赖只在 `pyproject.toml` 定义，锁文件由统一工具生成；只验证 CLI 的环境不安装 Bot 运行依赖。完整命令和条件见[开发与测试](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/DEVELOPMENT.md)。

Docker 上下文使用 `build_payload.py` 组装，不直接在 packaging 目录构建。Linux CI 原生区分 AMD64 / ARM64；隔离 WebDAV、网关、FUSE 与代理需要相应工具或显式开关。跳过不得写成通过，合成性能结果不等于实机长期吞吐。

## 提交与发布

保留用户未提交修改，不提交 Token、密码、Session、数据库和生产配置。新增模块同步 runtime／bootstrap 清单，保持命令、资源和公开入口兼容。

helper A 先公开核验，入口 B 再固定真实 A；正式源码只来自不可变版本 Tag。镜像、源码、部署包与文档在实际资产核验后同步，步骤见[发布检查清单](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/RELEASE-CHECKLIST.md)。不自行创建 Tag、推送或部署 VPS。

许可证、上游致谢和品牌资源继续保留。网站维护见[资料来源](/reference/sources/)，不提供桌面部署器恢复或构建教程。
