# TG2Cloud v1.5.10 发布与验收

[同标签原生双架构发布检查](https://github.com/jiajiaxd/TG2Cloud/actions/runs/43021884337)通过。本地回归 1635 项通过、17 项跳过。

## 发布资产

[源码 Release](https://github.com/jiajiaxd/TG2Cloud/releases/tag/v1.5.10)包含 `TG2Cloud-v1.5.10-source.tar.gz`、`TG2Cloud-v1.5.10-compose-clouddrive2.tar.gz`、`TG2Cloud-v1.5.10-compose-openlist.tar.gz` 和两份 SHA256 校验清单。已下载并验证三份归档。

[镜像构建](https://github.com/jiajiaxd/TG2Cloud/actions/runs/43022495595)和 [Compose 包发布](https://github.com/jiajiaxd/TG2Cloud/actions/runs/43022788744)通过。公开镜像标签为 `ghcr.io/jiajiaxd/tg2cloud:1.5.10`，平台为 Linux AMD64 和 ARM64。镜像索引为 `ghcr.io/jiajiaxd/tg2cloud@sha256:2d93bdf74cf32cdb718835c6f9563e69e1c9bf3c179af841b7a7a1a13d1731a2`。

## 线上升级

2026-11-11 在真实用户 VPS 将 OpenList Edition 的 Bot 从 v1.5.8 切换至 v1.5.10。数据库从 schema 3 迁移到 schema 4，完整性检查通过，保留 619 条任务记录。Bot 健康检查、Telegram 登录和 WebDAV 只读探测通过，队列恢复调度。实际 Telegram 附件转存尚未执行。
