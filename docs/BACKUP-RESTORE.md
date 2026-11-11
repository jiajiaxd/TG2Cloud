# 备份与恢复预检

v1.5.3 起，全新安装使用 `data/tg2cloud.db`；已有实例若只有 `data/tg115.db`，继续使用原文件，保留任务、授权和恢复记录，不自动改名或创建空库。若两个文件并存会停止并要求核对，不自动合并。备份／隔离恢复识别两种文件名，但每份实例只能有一个业务数据库。不要手动移动正在使用的 SQLite 文件或删除旁文件。


当前业务数据库使用 schema 4，较早版本升级时执行事务迁移。回退需要匹配旧程序和升级前数据库快照，不能只降级镜像。见[迁移与回退说明](FEATURE-ENHANCEMENTS.md)。

本页集中解释备份覆盖、现有工具及隔离恢复。没有一键覆盖生产数据的 Restore 命令；备份可读取不等于服务已恢复。任务级重试／冲突处理见[恢复指南](RECOVERY.md)，日常菜单见[运维指南](OPERATIONS.md)。



## 监听数据与独立 Session

新增来源、计划和反馈纳入原业务库一致性备份；新增的 `data/listener/personal.session` 须按私密 Session 单独保护，菜单实例快照与离线实例包在该文件存在时一并校验打包。停用监听并等待锁释放后复制，活跃旁文件不接受。数据库迁移与匹配快照回退见[监听指南](LISTENING.md)。

## 先确定要保护什么

| 资料 | 为什么要保留 | 一般位置 |
| --- | --- | --- |
| 程序版本、Compose、镜像身份 | 用匹配代码解释配置和 DB，不能仅依赖可变镜像标签。 | 实例程序目录、升级记录与回退点。 |
| `.env`、rclone 配置 | Bot 接入和目的端配置，包含秘密。 | 实例 `.env`、`config/`。 |
| 业务 SQLite | 任务、去重、验证、恢复保护及家庭授权。 | `data/tg2cloud.db`。 |
| Telegram Session | 保留已有登录／授权状态。 | `data/bot.session`。 |
| 暂存和失败保留文件 | 可能是任务唯一完整本地副本。 | `downloads/`。 |
| 网关配置与授权 | 云存储挂载、账号和访问权限。 | `clouddrive/config/` 或 `openlist/data/`。 |
| 公网代理与证书 | 路由、ACME 账号、续期、认证哈希。 | `/opt/tg2cloud-proxy`。 |
| LAN 模式／外部 WebDAV | 与业务独立，需分别保留。 | `/opt/tg2cloud-lan`、`/opt/tg2cloud-webdav`。 |

不要把 CloudDrive2 的 FUSE 挂载当普通本地目录递归打包。备份网关配置不等于备份云端文件；云端数据仍由你自己的存储服务保护。

## 现有备份的实际覆盖

| 类型 | 覆盖 | 不要假设包含 |
| --- | --- | --- |
| CloudDrive2 升级回退点 | 程序／配置、可用时的一致性业务 DB 快照。 | 完整 Session、网关授权、下载、HTTPS。 |
| OpenList 业务备份 | 程序配置、业务 DB 快照、OpenList 状态。 | Telegram Session、下载、共享 HTTPS。 |
| 共享代理备份 | 两版管理及附加路由、Nginx／Compose、认证哈希、证书／ACME 和续期记录。 | Bot DB、Session、网关授权、附加功能全部私密元数据。 |
| 离线快照包 | `.env`、Compose、业务 DB、Session、`config/` 及所选网关配置。 | 程序代码、下载、日志、HTTPS、LAN／附加状态、云端文件。 |

业务回退点、代理备份、离线快照不能互相代替。备份清单中的 SHA256 是完整性校验，不是来源数字签名。

## 日常菜单能做什么

v1.4.5 按“实例备份／共享代理”分组，主菜单仍为 13。以下按新版序号操作；旧 v1.4.4 的实例 6／7 对应新 2／3，旧代理 2／3／4／5 对应新 4／5／6／7。须显式升级离线工具，不根据旧序号盲选。所有停服、私密范围和清理确认不变，详见下方菜单与操作范围。

