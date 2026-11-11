# 公网 VPS 安装与升级

在自己的 Debian / Ubuntu Linux 主机上运行向导，选择 CloudDrive2 或 OpenList。新装先收集信息、预检和确认；已有标准实例保留配置升级。公网管理使用 HTTPS；可信内网和独立 Compose 分别使用[内网入口](LAN-INSTALL.md)与[Compose 教程](COMPOSE.md)。

当前入口固定辅助代码 A `60862325931197915ea8058261cca0f5f74599b3`；业务只安装正式稳定 Release。实际版本、CI、资产和未执行的实机项目见[当前发布记录](development/V1510-ACCEPTANCE.md)，不在本教程累积旧版 pin。

<a id="公网-nat-的已知限制与待发布修复"></a>

## 公网 NAT 与域名检查

已发布 v1.4.0 的 HTTPS 检查要求域名地址匹配网卡地址，Oracle 等公网映射到私有网卡的主机可能误报 DNS 失败，即使 A 记录正确、80／443 空闲。不要将公网 A 改成私有网卡地址，也不要为此关闭防火墙或停止其他项目。

v1.4.1 增加交互确认：仅在单一公网 A、所有 AAAA 均匹配本机、没有其他公网 IPv4 网卡且端口归属安全时，要求手动输入**云控制台分配给本机的公网 IPv4**，与 A 记录比对后再确认映射。不会从 DNS 自动填写或通过第三方查询出口 IP。留空、拒绝确认、地址不一致均停止。该确认仅保留在当前进程，重新操作须再次核对；它不是自动证明入站映射，后续 ACME 和 HTTPS 自检仍须通过。

此修复已进入 v1.4.1 正式资产与匹配在线 helper；重新运行本页公开命令可获得新版向导。独立外部 WebDAV 和 `tg2cloud` 的 HTTPS 修复也需显式更新到本版代码，既有离线命令不会自动更新。NAT 不影响 CPU 架构检测；本次 CloudDrive2 ARM64 首装已收到用户验收，其他版本／场景仍单独验证。章节原标题保留以兼容既有链接，不表示当前版本仍未发布。

## 支持范围

v1.3.0 已发布 `src/tg2cloud` 新布局；本地可运行 `python3 scripts/run_source.py install --help`。在线一键命令 URL 不变，使用本版已验证 helper pin 和正式稳定 payload；修改本地源码或仅推送文档不会更新 VPS。迁移与本地预检说明见[Linux 重构](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/LINUX-REFACTOR.md)。

v1.3.1 的[外部 WebDAV](external-webdav.md) 是独立可选入口，主安装不增加询问。附加功能启用后共享代理为 schema 2，后续管理和主卸载须使用匹配的新脚本；主卸载前先独立 uninstall 附加入口，不删除网盘文件。

| 场景 | 行为 |
| --- | --- |
| 全新 VPS | 选择 Edition，收集信息，预检，确认后安装 Docker 环境、基础服务及强制 HTTPS |
| 完整的已有 TG2Cloud | 识别目录、Compose 身份、持久化挂载和版本，复用现有配置升级所选 Edition |
| 已是最新稳定版 | 不重建、不重启；可以另行确认 HTTPS 续做或 WebDAV 验收 |
| 当前版本高于 latest | 不降级；停止隐式 HTTPS 变更 |
| 两个完整 Edition 同时存在 | 明确选择一套；`--edition both` 仅用于显式升级两套，依次执行，不是跨 Edition 原子事务 |
| TG115、残留目录、部分容器、同名外部容器 | 停止，不覆盖、不自动迁移或接管 |
| 手工修改过程序、Compose 或 Dockerfile | 停止，请先人工核对；不提供强制覆盖参数 |
| 新稳定版更换云网关镜像 digest | 停止自动升级；不隐式迁移 OpenList/CloudDrive2 数据库，先备份并在隔离环境验证网关迁移；不绕过身份与镜像检查 |

