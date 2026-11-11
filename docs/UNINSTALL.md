# TG2Cloud 卸载指南

通过 `tg2cloud` 菜单卸载当前 Edition，或使用对应安装入口进入已有实例管理。卸载前先做范围预检并备份；**默认完整清理会在确认后删除所选实例的配置、数据库、Session、下载及可识别备份**，需要保留时明确使用 `--keep-data`。

只清理核验属于 TG2Cloud 的所选资源，不删除云端文件，不卸载系统 Docker / Nginx，不接管其他项目或独立 Compose。另一 Edition、共享代理和外部 WebDAV 的依赖必须先处理。完整卸载不等于还原整个 Linux 系统。

当前在线入口固定辅助 A `60862325931197915ea8058261cca0f5f74599b3`；不另设卸载 Shell 下载命令。核验依据见[当前发布记录](development/V1510-ACCEPTANCE.md)。

## v1.3.2 统一菜单与最后实例清理

v1.4.2 的[外部 Docker Nginx 模式](DOCKER-NGINX.md)有额外保护：未恢复的事务阻止卸载；只删除所选 Edition 专属站点，绝不停止或删除外部 Nginx／Compose／网络。最后路由移除后撤销本功能续期任务，但默认保留外部证书、私密恢复状态及离线维护命令；不会套用下文 managed 的整目录清理。旧 v1.4.1 工具不支持 schema 3。

公网／内网安装入口不带参数时，可进入已安装 Edition 的管理菜单。当前选择 **14. 卸载当前实例**，复用同一卸载核心、依赖保护和删除确认，仅作用于所选 Edition，不会自动选择 all。另一 Edition 的容器和数据继续保留，仍使用的共享路由受到保护。

历史菜单编号见[历史维护说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-IMPROVEMENTS.md)。操作前始终核对菜单文字和当前 Edition，不按旧教程盲输编号。

最后一套默认完整清理后，重新核对 Docker、两个 Edition（包括停止/部分状态）、保留数据/备份、LAN 与附加路由、挂载和管理代码归属；无依赖时删除受管 `/usr/local/bin/tg2cloud` 及 `/opt/tg2cloud-cli` 中全部已核验代码，随后退出菜单。`--keep-data`、保留备份或其他实例仍在用时保留工具；未知同名命令/文件、忙碌或清理异常时不强删，返回 `TG2CLOUD_UNINSTALL_RESULT=PARTIAL` 和非零退出码，明确业务资源可能已移除而管理代码尚未确认清完，不自动重新安装。仅删除核验过的代码文件及空目录，不递归清空推算出的父路径。锁元数据保留以避免替换正在锁定的 inode，系统应用、镜像缓存和云端文件仍不删除。

v1.4.7 不再保留主分支的独立卸载脚本。命令缺失或损坏时，重新运行原 `install.sh`／`install-lan.sh`，选择已安装 Edition 后进入“卸载当前实例”，不要选择重新安装；若实例不完整而不能进入菜单，使用核验过的完整源码及下方 CLI 预检。历史 v1.4.6 脚本可在原 Tag 查看，不建议用旧工具覆盖新状态。旧主机须显式更新管理代码；本轮没有真实卸载验收。

## 在线一键入口

外部 WebDAV 安装后，先在外部管理菜单卸载附加入口，解除对应网关依赖，再主卸载；仅停用不解除依赖。v1.4.7 统一入口为 `tg2cloud` → 当前 Edition → **15. 外部 WebDAV → 7. 卸载外部 WebDAV**，历史 v1.4.6 尚无主菜单 15；既有 `tg2cloud-webdav uninstall --edition openlist`（或 `clouddrive2`）仍兼容。附加卸载不删除云端数据或人工原生账号，见[独立功能指南](external-webdav.md)。

源码的本地帮助入口为 `python3 scripts/run_source.py uninstall --help`，业务位于公共 `deployment/uninstall.py`。公网／内网在线 URL 不变，两个退役脚本的旧 main URL 不再提供；helper pin 已更新到 CI 验证的新布局提交；确认、归属检查、保留数据和共享资源保护不因目录整理改变。本轮未执行真实卸载。详见[Linux 重构说明](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/LINUX-REFACTOR.md)。

安装后运行统一管理命令，或先以显式子命令只读查看所有实例的清理范围：

```bash
tg2cloud uninstall --edition all --check
```

在菜单中选择 Edition → 14. 卸载当前实例；实际执行先展示范围，再等待默认 N 的确认及 `DELETE ALL …` 删除口令：

```bash
tg2cloud
```

## 本地源码运行

