"""Private, expiring configuration drafts for Telegram buttons and text fields.

Only an explicit Save calls the existing repository. No transfer or HTTP work
is performed by the local sample preview.
"""

from __future__ import annotations

import copy
import re
import secrets
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from tg2cloud.domain.actors import current_user
from tg2cloud.domain.classification import safe_directory
from tg2cloud.domain.planning import FIELDS, PlanningError, name_plan, profile
from tg2cloud.domain.source_directories import description, media_directory
from tg2cloud.listening import rules

MODES = {
    "compatible": "兼容命名（有效原名优先）",
    "caption": "说明标题优先",
    "template": "字段模板",
}
SCOPES = {"both": "文件名和说明", "name": "文件名", "caption": "说明文字"}
NAMES = {"contains": "包含文字", "exact": "完全相同", "glob": "通配匹配（*、?）"}
LABELS = {
    "keywords": "包含关键词",
    "exclude": "排除关键词",
    "extensions": "文件后缀",
    "names": "文件名条件",
    "prefixes": "清理前缀",
    "suffixes": "清理后缀",
}
FIELD_LABELS = dict(
    zip(
        (
            "title",
            "episode",
            "season",
            "chapter",
            "year",
            "resolution",
            "language",
            "version",
        ),
        ("标题", "集数", "季数", "章节", "年份", "分辨率", "语言", "版本"),
    )
)
TYPES = ("视频", "图片", "音频", "文档", "压缩包", "其他文件")


def size_input(value):
    text = value.strip()
    if text == "0":
        return 0
    match = re.fullmatch(
        r"(\d+(?:\.\d{1,3})?)\s*(B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?", text, re.IGNORECASE
    )
    if not match:
        raise PlanningError(
            "请输入大小，例如 100 MB、1.5 GB；0 表示不限，纯数字按 MB。"
        )
    power = {
        "B": 0,
        "KB": 1,
        "KIB": 1,
        "MB": 2,
        "MIB": 2,
        "GB": 3,
        "GIB": 3,
        "TB": 4,
        "TIB": 4,
    }[match[2].upper() if match[2] else "MB"]
    result = Decimal(match[1]) * 1024**power
    if result != int(result) or not 0 <= result <= 100 * 1024**4:
        raise PlanningError("大小须为有效整数字节，最多 100 TB。")
    return int(result)


def lines_input(text, key):
    values = (
        re.split(r"[\s,，、]+", text.strip())
        if key == "extensions"
        else text.splitlines()
    )
    values = list(dict.fromkeys(v.strip() for v in values if v.strip()))
    limit, length = (12, 80) if key in {"prefixes", "suffixes"} else (20, 100)
    if (
        not values
        or len(values) > limit
        or any(len(v) > length or any(ord(c) < 32 for c in v) for v in values)
    ):
        raise PlanningError(
            f"请每行填写一项，最多 {limit} 项，每项最多 {length} 字；清空请使用按钮。"
        )
    if key == "extensions":
        values = [rules.norm(v).lstrip(".") for v in values]
        if any(
            not v or len(v) > 24 or any(not (c.isalnum() or c == ".") for c in v)
            for v in values
        ):
            raise PlanningError("文件后缀格式不正确，例如 mp4、mkv。")
    return values


def rule_summary(value, *, compact=False):
    config = rules.validate(value)
    groups = []
    for i, g in enumerate(config["groups"], 1):
        parts = []
        for key, label in (
            ("types", "类型"),
            ("extensions", "后缀"),
            ("names", "文件名"),
            ("keywords", "关键词"),
        ):
            if g[key]:
                content = (
                    "、".join(v[:40] + ("…" if len(v) > 40 else "") for v in g[key][:3])
                    if compact
                    else "、".join(g[key])
                )
                if compact and len(g[key]) > 3:
                    content += f" 等 {len(g[key])} 项"
                if key == "keywords":
                    content += (
                        "（全部包含）" if g["keyword_mode"] == "all" else "（任意一个）"
                    )
                if key == "names":
                    content += "（" + NAMES[g["name_mode"]] + "）"
                parts.append(label + "：" + content)
        groups.append(f"条件组 {i}：" + "；".join(parts))
    from tg2cloud.telegram.views import format_bytes

    text = "\n".join(groups) if groups else "接收全部附件（仍受下方限制）"
    return (
        text
        + ("\n组内条件全部满足，任意一组满足即可。" if len(groups) > 1 else "")
        + "\n排除："
        + (
            (
                "、".join(config["exclude"][:3])
                + (
                    f" 等 {len(config['exclude'])} 项"
                    if len(config["exclude"]) > 3
                    else ""
                )
            )
            if compact and config["exclude"]
            else "、".join(config["exclude"]) or "无"
        )
        + "\n大小："
        + (format_bytes(config["min_bytes"]) if config["min_bytes"] else "不限下限")
        + " 至 "
        + (format_bytes(config["max_bytes"]) if config["max_bytes"] else "不限上限")
        + "\n文字范围："
        + SCOPES[config["scope"]]
        + ("\n排除范围：" + SCOPES[config["exclude_scope"]] if config.get("exclude_scope", "same") != "same" else "")
    )