正式 v1.4.1 面向 Debian/Ubuntu 原生 AMD64／ARM64，两架构共用检查和入口，仍要求 root、64 位用户态、Python 3.10+、Bash 和可交互终端。匹配 helper 与稳定包均已发布核验；CI 通过不等于 Oracle 或任意 NAS 实机通过。镜像证据、Oracle Cloud 与验证结果见[双架构说明](ARCHITECTURES.md)。系统需有可用 CA 根证书和时区数据库，CloudDrive2 仍需 `/dev/fuse`，内存和磁盘检查不变。

缺少 Python 时请先自行确认系统环境，并安装 `python3`、`ca-certificates`、`tzdata`。脚本不会在信息收集与确认前自动安装软件。APT/Docker 的安装权限只在首次基础安装的最终确认后交给现有安装器；升级要求已有 Docker daemon 和 Compose 可用，不自动升级 Docker 引擎。

## VPS 单行安装命令

以 root 登录 VPS，在 Bash 可交互终端运行（需 Python 3.10+、curl 和系统 CA 证书）：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh)
```

不带参数时先选择 Edition，随后识别全新安装或已有实例。脚本不会在收集信息、预检及最终确认之前安装软件或修改实例。当前仍建议先在专用测试 VPS 使用。

HTTPS 预检还需要宿主机的 `ss`、`ip`（`iproute2`）、`getent`、`flock` 和 `timeout`。缺少工具时会列出名称及对应安装命令，不会当作 DNS 错误，也不会在预检阶段自动安装软件。确认执行后的基础安装依赖包含 `iproute2` 和 `python3`；共享代理备份兼容宿主 Python 3.10。

只检查 CloudDrive2，不安装／升级：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition clouddrive2 --check
```

检查通过后，再运行 CloudDrive2 安装／升级向导：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition clouddrive2
```

只检查 OpenList，不安装／升级：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist --check
```