在目标 Linux 的 TG2Cloud 源码根目录中以 root 执行。要求 Debian / Ubuntu 原生 64 位用户态、Python 3.10+、Bash、本机默认 Docker；正式 v1.4.4 继续支持 AMD64 / ARM64，见[双架构与发布边界](ARCHITECTURES.md)。涉及 HTTPS 路由时需要现有 Docker Compose 及 `flock`，不会替你安装、升级、重启或卸载系统软件。

先只读查看范围：

```bash
python3 scripts/run_source.py uninstall --edition all --check
```

当前主分支及在线向导默认完整清理所选 TG2Cloud 实例及可识别备份。先核对范围，执行时还需输入删除口令：

```bash
python3 scripts/run_source.py uninstall --edition all
```

只卸载一个 Edition：

```bash
python3 scripts/run_source.py uninstall --edition clouddrive2
python3 scripts/run_source.py uninstall --edition openlist
```

不指定 `--edition` 时，向导询问卸载 `clouddrive2`、`openlist` 或 `all`。只读 `--check` 必须明确指定 Edition。实际执行前列出容器、网络、数据目录、备份目录和共享代理处理方式，先等待默认 **N** 的确认，再要求输入 `DELETE ALL all`；单 Edition 对应 `DELETE ALL clouddrive2` 或 `DELETE ALL openlist`。任一取消或不匹配均不执行卸载。没有 `--yes` 或无人值守强制删除。

## 清理模式

默认模式等同 `--purge-all`，包括配置、Session、SQLite、下载、日志、云网关授权配置以及所选 Edition 可识别的历史备份。没有其他 HTTPS 路由、另一 Edition 容器或保留实例目录时，也删除共享代理配置、证书和可识别的共享代理备份。**先把需要保留的备份复制到这些清理目录之外；这不是恢复操作，删除后不能靠原目录中的备份回退。**

```bash
python3 scripts/run_source.py uninstall --edition all --purge-all --check
python3 scripts/run_source.py uninstall --edition all --purge-all
```

只移除运行资源、保留配置和数据时，必须明确选择 `--keep-data`：

```bash
python3 scripts/run_source.py uninstall --edition all --keep-data --check
python3 scripts/run_source.py uninstall --edition all --keep-data
```

兼容原 `--purge-data`：删除实例数据，但保留历史备份：

```bash
python3 scripts/run_source.py uninstall --edition all --purge-data --check
python3 scripts/run_source.py uninstall --edition all --purge-data
```

`--purge-data` 仍使用 `DELETE all` / `DELETE clouddrive2` / `DELETE openlist`，与会删除备份的 `DELETE ALL …` 区分。三个模式互斥。

| 项目 | 默认 / `--purge-all` | `--purge-data` | `--keep-data` |
| --- | --- | --- | --- |
| 所选 Bot、云网关容器 | 停止并移除 | 同左 | 同左 |
| 所选项目网络 | 无外部连接且归属正确时移除 | 同左 | 同左 |
| 所选 HTTPS 路由 / LAN 容器与入口配置 | 移除；另一 Edition 路由保留 | 同左 | 同左 |
| TG2Cloud 共享 Nginx / Certbot 容器 | 没有剩余 HTTPS 路由时移除 | 同左 | 同左 |
| `.env`、Session、SQLite、下载、日志、云网关账号授权配置 | 删除所选标准实例目录 | 同左 | 保留 |
| 共享代理配置、证书私钥与日志 | 无剩余路由、其他 Edition 容器/保留目录时删除 | 同左 | 保留 |
| Edition 历史备份 | 删除所选可识别备份目录 | 保留 | 保留 |
| 共享代理历史备份 | 无剩余路由、其他 Edition 容器/保留目录时删除 | 保留 | 保留 |
| Docker 镜像缓存 / CLI 与代理锁元数据 | 保留 | 保留 | 保留 |
| 系统 Docker、Nginx、其他容器、旧 TG115、云端已有文件 | 不操作 | 不操作 | 不操作 |

标准实例目录仅为 `/opt/tg2cloud-clouddrive2` 和 `/opt/tg2cloud-openlist`。自定义目录、同名外部容器、额外服务、未知挂载或使用中的网络都会停止，不通过文件名前缀猜测归属。标准部署使用宿主机 bind mount，没有需要删除的命名卷；不会清理其他 Docker 卷或使用全局 `prune`。

项目网络为 `tg2cloud-clouddrive2-net`、`tg2cloud-openlist-net`；共享代理的 Certbot 使用 `tg2cloud-proxy_default`，仅在没有剩余 HTTPS 路由且没有外部容器连接时一起移除。Nginx 和 LAN 入口使用 host 网络，绝不删除 Docker 的 `host`、`bridge`、`none` 网络。

