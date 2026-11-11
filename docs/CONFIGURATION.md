# 配置与运行目录参考

v1.5.3 起，全新安装使用 `data/tg2cloud.db`；已有实例若只有 `data/tg115.db`，继续使用原文件，保留任务、授权和恢复记录，不自动改名或创建空库。若两个文件并存会停止并要求核对，不自动合并。备份／隔离恢复识别两种文件名，但每份实例只能有一个业务数据库。不要手动移动正在使用的 SQLite 文件或删除旁文件。


配置由 Linux 向导生成，升级默认保留已有值；本页用于理解和核对，不要求手写一份全新 `.env`。NAT 公网地址确认只保存在当前向导内存。变更前先看[运维流程](OPERATIONS.md#修改运行配置)和[备份指南](BACKUP-RESTORE.md)。

## 监听配置

监听默认关闭。来源、计划和可选设置在业务数据库中，当前版本为 schema 4。个人 Session 位于 `data/listener/personal.session`，与 Bot Session 分开。回退必须匹配代码和快照，操作见[监听指南](LISTENING.md)。

## 接入信息与账号不要混用

| 项目 | 用途 |
| --- | --- |
| Telegram API ID／API Hash | Telethon 的应用接入信息，Hash 属于秘密。 |
| Bot Token | 标识运行的 Bot；不要同时在两套实例使用同一 Token。 |
| `ALLOWED_USER_ID` | 安装时唯一管理员的数字 ID，不是用户名或 Bot ID。 |
| Bot 专用 WebDAV 账号 | Bot 在网关中写文件；不是网关管理员／会员账号。 |
| 外部 WebDAV 账号 | 可选附加功能的独立只读账号；不复用 Bot 或管理员。 |

安装只接受一个管理员 ID。家人通过[安装后用户管理](FAMILY-SHARING.md)授权，不能用逗号、空格或多个 ID 填充 `ALLOWED_USER_ID`；不要通过改这个字段迁移管理员。

## 标准宿主机布局

两个 Edition 分别使用 `/opt/tg2cloud-clouddrive2` 和 `/opt/tg2cloud-openlist`。下面的 `实例目录` 表示其中一套，不是仓库源码目录：

```text
实例目录/
  .env                  私密运行配置
  docker-compose.yml    该实例的容器编排
  Dockerfile / app/     已安装的公开程序及兼容入口
  manage.sh             该实例的历史维护脚本
  data/
    tg2cloud.db            业务数据库，新安装的业务数据库
    bot.session         Telegram Session，继续保留
  config/rclone/        rclone 配置
  downloads/            本地暂存与失败保留文件
  logs/                 Bot 日志
  clouddrive/config/    仅 CloudDrive2：网关配置及授权状态
  clouddrive/mounts/    仅 CloudDrive2：挂载位置，不应递归清理
  openlist/data/        仅 OpenList：网关持久化状态
```

可变数据不在 Git 仓库中。`tg2cloud.db` 是当前业务数据库名称，不表示安装了旧 TG115，不手工重命名。

| 独立目录 | 职责 |
| --- | --- |
| `/opt/tg2cloud-<edition>-backups` | 所选 Edition 的升级回退点。 |
| `/opt/tg2cloud-proxy`、`/opt/tg2cloud-proxy-backups` | 共享 HTTPS 路由、证书和独立备份。 |
| `/opt/tg2cloud-lan/<edition>` | 可信内网入口模式和配置；不在业务回退包内。 |
| `/opt/tg2cloud-cli` | 离线主管理工具及来源信息。 |
| `/opt/tg2cloud-webdav` | 可选外部 WebDAV 的私密配置和离线工具。 |

自定义目录只在支持它的命令并通过身份核对时使用，不代表卸载或 LAN 入口也支持任意目录。

## 核心配置项

`*_B64` 保存 UTF-8 的 Base64 编码，不是加密；不要解码后贴到聊天、Issue 或日志。表格只给字段名，不提供可误用的真实配置值。

| 字段 | 含义／约束 |
| --- | --- |
| `TELEGRAM_API_ID` | 大于零的应用 ID。 |
| `TELEGRAM_API_HASH_B64`、`BOT_TOKEN_B64` | 向导隐藏输入后编码保存，必须保密。 |
| `ALLOWED_USER_ID` | 唯一初始管理员，安装时是大于零的整数。 |
| `TG2CLOUD_STORAGE_BACKEND` | `clouddrive2` 或 `openlist`，与实例身份一致。 |
| `TG2CLOUD_RCLONE_REMOTE_NAME` | 对应 `cd2` 或 `openlist`，不任意改名。 |
| `WEBDAV_URL_B64` | Bot 在 Docker 网络中访问的网关地址，不是公网管理域名。 |
| `WEBDAV_USERNAME_B64`、`WEBDAV_PASSWORD_B64` | 与网关后台的 Bot 专用账号一致。 |
| `WEBDAV_TARGET_PATH_B64` | 相对于该账号根目录的子目录，允许空值。 |
| `LOCAL_TEMP_BUDGET_GB` | Bot 任务额度；手动方案默认 20，推荐方案可能更小。 |
| `MIN_FREE_DISK_GB` | 默认 8；首次向导不允许低于 8。不是网盘剩余容量。 |
| `TZ` | 新装固定默认 `Asia/Shanghai`；升级保留原配置，影响界面时间和每周计数边界。 |
| `OPENLIST_ADMIN_PASSWORD` | OpenList 初始化值；后台改密后不保证等于当前管理员密码。 |

Bot 账号根目录在网关后台配置。`.env` 中的相对子目录不能告诉程序完整的网关逻辑绝对路径；具体组合见[存储目录说明](STORAGE.md#根目录与子目录只组合一次)。

## 调度与资源参数

以下是当前 `Settings.from_env()` 的默认值，不建议为提高速度一次改动多项。它们不是固定并发数，实际放行受 CPU、内存、磁盘、目的端与错误率共同约束。

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `CONTROL_INTERVAL_SECONDS` | `3` | 调度控制周期，最小 1 秒。 |
| `CPU_TARGET_LOW_PERCENT` | `60` | 较低 CPU 目标阈值。 |
| `CPU_TARGET_HIGH_PERCENT` | `80` | 较高 CPU 目标阈值。 |
| `CPU_PRESSURE_PERCENT` | `90` | CPU 压力阈值；要求 0 < LOW < HIGH < PRESSURE ≤ 100。 |
| `MEMORY_SOFT_MIN_MB` | `1024` | 内存软安全线。 |
| `MEMORY_HARD_MIN_MB` | `512` | 内存硬安全线，须为正且不高于软线。 |
| `RAMP_UP_STEP` | `1` | 逐步扩大放行窗口的步长。 |
| `RAMP_DOWN_FACTOR` | `0.5` | 压力下降速比例；有效范围按代码限制在 0.1～0.9。 |
| `MAX_RETRIES` | `3` | 重试控制值，不表示所有错误都重试三次；认证／冲突等会停止。 |
| `REMOTE_HEALTH_INTERVAL_SECONDS` | `30` | 目的端常规探测间隔，至少 10 秒；冷却期间不绕过退避。 |

数值必须有效、有限；不要输入 `NaN`／`inf`。容量按 `1024³`／`1024²` 换算；`20GB` 是额度，不会分区或预分配一个 20GB 文件。

## 容器路径与安全设置

Bot 的 `/data`、`/downloads`、`/logs`、`/config` 分别绑定宿主机实例内同名目录。`DATA_DIR`、`DOWNLOAD_DIR`、`LOG_DIR`、`RCLONE_CONFIG_PATH` 由 Compose 设置；不要仅改其中一处导致程序看不到原数据库或 Session。

Bot 使用 UID/GID `10001:10001`、只读根文件系统、移除 capabilities 及 `no-new-privileges`；OpenList 网关使用 `1001:1001`。CloudDrive2 的特权／FUSE 只属于网关，不应复制到 Bot。不要使用 `chmod 777` 或将 Bot 改 root 来绕过错误。

旧 `TG115_*`、`CD2_WEBDAV_*`／`CD2_TARGET_PATH_B64` 等兼容字段仍可能存在。新字段优先，不能把它们当作独立账号各填不同值；使用现有完整配置与管理流程保持一致。

## 安全修改流程

1. 记录实际版本，处理活动任务与失败保留文件，先备份。
2. 在 root 私密目录准备完整候选配置，保持旧字段；不要只给一个增量键值。
3. 使用[已存在的 `apply-config` 流程](OPERATIONS.md#修改运行配置)预检与应用，核对结果。不要 `source .env`，不把配置当 Shell 脚本执行。
4. `docker restart`／普通 `restart` 不会更新容器创建时的环境；不要因此反复改密码。
5. 验证 Bot、网关与原任务；涉及凭据／目录时再显式执行 WebDAV 验收，并核对外部 WebDAV 的目录绑定。

失败或配置来源不明时停止，不通过删除 DB／Session、改版本号、关闭指纹校验或卸载重装解决。