def profile_summary(value):
    p = profile(value)
    return (
        "命名："
        + MODES[p["mode"]]
        + "\n模板："
        + p["template"]
        + "\n清理前缀："
        + ("、".join(p["prefixes"]) or "无")
        + "\n清理后缀："
        + ("、".join(p["suffixes"]) or "无")
        + "\n标题标记："
        + (p["label"] or "未设置")
    )


@dataclass
class Draft:
    id: str
    kind: str
    config: dict
    original: object
    source: int | None = None
    revision: int | None = None
    version: int = 0
    expires: float = 0
    page: str = ""
    group: int = 0
    sample: dict = field(
        default_factory=lambda: {
            "original": "示例视频.mp4",
            "caption": "城市漫游 第3集 1080P",
            "kind": "视频",
            "size": 1024**2,
        }
    )


def ui():
    from tg2cloud.telegram import planning

    return planning


def drafts(owner):
    if not hasattr(owner, "_configuration_drafts"):
        owner._configuration_drafts = {}
    now = time.monotonic()
    owner._configuration_drafts = {
        k: v for k, v in owner._configuration_drafts.items() if v.expires > now
    }
    return owner._configuration_drafts


def aliases(repo):
    return [
        dict(row)
        for row in repo.c.execute(
            "SELECT alias,path,owners FROM transfer_directories ORDER BY alias"
        )
    ]


def require(owner, identity, version):
    actor = current_user(owner.settings.allowed_user_id)
    d = drafts(owner).get(actor)
    if d is None or d.id != identity or d.version != version:
        raise PlanningError("编辑已过期或页面已变化，请重新打开设置。")
    repo = ui().store(owner)
    repo.authorize(actor, admin=d.source is not None or d.kind == "aliases")
    if d.source is not None and repo.source(actor, d.source)["revision"] != d.revision:
        raise PlanningError("来源配置已被修改，请取消草稿并重新打开。")
    if d.kind == "personal" and repo.preferences(actor) != d.original:
        raise PlanningError("个人配置已变化，请重新打开。")
    return actor, repo, d


def button(owner, actor, d, label, operation, *args):
    return ui().token_button(
        owner, actor, label, ("editor", d.id, d.version, operation, *args)
    )


async def start(owner, event, kind, source=None, revision=None, *, page=None):
    actor = current_user(owner.settings.allowed_user_id)
    repo = ui().store(owner)
    repo.authorize(actor, admin=kind != "personal")
    if source is not None:
        s = repo.source(actor, source)
        if s["revision"] != revision:
            raise PlanningError("来源已变化，请刷新后重试。")
        original = s["config"]
    elif kind == "personal":
        original = repo.preferences(actor)
    else:
        original = aliases(repo)
    config = copy.deepcopy(
        original if kind != "aliases" else {"alias": "", "path": "", "owners": []}
    )
    d = Draft(
        secrets.token_hex(8),
        kind,
        config,
        copy.deepcopy(original),
        source,
        revision,
        expires=time.monotonic() + 300,
    )
    if actor not in drafts(owner) and len(drafts(owner)) >= 128:
        raise PlanningError("正在编辑的用户过多，请稍后再试。")
    drafts(owner)[actor] = d
    ui().interactions(owner).pop(actor, None)
    await show(
        owner,
        event,
        d,
        page
        or (
            "naming"
            if kind in {"profile", "personal"}
            else "directory"
            if kind == "directory"
            else "mode"
            if kind == "mode"
            else "aliases"
            if kind == "aliases"
            else "rules"
        ),
    )


def group(d):
    groups = d.config["rules"]["groups"]
    if not 0 <= d.group < len(groups):
        raise PlanningError("请先添加条件组，或明确选择接收全部附件。")
    return groups[d.group]


