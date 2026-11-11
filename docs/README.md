# TG2Cloud 文档目录

当前维护 Linux 一键脚本和独立 Docker Compose，两 Edition 共用 Bot 核心。先选择部署方式，再配置自己的存储网关。项目不再提供 EXE 部署器或跨项目迁移教程。

## 第一次使用

| 目标 | 阅读顺序 |
| --- | --- |
| 公网 VPS 安装 | [填写信息清单](填写信息清单.md) → [Linux 环境要求](ARCHITECTURES.md) → [公网安装](VPS-INSTALL.md) |
| 可信内网或 NAS | [内网安装](LAN-INSTALL.md) → [网关配置](STORAGE.md) |
| 自己管理 Docker Compose | [Compose 新手教程](COMPOSE.md)：安装 Docker、初始化、可选 HTTPS、启动与升级 |
| 配好网关，完成首次转存 | [CloudDrive2 / OpenList](STORAGE.md) → [Bot 使用](BOT-USAGE.md) |

一键脚本与 Compose 是不同部署方式，已有实例按原方式升级，不能相互覆盖或接管。

v1.5.8 的 Compose 统一菜单、凭据隔离与资源保护见 [Compose 安全维护](COMPOSE-MANAGEMENT.md)；发布状态及未验收范围见[本版记录](development/V158-ACCEPTANCE.md)。

- [v1.5.10 fork 发布记录](development/V1510-ACCEPTANCE.md)

## 使用与可选功能

- [Bot 使用、菜单和命令](BOT-USAGE.md)：发送文件、查看任务、失败重试和恢复。
- [文件命名与媒体组](NAMING.md)：原名、说明、多语言标题、媒体组与命名边界。
- [管理员监听](LISTENING.md)：个人账号授权、来源、筛选草稿、审批和来源目录。
- [家庭共享](FAMILY-SHARING.md)：管理员与成员授权、共用保存目录和独立读取账号。
- [文件分类、通知与配额](FEATURE-ENHANCEMENTS.md)：可选设置、默认值与权限。
- [外部 WebDAV](external-webdav.md)：独立账号、只读访问、手机连接与维护。
- [复用已有 Docker Nginx](DOCKER-NGINX.md)：支持条件、证书责任与配置事务。

## 运维和排查

- [运行状态与维护](OPERATIONS.md)：`tg2cloud` 菜单、日志、服务、凭据和配置变更。
- [任务恢复与验证](RECOVERY.md)：取消后重新转存、远端冲突、遗留文件和磁盘保护。
- [配置与运行目录](CONFIGURATION.md)：环境变量、账号边界、数据库及 Session。
- [备份与恢复预检](BACKUP-RESTORE.md)：一致性快照、隔离检查、恢复前准备与回退。
- [卸载指南](UNINSTALL.md)：范围预检、完整清理、保留数据和依赖保护。
- [常见问题](FAQ.md)：按安装、网关、任务和数据问题快速定位。

## 开发与发布

- [v1.5.8 发布与兼容记录](development/V158-ACCEPTANCE.md)：两种部署的共享兼容、Compose 管理与安全维护；实机验收安排在发布后。

- [贡献指南](../.github/CONTRIBUTING.md)
- [仓库结构与维护规范](development/REPOSITORY.md)
- [Linux 开发与测试](development/DEVELOPMENT.md)
- [发布检查清单](development/RELEASE-CHECKLIST.md)
- [当前 v1.5.7 发布与兼容记录](development/V157-ACCEPTANCE.md)：监听冷却恢复、来源提示与实际日志限额；CI、资产与未执行的实机项目。
- [v1.5.6 发布与兼容记录](development/V156-ACCEPTANCE.md)：运行安全与诊断维护、发布和未执行的实机验收范围。
- [v1.5.5 发布记录](development/V155-ACCEPTANCE.md)：前版命名／监听增强及历史验收证据。
- [v1.5.4 发布与兼容记录](development/V154-ACCEPTANCE.md)：监听下载修复、验证边界与升级步骤。
- [v1.5.3 发布与兼容记录](development/V153-ACCEPTANCE.md)：实际 CI、资产摘要与尚未执行的实机清单。
- [所有 TG2Cloud 版本分别做了什么](../CHANGELOG.md)：保留版本事实；旧验收资料以固定历史提交链接查阅，不作为当前教程。
- [当前发布说明](../RELEASE_NOTES.md)

## 项目与许可

- [项目首页](../README.md) · [English README](../README_EN.md)
- [品牌规范](development/BRAND-GUIDE.md)
- [第三方组件](第三方组件说明.md) · [安全政策](../.github/SECURITY.md) · [MIT 许可证](../LICENSE)

本目录是仓库的完整阅读入口，网站提供独立的同主题教程。上游致谢、版权和许可证保留；现有实例的数据库及配置兼容说明保留在对应指南，不提供自动导入其他项目数据的承诺。不要公开凭据、Session、数据库或备份。