共享代理历史备份在 `/opt/tg2cloud-proxy-backups`，Edition 备份在各自 `/opt/tg2cloud-<edition>-backups`。只识别现有工具生成的普通文件名及私密归属；遇到手工文件、子目录、链接、外部引用或挂载点即停止，不读取备份中的凭据。确认后备份清单或元数据变化也停止。备份可能包含凭据或证书私钥；保留不表示可以公开上传。锁文件为并发协调所需的少量元数据，不是仍在运行的服务；卸载中不会删掉正在持有的锁再创建新 inode。

“完整清理”是清除上述可验证的 TG2Cloud 实例数据与备份，**不等于把 VPS 逐字节还原到安装前**：安装 / 升级过程中 APT 软件包的变化、Docker 镜像及构建缓存、系统日志、锁元数据，以及你在 Cloudflare 添加的 DNS 记录不会回滚。无法判断镜像 / 系统配置是否早已存在或被其他项目复用，因此不执行全局 prune，也不卸载系统软件。

## 安全与部分失败

- 先结束进行中的 Telegram / 云盘传输。停止容器最多等待 60 秒，超时后 Docker 可能终止进程，不能据此保证任务完成。
- 先核对 Compose 标签、安装目录、固定容器名称和挂载，再按不可变容器 / 网络 ID 移除。确认期间资源变化时停止；不执行手改 Compose 的 `down --remove-orphans`。
- 移除单个 HTTPS 路由复用现有事务和剩余路由自检。另一 Edition 的自检失败时恢复原路由，并在移除 Bot / 云网关前停止。
- CloudDrive2 数据目录可能包含真实云盘 FUSE 挂载。数据删除预检和删除前都会检查挂载；发现挂载即拒绝递归删除，也不会执行强制 / lazy 卸载。可先明确使用 `--keep-data` 移除运行资源，再确认挂载已释放后重新预检完整清理。仅去掉 `--purge-data` 已不再表示保留数据。
- 不删除云端文件，不读取 / 显示 `.env`、`rclone.conf`、密码或容器环境变量；异常原始输出不回显。
- 与一键安装 / 升级使用相同 Edition 锁，并使用共享 HTTPS 事务锁。**不要在另一终端并发操作相同实例，也不要使用无法协同锁的旧工具**。
- 失败、取消或连接中断可能部分完成。不会自动重装、删除更多数据或假装回滚全部容器；重新运行 `--check` 核对，确认剩余范围后再执行。
- `--keep-data` 保留的安装目录不能当作全新目录被安装器覆盖；如需全新安装，可在明确备份后使用本脚本清理可识别的标准残留，再运行安装向导。未知残留停止并要求人工核对。即使原容器已卸载，可识别的备份也可再次预检清理。

结果：`TG2CLOUD_UNINSTALL_CHECK=OK` 仅表示预检；`TG2CLOUD_UNINSTALL_RESULT=OK` 表示所选运行资源和路由的卸载后复检通过，数据 / 备份是否保留以计划为准。`CANCELLED` 不执行计划；`FAILED` / `INTERRUPTED` 不等于卸载完成。

## 执行前的选择清单

1. **只是升级？**不要卸载，用对应安装入口保留配置升级。
2. **只是暂时不转存？**用 Bot `/pause` 停止后续调度，或管理菜单明确停止 Bot；它们不是数据清理。
3. **暂时停止外部播放？**在外部 WebDAV 菜单选择“停用访问”（兼容 `tg2cloud-webdav disable`）；若要主卸载则必须先选择“卸载外部 WebDAV”，仅停用不解除依赖。
4. **想保留重装所需资料？**先另存完整私密备份，明确 `--keep-data` 的范围，不依赖即将删除的备份目录。
5. **确实完整清理？**逐项核对 Edition、目录、所有将删备份、挂载和删除口令，再确认默认完整模式。

## 完成后如何核对

按输出确认所选容器／网络与入口已移除，数据和备份是否保留与计划一致。若还有另一 Edition，核对其原 Bot、网关和管理入口未被误移除。最后实例的快捷命令清理还受依赖及归属保护，不因业务容器消失就保证工具一定删除。

`PARTIAL`、`FAILED`、`INTERRUPTED` 时先重新运行相同 Edition 的 `--check`，保留脱敏错误；不执行 `docker system prune`、递归删除 `/opt` 或强制卸载 FUSE。确认清理范围变化后才再次执行，不能假设中断自动撤销已删除对象。

备份清单和离机保存见[备份与恢复预检](BACKUP-RESTORE.md)，常见卸载问题见 [FAQ](FAQ.md#备份卸载与求助)。