def target_list(d, key):
    return (
        d.config["profile"][key]
        if key in {"prefixes", "suffixes"}
        else d.config["rules"][key]
        if key == "exclude"
        else group(d)[key]
    )


async def show(owner, event, d, page, notice=""):
    actor, repo, d = require(owner, d.id, d.version)
    ui().interactions(owner).pop(actor, None)
    d.version += 1
    d.expires = time.monotonic() + 300
    d.page = page
    b = lambda label, op, *args: button(owner, actor, d, label, op, *args)
    rows = []
    footer = [[b("保存修改", "save"), b("取消返回", "cancel")]]
    title = "设置草稿（保存后生效，5 分钟无操作过期）\n"
    if page == "rules":
        r = d.config["rules"]
        try:
            summary = rule_summary(r, compact=True)
        except PlanningError:
            summary = "尚有未完成的条件组，请逐项填写；空条件不会接收全部附件。"
        text = title + "筛选规则\n当前编辑：条件组 " + str(d.group + 1) + "\n" + summary
        rows = [
            [b("媒体类型", "page", "types"), b("文件后缀", "list", "extensions")],
            [b("包含关键词", "list", "keywords"), b("排除关键词", "list", "exclude")],
            [b("文件名条件", "list", "names"), b("文件大小", "page", "sizes")],
            [b("匹配范围", "page", "scope"), b("组合条件", "page", "groups")],
            [b("测试规则", "page", "sample")],
        ]
    elif page == "types":
        selected = group(d)["types"]
        text = title + "媒体类型（多选）；不限制类型时仍须有其他筛选条件。"
        rows = [
            [b(("☑ " if value in selected else "☐ ") + value, "type", value)]
            for value in TYPES
        ]
        rows += [[b("不限类型", "type", ""), b("返回规则", "page", "rules")]]
        footer = []
    elif page.startswith("list:"):
        key = page.split(":", 1)[1]
        values = target_list(d, key)
        text = (
            title
            + LABELS[key]
            + "\n"
            + ("\n".join(f"{i}. {v}" for i, v in enumerate(values, 1)) or "未设置")
        )
        rows = [
            [b("添加", "input", key, "add"), b("替换列表", "input", key, "replace")],
            [b("删除一项", "page", "delete:" + key), b("清空列表", "clear", key)],
        ]
        if key == "keywords":
            rows += [
                [
                    b(
                        "☑ 任意一个"
                        if group(d)["keyword_mode"] == "any"
                        else "任意一个",
                        "choice",
                        "keyword_mode",
                        "any",
                    ),
                    b(
                        "☑ 全部包含"
                        if group(d)["keyword_mode"] == "all"
                        else "全部包含",
                        "choice",
                        "keyword_mode",
                        "all",
                    ),
                ]
            ]
        if key == "exclude":
            rows += [[b("排除匹配范围", "page", "exclude-scope")]]
        if key == "names":
            rows += [
                [b(label, "choice", "name_mode", mode)] for mode, label in NAMES.items()
            ]
        rows += [
            [
                b(
                    "返回编辑",
                    "page",
                    "naming" if key in {"prefixes", "suffixes"} else "rules",
                )
            ]
        ]
        footer = []
    elif page.startswith("delete:"):
        key = page.split(":", 1)[1]
        text = "选择要删除的一项："
        rows = [
            [b(f"{i + 1}. {v[:35]}", "remove", key, i)]
            for i, v in enumerate(target_list(d, key))
        ]
        rows += [[b("返回列表", "list", key)]]
        footer = []
    elif page == "sizes":
        from tg2cloud.telegram.views import format_bytes

        r = d.config["rules"]
        text = (
            title
            + "文件大小\n最小："
            + (format_bytes(r["min_bytes"]) if r["min_bytes"] else "不限")
            + "\n最大："
            + (format_bytes(r["max_bytes"]) if r["max_bytes"] else "不限")
        )
        rows = [
            [
                b("修改最小值", "input", "min_bytes"),
                b("修改最大值", "input", "max_bytes"),
            ],
            [b("返回规则", "page", "rules")],
        ]
        footer = []
    elif page == "scope":
        text = title + "文字匹配范围：" + SCOPES[d.config["rules"]["scope"]]
        rows = [[b(label, "choice", "scope", key)] for key, label in SCOPES.items()] + [
            [b("返回规则", "page", "rules")]
        ]
        footer = []
    elif page == "exclude-scope":
        text = title + "排除词匹配范围；只改排除词，不改变包含条件的文字范围。"
        rows = [[b(label, "choice", "exclude_scope", key)] for key, label in {"same": "沿用文字范围", **SCOPES}.items()]
        rows += [[b("返回排除关键词", "list", "exclude")]]
        footer = []
    elif page == "groups":
        text = (
            title
            + "组合条件：组内全部满足，组间满足任意一组。最多 8 组；新组必须填写条件后才能保存。"
        )
        rows = [
            [b(f"编辑条件组 {i + 1}", "group", i), b("删除此组", "drop-group", i)]
            for i in range(len(d.config["rules"]["groups"]))
        ]
        rows += [
            [b("添加条件组", "add-group"), b("接收全部附件", "page", "all-offer")],
            [b("返回规则", "page", "rules")],
        ]
        footer = []
    elif page == "all-offer":
        text = "确认清除包含条件、接收所有类型附件？排除词和大小限制继续有效。仅保存后生效。"
        rows = [[b("确认接收全部", "all")], [b("返回组合条件", "page", "groups")]]
        footer = []
    elif page == "naming":
        text = (
            title
            + profile_summary(d.config["profile"])
            + "\n目录："
            + (d.config["profile"]["directory"] or "沿用默认")
        )
        rows = [
            [b("命名方式", "page", "naming-mode"), b("模板字段", "page", "template")],
            [b("清理前缀", "list", "prefixes"), b("清理后缀", "list", "suffixes")],
            [
                b("标题标记", "input", "label"),
                b("保存目录", "page", "profile-directory"),
            ],
            [
                b("预览命名", "page", "sample"),
                b("恢复默认方案", "page", "reset-profile"),
            ],
        ]
    elif page == "naming-mode":
        text = title + "选择命名方式："
        rows = [[b(label, "choice", "mode", key)] for key, label in MODES.items()] + [
            [b("返回命名", "page", "naming")]
        ]
        footer = []
    elif page == "template":
        text = (
            title
            + "命名模板："
            + d.config["profile"]["template"]
            + "\n点击增减字段；也可填写自定义模板。缺少的可选字段会省略。"
        )
        rows = [
            [
                b(
                    (
                        "☑ "
                        if "{" + key + "}" in d.config["profile"]["template"]
                        else "☐ "
                    )
                    + label,
                    "template",
                    key,
                )
            ]
            for key, label in FIELD_LABELS.items()
        ]
        rows += [
            [b("自定义模板", "input", "template"), b("返回命名", "page", "naming")]
        ]
        footer = []
    elif page == "reset-profile":
        text = "恢复兼容命名默认方案？将清除本草稿的模板定制、清理词和命名目录覆盖；保存前仍可取消整个草稿。"
        rows = [[b("确认恢复默认", "reset-profile")], [b("返回命名", "page", "naming")]]
        footer = []
    elif page in {"directory", "profile-directory"}:
        current = (
            d.config["profile"]["directory"]
            if page == "profile-directory"
            else d.config["directory"]
        )
        text = (
            title
            + "选择已授权目录\n当前："
            + (
                description(d.config)
                if page == "directory"
                else current or "沿用默认"
            )
        )
        rows = [
            [b(alias, "directory", page, alias)] for alias in repo.directories(actor)
        ]
        rows += [[b("沿用默认设置", "directory", page, "")]]
        if page == "directory":
            text += "\n来源目录分类独立于手动转存；只改变新计划，不移动已有文件。"
            rows.insert(0, [b("来源名称下按类型保存", "source-layout")])
            if d.config.get("directory_mode") == "source_type":
                text += "\n命名方案中的目录覆盖在此模式下不生效。"
        if page == "profile-directory":
            rows += [[b("返回命名", "page", "naming")]]
            footer = []
    elif page == "mode":
        text = (
            title
            + "转存模式："
            + ("确认后转存" if d.config["confirmation"] else "自动转存")
        )
        rows = [
            [
                b("自动转存", "choice", "confirmation", False),
                b("确认后转存", "choice", "confirmation", True),
            ]
        ]
    elif page == "sample":
        sample = d.sample
        from tg2cloud.telegram.views import format_bytes

        text = (
            title
            + "离线测试样例\n文件名："
            + sample["original"]
            + "\n说明："
            + sample["caption"]
            + "\n类型："
            + sample["kind"]
            + "\n大小："
            + format_bytes(sample["size"])
            + "\n不下载、不创建任务；不代表真实来源权限已通过。"
        )
        rows = [
            [
                b("修改文件名", "input", "sample-name"),
                b("修改说明", "input", "sample-caption"),
            ],
            [
                b("修改大小", "input", "sample-size"),
                b("修改类型", "page", "sample-type"),
            ],
            [b("测试当前样例", "preview")],
        ]
        if d.source is not None:
            rows += [[b("测试最近消息（草稿）", "recent")]]
        rows += [
            [
                b(
                    "返回编辑",
                    "page",
                    "naming" if d.kind in {"profile", "personal"} else "rules",
                )
            ]
        ]
        footer = []
    elif page == "sample-type":
        text = "选择样例媒体类型："
        rows = [[b(value, "sample-type", value)] for value in TYPES] + [
            [b("返回样例", "page", "sample")]
        ]
        footer = []
    elif page == "aliases":
        text = "目录别名管理\n仅管理员；路径是 Bot 上传根目录内的相对子目录，不是服务器绝对路径。"
        rows = [[b(row["alias"], "alias", row["alias"])] for row in aliases(repo)]
        rows += [[b("新增目录别名", "alias", "")], [b("返回转存设置", "cancel")]]
        footer = []
    elif page == "alias-edit":
        text = (
            title
            + "目录别名\n名称："
            + (d.config["alias"] or "待填写")
            + "\n相对目录："
            + (d.config["path"] or "待填写")
            + "\n授权："
            + ("、".join(str(i) for i in d.config["owners"]) or "仅管理员")
        )
        rows = [
            [
                b("填写别名", "input", "alias-name"),
                b("填写相对目录", "input", "alias-path"),
            ],
            [b("选择授权成员", "page", "alias-users")],
        ]
    elif page == "alias-users":
        text = title + "点击选择已授权家人；不选择表示仅管理员。"
        rows = [
            [
                b(
                    ("☑ " if user["id"] in d.config["owners"] else "☐ ") + user["name"],
                    "alias-user",
                    user["id"],
                )
            ]
            for user in repo.db.family_users(repo.admin)["users"]
            if user["enabled"]
        ]
        rows += [[b("返回目录设置", "page", "alias-edit")]]
        footer = []
    else:
        raise PlanningError("编辑页面已失效，请重新打开。")
    await ui().output(event, (notice + "\n\n" if notice else "") + text, rows + footer)


