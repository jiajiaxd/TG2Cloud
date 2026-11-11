# 更新日志

## TG2Cloud v1.5.10

- 私聊附件的转存状态改用原消息上的 Telegram 表情回应。
- `/status` 显示新任务的 WebDAV 保存路径、目录别名和分类规则。
- 转存设置可按用户开启三类自动分类，使用 `视频`、`图片`、`其它` 三个目录。
- 业务数据库迁移至 schema 4，已接收任务沿用接收时的保存目录。

## TG2Cloud v1.5.8

2026-11-08，[v1.5.8 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.8)已发布；Compose 增加统一离线管理、凭据隔离与资源保护。共享代码保持两种部署的归属边界，schema 3、现有配置与 Session 保留。同标签原生双架构 CI、源码、共享镜像和两版部署包已核验；真实 VPS、Telegram 与网关转存由用户发布后验收，见[本版记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V158-ACCEPTANCE.md)。

## TG2Cloud v1.5.7

2026-11-04，[v1.5.7 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.7) 已发布；同标签原生双架构与源码／镜像／Compose 资产已核验。监听普通下载增加有限冷却恢复、来源空响应复核与准确错误分类；安装升级和诊断检查实际容器日志限额。保留 schema 3、原任务和 Session；不自动重试历史失败或重建旧容器。实际验证范围见[本版记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V157-ACCEPTANCE.md)及[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。


## TG2Cloud v1.5.6

2026-11-01，[v1.5.6 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.6) 已发布；同标签原生双架构与源码／镜像／Compose 资产已核验。凭据标准输入、私密文件权限、容器日志轮转和独立监听诊断维护；保留 schema 3、原 Session、任务及并发策略。含 pyasn1 0.6.5 限定安全修复；实际 CI 和未执行的实机项目见[本版记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V156-ACCEPTANCE.md)和[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

## TG2Cloud v1.5.5

2026-10-30，[v1.5.5 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.5) 已发布，同标签原生双架构与实际资产核验通过。清理新文件名推广前后缀，保留链接文字屏蔽；管理员监听增加规则解释、可选排除范围、规则方案、有限失败恢复与受控历史预览。保留 schema 3、Session、已有任务及两种部署方式；回退可选字段要求见[本版记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V155-ACCEPTANCE.md)。[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。测试 VPS 的实际验收与未执行范围见本版记录。

## TG2Cloud v1.5.4

2026-10-30，[v1.5.4 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.4) 已发布；同标签原生双架构、源码、镜像与两版 Compose 资产核验通过。修复监听短时间下载限速、临时错误重试、旧账号请求隔离与失败原因保留；增加监听新任务并发退让。schema 3、配置、Session 和两种部署流程保持兼容，实机回归尚未执行。见[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)与[本版发布记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V154-ACCEPTANCE.md)。

## TG2Cloud v1.5.3

版本日期：2026-10-29。[v1.5.3 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.3) 已发布；入口 B、同标签原生双架构检查、源码包、共享镜像和两 Edition Compose 部署包已核验。真实 VPS、DNS／ACME、Telegram 与网关转存仍待用户验收。详见[发布记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V153-ACCEPTANCE.md)。

- 全新安装的数据库改为 `tg2cloud.db`；已有唯一旧库继续使用，任务与 Session 保留，两库并存停止并提示核对。
- 统一备份、恢复、监听、管理与诊断的数据库识别；新配置、日志及验收临时对象采用 TG2Cloud 命名，保留历史兼容读取。
- Compose 新增可选 HTTPS 计划与离线宿主向导，复用共享 Nginx 和 Certbot；已有其他代理仅导出候选配置。不改变公网／内网一键安装交互，不接管另一种部署。
- 本地验证、远端 CI、helper A/B、镜像及资产发布、真实网关验收分别记录，不能相互代替。


## TG2Cloud v1.5.2

版本日期：2026-10-28。[v1.5.2 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.2) 已发布；A／B、同标签双架构、共享镜像和两 Edition Compose 资产已核验。真实 VPS、NAS、Telegram 与网关转存仍待用户验收，详见[本版记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V152-ACCEPTANCE.md)。

- 临时网络／服务器异常保留监听启用状态并退避重连，失效授权和不安全 Session 继续停止。
- 修复系统启动不足 60 秒时首条监听通知被误抑制，保留后续 60 秒限流。
- 历史维护每类每批最多 500 行，保留期限和引用保护不变；schema 3 下幂等增加辅助索引。
- Compose 两 Edition 共用 Bot 镜像，复用原有网关固定镜像与权限；提供交互初始化、检查和离线备份，第一版用于内网或已有 HTTPS 代理。
- 新增正式 Tag 的原生双架构镜像／部署包工作流；镜像与部署包的实际发布结果见本版记录。保留一键脚本入口与配置／Session。

## TG2Cloud v1.5.1

版本日期：2026-10-28。[v1.5.1 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.1) 已发布；A／B、[同标签 Linux 检查](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40622910178)和实际源码资产已核验。真实 VPS、Telegram、两网关转存及小时级负载仍待发布后验收。

- 减少受阻任务和普通上传相同进度的重复数据库写入，保留速度显示、取消、重试、验证与本地副本保护。
- 调度与监听接收仅查询所需状态，个人统计复用索引；资源循环复用本轮暂存、流式数量和同文件系统采样。
- 监听增加单来源超时和公平轮询预算；全局历史维护按间隔执行，审批过期仍实时检查，失败事务回滚。
- 沿用 schema 3，不新增依赖、必填配置或端口；保留两网关提交策略及旧实例数据。合成数据库测量不能替代真实 VPS 长期验收。

## TG2Cloud v1.5.0

版本日期：2026-10-27。[v1.5.0 正式版](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.0) 已发布；A／B 与[同标签 Linux 检查](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40439954791)通过，实际源码包、校验清单与标签文件已核验。真实 VPS、Telegram 和用户网关仍待发布后验收。

- 监听规则预览与接收共用同一批次、同来源媒体组的说明文本，保留单个附件自身的说明及集数；不读取评论，也不额外抓取历史。
- 暂停、删除或修改来源后，旧轮询不再覆盖新状态或推进旧游标；下载前重新核对监听账号、连接和附件身份，失败的重新核验撤销旧结果。
- 离线管理工具改为从目标正式 Release 的已核验源码安装，单独核对实际版本、`--version` 与 `listen --help`，升级摘要分别显示 Bot 和 CLI 结果；当前旧菜单进程提示退出重开。
- 在线入口的后台进程缺少标准输入 TTY 时，监听登录使用当前控制终端；凭据不进入日志。失败提示指出检查阶段。
- 用户可见平台名称统一为 Linux；保留架构检测、镜像选择、CI 矩阵和历史验收范围。补齐 Session 辅助文件防误提交规则，精简网站维护 README。

没有新增数据库迁移、运行依赖或必填配置。v1.5.0 已完成辅助 A／入口 B／同标签发布与资产核验，既有版本和资产保留；本版 VPS、真实 Telegram 或网关验收尚未执行。

v1.4.3 新增可选分类、管理员通知、家庭成员配额和白名单诊断报告。分类／通知默认关闭，成员默认不限额；涉及业务 schema 2，升级前备份。见[转存](/usage/first-transfer/)、[个人配额](/usage/commands/)、[维护](/operations/maintenance/)和[备份](/operations/backup/)。

这里记录 TG2Cloud **全部历史版本**做了什么，而非仅列出目前还能下载的 Release。v1.0.0 至 v1.5.10 共 40 个版本，逐版说明如下；更细的修复与兼容记录见[仓库完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

可下载版本以 [GitHub Releases](https://github.com/LuoPoJunZi/TG2Cloud/releases) 实际列表为准，不固定“只保留几版”的数量。部分历史发布页和标签已移除，历史说明仍保留；下面的测试结论按当时版本理解，不表示今日仍能下载，也不替代当前环境验收。当前安装与下载见[下载与校验](/download/)。

| 版本 | 这一版主要做了什么 |
| --- | --- |
| [v1.5.10](#tg2cloud-v1-5-10) | Telegram 状态回应、保存目录展示和个人自动分类。 |
| [v1.5.8](#tg2cloud-v1-5-8) | Compose 统一管理、凭据隔离、资源诊断及两种部署的安全升级边界。 |
| [v1.5.7](#tg2cloud-v1-5-7) | 监听下载有限冷却恢复、来源提示和实际容器日志限额诊断。 |
| [v1.5.6](#tg2cloud-v1-5-6) | 凭据、私密文件与容器日志加固，独立监听健康及有界异常诊断。 |
| [v1.5.5](#tg2cloud-v1-5-5) | 推广前后缀清理、监听规则方案与解释、小批恢复和受控历史补拉。 |
| [v1.5.4](#tg2cloud-v1-5-4) | 监听下载限速恢复、临时错误有限重试、账号隔离和并发退让；保留脱敏失败原因。 |
| [v1.5.3](#tg2cloud-v1-5-3) | TG2Cloud 新安装命名统一、数据库兼容与可选 Compose HTTPS；一键脚本流程保持独立。 |
| [v1.5.2](#tg2cloud-v1-5-2) | 监听断网恢复、分批历史维护、独立 Compose 部署与共享双架构镜像。 |
| [v1.5.1](#tg2cloud-v1-5-1) | 监听公平轮询、后台维护、数据库／资源热点与上传进度优化。 |
| [v1.5.0](#tg2cloud-v1-5-0) | Linux 管理工具同步、Bot／CLI 版本验收、监听并发与预览、终端登录修复。 |
| [v1.4.11](#tg2cloud-v1-4-11) | 监听来源独立目录、类型归档、名称清理、创建失败恢复与返回导航。 |
| [v1.4.10](#tg2cloud-v1-4-10) | 监听交互表单、终端监听菜单、中文计划与导航、外部 WebDAV 升级恢复。 |
| [v1.4.9](#tg2cloud-v1-4-9) | 管理员监听、持久化审批与命名／目录方案，schema 3 和独立 Session 备份。 |
| [v1.4.8](#tg2cloud-v1-4-8) | 外部 WebDAV 安装、终端输入、实际目录与管理地址维护。 |
| [v1.4.7](#tg2cloud-v1-4-7) | 外部 WebDAV 统一入口、独立 Shell 退役、Certbot 挂载与中断恢复维护。 |
| [v1.4.6](#tg2cloud-v1-4-6) | 外部 WebDAV 界面、发布准备工具、共享 CI 与测试及代理模块维护。 |
| [v1.4.5](#tg2cloud-v1-4-5) | 统一管理次级页面，增强只读诊断、快照预检与隔离数据库恢复演练。 |
| [v1.4.4](#tg2cloud-v1-4-4) | 安装日志分级、升级结果与验收摘要；本地管理菜单精简及设置层级优化。 |
| [v1.4.3](#tg2cloud-v1-4-3) | 维护与备份增强、可选分类／通知／成员配额及脱敏报告、传输测速与编号菜单修复。 |
| [v1.4.2](#tg2cloud-v1-4-2) | 显式复用已有 Docker Nginx，单层代理、事务恢复、Webroot 证书与续期、附加路由及卸载保护。 |
| [v1.4.1](#tg2cloud-v1-4-1) | 修复公网 IPv4 NAT 的 HTTPS 预检；增加映射人工确认与执行前复核，补充 CloudDrive2 ARM64 首装验收。 |
| [v1.4.0](#tg2cloud-v1-4-0) | 原生支持 AMD64／ARM64；统一平台与镜像检查，接入双架构 CI 和发布验证。 |
| [v1.3.4](#tg2cloud-v1-3-4) | 增强长说明、图片和媒体组命名，处理网址污染名、斜杠说明与后缀；补全使用文档。 |
| [v1.3.3](#tg2cloud-v1-3-3) | 新增 Bot 家庭共享、外部 WebDAV 多只读账号；增强多语言命名，精简资源页。 |
| [v1.3.2](#tg2cloud-v1-3-2) | 中文编号安装与管理向导；新增离线 `tg2cloud` 管理命令，完善所选实例卸载及工具清理。 |
| [v1.3.1](#tg2cloud-v1-3-1) | 新增独立外部 WebDAV：独立账号与 HTTPS，只读访问既有目录；扩展共享代理与依赖保护。 |
| [v1.3.0](#tg2cloud-v1-3-0) | 转为 Linux Python + Bash 维护；冻结 Windows 版，整理共享源码、构建与指纹，完善磁盘推荐。 |
| [v1.2.1](#tg2cloud-v1-2-1) | 修复取消重传、远端冲突和遗留扫描；完善验证、备份、磁盘保护、说明命名与每周失败统计；最后一个 Windows 版。 |
| [v1.2.0](#tg2cloud-v1-2-0) | 增加独立内网／NAS 安装与卸载入口，显示内网 IP 和端口；当时默认保留数据。 |
| [v1.1.5](#tg2cloud-v1-1-5) | 修复 HTTPS 中断回退、Python 3.10 兼容；完善失败续做凭据展示与系统依赖提示。 |
| [v1.1.4](#tg2cloud-v1-1-4) | 修复终端不可 seek 与非 root 镜像源码读取权限；统一内部命名，保留旧数据位置。 |
| [v1.1.3](#tg2cloud-v1-1-3) | 新增公网 VPS 单行安装／保留配置升级；稳定 Release 引导和依赖兼容更新。 |
| [v1.1.2](#tg2cloud-v1-1-2) | 完善版本和故障提示、HTTPS 备份核验与续期演练、OpenList 冷却诊断。 |
| [v1.1.1](#tg2cloud-v1-1-1) | 共享 HTTPS 事务锁、状态原子提交与回退；OpenList 大目录和 401／429 探测修复。 |
| [v1.1.0](#tg2cloud-v1-1-0) | 受管部署必须完成 HTTPS 验收；日常管理不再使用 SSH 隧道按钮，后端保持回环监听。 |
| [v1.0.4](#tg2cloud-v1-0-4) | 紧凑 Bot 状态首页、动态 Edition 名称、独立 VPS 资源页及原消息刷新。 |
| [v1.0.3](#tg2cloud-v1-0-3) | 可选共享 Nginx／Certbot 域名 HTTPS、证书续期、失败回退及公开 `/dav` 阻断。 |
| [v1.0.2](#tg2cloud-v1-0-2) | 修复 OpenList MOVE 假成功，改为预留正式路径直接上传；CloudDrive2 策略不变。 |
| [v1.0.1](#tg2cloud-v1-0-1) | 修复 CloudDrive2 首装将 Bot 容器误判成额外网关的问题。 |
| [v1.0.0](#tg2cloud-v1-0-0) | 建立双 Edition 和独立实例身份，提供两个 PySide6 部署器，保留稳定转存核心与旧数据兼容。 |

v1.2.1 是最后一个 Windows 版，v1.0.2 仅保留历史变更记录，不再提供 Release 下载；新安装使用最新稳定版，不用旧 EXE 覆盖新实例。上游 TG115 的版本单独记录，不计入上述 TG2Cloud 版本。

## TG2Cloud v1.4.11

2026-10-26，[v1.4.11 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.11) 已正式发布；[同标签双架构](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40318301764)、main 与实际源码资产已核验。新监听来源按来源名称／媒体类型归档，去表情并限制名称长度，重名保留独立绑定；已有来源与手动转存不自动改目录。创建失败保留暂停记录并可重试，实际 Telegram 读取拒绝仍安全停止。补齐返回状态按钮、细分添加失败提示和 v1.4.10 升级基线；schema 3 无新 DDL、依赖或必填配置。详见[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)和[发布验收说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V1411-ACCEPTANCE.md)。真实 Telegram／VPS 验收安排在发布后。

## TG2Cloud v1.4.10

2026-10-26，[v1.4.10 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.10) 已发布；A／B、main、[同标签双架构](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40287434283)和实际源码资产已核验。监听筛选、命名、目录改为按钮和逐项文字交互，草稿预览后明确保存；主机增加监听管理，手机号与验证码可见、仅两步验证密码隐藏。外部 WebDAV 维护代码升级不再被未完成账号认证阻断，入口继续安全关闭。补齐计划中文状态、默认目录与返回导航，无新增数据库迁移或运行依赖；真实 Telegram、VPS 和两网关验收仍待用户执行。详见[完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)和[监听指南](/usage/listening/)。

## TG2Cloud v1.4.9

2026-10-26，[v1.4.9 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.9) 已正式发布，A／B、[同标签双架构验证](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40268795680)及实际下载资产已核验。新增管理员专属监听、来源筛选、持久化转存计划、确认前改名和目录／批次操作。业务数据库 schema 2 → 3，个人 Session 独立保存，监听默认关闭。详情见[监听使用说明](/usage/listening/)及[仓库完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。真实登录与两网关转存安排在发布后，不以自动化代替实机验收。

## TG2Cloud v1.4.8

2026-10-25，[v1.4.8 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.8) 已正式发布。A／B 各五项 CI、[同标签双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40175950235)及实际源码资产核验通过；真实终端、原生账号目录及手机仍须人工验收。详细记录见[仓库更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

- 减少外部 WebDAV 重复标题和环境表，保留实际平台与实例检查。
- 修复父子菜单预读输入，普通字段回显、空邮箱跳过，错误按字段解释，密码隐藏。
- 读取或复用核实后的实际目录，未知／加密配置首次补录；后台建号显示管理地址，取消重复手打路径并保留只读确认。
- 不新增运行依赖、必填配置或数据库迁移，补入 v1.4.7 升级基线；新工具须显式升级，实机另验。

## TG2Cloud v1.4.7

2026-10-25，[v1.4.7 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.7) 已正式发布。A／B 各五项 CI、[同标签双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40160704507)和实际源码资产核验通过；本版实机仍需独立验收。详细范围见[仓库完整记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

- `tg2cloud` 新增 15. 外部 WebDAV，按所选 Edition 管理独立只读入口；安装主流程不默认询问或启用。
- 根目录只保留公网与内网两个入口，独立卸载和外部 WebDAV Shell 文件退役；卸载仍通过菜单 14 或 `tg2cloud uninstall`，原清理及预检参数保留。
- API 2 明示新源码布局；旧 API 1 工具经确认仅迁移维护代码，不变更账号、路由和文件。
- Certbot 启动与健康检查复核实际挂载；代码准备在认证／路由变更之前完成，候选失败清理且可安全重试。
- 不新增运行依赖、环境变量或数据库迁移，补入 v1.4.6 升级基线。真实 VPS、手机、公网 ACME 和恢复验收尚未执行。

## TG2Cloud v1.4.6

2026-10-24，[v1.4.6 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.6) 已正式发布。A、B 各五项 CI、[同标签双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40089991036)和实际源码资产核验通过；本版实机仍需独立验收。详情见[仓库完整记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)和[本版维护说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/LOCAL-MAINTENANCE.md)。

- 外部 WebDAV 状态／连接结果可刷新和返回；用户管理统一上下文，卸载／升级后退出旧进程。
- 生成发布审阅计划与候选补丁，保留正式 A／B 和同标签验证流程。
- 分类四组命名回归，抽离纯代理渲染并保留旧接口；日常和正式 CI 共用现有检查实现。
- 补齐 v1.4.5 原正式提交的升级基线，保留配置、任务、Session 与两版策略。无新增运行依赖、配置项或数据库迁移。

## TG2Cloud v1.4.5

[v1.4.5 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.5) 已正式发布。辅助 A、入口 B 与[同标签原生双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/40073091331)全部通过，实际源码包、SHA256 清单及 GitHub 资产摘要已核验。详细范围见[仓库更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)与[维护说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-NEXT.md)。

- 状态、日志和业务就绪页面可停留刷新；其他次级页面统一上下文、分组与返回，主菜单编号不变。
- 备份子菜单按实例 1～3、代理 4～7 分组，保持原确认与数据保护。
- 只读诊断增加入口检查和处理建议；快照拒绝越界文件及 SQLite 日志旁文件。
- 新增仅使用临时副本的数据库启动／迁移／恢复演练，不是生产恢复；补充 v1.4.3／v1.4.4 可信基线与维护发布预检。
- 扩充合成命名与两网关重启恢复测试；不更改命名规则、传输策略、运行依赖或数据库 schema。
- 仅开发审计依赖 filelock 4.2.0 → 4.2.1 安全更新，保持 Bot 锁文件不变，不绕过漏洞审计。

GitHub 自动检查和资产核验已完成；本版真实 VPS、Telegram／用户网盘、ACME 与完整生产恢复未执行，不把模拟或隔离测试写成实机通过。

## TG2Cloud v1.4.4

[v1.4.4 Release](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.4) 已正式发布，定位为稳定性与用户体验维护版。辅助 A `ea93c95eda0fa68c807b56c41871e09b7a19634b`、入口 B／Tag `6164a237108786c01a7a958ab56e16023df04d79` 各五项 CI 及[同标签原生双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39920070111)全部通过，实际源码包、SHA256 清单与 GitHub 资产摘要已核验。 完整范围见[仓库记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)，下载与真实验收边界见[下载页](/download/)。

- 安装日志分为正常信息、受管构建提醒、未知警告和错误；保留原文、退出码和成功标记，同类解释仅出现一次。
- 公网／内网执行后汇总基础步骤、配置保留、数据库备份、代码／版本、健康与本机入口，失败和中断不假定回退；入口通过后读取一次现有业务观察，未执行的 WebDAV、真实转存与外网项目单列。
- 重排管理菜单，分类与通知分为 8／9、诊断 12、备份 13、卸载 14；减少服务和家人配额设置的功能层级，保留确认与权限。
- 移除命名预览菜单，不保留隐藏入口；独立命令和 Bot 命名不变。无新增数据库迁移、依赖或必填配置，不重写传输核心。
- 须显式升级匹配的离线管理工具，详见[维护](/operations/maintenance/)和[升级反馈](/operations/update/)。本版已有用户确认的双架构 CloudDrive2 升级记录；真实 Telegram 转存、ACME／回退及其他场景未由本次日志确认，历史验收不外推本版。

发布后用户验收补充（2026-10-23）：用户确认 Ubuntu 26.04.1 ARM64、Debian 13 AMD64 两次 CloudDrive2 v1.4.3 → v1.4.4 升级通过。两日志显示配置保留、数据库备份、运行代码／版本、Bot healthy、本机 HTTPS 与最近业务就绪观察通过；信息分级与摘要已展示，Debian 的容量提醒未阻断升级。WebDAV 写入未执行，实际转存与公网仍待单独验收，详见[双架构用户记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V144-ACCEPTANCE.md)。不修改 Tag、资产或远端 Release 正文。

## TG2Cloud v1.4.3

2026-10-23，[v1.4.3 已正式发布](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.3)。辅助 A `cace622ffbbcecd28db7b00a29c26901e8fa139d`、入口 B／Tag `5aaf6a9b158d785ffa2fee52750c022fb8654810` 各五项 CI 与[同标签原生双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39901152742)全部通过，实际源码包、SHA256 清单与 GitHub 资产摘要核验通过。 新增可选分类、管理员通知、成员配额及脱敏报告，修复测速、保留简洁首页，统一编号菜单和外部 WebDAV 默认值。业务数据库迁移到 schema 2，升级前备份；范围见[仓库更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。本版已收到限定的[用户升级日志](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V143-ACCEPTANCE.md)；真实转存、外网访问和故障回退尚未确认。

本版还包括四个旧版可信基线、实例快照／隔离预检、业务就绪观察、Nginx 生命周期回归与命名预览；延续实例身份、历史路径、命名优先级与冷却保护，不增加生产覆盖恢复。开发阶段记录与发布核验见[维护增强](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-IMPROVEMENTS.md)，不回写旧版已发布资产。

## TG2Cloud v1.4.2

2026-10-21，[v1.4.2 已正式发布](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.2)。辅助 A、固定入口 B 各五项 CI 及[同标签原生双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39592291162)全部成功，实际源码资产、SHA256 和 GitHub 摘要核验通过。完整范围见[仓库变更](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)，不将 CI 扩大为 VPS、ACME 或迁移实机验收。

发布后同日另完成 CloudDrive2 v1.3.4 → v1.4.2 的授权人工升级：原 Release／Tag 已删除，先核验原提交并备份，再调用正式升级核心。数据保留、Bot 健康、只读 WebDAV、外部电脑 HTTPS 与升级后在线复检通过，继续使用 managed。自动缺失基线处理尚未改进，真实转存和新代理模式未验收，详见[本次记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V142-ACCEPTANCE.md)。这只是发布后文档补充，不改写正式资产。

- 新增显式授权的 external_docker 模式，不关闭外部 Nginx，不增加第二层代理，不修改外部 Compose；默认 managed 模式与 Bot 流程不变。
- 核验端口真实归属、持久化配置和稳定网络别名；使用逐文件事务、私密备份、nginx -t、reload 和实际 TLS／后端检查。
- Webroot 签发及宿主离线续期，复用证书仍由原工具负责；共享 schema 3 保留独立外部 WebDAV，卸载不停止外部代理且默认保留证书与恢复材料。
- 标准目录、普通 Nginx 和已运行的 cron 等支持条件见[域名 HTTPS](/deploy/domain-https/)。external_docker 的真实 VPS 接入、ACME、长期续期、代理迁移和现有网站业务仍待实机验收；不改变 Bot 依赖、镜像或数据库。

## TG2Cloud v1.4.1

发布审计发现的开发依赖漏洞通过更新 uv 0.13.4、certifi 2026.10.19 并统一重生成哈希锁修复；Bot 运行依赖和网关镜像不变，保留安全审计。

版本日期：2026-10-21，[v1.4.1 已正式发布](https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.4.1)。单一公网 A、已核对本机 AAAA 且端口归属安全的 NAT 场景增加云控制台公网 IPv4 人工确认，确认仅本次有效，执行前重新比对。错误记录、端口占用和拒绝确认仍会停止；ACME、TLS 和失败回退继续执行。新增 DNS／80／443 分项错误提示和回环地址保护。辅助 A／固定入口 B 各五项 CI、[同标签双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39525213331)及实际资产校验通过。发布后用户确认Ubuntu26.04.1／ARM64／公网NAT的CloudDrive2首装、本机HTTPS与WebDAV通过，见[验收范围](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V141-ACCEPTANCE.md)；OpenList、外网手机、升级回退与长期续期不外推。此为文档证据补充，不改已发布资产。完整改动见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)，环境要求见[部署前准备](/guide/prerequisites/)。

## TG2Cloud v1.4.0

完整改动见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

统一主安装、LAN、维护、卸载与外部 WebDAV 的架构检查，核对内核、64 位用户态、Docker daemon 和镜像原生平台，不自动设置 QEMU。两 Edition、依赖、镜像版本、配置与数据路径不变；新增原生双架构 CI、隔离网关与扩展依赖检查。版本日期：2026-10-20，[v1.4.0 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v140)；A／B 各五项 CI 与[同标签双架构发布](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39426176679)成功，实际源码包、SHA256 清单与 GitHub 资产摘要已核验。Oracle／真实 VPS、云盘与手机仍由用户发布后验收，不能用 CI 代替。见[部署前准备](/guide/prerequisites/)。

TG2Cloud 与上游 TG115 分别记录版本。以下是仓库 CHANGELOG 和发布说明的整理，不把历史 TG115 的版本号当成 TG2Cloud 发布版本。

## TG2Cloud v1.3.4

版本与资料核对日期：2026-10-19。[v1.3.4 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v134) 已正式发布；辅助 A 与入口 B 各五项 CI、[同标签发布工作流](https://github.com/LuoPoJunZi/TG2Cloud/actions/runs/39204327020)全部成功，实际源码包、SHA256 清单与 GitHub 资产摘要已核验。详见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

### 待发布边界修复

以下规则已随 v1.3.4 发布，旧标题仅用于保留链接锚点，不表示仍待发布。

- 媒体斜杠说明正常接收；改善表情标题、正常作品名与推广／凭据区分、相邻作品名／集数、斜杠文字、中文旁域名及尾部画质过滤。
- 网址、账号或处理前缀污染的视频原名可使用实际可靠正文；无原名、数字／默认／污染名的单图片可使用自身说明，不借用无关消息。
- 同组恰好一图一视频、真实后缀可区分时共用无编号标题；多成员、同类或后缀不明确继续编号。真实后缀和正常 MKV 格式保留，明显错误的视频后缀保守修正。
- 保留正常原名、隐藏实体、鉴权、去重、无说明兜底、原名记录与远端冲突保护；不改历史任务，不增依赖、数据库迁移或传输流程，不抓评论／频道，不做 OCR。
- 补全仓库命名、配置、备份恢复和 FAQ 文档，网站独立同步，README 保留简短入口和原致谢许可。

新规则示例和限制见[第一次转存](/usage/first-transfer/)。本地全量 864 项（838 成功、26 既有环境跳过）、Python 3.10 CLI 393 项（382 成功、11 环境跳过），Node.js 22 构建与网站 19 项测试通过。真实 VPS、Telegram、两版网关、手机或升级尚未验收；用户确认的 CloudDrive2 v1.3.3 转存不扩大为本版结论。

## TG2Cloud v1.3.3

版本日期：2026-10-18。[v1.3.3 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v133) 已正式发布；辅助提交、入口提交与同标签 Actions 均通过，实际源码包与 SHA256 已下载核对。详见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

新增家庭共享：Bot 安装后授权成员、各自任务与通知、共用保存目录；外部 WebDAV 支持多个独立只读账号，授权和目录由网关后台确认。未增加个人目录，也未完成本轮真实网关／手机验收；详见[Bot 使用](/usage/commands/)与[外部 WebDAV](/deploy/external-webdav/)。

视频命名增量增强 Unicode 多语言、混合随机 ID、广告域名与元数据过滤，同条消息及本组说明共用候选评分；可靠原名、扩展名、媒体组指定名称、无说明回退及既有去重保留。识别异常不阻止接收，不抓评论／频道，不增依赖。示例与限制见[第一次转存](/usage/first-transfer/)；真实 Telegram 或网关验收仍需独立完成。

资源页移除文件系统容量清单，后台磁盘采样与安全保护不变。新增回归与既有恢复、权限、转存检查共同运行；自动检查不代替[历史实机记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V130-ACCEPTANCE.md)之外的新验收。

发布后补充（2026-10-19）：用户确认 CloudDrive2 v1.3.3 升级后的实际转存验收完成；不扩大为 OpenList、家庭共享或所有异常路径的验收。

## TG2Cloud v1.3.2

版本与资料核对日期：2026-10-18。[v1.3.2 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v132) 已正式发布；辅助提交、入口提交和同标签发布检查全部通过，下载的源码包、实际 SHA256 与公开资产摘要已核对。详见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

- 公网／内网默认入口采用中文编号向导，未安装的 Edition 确认后进入安装，已有实例进入管理；新装 WebDAV 密码回车生成 8 位，升级保留原配置。
- 新增离线 `tg2cloud`：安装升级、状态、日志、启停、WebDAV 验收、HTTPS、备份、凭据与“卸载当前实例”；危险操作保留确认，状态／日志不下载代码。
- 最后一套完整卸载后，仅在无依赖且归属核验通过时清理管理代码和命令；另一 Edition、云端文件、系统软件与防并发锁不删除。
- 外部 WebDAV 使用独立中文编号菜单、实际目录确认及简洁手机参数；不加入主安装或 Bot 菜单。

不新增 Bot 依赖、数据库迁移、网关镜像或环境变量。新安装／升级／卸载、真实手机与原生账号权限仍需单独验收，自动测试不等于 VPS 验收。

## TG2Cloud v1.3.1

发布日期与资料核对日期：2026-10-18。[v1.3.1 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v131) 已从同一不可变 Tag 验证并发布源码包/实际 SHA256，下载及公开资产摘要已核对。本轮改动见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)。

- 独立 `install-webdav.sh` 和离线维护命令；主安装不询问或默认启用，不改 Bot 配置与菜单。
- 原生独立只读账号、最终目录确认、专用 HTTPS 域名单账号门禁和 Range 读取；不复用 Bot/管理员密码。
- 共享代理 schema 2、认证文件轮换、管理路由保留、证书续期与卸载依赖保护。
- 修正只读方法检查与编码反斜杠拦截，隔离 Nginx 覆盖两版认证、中文/编码、写方法拒绝、密码轮换和视频 Range。

不新增数据库迁移、Bot 配置或依赖，不升级网关镜像。原生网关账号/目录、手机、公网 ACME 和 ARM64 尚未实机验收；历史 v1.3.0 CloudDrive2 记录不作为本版附加功能验收。

## TG2Cloud v1.3.0

版本与资料核对日期：2026-10-17。本版以 Linux 一键脚本维护 CloudDrive2 和 OpenList；Windows EXE 停留在 v1.2.1。该版发布与兼容信息见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v130)；v1.3.0 Release／Tag 现已移除，不再作为下载入口。

- VPS 与内网首次安装提供流式优先、均衡和手动磁盘预算，复用现有资源算法；升级保留原配置。
- 执行前在锁内重新检查容量，磁盘条件变化则停止；任务预算不是分区，也不覆盖所有网关缓存。
- Linux／Docker／WebDAV 回归后生成一次源码包及实际 SHA256，发布任务复用同一 artifact；三个在线入口固定到匹配的辅助源码。
- 共享核心模块化到 `src/tg2cloud/`，保留既有配置、数据库、Session 和后端提交策略，不新增数据库结构迁移或配置项。
- 视频命名优先有效长描述与引用块，过滤链接、话题和推广；CI 工具与已验证依赖更新，网关镜像不变。

新布局已通过 Linux 全量回归、宿主 Python 3.10/3.13、两 Edition 非 root 镜像和隔离 LAN 网关检查。[发布工作流](https://github.com/LuoPoJunZi/TG2Cloud/actions/workflows/release.yml) 已从同一 Tag 验证、打包并发布源码包与实际 SHA256。

发布后补充（2026-10-17）：CloudDrive2 旧测试候选经授权备份、人工核对后，使用正式 v1.3.0 原生流程迁移成功，用户确认升级后使用验收完成。历史任务、配置与 Session 授权保留，健康、指纹、HTTPS、只读 WebDAV 和在线入口复检通过；OpenList 与共享代理容器未重启。这不是任意候选代码可被自动覆盖的证明，也不替代首次安装、故障回退、NAS 及全部异常传输验证，见[验收记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V130-ACCEPTANCE.md)。

## TG2Cloud v1.2.1

本节对应 v1.2.1 正式版本，详见[源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/v1.2.1/CHANGELOG.md)与 [v1.2.1 Release](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/CHANGELOG.md#tg2cloud-v121)。

- 视频数字/默认名称从同条说明提取标题，过滤链接、话题与常见推广；不获取评论区资源。
- 整组图片/视频可共用本组说明标题并分别编号；没有说明的单个视频保留原名，不回查频道。
- 失败数字每周一按容器时区切换统计范围，首页仍显示 `❌ 数字`，不删除失败历史或文件。

- 已取消任务确认后重新转存，保留去重、编号与历史；新增归属受限的查询和状态分页。
- 远端文件不完整或结果不确定时保留数据，允许确认换名重传；OpenList 不恢复使用不可靠的 MOVE。
- 遗留扫描增量读取并显示完整性，删除范围和数量保护不变。
- 大小验证记录、CloudDrive2 安全回退、离线备份预检、多文件系统容量诊断与错误脱敏。

发布日期与内容核对日期：2026-10-15。两个 EXE 已由同标签 Actions 构建、自检和发布，实际 SHA256SUMS 已核对。包含主分支此前的 OpenList DB 快照/digest 回退修复。CloudDrive2 候选已完成保留历史任务的迁移、健康启动与只读 WebDAV 检查，真实 Telegram 转存、完整安装升级、OpenList 实机和灾难恢复仍待验收；正式下载为 v1.2.1。见[源码验收清单](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/RELIABILITY-ACCEPTANCE.md)。

## TG2Cloud v1.2.0

发布日期与内容核对日期：2026-10-11。两个 Windows EXE 已由 GitHub Actions 从同一 v1.2.0 Tag 测试、构建和自检；Release 复用该次 Windows artifact，实际 SHA256SUMS 与资产摘要已核对。

- 增加独立内网向导，人工输入私有 IPv4，不申请域名证书、不改变原 EXE / 公网 VPS 的强制 HTTPS；验收前再次显示内网 IP 和 Edition 固定端口。
- 增加独立卸载入口，先预检并确认所选 Edition / all，默认保留业务数据、历史备份和证书，不卸载系统 Docker/Nginx；未知归属、外部引用、FUSE 或使用中的网络均停止。
- 分支 CI 检查 Python 3.10/3.13；发布验证覆盖三个 Shell 入口、两版候选镜像与隔离 LAN 网关，两个部署器仍是主力。

用户提供的 CloudDrive2 内网 Debian 日志显示首次部署和 WebDAV 验收通过；OpenList 内网、其他 NAS、跨版本升级/回退、真实卸载及本轮 Telegram 转存仍未验收。

[查看 v1.2.0 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v120) · [下载与安装入口](/download/)。

## TG2Cloud v1.1.5

发布日期与内容核对日期：2026-10-10。两个 Windows EXE 已由 GitHub Actions 从同一 v1.1.5 Tag 测试、构建和自检；Release 复用该次 Windows artifact，实际 SHA256SUMS 与资产摘要已核对。

- HTTPS 配置在 Ctrl+C、TERM 或 HUP 时执行有限回退；提交与回退期间延后重复信号，已提交状态不会恢复成旧运行配置，另一 Edition 路由继续保留。
- 共享代理备份改为分块 SHA256，证书与续期日期使用兼容 UTC 接口，宿主 Python 3.10 纳入维护兼容检查。
- 首次基础安装成功但 HTTPS 失败后，续做成功再次提供凭据逐项确认；新增独立 `--show-credentials`，不安装、升级或改密，保存的 OpenList 初始化密码可能已更改。
- HTTPS 预检列出缺少的工具和安装命令；基础部署补齐 `iproute2`、`python3`，预检本身不自动安装软件。
- 补充中断、提交一致性、备份兼容和凭据隐私回归；Telegram、SQLite、队列、rclone、WebDAV、streaming 和持久化兼容标识未改。

本地回归 470 passed、18 skipped、211 subtests passed；同标签发布检查通过。真实 VPS 的新中断/续做流程、首次安装、跨版本升级、回退与 Telegram/云盘转存仍待验收，OpenList 脚本实机验收暂缓。

[查看 v1.1.5 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v115) · [下载与 VPS 单行入口](/download/)。

## TG2Cloud v1.1.4

发布日期与内容核对日期：2026-10-09。两个 Windows EXE 已由 GitHub Actions 从同一 v1.1.4 Tag 测试、构建和自检，Release 复用该次 Windows artifact；实际 SHA256SUMS 与资产摘要已核对。

- 修复 `/dev/tty` 输入流打开失败，以及 CLI 私有源码导致非 root 候选镜像无法读取 `app/__init__.py` 的问题；两 Edition 共用修复。
- 公开构建文件为 0644、子目录为 0755，私有外层目录与秘密仍分别保持 0700/0600，秘密不进入 Docker 上下文。
- 两版 Bot 镜像内部程序目录改为 `/opt/tg2cloud`，用户/组与 logger 改为 `tg2cloud`，新日志使用 `tg2cloud.log`；UID/GID 仍为 `10001:10001`。
- 保留 `tg115.db`、`bot.session`、旧日志、兼容变量与 verify 前缀；不迁移数据、不重写 Telegram、SQLite、rclone、WebDAV 或 HTTPS 业务流程。
- 新增 Linux 真实候选镜像启动门槛；正式两个 EXE 仍由 Windows Actions 构建，Release 复用该次 artifact 与实际 SHA256。

真实首次安装、跨版本升级、回退和 Telegram/云盘转存仍待修复后的实机验收，OpenList 脚本实机验收暂缓。

[查看 v1.1.4 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v114) · [下载与 VPS 单行入口](/download/)。

## TG2Cloud v1.1.3

发布日期与内容核对日期：2026-10-09。两个 Windows EXE 已由 GitHub Actions 从同一 v1.1.3 Tag 重新测试、构建和自检；Release 复用该次产物及实际 SHA256，不使用本机旧构建。

- 新增可选 VPS 单行安装/保留配置升级向导；先收集信息、预检及确认，两个 PySide6 部署器仍是主力。
- 向导模块固定已验证的 commit，实际 payload 始终来自最新正式稳定 Release，不安装 main/RC 未发布业务代码。
- 已有完整实例复用配置，核对官方源码、运行指纹与挂载；TG115、部分实例、手改代码、目录冲突和网关数据库迁移安全停止。
- 复用现有 Docker、备份/有限回退与强制 HTTPS；健康域名不隐式切换，WebDAV 写入验收另行确认。
- 同步 Bot、两个部署器、Windows 资源和文档版本；正式发布后同步下载链接与网站发布状态，保留历史验收记录，不把发布成功当作实机验收。
- 合入 Telethon 1.45.0、PyInstaller 6.22.3 的限定兼容验证及 CI 工具升级；新版 EXE 的真实 VPS 部署、Telegram 登录和转存仍需对应验收。

CloudDrive2 脚本仅通过真实 VPS 只读预检，未执行首次安装、跨版本升级或回退；OpenList 脚本实机验收暂缓。

该历史版本的 Tag/Release 后来已移除，不再作为下载入口。[查看历史源码更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/9ef61daffe4e62a5177dfcc50e78aa4df70f1af6/CHANGELOG.md) · [下载与 VPS 单行入口](/download/) · [脚本完整指南](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/VPS-INSTALL.md)。

## TG2Cloud v1.1.2

发布日期：2026-10-08。本次聚焦运行状态、故障提示与 HTTPS 维护，两个 Windows EXE 继续由 Actions 从同一不可变标签构建一次，并以该次实际产物生成 SHA-256。

**实际版本与阶段。** 运行状态分别显示本机部署器和 VPS Bot 实际版本；未知不当作最新版，不自动升级或降级。既有进度、日志与弹窗显示实际执行阶段和核对建议，不虚构百分比或根因。

**共享代理维护。** 两版 HTTPS 对话框新增私密代理备份、完整性检查、隔离解包和当前域名续期 dry-run。历史备份可选择核验；清理须先预览再确认，默认取消、至少保留一份，清单变化或校验失败拒绝执行。维护增加远端时限与精确任务清理，断连时不冒充清理已完成。

**续期与限流诊断。** 区分续期检查成功与证书实际变更；续期失败、已有记录超过 26 小时未更新或证书临近到期显示黄色警告，当前 HTTPS 自检通过时入口仍可用。OpenList `/doctor` 显示真实探测时间、401/429 分类和剩余冷却，原有退避与转存逻辑不变。

**构建与发布。** 部署器与 Bot 共用版本源，校验 Tag、源码、Windows 资源和发布文档一致性；修复打包备份助手的相对路径问题，增加备份对话框自检。Release 等待同标签 Windows/Linux 检查成功，复用已构建的 artifact，拒绝替换已有 Release。

本地回归与标签 CI 通过。专用 Debian 13 VPS 的代理备份/核验/隔离解包、OpenList 路由移除后恢复和续期 dry-run 通过；两版各 11 项 HTTPS 自检通过，CloudDrive2 既有配置与容器保持不变。历史备份清理只做无删除预览。

真实 Bot/网盘转存、401/429 实际恢复、长期自动续期、完整灾难恢复、独立网络的后端端口隔离及真实 Windows 桌面交互仍待验收，不把隔离解包或本机 HTTPS 自检当作全链路通过。

[查看该版历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v112) · [维护与诊断说明](/operations/maintenance/) · [备份与恢复边界](/operations/backup/)。

## TG2Cloud v1.1.1

**共享 HTTPS 事务保护。** 配置/移除使用 VPS 级事务锁，状态原子提交；移除路由同步 Certbot 活动域名，并检查保留 Edition，失败回退旧配置。

**OpenList 探测与路径保护。** 大目录检查不再截断至 10,000 项；只读探测区分 401/429，合并短时间刷新并增加冷却与限流退避。CloudDrive2 上传、改名命令与探测策略不变。

**发布门禁。** 同一标签的 Linux 验证和 Windows 构建均成功后，才发布一次构建生成的两个 EXE 与实际 SHA-256。

本轮双网关 HTTPS 共存、外部访问/跳转/公开 WebDAV 阻断及真实 SSH 锁互斥/断锁释放通过。OpenList Bot/WebDAV/限流恢复、路由移除和长期续期尚未重新实测；沿用旧版转存验收基线，不宣称本版全链路重新验收。

[查看该版历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v111)。

## TG2Cloud v1.1.0

该版本的两个 Windows EXE 从同一不可变标签源码测试、构建和自检，并使用 GitHub Actions 实际产物计算 SHA-256。

**强制 HTTPS 管理入口。** 受管 CloudDrive2/OpenList 基础容器健康后自动进入域名配置；证书、HTTPS、HTTP 跳转、公开 `/dav` 阻断和后端回环监听全部通过后才显示“部署完成”。

**收紧公网边界。** CloudDrive2 19798 与 OpenList 5244 继续只监听 VPS 回环地址，只有共享 Nginx 使用公网 80/443。普通工作台不再显示固定端口 SSH 隧道按钮，底层隧道代码仅保留兼容和故障恢复能力。

**验收门禁。** 受管网关在 WebDAV 最终验收前再次检查当前 Edition 的 HTTPS 状态；外部 WebDAV 模式不要求为不存在的本地管理容器配置域名。

CloudDrive2 与 OpenList 已在真实 VPS 完成受管部署、证书签发/复用、HTTPS 自检和 WebDAV 全流程验收。

[查看该版历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v110)。

## TG2Cloud v1.0.4

该版本的两个 Windows EXE 从同一不可变标签源码测试、构建和自检，并使用 GitHub Actions 实际产物计算 SHA-256。

**Bot 状态首页。** 使用紧凑的任务与实时速度面板，根据实际 Edition 显示 CloudDrive2 或 OpenList，并以数字时间标记本次状态生成时间。

**按钮与资源页。** 首页按钮精简为任务、VPS 资源和原地刷新；CPU、可用内存、可用磁盘与 TG2Cloud 本地额度进入独立资源页，按钮结果继续编辑原消息。

**兼容与边界。** 目的端状态、任务统计、分阶段速度与 `ResourceMonitor` 均复用现有实现，旧 `menu:status` 回调继续兼容；Telegram 下载、SQLite 队列、rclone、WebDAV、streaming 和既有部署流程未被重写。

新 Bot 界面已通过自动回归测试；v1.0.3 已完成的共享域名 HTTPS 验收，以及两版既有基础部署和 WebDAV 真实 VPS 验收结果继续作为回归基线。

[查看该版历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v104)。

## TG2Cloud v1.0.3

该版本的两个 Windows EXE 从同一不可变标签源码测试、构建和自检，并使用 GitHub Actions 实际产物计算 SHA-256。

**域名 HTTPS。** 新增两个 Edition 共用的 Dockerized Nginx/Certbot 网关，可为 CloudDrive2 与 OpenList 管理界面分别配置 HTTPS 域名；原 SSH 隧道和 Docker 内网 WebDAV 保持不变。

**安全与回退。** 增加 DNS、端口归属、证书、HTTPS、跳转、公开 `/dav` 阻断和后端回环监听检查；配置失败保留旧路由，不停止或覆盖外部 Web 服务。

**可靠性与界面。** 修复证书复用、失败清理、续期筛选、状态脚本和 NAT 回环误报，域名状态结果改为固定高度、可滚动和可复制的小型日志框。

共享域名 HTTPS 功能已完成验收，适用于 CloudDrive2 与 OpenList。两版原有基础部署和 WebDAV 真实 VPS 验收结果继续作为回归基线。

[查看该版历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v103)。

## TG2Cloud v1.0.2

该版本的两个 Windows EXE 从同一标签源码构建，并使用实际产物计算 SHA-256。

**OpenList 写入兼容性。** 针对部分 OpenList/115 Open 对 MOVE 返回成功但目标文件未生成的情况，改成预留无冲突最终路径后直接写入，保留大小复验、失败保护和安全清理。

**CloudDrive2 稳定流程。** 继续使用临时上传、改名和大小复验；OpenList 新逻辑按后端隔离。

**部署界面与错误提示。** 修复 OpenList 工作台窄侧栏裁切，区分 401 凭据错误和 429 限流。

发布说明记载两版已完成真实 VPS 基础部署与 WebDAV 验收；Telegram 和不同文件规模仍应在用户实际环境继续验证。

该版 Release／Tag 已移除，[查看 v1.0.2 历史记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md#tg2cloud-v102)。

## TG2Cloud v1.0.1

修复 CloudDrive2 首次部署时，网络修复发现逻辑把当前 Bot 容器误判为第二个网关的问题。

仅从网关发现中排除当前 Edition 的 Bot，保留多个真实网关和旧 TG115/固定端口冲突的保护，增加对应回归测试。该历史条目的验证说明按当时记录理解，不当作当前全链路验收承诺。

## TG2Cloud v1.0.0

建立两个 PySide6 正式 Edition，使用独立安装目录、容器、Docker 网络和固定管理隧道端口。

加入新命名空间与必要旧标记兼容，既有 TG2Cloud 重新部署默认保留 `.env`，明确旧 TG115 不会被自动接管。OpenList 增加管理、脱敏日志、一致性备份等专属操作。

正式构建不再包含 Classic/Tkinter 部署器。

## 上游来源与许可

TG2Cloud 基于 [whyhhh20/TG115](https://github.com/whyhhh20/TG115) 演进，保留原作者、MIT 版权和许可证。上游自己的版本由上游维护，不作为 TG2Cloud 的安装或升级路线。

历史版本条目是更新记录，不是旧版文档快照；旧部署器不再作为当前下载方式。历史验收使用固定源码提交链接，不随旧 Release 或 Tag 的删除而变成当前教程。

## 当前仍然存在的限制

没有覆盖生产数据的一键 Restore；实例快照和共享代理备份校验不等于完整服务恢复。不同部署方式不相互接管，不提供跨实例 Token 分布式锁。真实 VPS、Telegram、网关、证书签发与长期续期均按实际版本和范围验收，见[备份边界](/operations/backup/)与[当前发布记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V157-ACCEPTANCE.md)。
