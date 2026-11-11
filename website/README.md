# TG2Cloud Docs

**TG2Cloud v1.5.10**，资料核对日期：2026-11-11。fork 发布与验收进度见[本版记录](../docs/development/V1510-ACCEPTANCE.md)。

这是静态文档网站，部署网站不会部署 TG2Cloud 服务。项目来源：[LuoPoJunZi/TG2Cloud](https://github.com/LuoPoJunZi/TG2Cloud)；上游致谢：[whyhhh20/TG115](https://github.com/whyhhh20/TG115)。完整版本事实见[更新日志](docs/changelog.md)。

## 立即使用

安装 Node.js 22，在本目录打开终端：

```bash
npm ci --ignore-scripts
npm run build
npm test
npm run preview
```

打开 `http://127.0.0.1:4173`，按 `Ctrl+C` 停止。

本项目没有第三方 npm 依赖；`npm ci` 只是标准化安装步骤，也可以直接执行构建命令。不需要 Python、Docker、数据库、Cloudflare API Token 或 Telegram Token。

修改文档时执行：

```bash
npm run dev
```

保存 `docs/`、`src/`、`public/` 或站点配置后会自动重新构建；**浏览器需要手动刷新，不提供热更新**。预览服务只监听本机回环地址，不是生产服务器。

## Cloudflare Pages 部署

推荐使用 GitHub 集成，后续提交 Markdown 就能触发部署。详细步骤见 [DEPLOY.md](DEPLOY.md)。

| 配置项 | 本项目的值 |
| --- | --- |
| 框架预设 | None |
| 生产分支 | `main`，或你实际使用的分支 |
| 构建命令 | `npm run build` |
| 构建输出目录 | `dist` |
| 根目录 | 独立文档仓库时留空 |
| 环境变量 | `NODE_VERSION=22` |
| 可选环境变量 | `SITE_URL`，填写实际生产站点完整源地址 |

推荐新建独立文档仓库，例如 `TG2Cloud-Docs`。这是建议名称，并未替你创建仓库。

也可把本目录完整放进 TG2Cloud 原仓库的 `website/` 子目录，此时 Pages **根目录填 `website`**，其余不变。不要将压缩包中的 `README.md`、`scripts/`、`docs/` 等直接覆盖到 TG2Cloud 原仓库根目录。

### 直接上传版本

交付的 `TG2Cloud-Docs-Cloudflare-Pages.zip` 已经构建好，压缩包根层就是 `index.html`。在 Pages 的“直接上传 / 拖放文件”流程上传即可，无需在线构建。

注意：Cloudflare 的 Direct Upload 项目不能在以后直接改为 Git 集成项目。准备长期通过 GitHub 更新时，一开始就选择 Git 集成。直接上传版本每次修改后需要重新构建并上传。

### 站点地址与 SEO

`site.config.json` 中 `siteUrl` 使用已经确认的正式地址 `https://tg2cloud.pages.dev`，用于 canonical、sitemap 和 robots。复制网站到其他域名时，应设置自己的 `SITE_URL`，不要沿用原站地址；未知域名时可将配置留空，不生成猜测地址。

改用自有域名时，设置构建环境变量 `SITE_URL` 为真实源地址，例如 `https://你的实际文档域名`，然后重新部署。也可修改 `site.config.json` 的 `siteUrl`。环境变量优先。

只支持部署在域名根路径，不支持 `/some-prefix/` 这样的子路径。将源码放在 Git 仓库 `website/` 子目录不影响这一点：Pages 仍将其 `dist` 发布到网站根路径。

`.env.example` 仅用于解释变量；构建器不自动读取 `.env`。在 PowerShell 中需使用 `$env:SITE_URL="..."`，或直接修改 JSON 配置。

## 包含的文档

| 分类 | 内容 |
| --- | --- |
| 开始使用（5 篇） | 项目介绍、版本选择、部署前准备、从零部署、下载与校验 |
| 部署与配置（9 篇） | SSH、HTTPS、Telegram、两版网关、资源、WebDAV 验收、外部 WebDAV、Compose |
| 日常使用（5 篇） | 第一次转存、Bot 命令、任务状态、流式传输、管理员监听 |
| 运维与升级（3 篇） | 状态与日志、升级与配置、备份边界 |
| 问题排查（4 篇） | FAQ、SSH 与管理页、WebDAV、队列/空间/上传失败 |
| 项目参考（6 篇） | 配置路径、安全、更新日志、开发、致谢、资料来源 |

首页与文档内容区分了两个 Edition，不把“网关接收与大小检查成功”描述为“云盘官方最终完成”。旧版本菜单指向真实更新日志，而不是没有维护的历史版本文档镜像。版本号及文章内容采用显式维护，不会自动跟随 GitHub Release 更新。

## 如何修改

```text
TG2Cloud-Docs/
├── docs/                    # 31 篇中文 Markdown 正文
├── public/
│   ├── assets/
│   │   ├── style.css        # 全站样式、响应式与主题
│   │   ├── app.js           # 搜索、主题、目录、复制与弹窗
│   │   ├── theme-init.js    # 首屏主题初始化
│   │   ├── tg2cloud-icon.svg      # 正式可缩放网页图标
│   │   ├── tg2cloud-icon-32.png   # 浏览器 PNG 图标
│   │   ├── tg2cloud-icon-64.png   # 页头品牌图标
│   │   └── tg2cloud-icon-256.png  # Apple Touch 图标
│   ├── _headers            # Cloudflare Pages 响应头
│   ├── favicon.ico         # 正式 ICO 兼容入口
│   └── LICENSE.txt
├── src/
│   ├── templates.mjs       # 首页及文章 HTML 模板
│   └── icons.mjs           # 内联 SVG 界面图标
├── scripts/                # 构建、预览、开发监听、链接检查
├── tests/                  # Markdown 渲染与版本内容一致性测试
├── site.config.json        # 版本、导航、项目地址与站点地址
├── DEPLOY.md               # Pages 部署说明
└── package.json
```

日常内容直接编辑对应 Markdown。新增文章时，创建 `docs/分类/文件名.md`，并在 `site.config.json` 的 `navigation` 中新增标题与 `slug`；slug 不加开头或结尾斜杠，站内链接使用 `/分类/文件名/`。

首页文案、卡片与流程图在 `src/templates.mjs` 的 `homeContent()`；配色在 `public/assets/style.css`。更新版本时同步配置中的 `version`、`verifiedAt`、更新日志与受影响的教程。`publishedVersion` 是实际可下载的正式版本，`releaseStatus` 为 `unreleased` 或 `released`；尚未发布时保留真实下载基线，不生成不存在的新版本资产／Tag 链接。正式 Release 完成后再同步下载链接、`publishedVersion` 和状态。

提交前运行：

```bash
npm run build
npm test
```

本仓库的版本、公开脚本命令和品牌副本一致性测试会读取上级 TG2Cloud 源文档与 `assets/brand/`，因此完整检查需要保留仓库目录结构；只拷贝 `website/` 可以构建与预览，但不能完成这些仓库级测试。来源与同步职责见 [仓库维护规范](../docs/development/REPOSITORY.md)。

不要编辑生成后的 `dist/` 来维护文章；下次构建会覆盖它。`dist/` 已加入 `.gitignore`，由 Pages 每次重新构建。

### Markdown 支持范围

这是一个 **Node.js 标准库实现的轻量静态文档生成器，不是 VitePress / Vue 工程**。不使用其插件语法或运行时。

支持标题、段落、基础单层列表、表格、链接、图片、行内代码、加粗、代码块和以下提示块：

```markdown
::: tip 操作提示
先完成测试，再处理正式文件。
:::
```

提示类型为 `info`、`tip`、`warning`、`danger`。请使用现有文档中的写法。暂不支持复杂嵌套列表、MDX、Vue 组件、数学公式渲染、原始 HTML 或任意插件；原始 HTML 会被转义。

站内搜索索引在构建时生成，浏览器首次打开搜索时加载本网站的 JSON，不依赖第三方搜索服务。未配置统计、广告、遥测或登录系统。

文章改名或拆分章节时，先检查旧锚点链接。必要的兼容映射维护在 `src/legacy-anchors.json`：键为旧锚点 ID，值为本页仍存在的章节标题。构建器生成经过校验的空锚点，不放开 Markdown 原始 HTML，也不把旧标题重复加入目录或搜索。新映射必须通过唯一 ID、目标存在和链接检查。

文章底部的“查看本页源码”打开本网站对应 Markdown，“参考项目文档”打开功能依据，两者不混用。版本菜单从完整更新日志提取最近版本，历史版本入口不是旧版文档快照。

## 品牌与截图

页头与浏览器图标直接复制自主仓库 `assets/brand/`，不重新绘制或修改，确保文档站与部署器使用同一套 TG2Cloud 正式品牌资源。首页流程图是 HTML/CSS 工作原理示意，不是正在运行的任务状态或部署器截图。

`npm test` 会逐字节校验 SVG、32/64/256 PNG 和 favicon ICO 五个副本。正式资源改变时，从 `assets/brand/` 手动复制对应文件后再检查；测试不会自动覆盖资源或重新生成图标。

没有放置“安全占位截图”，也未嵌入伪造的实机界面。今后加入真实截图，应先移除 IP、SSH 凭据、Bot Token、API Hash、Cookie、网盘 Token、私人文件名等敏感信息，再放进 `public/images/` 并用普通 Markdown 图片语法引用。

## 验证与交付边界

提交前已执行构建、Markdown 单元测试和内部链接检查。GitHub 中的 `website-docs` Workflow 会在网站源码发生变化时重新执行构建与检查，但不能代替部署后的浏览器与 Cloudflare 在线验收。

上传网站源码不会自动创建 Cloudflare 项目、部署 Bot 或进行真实网盘上传验收。公开资料只用于编写教程，不等同于当前 VPS 实测结果。

## 来源与许可

采用 MIT 许可证，保留上游版权说明。详见 [LICENSE](LICENSE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与站内“项目来源与致谢”。

Cloudflare 官方参考：
- [Build configuration](https://developers.cloudflare.com/pages/configuration/build-configuration/)
- [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