async def prompt(owner, event, d, key, operation="replace"):
    actor, _, d = require(owner, d.id, d.version)
    d.version += 1
    hints = {
        "min_bytes": "输入最小大小，例如 100 MB、1.5 GB；0 表示不限，纯数字按 MB。",
        "max_bytes": "输入最大大小，例如 2 GB；0 表示不限，纯数字按 MB。",
        "label": "输入说明中的标题标记，例如 标题：；输入 清空 取消标记。",
        "template": "填写模板，可使用 {title}、{episode} 等页面列出的字段，例如 {title} {episode}。",
        "sample-name": "输入样例文件名（包含后缀），例如 课程第1集.mp4；不是实际上传文件。",
        "sample-caption": "输入样例说明文字；输入 清空 表示没有说明。",
        "sample-size": "输入样例大小，例如 100 MB；需大于 0。",
        "alias-name": "输入便于选择的目录别名，例如 课程。",
        "alias-path": "输入 Bot 上传根目录内的相对目录，例如 课程/物理；不能以 / 开头。",
    }
    message = hints.get(
        key,
        "请输入"
        + LABELS.get(key, "内容")
        + "，每行一项；可填写多项。"
        + ("本次追加到列表。" if operation == "add" else "本次替换整份列表。"),
    )
    ui().interactions(owner)[actor] = (
        time.monotonic() + 300,
        ("editor-input", d.id, d.version, key, operation),
    )
    d.expires = time.monotonic() + 300
    await ui().output(
        event,
        message + "\n5 分钟内回复，填写完成后仍须保存草稿。",
        [[button(owner, actor, d, "取消填写", "page", d.page)]],
    )


