# 来源、致谢与素材说明

**TG2Cloud v1.5.10**，资料核对日期：2026-11-11。文档使用项目原有依赖、品牌资源和许可证。

## 主项目与上游

本网站为 LuoPoJunZi/TG2Cloud 整理中文使用与维护文档，保留项目与上游作者致谢：
- https://github.com/LuoPoJunZi/TG2Cloud
- https://github.com/whyhhh20/TG115

TG2Cloud 的公开 LICENSE 为 MIT，版权行为 `Copyright (c) 2026 TG115 Contributors`。完整许可保留在根目录 LICENSE 与静态产物 LICENSE.txt 中。
- https://github.com/LuoPoJunZi/TG2Cloud/blob/main/LICENSE

主要技术资料：
- README：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/README.md
- 当前正式发布：https://github.com/LuoPoJunZi/TG2Cloud/releases/tag/v1.5.7
- 运行维护：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/OPERATIONS.md
- VPS 单行脚本：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/docs/VPS-INSTALL.md
- CHANGELOG：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/CHANGELOG.md
- 产品参数：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/src/tg2cloud/deployment/profiles.py
- 安全说明：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/.github/SECURITY.md
- 贡献说明：https://github.com/LuoPoJunZi/TG2Cloud/blob/main/.github/CONTRIBUTING.md

README 与 main 分支可能在之后更新。正式 Release 的确定行为应以对应标签、发布说明及用户实际验收为准。

## 界面与素材

页面的栏目、文档导航和首页组织参考 https://tg115.pages.dev/ 的文档站思路；没有下载其整站代码或第三方图片。

本站 HTML/CSS 模板、轻量云图标、流程示意和交互代码随源码提供。没有加入商业素材、部署器虚构截图或字体文件。字体使用操作系统已有字体。

CloudDrive2、OpenList、Telegram、GitHub、Cloudflare 等名称仅用于描述兼容组件、资料来源与部署平台，不表示这些平台对本网站的背书。

TG2Cloud v1.0.3 的可选域名 HTTPS 功能使用 Nginx 与 Certbot 容器。Nginx 开源版采用 BSD-2-Clause 许可，Certbot 采用 Apache-2.0 许可；具体版本与其他第三方组件说明见主仓库的 `docs/第三方组件说明.md`。

## 构建实现

自包含 Node.js 标准库静态生成器，无第三方 npm 运行或构建依赖。并非 VitePress、Vue 或 React 项目，不声称提供这些框架的完整能力。

Cloudflare 部署说明参考官方文档：
- https://developers.cloudflare.com/pages/configuration/build-configuration/
- https://developers.cloudflare.com/pages/get-started/direct-upload/