检查通过后，再运行 OpenList 安装／升级向导：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist
```

两套命令只操作所选 Edition；全新 VPS 收集信息后安装，完整已有实例保留配置升级。OpenList 脚本实机验收仍暂缓，请先在专用测试 VPS 验证；`--check` 通过不等于安装或升级成功。

进程替换 `<(...)` 不占用交互标准输入；向导仍通过 `/dev/tty` 隐藏读取秘密。不支持用 `curl | bash`、无人值守管道或命令行参数传入密码。

这类命令会立即执行从仓库下载的代码，只有信任仓库和维护者时才使用。不希望直接运行远程代码时，可先下载、检查，再运行：

```bash
curl -fSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh -o tg2cloud-install.sh
less tg2cloud-install.sh
bash ./tg2cloud-install.sh --edition clouddrive2 --check
bash ./tg2cloud-install.sh --edition clouddrive2
```

不要覆盖自己已有的同名文件。网络、API 限流或下载校验失败时停止，不安装替代代码。`curl -f` 会显示 HTTP 下载错误；若首段脚本未下载成功，不会进入向导，即使外层 Bash 的退出码是 0 也不代表安装完成。

## 从本地源码试用

在 VPS 上进入包含这些新增文件的源码目录，以 root 运行：

```bash
git clone https://github.com/LuoPoJunZi/TG2Cloud.git
cd TG2Cloud
bash ./install.sh --help
bash ./install.sh --edition clouddrive2 --check
bash ./install.sh --edition clouddrive2
```

OpenList 使用 `--edition openlist`，其脚本实机验收仍暂缓。不指定 Edition 时出现选择向导。已有两套完整实例可使用 `--edition both`；不支持一次向导在全新 VPS 批量安装两套。

`--check` 只读运行实例及 HTTPS 状态，不收集秘密、安装软件或修改运行配置。它仍会访问公开 GitHub API 并在私有临时目录下载源码，因此需要网络和一定的临时磁盘空间。检查通过不代表 WebDAV、HTTPS 公网访问或 Telegram 实际转存已验收。

### 旧版本 Release／Tag 已删除

v1.4.3 已增加四个受支持旧版的[可信目录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-IMPROVEMENTS.md#1-旧版本可信基线)，旧 Release 删除时仍核对原提交和载荷。未知版本继续要求正式基线。下面保留 v1.4.2 当时的限制与人工验收记录，不要下载任意 SHA 或绕过源码核验。

当前向导需要核验已安装版本的正式源码基线。若该版本的 GitHub Release 或 Tag 已删除，旧版本查询可能返回 404 并在升级前停止；即使版本号、容器和现有服务正常，也不能据此跳过基线检查。先保留原实例，不卸载、不改版本标记、不从未知来源覆盖代码。

应先保存配置、数据库一致性快照、Session、必要网关配置和共享代理备份，再由维护者单独审阅可追溯的原提交与目标正式资产。本次 v1.3.4 → v1.4.2 按明确授权完成了这条人工路径，见[验收记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V142-ACCEPTANCE.md)；它不是新增的自动接管功能，不提供通用强制升级参数。升级后同版本在线 `--check` 通过，也不代表升级前缺失的 Release 已恢复可用。

### 终端输入错误

若旧向导在显示正式 Release 后立即报 `File or stream is not seekable.`，这是交互终端打开方式的兼容问题，不是 Docker、HTTPS 或 WebDAV 部署失败。该错误发生在升级计划及最终确认之前，尚未执行安装/升级，不需要卸载或删除已有数据。

终端修复只影响独立向导，不改写已有 Release。单行入口固定到不可变向导 commit，只有维护者将入口 pin 更新到通过 CI 的修复提交后，重新下载才会使用修复；不要通过删除实例、改为无人值守管道或跳过确认绕过错误。

目标 payload 始终来自 GitHub 最新正式稳定 Release 的源码，不是本地工作树或 `main`。v1.3.0 起已包含脚本和模块化源码；未来从本地试用新向导时，也不会把尚未发布的业务代码装到 VPS。

### APT 软件源错误

如果执行确认后停在“安装基础软件”，并提示没有 Release 文件，先区分系统 APT 与 TG2Cloud 容器问题。在自己的终端直接运行 `apt-get update` 复现原始错误；它更新软件包索引，不执行软件安装或升级。

核对当前系统使用的活跃源文件（通常为 `/etc/apt/sources.list`、`/etc/apt/sources.list.d/*.sources` 或 `*.list`），尤其是 URI 的协议、主机名与路径，以及 Suites 的发行代号和 Signed-By。`.bak` 文件不等于活跃配置。先备份具体文件，只修正已经确认错误的条目；不整份覆盖源列表、不混用发行代号、不删除安全更新源或关闭签名验证。

本次 Ubuntu26.04.1 ARM64 用户反馈中，源文件实际为 `https:///ubuntu-ports/`，APT 输出为 `https:/ubuntu-ports`；日志地址可能经过格式化，不能只按其缩写精确搜索就认定源文件无误。用户备份并修正缺失主机名的 URI 后，索引更新成功，再运行原安装入口完成验收，见[v1.4.1 记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V141-ACCEPTANCE.md)。这是该主机的系统配置修正，不是脚本自动换源功能。

分享排查信息前移除私有源账号、令牌和全部建号密码。APT 失败或终端提示交错时，不通过删除数据库、Session、整个安装目录或批量结束 Python 进程“修复”；先核对实际失败阶段与对应进程。本次重跑未复现此前的提示交错，不代表其根因已被代码修复。

### 候选镜像源码权限错误

候选容器出现无法读取源码或配置的权限错误时，保留失败阶段和私有日志，核对来源是否为完整正式载荷、构建上下文是否完整，以及实际运行用户与文件权限。不要改为 root、递归开放权限或删除数据库来掩盖问题。

若问题发生在候选验证阶段，不应假定旧实例已经替换；按真实退出码、备份与回退记录确认当前服务。维护者修复须在新提交和版本中验证，不移动已经发布的 Tag。

## 入口与稳定部署版本

公网和内网 Shell 入口固定下载真实不可变的辅助代码 A；业务载荷另从最新正式稳定 Release 解析到唯一提交。辅助工具、目标版本和已运行 Bot 是不同对象，更新入口不会自动升级用户实例。

两个公开入口保留本地源码运行和显式参数。查看帮助或 `--check` 不等于安装；只有确认计划后才进入依赖准备、备份、候选构建和切换。未知版本、缺失源码和不可信实例停止，不回退执行未校验的 main 或预发布代码。

源码身份固定到 commit，下载使用系统 HTTPS；手动下载源码资产时使用同版 `SHA256SUMS.txt`，两条路径不要混为一谈。校验和不是数字签名，仓库和发布账号仍是信任边界；流程见[发布检查清单](development/RELEASE-CHECKLIST.md)。

## 首次安装

### v1.3.2 安装与管理交互

v1.3.2 的公网／内网入口不带参数时进入新版向导；业务 payload 仍只取正式稳定 Release，不部署 main 或预发布 Bot。本地运行 `bash ./install.sh` 同样有效。在线入口必须按[发布门槛](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/LINUX-REFACTOR.md#递归指纹与发布门槛)先验证 helper A，再更新入口 B 的 pin 和清单；已部署主机需显式运行向导确认更新。

不带参数的公网／内网入口先选择 Edition：未安装则确认进入其安装向导；已有实例则打开统一管理菜单，可按名称选择“卸载当前实例”，不必另找卸载命令。正式 v1.4.3 为 9，v1.4.4 新菜单为 14，须更新离线工具才会变化，完整说明见[运维菜单](OPERATIONS.md#本地管理菜单)。已保存的公网／内网模式优先于入口名称，不会隐式转模式。v1.4.7 移除根目录独立卸载脚本；卸载预检、全 Edition 和数据保留参数仍可用 `tg2cloud uninstall --edition all --check` 等子命令调用同一核心。快捷命令损坏时重新运行原安装入口，选择已安装实例的卸载项，不选择重新安装。

- Edition 使用编号选择；版本提示不显示提交摘要，实际 commit 仍保存在引导元数据并校验。
- WebDAV 用户名提示为“回车默认 tg2cloud”；手动填写的值原样使用。密码隐藏输入，回车生成 **8 位**大小写字母与数字，手动密码仍可使用更长值。只改变 Bot 默认 WebDAV 密码，不改变 OpenList 初始化管理员密码和外部 WebDAV 的密码策略。
- “Bot 保存子目录”可留空，表示使用该 WebDAV 账号根目录；账号根目录由用户在后台设置，不推断成 VPS 路径或固定网盘目录。
- 新安装固定默认 `Asia/Shanghai`，不再询问时区；升级保留已有 `.env` 原始字节，包括原时区、密码和预算。
- 计划确认后安装私密、不可变的离线管理代码及 `/usr/local/bin/tg2cloud`。命令或运行目录被未知程序占用时停止，不覆盖；取消与 `--check` 不安装它。基础安装失败后，已安装的命令可用于核对状态，但身份不完整的实例仍会拒绝维护，不自动修复。
- 首次 HTTPS 成功后，建号凭据汇总到当前私有终端，不重复询问是否显示，也不写入普通日志。已有实例的“查看凭据”和 `--show-credentials` 仍逐项确认。避免录屏、旁观或分享终端内容。
- 跳过 WebDAV 验收会明确提示未执行；容器或 HTTPS 健康不等于转存通过。下次直接输入 `tg2cloud`，菜单及限制见[运维说明](OPERATIONS.md#本地管理菜单)。

显式 `--edition`、`--check` 等旧参数继续提供原有结果标记；自动化不应解析新版人类可读文案。新版默认交互及管理菜单调用安装器时安装离线命令，已有实例没有它时可从新版源码运行 `python3 scripts/run_source.py manage`。未选择实际安装/升级的已有最新实例，也可单独确认只安装管理命令，不重启容器。

### 已发布向导的流程

1. 选择 CloudDrive2 或 OpenList。
2. 填写管理域名和可选 Let's Encrypt 邮箱。A/AAAA 必须正确直指 VPS，首次签发时 Cloudflare 使用“仅 DNS”。检查 80/443 是否能安全使用；公网防火墙与 ACME 可达性仍需用户确认。
3. 向导先读取资源，选择流式优先、均衡或手动方案，再收集 Telegram 和 WebDAV 信息。新装时区默认 `Asia/Shanghai`，不再单独询问；秘密隐藏输入，Bot WebDAV 密码留空生成 8 位。
4. 任务预算不是磁盘分区，推荐数值由实际可用空间、Docker 分区、内存和 FUSE 条件计算；手动配置仍需通过检查，保留空间不低于 `8GB`。执行前再次探测，条件变化则停止。手动输入默认 `20GB/8GB`；升级保留原配置，不静默应用新推荐。见[切换说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/SCRIPT-FIRST.md)。
5. 查看不含秘密的计划，确认后执行。默认回答为取消。
6. 基础服务安装完成后使用既有共享 Nginx/Certbot 配置 HTTPS。后端仍仅回环监听，不开放 IP 加端口入口；公网 `/dav` 继续阻断。
7. 打开自己的 HTTPS 管理页，自行配置云存储，再创建填写过的专用 WebDAV 用户。TG2Cloud 不收集云盘 Cookie、OAuth 或 Token。两版具体权限与路径示例见[存储网关配置](STORAGE.md)。
8. 默认中文交互的新装流程会在当前私有终端集中显示后台建号所需的 WebDAV 信息及 OpenList 初始化密码，不再逐项询问；显式参数的兼容流程、升级后的查看凭据仍逐项确认。不会写入普通日志或重设已有管理员密码，请避免录屏或旁观。
9. 另行确认 WebDAV 写入验收。它会创建并清理随机测试文件，未确认则不执行。验收失败不自动反复重试；仍需在云盘官方客户端确认最终文件，并测试 Telegram 真实转存。

所有输入先在进程内收集；确认安装时才写入权限 `600` 的临时配置，并交给原安装器。Base64 只是避免 Shell 解析错误，不是加密。VPS 上的 `.env`、`rclone.conf`、备份仍是敏感文件，不要公开。

完成后按 [Bot 使用指南](BOT-USAGE.md)进行首次转存；运行管理、修改配置与排查入口见[运维指南](OPERATIONS.md)。

## 已有实例升级

```bash
bash ./install.sh --edition clouddrive2 --check
bash ./install.sh --edition clouddrive2
```

脚本读取 Docker/Compose 身份和绑定目录，核对实际运行代码与磁盘源码，再与当前版本的正式 Release 源码比较。Windows payload 的 CRLF 与 LF 差异不视为手工修改。

较早正式版本没有 `app/version.py` 时，只从 `app/__init__.py` 静态读取明确的 `__version__` 常量，不执行它的内容；升级计划仍要求全套程序与该版本官方源码一致。新版版本文件存在但无效时直接停止，不退回旧文件猜测版本。

升级不再询问 Bot Token、API Hash、WebDAV 密码。候选配置仅要求保留现有 `.env`；升级前后核对其原始字节。CloudDrive2 的现有安装器会规范化 `.env` 换行，因此该 Edition 的 `.env` 若含 CRLF/回车，CLI 会在写入前停止并要求人工核对，不擅自改成 LF。Session、SQLite、下载目录及云网关持久化目录保留，不清空、不重新授权云盘。

确认后，现有安装器复用 APT 基础依赖检查，可能更新相关系统软件包；不主动升级 Docker 引擎。随后做候选构建及隔离预检，保存程序备份、短暂停止所选 Bot 并创建 SQLite 一致性快照，再切换程序。健康检查失败时调用已有回退；请以回退日志和实例状态为准，不能保证所有外部故障都能自动恢复。CLI 自己不另写数据库恢复或网关迁移逻辑。

### 源码基线不一致时

出现“现有程序与已发布版本不一致”或额外/缺失源码时停止。版本号相同不代表代码相同；不要改版本文件、删 Session/数据库、关闭指纹校验或强制覆盖。先保存原程序、配置、数据库一致性快照、Session 和必要数据，再单独审阅差异及恢复方案。未知或自定义候选需要单独审阅，不是公开脚本可自动接管的对象。

rclone 运行时可能重新混淆同一密码，导致 `rclone.conf` 字节变化；这与 `.env` 原始字节保留是不同检查。不能仅凭文件 hash 变化认定已改密，也不能忽略真正的 URL、用户或密码变化。仅在私有环境核对实际值，不将解混淆输出、完整配置或备份贴到 Issue；rclone 混淆不等于加密。

健康的已有 HTTPS 路由和证书原样保留；不切换域名、不重新签发，不重启未选中的 Bot。基础安装器仍可能对所选 Edition 的网关做既有的 Compose/网络操作；HTTPS 显式修复会操作共享代理，可能使管理页连接短暂中断。

当前管理工具使用 Edition 锁和共享 HTTPS 事务锁；不要从其他终端或旧工具并发修改同一实例，未知写入端不在锁协调的保证范围。

## HTTPS 续做与验收

如果基础安装成功而 HTTPS 失败，保留已安装数据，不要删除容器或反复全新安装：

```bash
bash ./install.sh --edition openlist --configure-https
bash ./install.sh --edition openlist --verify
```

`--configure-https` 是明确的配置/修复授权，执行前仍需要确认。有已保存域名时只能沿用它，不提供隐式切换。已是最新版本时只续做 HTTPS，不重建 Bot。没有保存域名时才收集新域名。

首次 HTTPS 失败前生成的秘密已经由安装器保存到 VPS `.env`。v1.1.5 向导在 HTTPS 续做成功后再次提供逐项确认显示；也可单独查看已有凭据，不安装、不升级、不修复 HTTPS、不重置密码：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist --show-credentials
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition clouddrive2 --show-credentials
```

每项默认不显示，仅在确认后写入当前私有终端，不进入普通日志。OpenList 显示的是保存的初始化管理员密码；如果后来在管理页改过密码，这不是当前密码。请避免旁观或录屏，不要把完整 `.env` 贴进日志、聊天或 Issue。该参数不能与 `--check`、`--configure-https` 或 `--verify` 组合。

公开单行入口固定到前文说明的不可变向导源码，包含这些修复和新参数；实际 Bot payload 仍只取最新正式稳定 Release。使用已下载的旧入口时，重新下载才能获得新向导；从本地 checkout 使用时，按该 checkout 的参数执行。

HTTPS 配置收到 Ctrl+C、TERM 或 HUP 时会尝试恢复原代理配置；状态提交与回退期间的重复信号会延后处理，保留原有命令超时。请等待退出后核对状态，不用强制杀进程加速；断网、断电、SIGKILL 或回退命令失败时仍可能需要人工恢复。已提交的新路由不会仅因提交结束时收到取消信号而恢复成旧运行配置。

`--verify` 仍需第二次确认，只有 HTTPS 自检健康才执行现有 `manage.sh verify`。返回 401、429 或业务错误不会触发自动改密、重装或循环验收。

状态结果区分：

- `TG2CLOUD_CLI_RESULT=NO_CHANGE`：未升级或重启。
- `TG2CLOUD_CLI_RESULT=CANCELLED`：用户取消，未执行计划内变更。
- `TG2CLOUD_CLI_BASE_HTTPS=OK`：基础服务及 VPS 本机 HTTPS 检查通过；不是公网或云盘验收结论。
- `TG2CLOUD_CLI_WEBDAV=NOT_RUN/OK`：独立写入验收的实际结果。
- `TG2CLOUD_CLI_RESULT=FAILED/INTERRUPTED`：停止后续操作；请核对备份、回退及当前实例状态，不假定已恢复。

无参数的统一菜单可按名称进入“卸载当前实例”，但核心安装器没有 `--uninstall` 参数，`manage.sh` 也没有 `uninstall` 子命令；菜单复用独立的[卸载核心](UNINSTALL.md)，不在升级流程中删除业务数据。不要用不存在的参数、手工删除目录或卸载来解决升级问题。其他项目或身份未知的资源不在受管卸载范围，不能用卸载绕过升级保护。

## 停止并移除容器（保留数据，不是完整卸载）

标准安装目录下，可以在 VPS 上用下面的命令停止并移除所选 Edition 的 Compose 容器及项目网络。先确认没有进行中的传输，并做好必要备份；执行一条对应命令即可，不必同时移除两个 Edition：

```bash
# CloudDrive2
cd /opt/tg2cloud-clouddrive2 && docker compose down

# OpenList
cd /opt/tg2cloud-openlist && docker compose down
```

这里不使用 `--volumes`、`--rmi`、`--remove-orphans` 或目录删除命令。标准 TG2Cloud 的持久化数据使用宿主机目录挂载，`.env`、Session、SQLite、下载、云网关配置与备份仍保留；Docker 引擎和另一 Edition 不会由这两条标准项目命令卸载。`down` 的范围见 [Docker 官方说明](https://docs.docker.com/reference/cli/docker/compose/down/)。

**这不是完整的一键卸载**：共享 Nginx/Certbot、证书和已保存 HTTPS 路由仍存在，本节两条命令也不会移除独立 LAN 入口。需要统一移除受管资源与入口时，使用 [统一卸载向导](UNINSTALL.md)。当前主分支及在线增强版默认双重确认后清理所选数据与可识别备份，保留数据请明确加 `--keep-data`；不卸载系统 Docker / Nginx。用户已反馈原保留数据卸载在其 VPS 通过；完整清理仍待新的实机验证，在线只固定到通过 CI 的源码，不修改历史 Tag 或发布资产。请先只读预检，把必要备份保存到清理目录之外。

## 验证与验收范围

自动检查、历史用户反馈和本次实际业务验收分别记录。新安装、保留配置升级、WebDAV、真实 Telegram 转存、外部网络、续期及回退都要核对自己的环境；当前 CI、资产和待验收清单见[发布记录](development/V157-ACCEPTANCE.md)。

## 参数、升级后检查与下一步

v1.4.4 源码在确认执行后增加日志分类、逐项结果摘要与一次只读业务就绪观察，原命令退出码、成功标记、WebDAV 确认和真实转存人工验收边界不变。旧 v1.4.3 入口及工具不含新增反馈，须升级为 v1.4.4 匹配的离线工具后才生效；完整用法见[安装日志与结果摘要](OPERATIONS.md#安装日志与结果摘要v144)。不重复调整已确认菜单，不改预算、配置、数据库或后端提交策略。

v1.4.2 提供[复用已有 Docker Nginx](DOCKER-NGINX.md)，由只读检测、明确授权和持久化条件决定是否接入，不停止原 Nginx、不增加第二层代理。新参数 `--proxy-mode`、`--nginx-container`、`--authorize-proxy` 的实际用法及支持边界见专题。原有 managed 实例不会自动切换。

| 参数／入口 | 用途 | 会不会修改实例 |
| --- | --- | --- |
| 无参数入口 | 编号选择 Edition，新装或进入已有实例菜单。 | 所选操作另行确认。 |
| `--edition clouddrive2`／`openlist` | 指定安装／升级对象。 | 展示计划并确认后执行。 |
| `--edition both` | 只用于两套完整已有实例。 | 确认所选计划后依次执行，不是一起回滚的事务。 |
| `--check` | 只读身份、版本、容量与已有 HTTPS 检查。 | 不升级；仍下载公开核验源码并占用临时空间。 |
| `--configure-https` | 显式续做／修复 HTTPS，已有域名不隐式更换。 | 确认后可能重载／重建共享代理。 |
| `--verify` | 使用现有配置执行 WebDAV 写入验收。 | 二次确认后创建并清理测试文件。 |
| `--show-credentials` | 私有终端逐项查看已保存凭据。 | 不升级／改密，不能与其他操作标志混用。 |
| `--install-dir /opt/自定义目录` | 单 Edition 的受支持安装／识别位置。 | 不搬迁数据；与其他受管路径重叠或身份不符会拒绝。 |

升级完成后核对：实际版本为目标正式版，Bot healthy 且不重启循环；配置、任务与 Session 保留；管理页在本机和外部网络均可访问；再用自己的小文件完成转存。后续再验证大文件、取消／恢复和家庭权限，不把一次正常转存写成全部场景通过。本次已执行范围见 [v1.3.3 记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/V133-ACCEPTANCE.md)。

完整字段和数据位置见[配置参考](CONFIGURATION.md)，独立备份见[备份与恢复预检](BACKUP-RESTORE.md)，命名规则见[命名指南](NAMING.md)，常见异常见 [FAQ](FAQ.md)。