async def save(owner, event, d):
    actor, repo, d = require(owner, d.id, d.version)
    if d.source is not None:
        config = repo.source_config(actor, d.config)
        if config.get("directory_mode") == "source_type" and config.get("source_folder"):
            try:
                media_directory(config, base=owner.settings.cd2_target)
            except ValueError:
                raise PlanningError("Bot 保存根目录已变化，请先核对并恢复配置；草稿尚未保存。") from None
        old = repo.source(actor, d.source)
        changed_layout = config.get("directory_mode", "legacy") != old["config"].get("directory_mode", "legacy")
        repo.change_source(actor, d.source, d.revision, config=config,
                           enabled=False if changed_layout else None,
                           target_base=owner.settings.cd2_target)
        if changed_layout and config.get("directory_mode") == "source_type":
            from tg2cloud.listening.service import ListenerReadError
            try:
                await owner.listener.prepare_directory(actor, repo.source(actor, d.source))
            except ListenerReadError:
                drafts(owner).pop(actor, None)
                ui().interactions(owner).pop(actor, None)
                await ui().source_card(owner, event, d.source)
                return
    elif d.kind == "personal":
        new_profile = profile(d.config["profile"])
        if d.original["auto_classify"] and new_profile["directory"] != d.original["profile"]["directory"]:
            if repo.preferences(actor) != d.original:
                raise PlanningError("配置已变化，请重新打开。")
            await ui().prepare_personal_classification(owner, repo, actor, {"profile": new_profile})
        with repo.transaction(actor):
            if repo.preferences(actor) != d.original:
                raise PlanningError("配置已变化，请重新打开。")
            repo.preferences(
                actor,
                {
                    "profile": new_profile,
                    "confirmation": d.config["confirmation"],
                },
            )
    else:
        with repo.transaction(actor, admin=True):
            if aliases(repo) != d.original:
                raise PlanningError("目录列表已变化，请重新打开。")
            if not d.config["alias"] or not d.config["path"]:
                raise PlanningError("请先填写目录别名和相对路径。")
            repo.set_directory(actor, **d.config)
    drafts(owner).pop(actor, None)
    ui().interactions(owner).pop(actor, None)
    await ui().output(
        event,
        "设置已保存，仅作用于新计划；已入队任务保持原名称和目录。"
        + ("\n目录模式已切换，来源已暂停；核对后点击启用。"
           if d.source is not None and changed_layout else ""),
        [
            [
                ui().token_button(
                    owner,
                    actor,
                    "返回监听来源" if d.source is not None else "返回转存设置",
                    ("source", d.source) if d.source is not None else ("settings",),
                )
            ]
        ],
    )


