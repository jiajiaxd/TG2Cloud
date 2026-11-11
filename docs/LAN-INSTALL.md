# 局域网 / NAS 安装与升级

在运行服务的 Linux 主机上执行 `install-lan.sh`，填写该主机实际拥有的私有 IPv4；无需域名或证书。公网主机使用[VPS 入口](VPS-INSTALL.md)，自己维护容器的用户使用[Compose 教程](COMPOSE.md)。

本入口只在可信内网提供 HTTP 管理，不能转发到公网。已有实例按原部署方式升级；系统、Docker 和网关的实际要求见下文。安装后仍须独立验证局域网访问、WebDAV 写入和实际转存。

## 支持范围与边界

v1.4.4 源码在确认执行后补充内网安装／升级摘要、日志分级和一次只读业务就绪观察；公网 HTTPS 明确不适用，局域网其他设备访问和真实转存仍须人工验收。沿用原 WebDAV 确认，不新增写入或网络探测，不改内网模式和下面的支持范围。旧 v1.4.3 入口与工具不包含这些新增反馈，见[结果与验收说明](OPERATIONS.md#安装日志与结果摘要v144)。

当前源码入口为 `python3 scripts/run_source.py lan --help`；公共在线 URL 不变，helper pin 已更新到 CI 验证的新布局提交。CLI 与 VPS 入口共享部署模块，不导入另一个向导；内网 IP 收集和 HTTPS 边界不变。见[Linux 开发说明](development/DEVELOPMENT.md)。

- Debian/Ubuntu、64 位原生用户态、root、Python 3.10+、Bash、curl（在线入口）、iproute2、CA 证书、时区数据库及可交互终端。正式 v1.4.1 支持原生 AMD64 / ARM64；匹配稳定包和 helper 已发布，原生隔离 CI 通过，NAS 实机仍需独立验收，见[双架构说明](ARCHITECTURES.md)。
- 本机默认 rootful Docker Engine 28+、Compose v2；不支持远端 Docker、rootless 或外部 Compose 覆盖。Docker 尚未安装时，由原安装器在最终确认后安装；已安装的旧引擎需要人工升级，脚本不会为此重启 NAS 上的其他容器。
- CloudDrive2 仍需要 `/dev/fuse`，容量和磁盘保护沿用原安装器。容器权限、APT 依赖安装等原有要求不会因“内网模式”消失。
- 不承诺直接支持 DSM、QTS、Unraid、OpenWrt 或 Docker Desktop。原生 ARM64 不等于支持所有 ARM NAS 的厂商系统；可建立符合条件的 Debian/Ubuntu 虚拟机，填写**虚拟机自己的 IP**。
- 必须能连接 GitHub、Docker 镜像源、Telegram 和使用的云存储。内网安装不是离线安装。
- 只接受本机启用网卡上的 `10.x.x.x`、`172.16.x.x`—`172.31.x.x`、`192.168.x.x` 标准 IPv4。拒绝公网、回环、通配地址、域名、URL、端口和 Docker 自动桥接网卡；不自动猜测安装位置。

Docker 28 之前存在同一二层网络可访问回环发布端口的问题，故本入口设置独立最低版本要求。见 [Docker 官方端口发布说明](https://docs.docker.com/engine/network/port-publishing/)。

## 为什么保留回环后端

原安装器、网络修复和健康检查仍使用固定回环地址。内网脚本不修改它们，而是增加一个独立 Docker Nginx 管理入口：

```text
局域网浏览器
  → 手填内网 IP:固定端口（HTTP，独立 Nginx）
  → Linux 本机 127.0.0.1:固定端口
  → 原 CloudDrive2 / OpenList 网关
```

| Edition | 内网管理地址示例 | 后端仍保持 | 独立入口容器 |
| --- | --- | --- | --- |
| CloudDrive2 | `http://192.168.26.5:19798` | `127.0.0.1:19798` | `tg2cloud-lan-cd2` |
| OpenList | `http://192.168.26.5:5244` | `127.0.0.1:5244` | `tg2cloud-lan-openlist` |

Nginx 仅监听指定内网 IPv4，不监听 `0.0.0.0`、公网 IPv4 或 IPv6，不占用 80/443。它拒绝 `/dav`、`/dav/` 及大小写变体；Bot 的内部 WebDAV 地址不变。管理页使用 HTTP，账号、密码和云存储授权可能在局域网中以明文传输，**只适合可信内网**。

不要配置路由器公网端口转发或 UPnP，不要把管理入口放入公网反代。只绑定私有 IP 也不能防止人为路由、端口转发或不安全的共享网络。脚本不调整路由器、NAS 防火墙或宿主机 Docker daemon 配置。

## 在线一键向导（推荐）

v1.3.2 的默认交互采用新版中文提示：WebDAV 密码回车生成 8 位，新安装默认时区 `Asia/Shanghai`，账号根目录仍在后台设置；已有配置不改写。最终确认后安装离线 `tg2cloud` 菜单，保留内网模式与保存的 IP，不隐式转换到公网 HTTPS。旧主机须显式更新，不会自动获得新版菜单；也可从已审阅源码运行 `python3 scripts/run_source.py manage`，详见[本地管理说明](OPERATIONS.md#本地管理菜单)。原有显式参数和结果标记保持兼容。

新版不带参数时与公网入口共用 Edition 选择及管理菜单：未安装则确认进入对应 Edition 的内网安装向导；已有实例显示包含卸载的菜单，并按原已保存模式维护。无需另记卸载命令；v1.4.7 移除根目录独立卸载脚本，保留 `tg2cloud uninstall` 预检及原清理参数；命令缺失时可重新运行本内网入口，进入已安装 Edition 的管理菜单。最后一套默认完整卸载后，核验无依赖才清理 `tg2cloud` 和受管管理代码；另有实例或选择保留数据时不清理它们。

目标 Linux 能联网，并已具备上述运行条件时，以 root 执行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh)
```

无需预先下载完整项目。向导先选择 Edition，首次安装手工填写运行脚本的 Linux 内网 IPv4，再收集 Telegram 和专用 WebDAV 信息、检查容量并展示计划。最终确认默认 **N**；确认前不安装软件、不写入实例或内网模式记录。原 VPS 向导的域名/HTTPS 步骤不会出现在本入口中。

分别选择 CloudDrive2 或 OpenList：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh) --edition clouddrive2
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh) --edition openlist
```

首次只读预检需明确 Edition 和本机地址；例如：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh) --edition clouddrive2 --lan-ip 192.168.26.5 --check
```

示例 IP 必须换成自己的 Linux / 虚拟机地址，不能填写另一台设备的地址。后续升级复用已保存信息与 IP，不必重复输入。下载失败直接停止，不回退到 main/RC 或其他源；在线引导的私有临时源码目录退出时清理，不清理用户的运行数据。

## 从本地源码运行（备选）

先把经过审查、包含本入口的完整源码放到目标 Linux，在项目根目录运行。示例地址必须替换成实际运行脚本的 Linux 地址。

CloudDrive2 只读预检：

```bash
bash ./install-lan.sh --edition clouddrive2 --lan-ip 192.168.26.5 --check
```

安装 / 升级向导：

```bash
bash ./install-lan.sh --edition clouddrive2
```

首次安装会要求输入内网地址；也可以提前通过 `--lan-ip` 指定。向导随后收集 Telegram 和专用 WebDAV 信息、检查容量、展示 HTTP 风险和安装计划。最终确认默认 **N**：确认前不安装软件、不写入实例或内网模式记录。

首次 `--check` 使用默认 20GB 任务预算与 8GB 最低剩余空间，不收集秘密。v1.3.0 交互向导提供流式优先、均衡和手动预算，复用 VPS 推荐算法，执行前重新校验；已有实例升级保留原值。见[切换说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/SCRIPT-FIRST.md)。安装目录使用 Edition 的标准 `/opt` 路径，不提供自定义目录或迁移功能。

OpenList 对应命令：

```bash
bash ./install-lan.sh --edition openlist --lan-ip 192.168.26.5 --check
bash ./install-lan.sh --edition openlist
```

不要使用 `curl | bash` 或把秘密放入命令参数。密码通过私有终端隐藏读取；默认中文新装确认后会在后台建号步骤集中显示所需凭据，显式参数兼容流程与后续查看凭据仍逐项确认。凭据不写普通日志，不建议录屏。

下方维护示例使用本地 `bash ./install-lan.sh`；也可替换为上面的 `bash <(curl -fsSL …/install-lan.sh)` 在线入口，保留相同的 `--edition`、`--verify` 或 `--show-credentials` 参数。

## 已有实例与升级

只有同时满足下列条件，才自动生成保留配置的升级计划：

1. 由本脚本创建并具有完整、未修改的内网模式记录。
2. 原 Bot、网关、Compose 身份、数据挂载及实际运行代码核对通过。
3. 安装代码与对应正式 Release 一致，新 Release 没有改变云网关镜像 digest。
4. 已保存内网 IP 仍属于本机启用网卡，所选 Edition 没有 HTTPS 路由。

升级保留 `.env` 原始字节、Telegram Session、SQLite、下载和网关持久化数据，复用原安装器备份与有限回退。可能更新基础 APT 软件包，所选 Bot 可能短暂停止；不会主动升级已有 Docker 引擎。另一 Edition 不会被重启或修改。

最新版本且入口健康时，不重建、不重启。入口故障需要重新预检和明确确认，只恢复经核对的受管入口。当前版本高于 latest 时不降级。其他访问模式创建的实例、TG115、部分容器、外部同名容器、手改配置都停止，不自动接管；**不要用本脚本把已有 HTTPS 实例改成 HTTP**。

内网模式存放在 `/opt/tg2cloud-lan/<edition>/`，与原 `/opt/tg2cloud-clouddrive2`、`/opt/tg2cloud-openlist` 分开。升级复用已保存的 IP，不能用 `--lan-ip` 隐式换地址。建议预先设置 DHCP 地址保留或静态 IP；地址失效时停止并提示，不尝试切换到公网模式。

原 payload 备份不包含这个独立目录。备份运行实例时应另行保留对应内网模式目录；安装入口不提供内网模式转换或地址迁移。卸载由 [统一卸载入口](UNINSTALL.md) 处理，包含所选 LAN 管理容器与入口配置。当前主分支及在线完整清理会在双重确认后删除所选业务数据及可识别备份，需要保留时明确加 `--keep-data`。入口固定已核验辅助代码，不并发操作同一实例；验收应以实际版本为准。

## 管理页、WebDAV 与实际转存分别验收

本机入口成功标记：

```text
TG2CLOUD_LAN_BASE=OK；TG2CLOUD_LAN_ENTRY=OK；HTTPS=NOT_APPLICABLE
```

这只表示基础服务、指定地址上的本机管理页和 `/dav` 阻断通过，**不等同于另一台内网电脑可访问、WebDAV 写入通过或云盘转存通过**。`--check` 不安装、不升级、不写测试文件；已有入口故障时不会给出通过标记。

从另一台局域网电脑访问管理页，配置自己的云存储，再建立与 Bot 保存信息一致的专用 WebDAV 用户。云盘 Token、Cookie 和 OAuth 仍只在自己的 CloudDrive2/OpenList 中填写，脚本不收集。

两版后台用户、目录与验收阶段见[存储网关指南](STORAGE.md)；安装后的命令与实际转存见 [Bot 使用指南](BOT-USAGE.md)。不需要为了这些后台配置重新安装。

向导在基础安装与内网入口检查通过后、显示凭据和询问 WebDAV 写入验收之前，再次给出完整管理地址，避免被前面的镜像构建日志淹没。例如：

```text
CloudDrive2 内网管理页：http://192.168.26.5:19798
请先用局域网电脑的浏览器打开上面的地址，配置云存储，并创建与保存凭据一致的专用 WebDAV 用户；完成后再确认写入验收。
```

OpenList 对应端口是 `5244`，地址采用本人输入并通过检查的 IP。尚未完成管理页配置时，写入验收选择 **N**；之后可单独运行在线验收，不需要重新安装：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh) --edition clouddrive2 --verify
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh) --edition openlist --verify
```

另行请求 WebDAV 写入验收：

```bash
bash ./install-lan.sh --edition clouddrive2 --verify
bash ./install-lan.sh --edition openlist --verify
```

即使指定了 `--verify`，也会再次说明随机测试文件的创建与清理并要求确认，失败不自动重复。真实 Telegram 转存还需发送小文件，并在云存储官方客户端核对最终文件。

单独查看已保存凭据：

```bash
bash ./install-lan.sh --edition clouddrive2 --show-credentials
bash ./install-lan.sh --edition openlist --show-credentials
```

每项默认不显示，不安装、不升级、不改密；不能与 `--check` 或 `--verify` 组合。OpenList 显示的是保存的初始化管理员密码，不保证等于后来在管理页改过的当前密码。

## 失败后如何处理

- **IP 不属于本机或固定端口占用**：核对虚拟机地址、DHCP 与占用服务，不自动改端口或停止外部服务。
- **基础安装失败**：核对原安装器脱敏日志、备份和回退结果。部分实例不会自动重装，不要删除数据目录求“重试”。
- **基础安装成功但入口失败**：模式记录与数据保留；重新运行本入口进行预检及确认，续做入口，不当作首次安装覆盖数据。
- **取消、中断、掉线或断电**：不能假定已经完全回退。重新只读检查，确认容器、版本和数据状态；SIGKILL/断电不保证自动恢复。
- **旧 Docker、非受管实例或手改配置**：人工核对，不提供强制接管参数。

已收到的 CloudDrive2 实机日志显示内网入口及 WebDAV 的认证、列目录、写入、大小复验、改名和清理均通过。这不替代不同 NAS 系统、OpenList、跨版本升级与回退、外部浏览器或真实 Telegram 云盘转存验收；其他项目仍需单独检查。

## 安装后检查与长期使用

1. 从另一台可信内网设备打开实际 IP＋端口；Linux 本机能打开不能证明跨设备可达。
2. 在管理页挂载云存储并创建 Bot 专用用户，再显式确认 WebDAV 写入验收。
3. 向 Bot 发送自己的小文件，在网关及云存储客户端核对，不把 `HTTPS=NOT_APPLICABLE` 当成文件转存结果。
4. 使用 `tg2cloud` 维护、升级和管理家人；菜单保留已记录 LAN 模式，不隐式申请域名或切公网。
5. 长期固定主机 IP，单独备份 LAN 状态和业务资料。不能仅复制业务升级包就认为内网入口可恢复。

当前没有一键更换 LAN IP 或 LAN→公网的转换命令。地址变化、身份记录损坏或希望改为 HTTPS 时先保留数据，审阅独立迁移方案，不手工改状态去绕过检查。外部 WebDAV 仍要求独立公网 HTTPS／ACME 条件，内网安装成功不表示该附加功能也能自动在家庭网络签证书。

字段与目录见[配置参考](CONFIGURATION.md)，备份见[备份指南](BACKUP-RESTORE.md)，常见 NAS、网络与容量问题见 [FAQ](FAQ.md)。
