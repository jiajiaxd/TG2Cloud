# 从零开始部署

在自己的 Linux 主机运行安装脚本，再到存储网关挂载云盘、创建 WebDAV 用户，最后验证一个真实小文件。通过自己的终端操作即可。

:::tip 先选安装场景
公网 VPS 使用 HTTPS 域名；可信内网 / NAS 使用独立内网入口。两种方式都需要主机能够访问 GitHub、Telegram、镜像仓库和目的端，具体条件见[部署前准备](/guide/prerequisites/)。
:::

## 第一步：登录自己的 Linux 主机

通过自己的 SSH 终端登录符合[部署前准备](/guide/prerequisites/)的 Debian / Ubuntu Linux 主机，并以 root 运行安装入口。首次连接或主机指纹变化时，先按[SSH 指南](/deploy/ssh/)核对服务器身份。

准备 Telegram API ID、API Hash、Bot Token，以及一个管理员数字 ID。CloudDrive2 还需要主机提供 `/dev/fuse`；OpenList 不要求 FUSE。

## 第二步：选择安装入口

公网 VPS：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh)
```

可信内网 / NAS：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh)
```

选择 `1. CloudDrive2` 或 `2. OpenList`。未安装时，确认进入安装向导；已有实例则打开[本地管理菜单](/operations/maintenance/)，不要将升级当成重新安装。

入口的 Python 向导固定到受审阅提交，Bot 部署资源来自正式稳定 Release；下载失败时停止，不改用未发布的 main 业务代码。

## 第三步：配置管理入口

| 场景 | 需要填写 | 访问方式 |
| --- | --- | --- |
| 公网 VPS | 指向本机的独立管理域名，可选 Let's Encrypt 邮箱 | `https://你的管理域名` |
| 可信内网 | 本机实际拥有的私有 IPv4 | 向导显示的 `http://内网IP:端口` |

公网需核对 DNS A/AAAA、80/443 入站规则和端口归属。公网 NAT 主机按提示核实云控制台分配的公网 IPv4，不能将 A 记录改成私有地址。首次签发 Cloudflare 使用“仅 DNS”。

80/443 已被其他代理占用时，不停止未知服务。受支持的已有 Docker Nginx 仅在显式授权后接入；不满足条件时按[HTTPS 指南](/deploy/domain-https/)检查人工接入方案。

内网入口不申请证书；HTTP 不加密，禁止把管理端口转发到公网。

## 第四步：填写 Telegram 与存储方案

按向导选择流式优先、均衡或手动预算，并填写：

| 字段 | 填写方式 |
| --- | --- |
| Telegram API ID / API Hash | 配套的应用凭据 |
| Bot Token | 自己的 BotFather Token |
| 管理员数字 ID | 安装时只填一个 ID；家人安装后另行授权 |
| WebDAV 用户名 | 新装回车默认 `tg2cloud`，也可自行输入 |
| WebDAV 密码 | 隐藏输入；留空自动生成 |
| Bot 保存子目录 | 相对路径，可留空；账号根目录在网关后台设置 |

时区新装默认 `Asia/Shanghai`，升级保留现有值。20GB 任务预算、8GB 磁盘保留只是源码默认，实际推荐按实时资源计算；预算不是磁盘分区，也不约束网关全部缓存。详见[资源预算](/deploy/resources/)。

## 第五步：核对计划并执行

确认 Edition、安装目录、资源预算、管理入口和是否为保留配置升级，再同意执行。未确认前不安装；执行后可能安装基础系统依赖、构建镜像并启动所选实例。

查看真实阶段、错误及最终摘要。常见 `WARNING` 不等于失败，但也不能忽略错误；解释见[安装反馈](/operations/update/#安装与升级反馈)。

基础健康与管理入口通过后，后续可运行离线管理命令：

```bash
tg2cloud
```

查看状态或日志不会自动下载新版。安装中断后先核对原实例和失败阶段，不要删除数据库、Session 或整个安装目录。

## 第六步：挂载云存储并创建 WebDAV 用户

打开向导给出的管理地址，由本人登录网关、添加云存储并选择目标目录：

- [CloudDrive2 配置](/deploy/clouddrive2/)：创建专用 WebDAV 用户，允许实际读取、写入、改名和删除。
- [OpenList 配置](/deploy/openlist/)：使用初始化管理员凭据登录，再创建独立普通 WebDAV 用户，允许列表、读取、写入和删除。

用户名、密码必须与安装时保存的值一致。Bot 的专用用户不是网关管理员或云盘登录账号。

管理地址只用于浏览器，不能替换 Bot 的 Docker 内部 WebDAV 地址。最终保存位置为“用户根目录 + Bot 相对子目录”；不要重复填写同一段路径。

## 第七步：执行 WebDAV 真实验收

运行 `tg2cloud`，选择对应 Edition，再选 **11. WebDAV 验收**。确认后会创建并清理随机小测试文件，不是只读检查。

```text
TG2CLOUD_DESTINATION=OK
```

CloudDrive2 会验证临时上传、改名和复验；OpenList 直接写入预留最终路径并复验，不依赖 MOVE。只见到“认证通过”或容器 healthy，不能替代最终通过标记。详见[验收步骤](/deploy/verification/)。

## 第八步：发送第一个测试文件

与 Bot 一对一私聊，先发送一个自己有权保存的 5～20MB 文件。通过 `/queue`、`/task 编号` 和 `/status` 观察处理。

Bot 完成后，在云存储官方客户端检查位置、大小及可打开性。WebDAV 大小复验不等于内容哈希一致，也不证明云盘官方最终完成。

## 首次部署完成清单

1. 服务器身份及安装资源检查通过。
2. Bot 只接受管理员及后续显式授权的家人私聊。
3. 管理入口可用；公网模式下后端端口不直接暴露。
4. 网关已挂载存储，专用 WebDAV 用户和目标目录正确。
5. WebDAV 验收出现完整成功标记。
6. 真实小文件可在云存储中正常打开。

本机 HTTPS 通过后，仍须从另一网络验证公网访问；内网部署从局域网其他设备验证。日常操作见[Bot 命令](/usage/commands/)，已有实例见[升级说明](/operations/update/)。
