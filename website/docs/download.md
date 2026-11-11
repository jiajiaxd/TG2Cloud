# 安装、下载与校验

本文对应 **TG2Cloud v1.5.10**，核对日期：2026-11-11。[fork 正式版](https://github.com/jiajiaxd/TG2Cloud/releases/tag/v1.5.10)提供源码包和 SHA256 校验清单。真实 VPS 更新进度见[本版记录](https://github.com/jiajiaxd/TG2Cloud/blob/main/docs/development/V1510-ACCEPTANCE.md)。

业务部署只使用正式稳定源码，部署平台为 Linux。已有外部 WebDAV 工具须在主菜单 15 的子菜单选择 8 升级，才会使用新向导。

## 公网 VPS 安装与升级

在符合[部署前准备](/guide/prerequisites/)的 Debian / Ubuntu Linux 主机上，以 root 运行；需要 Python 3.10+、curl、CA 证书和可交互终端：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh)
```

向导选择 Edition：未安装时收集信息并展示计划；已有可核验实例进入管理菜单，选择“安装与升级”。确认前不执行安装，升级默认保留已有配置和数据。完整过程见[从零部署](/guide/quick-start/)与[升级说明](/operations/update/)。

只做 CloudDrive2 预检：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition clouddrive2 --check
```

OpenList 先检查，再按需要进入安装 / 升级向导：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist --check
```

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist
```

`--check` 是只读预检，不代表安装、升级或 WebDAV 验收完成。旧 TG115、未知代码、部分安装和身份不符时停止，不添加强制覆盖参数。

## 可信内网 / NAS 安装

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install-lan.sh)
```

按向导输入主机实际拥有的私有 IPv4，不需要域名或 ACME。HTTP 不加密，不允许把内网管理入口转发到公网；要求本机 rootful Docker 28+，不保证兼容任意 NAS 系统。实际管理地址由向导显示，详见[内网指南](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/LAN-INSTALL.md)。

## 可选的外部 WebDAV

主安装不询问或默认启用此功能。v1.4.7 从 `tg2cloud` → 15. 外部 WebDAV 按需安装与维护，无需额外安装命令；历史 v1.4.6 尚无该菜单：

```bash
tg2cloud
```

它使用独立域名和独立只读账号，不复用 Bot 或网关管理员凭据。配置与维护见[外部 WebDAV](/deploy/external-webdav/)。

## 日常管理、凭据与卸载

安装后运行 `tg2cloud`。查看状态、日志、WebDAV 凭据和卸载均在[本地管理菜单](/operations/maintenance/)；v1.4.7 也包含外部 WebDAV 子菜单，历史 `tg2cloud-webdav` 仍兼容。

仅查看已有凭据，也可在自己的私有交互终端运行：

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition clouddrive2 --show-credentials
bash <(curl -fsSL https://raw.githubusercontent.com/jiajiaxd/TG2Cloud/main/install.sh) --edition openlist --show-credentials
```

每项确认后才显示，不安装、升级、改密或重建；已保存的 OpenList 初始化密码可能已在后台修改。不要截图、录屏或公开分享。

卸载不是升级步骤。新版主分支不再提供两个独立 Shell 文件；菜单卸载仅作用于当前 Edition，预检全部实例可用：

```bash
tg2cloud uninstall --edition all --check
```

命令损坏时重新运行原公网／内网安装入口，进入已有实例管理菜单，不选择重新安装；部分实例使用核验过的完整源码 CLI。历史脚本保留在原 Tag。实际默认完整卸载会在确认后清理所选实例数据与可识别备份；需要保留时使用 `--keep-data`。不删除云端文件或卸载系统 Docker / Nginx；完整清理不等于把 VPS 恢复到安装前。范围与依赖保护见[卸载指南](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/UNINSTALL.md)。

卸载前核对当前工具实际显示的清理范围，不用历史版本的默认行为推断当前会保留哪些数据。

## 源码包与 SHA-256

| 文件 | 用途 |
| --- | --- |
| [TG2Cloud-v1.5.10-source.tar.gz](https://github.com/jiajiaxd/TG2Cloud/releases/download/v1.5.10/TG2Cloud-v1.5.10-source.tar.gz) | 同标签源码，包含两 Edition 运行资源 |
| [SHA256SUMS.txt](https://github.com/jiajiaxd/TG2Cloud/releases/download/v1.5.10/SHA256SUMS.txt) | 对应该次 Actions 源码包的校验清单 |

将两个文件保存到同一目录，在 Linux 中执行：

```bash
sha256sum -c SHA256SUMS.txt
```

本版源码包 SHA256 为 `1018c0e7c2029d081393916c16347b798436c1b93b807dec186b9871a064915e`。校验不一致时停止，不混用其他版本的清单。校验和不是数字签名。

[本版 Release](https://github.com/jiajiaxd/TG2Cloud/releases/tag/v1.5.10) · [最新 Release](https://github.com/jiajiaxd/TG2Cloud/releases/latest) · [全部 Releases](https://github.com/jiajiaxd/TG2Cloud/releases)

### 在线入口与源码资产的区别

公网 / 内网两个轻量入口固定向导 commit，卸载通过 `tg2cloud` 菜单或子命令进入；业务部署资源解析正式稳定 Release 的不可变 commit。它们与手动下载源码资产、执行 SHA-256 清单检查不是同一条路径。

外部 WebDAV 从 `tg2cloud` → 15. 外部 WebDAV 按需进入，并验证正式源码资产及同版校验清单。任一路径下载失败都不回退未校验的 main / RC 业务代码；不会因为更新网站就自动更新已运行实例。

## 发布与验收范围

源码、镜像和两版 Compose 部署包须使用同一版本；Compose 下载和摘要核对见[完整教程](/deploy/compose/)。完整版本事实见[更新日志](/changelog/)，当前资产和未执行的真实环境项目见[发布记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/V157-ACCEPTANCE.md)。

发布及校验成功不等于真实 VPS、Telegram、DNS／ACME 或网盘转存已验收。测试结论按实际版本和范围理解，不提供 EXE 下载和桌面构建步骤。
