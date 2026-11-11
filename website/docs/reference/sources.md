# 资料来源与验证边界

本文源码版本为 **v1.5.10**，核对日期 **2026 年 11 月 11 日**。[fork 正式版](https://github.com/jiajiaxd/TG2Cloud/releases/tag/v1.5.10)提供源码包和 SHA256 校验清单。发布与验收见[本版记录](https://github.com/jiajiaxd/TG2Cloud/blob/main/docs/development/V1510-ACCEPTANCE.md)。

## 主要来源

| 主题 | 仓库来源 |
| --- | --- |
| 安装与升级 | [公网](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/VPS-INSTALL.md)、[内网](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/LAN-INSTALL.md)、[Compose](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/COMPOSE.md) |
| 网关和使用 | [存储](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/STORAGE.md)、[Bot](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/BOT-USAGE.md)、[监听](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/LISTENING.md) |
| 维护与数据 | [运维](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/OPERATIONS.md)、[配置](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/CONFIGURATION.md)、[备份](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/BACKUP-RESTORE.md) |
| Compose 管理增强 | [Compose 安全维护](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/COMPOSE-MANAGEMENT.md)；发布状态另见本版记录，文档不代替实机验收 |
| 开发与发布 | [开发指南](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/DEVELOPMENT.md)、[发布清单](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/development/RELEASE-CHECKLIST.md) |
| 版本事实 | [完整更新记录](https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md)；旧验收资料使用固定历史提交链接，不作为当前教程 |

仓库 docs 与本站是独立阅读入口，可以覆盖相同主题；命令、实际能力、安全边界和发布事实保持一致。已经退休的部署器和跨项目迁移教程不在当前网站提供，上游来源和许可另见[致谢](/reference/credits/)。

## 文档与软件版本分别维护

`site.config.json` 的 `version` 表示网站讲解的软件源码版本；`publishedVersion` 表示实际可下载的正式版本，`releaseStatus` 区分 `unreleased` 与 `released`。`package.json` 和 lockfile 与网站源码版本保持一致；依赖和历史版本不机械替换。

导航“最新 Release”只是跳转到 GitHub，不代表站内内容自动跟随最新。未发布的源码更新可以先更新文档版本，但必须说明待发布，并保留真实下载链接。正式发布完成后再同步下载链接、`publishedVersion`、状态、更新日志和教程。

## Markdown 内容在哪里

文章位于 `docs/`。导航分类、文章标题与路径位于 `site.config.json`。新增文章后，把它加入相应导航，再执行构建与校验。

本静态引擎支持标题、段落、单层有序/无序列表、表格、代码块、链接、粗体、图片与提示块。不执行 Markdown 中的任意 HTML 或脚本；不是 VitePress/Vue 插件运行环境。

## 本地查看与构建

文档站只需要 Node.js 22 或更高版本，没有第三方 npm 依赖。

```bash
npm run build
npm test
npm run preview
```

浏览器打开命令输出的本地地址，不要双击 `dist/index.html`；本地搜索和根路径资源需要 HTTP 服务。

开发时可使用 `npm run dev`，它会监测内容变化并重新构建；刷新浏览器查看修改。

## Cloudflare Pages 配置

当前网站源码位于 TG2Cloud 仓库的 `website/`，Pages 根目录应设为 `website`；构建命令 `npm run build`，输出目录 `dist`，Node 版本 `22`。部署成独立文档仓库时才将根目录留空。

每个文章都生成独立 HTML，不需要 SPA 全站回退。正式地址已确认是 `https://tg2cloud.pages.dev/`，配置据此生成 canonical、站点地图及 robots 入口。自行部署副本时必须改成自己的 `SITE_URL`；未知域名不猜测。

## 图片与隐私

页面不依赖外部字体、CDN 图片或第三方统计。首页为流程示意，而非部署器截图；没有用占位截图冒充实际运行结果。

后续补充界面截图时，把真实脱敏图片放入 `public/images/`，在 Markdown 中引用，并标注 Edition 与版本。不要提交真实 Token、IP、密码、二维码或私人文件名。