async def callback(owner, event, args):
    identity, version, operation, *values = args
    actor = current_user(owner.settings.allowed_user_id)
    d = None
    try:
        d = drafts(owner).get(actor)
        if (
            operation == "cancel"
            and d is not None
            and d.id == identity
            and d.version == version
        ):
            ui().store(owner).authorize(
                actor, admin=d.source is not None or d.kind == "aliases"
            )
            drafts(owner).pop(actor, None)
            ui().interactions(owner).pop(actor, None)
            if d.source is not None:
                await ui().source_card(owner, event, d.source)
            else:
                await ui().settings(owner, event)
            return
        actor, repo, d = require(owner, identity, version)
        if operation == "save":
            await save(owner, event, d)
            return
        if operation == "input":
            await prompt(owner, event, d, *values)
            return
        page = d.page
        if operation == "page":
            page = values[0]
        elif operation == "list":
            page = "list:" + values[0]
        elif operation in {"type", "sample-type"}:
            value = values[0]
            if value and value not in TYPES:
                raise PlanningError("媒体类型无效。")
            if operation == "sample-type":
                d.sample["kind"] = value
                page = "sample"
            else:
                types = group(d)["types"]
                if not value:
                    types.clear()
                elif value in types:
                    types.remove(value)
                else:
                    types.append(value)
        elif operation in {"clear", "remove"}:
            target = target_list(d, values[0])
            if operation == "clear":
                target.clear()
            elif type(values[1]) is int and 0 <= values[1] < len(target):
                target.pop(values[1])
            else:
                raise PlanningError("列表项已变化。")
            page = "list:" + values[0]
        elif operation == "choice":
            key, value = values
            allowed = {
                "scope": SCOPES,
                "exclude_scope": {"same", *SCOPES},
                "mode": MODES,
                "keyword_mode": {"any", "all"},
                "name_mode": NAMES,
                "confirmation": {True, False},
            }
            if key not in allowed or value not in allowed[key]:
                raise PlanningError("选项无效。")
            if key in {"keyword_mode", "name_mode"}:
                group(d)[key] = value
            elif key == "mode":
                d.config["profile"][key] = value
                page = "naming"
            elif key == "confirmation":
                d.config[key] = value
            elif key == "exclude_scope" and value == "same":
                d.config["rules"].pop(key, None)
            else:
                d.config["rules"][key] = value
        elif operation in {"group", "drop-group"}:
            index = values[0]
            if type(index) is not int or not 0 <= index < len(
                d.config["rules"]["groups"]
            ):
                raise PlanningError("条件组已变化。")
            if operation == "drop-group":
                d.config["rules"]["groups"].pop(index)
                d.group = 0
            else:
                d.group = index
                page = "rules"
        elif operation == "add-group":
            if len(d.config["rules"]["groups"]) >= 8:
                raise PlanningError("最多 8 个条件组。")
            d.config["rules"]["groups"].append(
                {
                    "types": [],
                    "extensions": [],
                    "names": [],
                    "name_mode": "contains",
                    "keywords": [],
                    "keyword_mode": "any",
                }
            )
            d.config["rules"]["all_attachments"] = False
            d.group = len(d.config["rules"]["groups"]) - 1
            page = "rules"
        elif operation == "all":
            d.config["rules"].update(groups=[], all_attachments=True)
            page = "rules"
        elif operation == "template":
            key = values[0]
            if key not in FIELDS:
                raise PlanningError("模板字段无效。")
            token = "{" + key + "}"
            current = d.config["profile"]["template"]
            d.config["profile"]["template"] = (
                current.replace(token, "").strip()
                if token in current
                else (current + " " + token).strip()
            )
        elif operation == "reset-profile":
            d.config["profile"] = profile()
            page = "naming"
        elif operation == "source-layout":
            if d.source is None:
                raise PlanningError("来源目录仅适用于监听来源")
            d.config["directory_mode"] = "source_type"
            d.config["directory"] = ""
            page = "directory"
        elif operation == "directory":
            target, alias = values
            path = repo.directory(actor, alias) or ""
            if target == "profile-directory":
                d.config["profile"]["directory"] = path
                page = "naming"
            elif target == "directory":
                d.config["directory"] = alias
                d.config["directory_mode"] = "legacy"
            else:
                raise PlanningError("目录选项无效。")
        elif operation == "alias":
            import json

            value = next((r for r in aliases(repo) if r["alias"] == values[0]), None)
            if values[0] and value is None:
                raise PlanningError("目录别名已变化。")
            d.config = (
                {
                    "alias": value["alias"],
                    "path": value["path"],
                    "owners": json.loads(value["owners"]),
                }
                if value
                else {"alias": "", "path": "", "owners": []}
            )
            page = "alias-edit"
        elif operation == "alias-user":
            user = values[0]
            if not any(
                r["id"] == user and r["enabled"]
                for r in repo.db.family_users(repo.admin)["users"]
            ):
                raise PlanningError("成员授权已变化。")
            target = d.config["owners"]
            target.remove(user) if user in target else target.append(user)
        elif operation == "preview":
            sample = d.sample
            result = name_plan(
                sample["original"],
                sample["caption"],
                "样例.mp4",
                kind=sample["kind"],
                extension=Path(sample["original"]).suffix,
                options=d.config["profile"],
            )
            text = "命名预览：" + result["file_name"] + "\n依据：" + result["basis"]
            if "rules" in d.config:
                matched, reason = rules.explain(
                    d.config["rules"],
                    sample
                    | {
                        "attachment": True,
                        "protected": False,
                        "extension": Path(sample["original"]).suffix,
                    },
                    source_allowed=True,
                )
                text = ("匹配：" if matched else "跳过：") + reason + "\n" + text
            await show(owner, event, d, "sample", text)
            return
        elif operation == "recent":
            from tg2cloud.telegram.listening_tools import test_result
            results = await owner.listener.test(
                actor, d.source, config=copy.deepcopy(d.config)
            )
            require(owner, identity, version)
            text = "草稿最近消息测试（只读，不登记任务）\n" + (
                "\n".join(
                    test_result(mid, matched, reason, naming)
                    for mid, matched, reason, naming in results
                )
                or "没有可测试的最近消息。"
            )
            await show(owner, event, d, "sample", text)
            return
        else:
            raise PlanningError("编辑操作无效，请刷新。")
        await show(owner, event, d, page)
    except (ValueError, TypeError, KeyError, IndexError, PermissionError) as exc:
        text = (
            str(exc)
            if isinstance(exc, PlanningError)
            else "填写内容或配置已变化，请重新打开核对。"
        )
        rows = (
            [[button(owner, actor, d, "返回编辑", "page", d.page)]]
            if d and drafts(owner).get(actor) is d
            else [
                [
                    ui().token_button(
                        owner,
                        actor,
                        "返回监听管理"
                        if actor == owner.settings.allowed_user_id
                        else "返回转存设置",
                        ("listen",)
                        if actor == owner.settings.allowed_user_id
                        else ("settings",),
                    )
                ]
            ]
        )
        await ui().output(event, "设置未保存：" + text, rows)