v1.4.3 新增实例快照导出／隔离预检，需确认所选 Bot 和网关的维护窗口；归档不含 downloads、共享 HTTPS 或附加状态，恢复失败记录不会自动重放。详见[实例快照](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-IMPROVEMENTS.md#2-实例快照导出)。下方原有代理备份菜单继续保留。

运行 `tg2cloud`，选择 Edition → **13. 数据备份管理**（旧 v1.4.3 主菜单为 7；v1.4.4 起主菜单为 13）：

1. 查看历史备份：列出受管实例回退点，不代表自动验证业务内容。
2. 创建实例快照：确认维护窗口后保存限定配置、数据库、Session 和网关配置，不包含下载、共享代理或云端文件。
3. 校验实例快照：检查归档、版本与资源，只在独立目录解包，不覆盖生产数据。
4. 创建代理备份：含其他 Edition 的共享配置和证书，不停止 Bot。
5. 查看代理备份：查看可识别记录及完整性。
6. 校验代理备份：只在新私密目录演练，不替换运行数据。
7. 清理代理备份：先预览、再确认；固定保留最近 5 份有效备份。

v1.4.3 的实例快照只覆盖上面明确的范围，不是包含全部下载／云端文件的完整副本。OpenList 的旧 `manage.sh backup` 也会短暂停止网关与 Bot，不能当成无影响操作。业务备份与旧备份清理命令差异见[实例脚本](OPERATIONS.md#现有每实例脚本继续保留)。

默认完整卸载会删除所选实例和可识别备份。重要备份必须另存于[卸载清理范围](UNINSTALL.md#清理模式)之外，并保护私密离机副本。

## 隔离数据库启动与恢复演练（v1.4.5）

菜单中的“校验实例快照”仍只验证归档、数据库和兼容性，不悄悄启动迁移。需要进一步核对当前代码能否打开／迁移数据库并执行重启恢复时，使用[隔离演练工具](https://github.com/LuoPoJunZi/TG2Cloud/blob/c7e0b4b7497fbfa258c752dcff4666d1e2011eae/docs/development/MAINTENANCE-NEXT.md#2-隔离数据库恢复演练)，只操作已验证的临时副本。

工具不加载 Session、环境文件或归档内代码，不启动第二个 Bot／网关，不访问数据库中记录的生产文件路径。快照不含 downloads，演练按缺失本地副本建模；成功也不等于实际服务恢复、授权有效或云端文件可读。正式恢复仍须保护当前实例，匹配代码与数据库，单独验收。

v1.4.5 预检拒绝声明范围之外的文件和 SQLite `-wal`／`-shm`／`-journal` 旁文件；失败或普通中断关闭数据库句柄并清理自己的临时副本，不删除源归档或运行数据。

## 一致性数据库与 Session

运行中的 SQLite 可能有 WAL。不要只复制主 `.db`、删除 `-wal`，或把一次普通文件复制称为一致性备份。

部署流程使用 SQLite backup 接口生成快照并执行 `quick_check`。Session 本身也可能使用 SQLite，不能以“只是登录文件”为由忽略写入一致性。业务库备份成功不表示同时备份了 Session 和网关状态。

如需离线快照，先安排维护窗口、等待活动任务结束并停止会修改所选 DB／Session／网关状态的服务，再制作独立静止副本。仅 `/pause` 不会停止当前传输，也不是冻结数据库的操作。不要启动第二个同 Token 的 Bot 来验证备份。

## 离线快照工具

仅适用于标准布局、用户已准备的静止副本。推荐使用与 Bot 一致的 Python 3.12 环境及匹配版本源码；模块为 `tg2cloud.persistence.bundle`，不需要 Telethon。

从源码根目录查看帮助，不操作实例：

```bash
PYTHONPATH=src python3 -m tg2cloud.persistence.bundle --help
```

静止副本的最小结构：

```text
/srv/private-snapshots/openlist/
  .env
  docker-compose.yml
  data/tg2cloud.db
  data/bot.session
  config/                 需要实际配置文件，不能只是空目录
  openlist/data/          需要实际网关状态文件
```

CloudDrive2 将网关目录改为 `clouddrive/config/`，其余相同。不得含链接、越界路径或需要读取云盘挂载的条目。

以下只是**已经准备好私密目录与静止副本后**的工具用法，不是自动制作运行实例完整备份的命令。路径、Edition 和版本必须替换成实际值，归档必须是尚不存在的新文件：

```bash
PYTHONPATH=src python3 -m tg2cloud.persistence.bundle pack /srv/private-backups/openlist-1.3.3.tar.gz --snapshot /srv/private-snapshots/openlist --edition openlist --version 1.3.3 --offline-confirmed
PYTHONPATH=src python3 -m tg2cloud.persistence.bundle check /srv/private-backups/openlist-1.3.3.tar.gz --scratch /srv/private-restore-check --edition openlist --version 1.3.3
```

`--snapshot` 是副本，不是运行中的 `/opt/tg2cloud-openlist`；`--scratch` 是已存在的私密测试父目录，不是生产实例目录。`pack --version` 写快照来源版本，`check --version` 指拟恢复目标版本，不能为通过检查随意填写。

已安装镜像内继续保留 `python -m app.backup_bundle` 兼容入口，但主仓库根目录已经没有旧 `app/`。不要在新 checkout 中直接照搬旧 `app.*` 命令。

### 检查结果与上限

- 包内记录 Edition、版本、范围、大小和逐文件 SHA256；DB／Session 执行完整性检查。
- 拒绝跨 Edition、目标低于来源、跨主版本、清单缺项／重复、链接／穿越及摘要不匹配。
- 默认最多 2 GiB／20,000 文件，隔离预检另需至少 256 MiB 余量。大网关状态需另行设计备份，不能关闭检查假装完整。
- 归档 `0600`，隔离目录 `0700`。检查时创建自己的隔离子目录，结束后清理该子目录，不覆盖运行文件。
- `TG2CLOUD_BACKUP_PREFLIGHT=OK` 仅说明结构、容量及 DB 检查通过，不证明网关可启动、Session 可登录或实际文件可读。

## 恢复前的人工检查

可先按上面的[隔离数据库演练](#隔离数据库启动与恢复演练v145)核对临时副本，但演练通过不代替下列生产恢复前检查；旧 v1.4.4 工具需升级，不直接调用归档内的未知程序。

1. 保留当前可用实例，另做备份，不先删除现有数据库。
2. 核对来源版本、目标代码、网关镜像／数据库兼容性、固定端口及挂载关系。
3. 确认目标磁盘和 inode 充足，恢复文件权限与运行 UID/GID 正确。
4. 一致保护 DB、Session、配置、下载及远端恢复保护记录；不要拼接不同时间点的状态。
5. 先在隔离主机验证，确保原 Bot 不会同时处理同一 Token；需要真实接入时另行授权并安排维护窗口。
6. 独立恢复网关、LAN／HTTPS、外部 WebDAV 元数据和认证资源；哈希可读取不表示后台密码已恢复。
7. 验证任务历史／去重、授权、读目录、真实测试文件及公网／内网访问，再决定是否切换。

旧程序可能不理解新任务的保护记录或代理 schema。不得直接把旧镜像挂上新 DB 继续跑任务，也不要手工降低状态版本。

## 失败与回退

快照损坏、清单缺项或 DB 检查失败时保留原始材料，停止生产恢复。校验值一致仍不能证明备份可信，应只使用自己控制的来源。

部署中的候选预检或健康检查失败，会尝试既有有限回退；回退日志不是灾难恢复成功证明。以实际容器、代码／镜像身份、配置字节、DB 一致性和后续转存结果核对，详见[升级说明](VPS-INSTALL.md#已有实例升级)。

恢复涉及真实数据时不要直接执行网上的 `tar` 覆盖、`docker system prune`、数据库重建或目录删除命令。本项目当前没有保证生产恢复原子性的自动按钮。