async def text(owner, event, args, value):
    identity, version, key, operation = args
    actor = current_user(owner.settings.allowed_user_id)
    try:
        actor, repo, d = require(owner, identity, version)
        if not isinstance(value, str) or len(value) > 8192:
            raise PlanningError("输入过长，最多 8192 字。")
        if key in LABELS:
            values = lines_input(value, key)
            target = target_list(d, key)
            candidate = (
                list(dict.fromkeys([*target, *values]))
                if operation == "add"
                else values
            )
            limit = 12 if key in {"prefixes", "suffixes"} else 20
            if len(candidate) > limit:
                raise PlanningError(f"最多 {limit} 项，请先删除多余项。")
            target[:] = candidate
            page = "list:" + key
        elif key in {"min_bytes", "max_bytes"}:
            result = size_input(value)
            r = d.config["rules"]
            minimum = result if key == "min_bytes" else r["min_bytes"]
            maximum = result if key == "max_bytes" else r["max_bytes"]
            if maximum and minimum > maximum:
                raise PlanningError("最小大小不能超过最大大小。")
            r[key] = result
            page = "sizes"
        elif key in {"label", "template"}:
            candidate = d.config["profile"] | {
                key: "" if value.strip() == "清空" else value.strip()
            }
            d.config["profile"] = profile(candidate)
            page = "naming"
        elif key.startswith("sample-"):
            if key == "sample-size":
                result = size_input(value)
                if result <= 0:
                    raise PlanningError("样例大小需大于 0。")
                d.sample["size"] = result
            elif key == "sample-name":
                if (
                    not value.strip()
                    or len(value) > 250
                    or any(ord(c) < 32 or c in "/\\" for c in value)
                ):
                    raise PlanningError("请输入不含路径或控制字符的样例文件名。")
                d.sample["original"] = value.strip()
            elif key == "sample-caption":
                d.sample["caption"] = "" if value.strip() == "清空" else value
            else:
                raise PlanningError("样例字段无效。")
            page = "sample"
        elif key in {"alias-name", "alias-path"}:
            if key == "alias-name":
                v = value.strip()
                if not 1 <= len(v) <= 32 or any(ord(c) < 32 or c in "/:%" for c in v):
                    raise PlanningError("别名应为 1 至 32 字，不能包含路径或控制字符。")
                if v != d.config["alias"] and any(
                    r["alias"] == v for r in aliases(repo)
                ):
                    raise PlanningError("已有同名别名，请从列表中选择修改。")
                if (
                    d.config["alias"]
                    and any(r["alias"] == d.config["alias"] for r in d.original)
                    and v != d.config["alias"]
                ):
                    raise PlanningError(
                        "已有别名被来源引用，请保持名称，仅修改路径或授权。"
                    )
                d.config["alias"] = v
            else:
                d.config["path"] = safe_directory(value.strip())
            page = "alias-edit"
        else:
            raise PlanningError("输入已失效，请重新选择字段。")
        await show(owner, event, d, page)
    except (ValueError, KeyError, TypeError, PermissionError) as exc:
        text = (
            str(exc)
            if isinstance(exc, PlanningError)
            else "输入格式或配置不可确认，请重新填写。"
        )
        d = drafts(owner).get(actor)
        rows = (
            [[button(owner, actor, d, "取消填写", "page", d.page)]]
            if d and d.id == identity
            else [
                [
                    ui().token_button(
                        owner,
                        actor,
                        "返回监听管理"
                        if actor == owner.settings.allowed_user_id
                        else "返回转存设置",
                        ("listen",)
                        if actor == owner.settings.allowed_user_id
                        else ("settings",),
                    )
                ]
            ]
        )
        await ui().output(event, "尚未保存：" + text, rows)
    return True
