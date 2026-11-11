"""Optional transfer previews and administrator listening UI; no attachment capture."""

from __future__ import annotations

import json
import secrets
import time

from telethon import Button

from tg2cloud.domain.actors import current_user
from tg2cloud.domain.classification import MANUAL_MEDIA
from tg2cloud.domain.classification import directory as classified_directory
from tg2cloud.domain.planning import PlanningError, name_plan, profile
from tg2cloud.domain.source_directories import description
from tg2cloud.listening import account, rules
from tg2cloud.persistence.plans import Plans
from tg2cloud.telegram.reactions import PENDING, REJECTED
from tg2cloud.telegram.views import format_bytes
from tg2cloud.transfer.destination import prepare_media_directories


def store(owner):
    return Plans(owner.db, owner.settings.allowed_user_id)


def interactions(owner):
    if not hasattr(owner, "_plan_interactions"):
        owner._plan_interactions = {}
    now = time.monotonic()
    owner._plan_interactions = {
        k: v for k, v in owner._plan_interactions.items() if v[0] > now
    }
    return owner._plan_interactions


def token_button(owner, actor, label, action):
    if not hasattr(owner, "_plan_buttons"):
        owner._plan_buttons = {}
    now = time.monotonic()
    owner._plan_buttons = {k: v for k, v in owner._plan_buttons.items() if v[0] > now}
    if len(owner._plan_buttons) >= 1024:
        owner._plan_buttons.clear()
    token = secrets.token_hex(8)
    owner._plan_buttons[token] = (now + 300, actor, action)
    return Button.inline(label, data=("planui:" + token).encode())


async def output(event, text, buttons=None):
    # Telethon supports reply on messages and edit on callbacks. Plain text, no markup injection.
    # Telegram limits text by UTF-16 units. Long names/feedback must not make
    # an already-persisted operation look like it failed to the user.
    chunks, part, units = [], [], 0
    for char in text:
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > 3500:
            chunks.append("".join(part))
            part, units = [], 0
        part.append(char)
        units += width
    chunks.append("".join(part))
    for index, chunk in enumerate(chunks):
        keyboard = buttons if index == len(chunks) - 1 else None
        if index == 0:
            send = event.edit if hasattr(event, "data") else event.reply
        else:
            send = event.respond
        await send(chunk, buttons=keyboard, parse_mode=None)


async def ask(owner, event, action, prompt):
    actor = current_user(owner.settings.allowed_user_id)
    interactions(owner)[actor] = (time.monotonic() + 300, action)
    back = ("source", action[1]) if action[0] == "tools-name" else ("listen",) if action[0] == "add" else ("view", action[1]) if action[0] == "rename" else ("settings",)
    await output(event, prompt + "\n5 分钟内回复文本。发送附件仍正常转存。",
                 [[token_button(owner, actor, "取消填写", ("cancelinput", back))]])


async def plan_card(owner, event, plan):
    actor = current_user(owner.settings.allowed_user_id)
    value = plan["payload"]
    rows = []
    if plan["status"] == "pending":
        key = (plan["id"], plan["revision"])
        rows = [
            [
                token_button(owner, actor, "确认转存", ("approve", *key)),
                token_button(owner, actor, "修改名称", ("rename", *key)),
            ],
            [
                token_button(owner, actor, "选择目录", ("directory", *key)),
                token_button(owner, actor, "忽略本次", ("ignore", *key)),
            ],
            [token_button(owner, actor, "批次操作", ("batch", *key))],
        ]
    status = {"pending": "待确认", "submitted": "已入队", "ignored": "已忽略", "expired": "已过期"}.get(plan["status"], "状态待核对")
    directory = value["directory_override"]
    if value["classification_options"]["classification"] == MANUAL_MEDIA:
        directory = classified_directory(
            value["classification_options"], value["created_at"], kind=value["media_kind"],
            mime=value["mime_type"], extension=value["media_extension"], parent=directory,
        )
    directory = "现有分类与默认目录" if directory is None else directory or "Bot 保存目录（无附加子目录）"
    text = (
        f"📦 转存计划 #{plan['id']}\n状态：{status}\n原名：{value['original_file_name'] or '无原名'}"
        f"\n候选：{value['file_name']}\n目录：{directory}"
        f"\n大小：{format_bytes(value['file_size'])}\n依据：{value['basis']}"
    )
    if plan["source"] is not None:
        source = store(owner).source(actor, plan["source"])
        text += f"\n监听来源：{source['title']}\n规则快照：版本 {value['source_revision']}；按接收时的规则匹配"
    rows.append([token_button(owner, actor, "返回待确认列表", ("pending", 0))])
    await output(event, text, rows)


async def submit(owner, actor, plan_id, revision):
    repo = store(owner)
    p = repo.get(actor, plan_id)
    if p["payload"]["target_base"] != owner.settings.cd2_target:
        raise ValueError("Bot 上传根目录已变化；请重新建立计划，不自动切换目录")
    if p["source"] is not None and p["status"] == "pending":
        from tg2cloud.listening.service import CheckedSource

        owner.listener.require_admin(actor)
        data = p["payload"]
        reader = CheckedSource(
            owner.listener,
            {
                "sender_id": actor,
                "read_identity": p["identity"],
                "source_id": p["source"],
                "message_id": p["message"],
                "media_key": data["media_key"],
            },
        )
        await reader.get_messages(p["chat"], ids=p["message"])
    task, created = repo.submit(actor, plan_id, revision)
    if p["source"] is None:
        owner._mark_task_delivery(p["chat"], p["message"], task, created)
    return task, created


async def pending(owner, event, after=0):
    actor = current_user(owner.settings.allowed_user_id)
    plans = store(owner).pending(actor, after)
    buttons = [
        [
            token_button(
                owner,
                actor,
                f"#{p['id']} {p['payload']['file_name'][:25]}",
                ("view", p["id"]),
            )
        ]
        for p in plans
    ]
    if len(plans) == 10:
        buttons.append(
            [token_button(owner, actor, "下一页", ("pending", plans[-1]["id"]))]
        )
    buttons.append([token_button(owner, actor, "返回监听管理" if actor == owner.settings.allowed_user_id else "返回转存设置", ("listen",) if actor == owner.settings.allowed_user_id else ("settings",))])
    await output(
        event,
        "待确认转存\n\n"
        + (
            "选择计划；最多保留 7 天，确认前不下载、不预留额度。"
            if plans
            else "暂无待确认记录。"
        ),
        buttons,
    )


async def settings(owner, event):
    actor = current_user(owner.settings.allowed_user_id)
    prefs = store(owner).preferences(actor)
    from tg2cloud.telegram.editor import MODES

    rows = [
        [
            token_button(
                owner,
                actor,
                "切换确认模式",
                ("confirmation", not prefs["confirmation"]),
            ),
            token_button(owner, actor, "命名设置", ("preferences",)),
        ],
        [
            token_button(owner, actor, "待确认列表", ("pending", 0)),
            token_button(owner, actor, "修正记录", ("feedback",)),
        ],
        [token_button(owner, actor, "关闭自动分类" if prefs["auto_classify"] else "开启自动分类",
                      ("auto-classify", prefs["auto_classify"]))],
    ]
    navigation = []
    if actor == owner.settings.allowed_user_id:
        navigation.append(token_button(owner, actor, "目录别名管理", ("aliases",)))
    navigation.append(Button.inline("返回系统状态", data=b"menu:home"))
    rows.append(navigation)
    await output(
        event,
        "转存设置\n确认模式："
        + ("开启" if prefs["confirmation"] else "关闭（默认自动转存）")
        + "\n命名模式："
        + MODES[prefs["profile"]["mode"]]
        + "\n自动分类："
        + ("开启（视频、图片、其它）" if prefs["auto_classify"] else "关闭")
        + "\n仅影响新计划；已入队任务保持原名称和目录。",
        rows,
    )


async def prepare_personal_classification(owner, repo, actor, prefs):
    parent, _ = repo.personal_directory(actor, prefs)
    try:
        await prepare_media_directories(owner.rclone, parent)
    except (OSError, RuntimeError, ValueError):
        raise PlanningError("分类目录创建失败，请检查保存目录和 WebDAV 权限后重试。") from None


async def listening(owner, event):
    actor = current_user(owner.settings.allowed_user_id)
    owner.listener.require_admin(actor)
    value = account.state(owner.db)
    rows = [
        [
            token_button(owner, actor, "启用监听账号", ("account", True)),
            token_button(owner, actor, "停用监听账号", ("account", False)),
        ],
        [
            token_button(owner, actor, "添加来源", ("add",)),
            token_button(owner, actor, "待确认列表", ("pending", 0)),
        ],
    ]
    rows.append([Button.inline("返回系统状态", data=b"menu:home")])
    for source in store(owner).sources(actor):
        rows.append(
            [
                token_button(
                    owner,
                    actor,
                    source["title"][:30]
                    + (" · 启用" if source["enabled"] else " · 暂停"),
                    ("source", source["id"]),
                )
            ]
        )
    await output(
        event,
        "监听管理（仅管理员）\n\n账号："
        + value["status"]
        + "\n首次登录：在 VPS 运行 tg2cloud，选择“监听管理”→“登录监听账号”。\n默认关闭；仅接收已加入来源的新附件，不读取评论、不自动重处理消息编辑。",
        rows,
    )


async def source_card(owner, event, source_id):
    actor = current_user(owner.settings.allowed_user_id)
    owner.listener.require_admin(actor)
    repo = store(owner)
    s = repo.source(actor, source_id)
    sid, rev = s["id"], s["revision"]
    buttons = [
        [
            token_button(
                owner,
                actor,
                "暂停" if s["enabled"] else "启用",
                ("source-enable", sid, rev, not s["enabled"]),
            ),
            token_button(owner, actor, "测试规则", ("test", sid)),
        ],
        [
            token_button(owner, actor, "筛选规则", ("rules", sid, rev)),
            token_button(owner, actor, "命名方案", ("profile", sid, rev)),
        ],
        [
            token_button(owner, actor, "保存目录", ("source-directory", sid, rev)),
            token_button(owner, actor, "切换自动与确认", ("source-confirm", sid, rev)),
        ],
        [
            token_button(owner, actor, "删除来源", ("delete-offer", sid, rev)),
            token_button(owner, actor, "返回监听管理", ("listen",)),
        ],
    ]
    buttons += [[token_button(owner, actor, "规则方案", ("listen-tool", "templates", sid)),
                 token_button(owner, actor, "失败恢复", ("listen-tool", "failures", sid))],
                [token_button(owner, actor, "历史补拉", ("listen-tool", "history", sid))]]
    if "目录创建未完成" in s["status"]:
        buttons.append([token_button(owner, actor, "重试创建目录", ("source-directory-retry", sid, rev))])
    buttons.append([token_button(owner, actor, "命名规则历史与撤销", ("history", sid))])
    from tg2cloud.telegram.editor import MODES, rule_summary

    stats = {
        r[0]: r[1]
        for r in owner.db._conn.execute(
            "SELECT result,count(*) FROM listener_events WHERE source=? GROUP BY result",
            (sid,),
        )
    }
    counts = owner.db._conn.execute(
        "SELECT count(*),COALESCE(sum(is_attachment),0),COALESCE(sum(matched),0) FROM listener_events WHERE source=?",
        (sid,),
    ).fetchone()
    waiting = owner.db._conn.execute(
        "SELECT count(*) FROM transfer_plans WHERE source=? AND status='pending' AND expires>?",
        (sid, time.time()),
    ).fetchone()[0]
    from tg2cloud.listening.management import destination
    try:
        directory_preview = destination(owner, actor, s)
    except ValueError:
        directory_preview = "目录绑定待核对，请检查保存目录"
    wait_summary = owner.listener.wait_summary(source_id=sid)
    summary = f"收到 {counts[0]} · 附件 {counts[1]} · 匹配 {counts[2]} · 跳过 {counts[0] - counts[2]} · 待确认 {waiting} · 入队 {stats.get('已入队', 0)}"
    await output(
        event,
        f"来源 #{sid}：{s['title']}\n启用从当前时点开始，暂停期间不补抓；重启补拉最多 6 小时。\n状态：{s['status']}\n规则版本：{rev}\n模式：{'确认后转存' if s['config']['confirmation'] else '自动转存'}"
        f"\n目录：{description(s['config'])}\n视频保存预览：{directory_preview}\n"
        + rule_summary(s['config']['rules'], compact=True) + "\n命名：" + MODES[s['config']['profile']['mode']]
        + ("\n" + wait_summary if wait_summary else "")
        + f"\n{summary}\n最近接收：" + ("；".join(f"{key} {value}" for key, value in stats.items()) or "暂无记录"),
        buttons,
    )


async def command(owner, event, text):
    command = text.split()[0].split("@")[0].lower()
    if command not in {"/listen", "/pending", "/transfer", "/cancelinput"}:
        return False
    actor = current_user(owner.settings.allowed_user_id)
    try:
        store(owner).authorize(actor, admin=command == "/listen")
        if command == "/listen":
            await listening(owner, event)
        elif command == "/pending":
            await pending(owner, event)
        elif command == "/transfer":
            await settings(owner, event)
        else:
            interactions(owner).pop(actor, None)
            await output(event, "已取消文本设置；转存任务保持不变。")
    except (ValueError, PermissionError):
        await output(event, "无权操作，或设置暂不可用；请刷新菜单。")
    return True


async def callback(owner, event):
    raw = bytes(event.data)
    if raw == b"menu:listen":
        await event.answer()
        try:
            await listening(owner, event)
        except PermissionError:
            await output(event, "此功能仅限管理员。")
        return True
    if raw == b"menu:transfer":
        await event.answer()
        await settings(owner, event)
        return True
    if not raw.startswith(b"planui:"):
        return False
    actor = current_user(owner.settings.allowed_user_id)
    token = raw[7:].decode("ascii", errors="replace")
    record = getattr(owner, "_plan_buttons", {}).get(token)
    if not record or record[0] < time.monotonic() or record[1] != actor:
        await event.answer("按钮已失效或无权使用，请重新打开菜单。", alert=True)
        return True
    # Consume only for the authorized actor. Concurrent clicks cannot perform two writes.
    owner._plan_buttons.pop(token, None)
    await event.answer()
    action, *args = record[2]
    repo = store(owner)
    try:
        repo.authorize(actor)
        if action in {
            "listen",
            "add",
            "account",
            "source",
            "source-enable",
            "test",
            "rules",
            "profile",
            "source-directory", "source-directory-retry",
            "source-confirm",
            "delete-offer",
            "delete",
            "history",
            "restore-rule",
            "restore-offer",
            "save-feedback",
        }:
            owner.listener.require_admin(actor)
        if action == "listen-tool":
            from tg2cloud.telegram import listening_tools
            await listening_tools.callback(owner, event, args)
        elif action == "editor":
            from tg2cloud.telegram import editor
            await editor.callback(owner, event, args)
        elif action == "settings":
            await settings(owner, event)
        elif action == "auto-classify":
            prefs = repo.preferences(actor)
            if prefs["auto_classify"] != args[0]:
                raise PlanningError("自动分类设置已变化，请重新打开转存设置。")
            enabled = not prefs["auto_classify"]
            if enabled:
                await prepare_personal_classification(owner, repo, actor, prefs)
            with repo.transaction(actor):
                if repo.preferences(actor) != prefs:
                    raise PlanningError("转存设置已变化，请重新打开。")
                repo.preferences(actor, {"auto_classify": enabled})
            await settings(owner, event)
        elif action == "cancelinput":
            interactions(owner).pop(actor, None)
            await output(event, "已取消填写，配置和任务未改变。", [[token_button(owner, actor, "返回", args[0])]])
        elif action in {"rules", "profile", "source-directory", "source-confirm", "preferences", "aliases"}:
            from tg2cloud.telegram import editor
            kind = {"rules": "rules", "profile": "profile", "source-directory": "directory",
                    "source-confirm": "mode", "preferences": "personal", "aliases": "aliases"}[action]
            await editor.start(owner, event, kind, *args)
        elif action == "listen":
            await listening(owner, event)
        elif action == "account":
            if args[0] and not account.state(owner.db)["account"]:
                raise ValueError("请先在 VPS 终端登录个人账号")
            account.write_state(
                owner.db, enabled=args[0], status="等待连接" if args[0] else "已停用"
            )
            await listening(owner, event)
        elif action == "add":
            await ask(
                owner,
                event,
                ("add",),
                "发送已加入来源的 @用户名、聊天 ID 或链接；自动创建来源目录，按类型归档。添加后暂停、确认后转存。默认仅视频、至少 50 MB，排除广告、内部群、搜索引擎。",
            )
        elif action == "source":
            await source_card(owner, event, args[0])
        elif action == "source-directory-retry":
            source = repo.source(actor, args[0])
            if source["revision"] != args[1]:
                raise PlanningError("来源已变化，请刷新")
            await owner.listener.prepare_directory(actor, source)
            await source_card(owner, event, args[0])
        elif action in {"source-enable", "delete", "source-confirm"}:
            sid, rev = args[:2]
            s = repo.source(actor, sid)
            if action == "source-enable" and args[2]:
                from tg2cloud.listening.service import verified_chat

                if not owner.listener.client:
                    raise ValueError("监听账号未连接")
                await verified_chat(owner.listener.client, s["chat"])
                await owner.listener.prepare_directory(actor, s)
            cursor = None
            if action == "source-enable" and args[2]:
                latest = await owner.listener.client.get_messages(s["chat"], limit=1)
                cursor = latest[0].id if latest else 0
            config = (
                s["config"] | {"confirmation": not s["config"]["confirmation"]}
                if action == "source-confirm"
                else None
            )
            repo.change_source(
                actor,
                sid,
                rev,
                config=config,
                enabled=args[2] if action == "source-enable" else None,
                delete=action == "delete",
                cursor=cursor,
            )
            await listening(owner, event) if action == "delete" else await source_card(
                owner, event, sid
            )
        elif action == "delete-offer":
            await output(
                event,
                "确认删除此监听来源？停止新接收，保留任务和云端文件。",
                [[token_button(owner, actor, "确认删除", ("delete", *args))],
                 [token_button(owner, actor, "取消返回来源", ("source", args[0]))]],
            )
        elif action == "test":
            results = await owner.listener.test(actor, args[0])
            from tg2cloud.telegram.listening_tools import test_result
            await output(
                event,
                "规则测试（只读，无任务、额度和进度副作用）\n"
                + "\n".join(
                    test_result(mid, matched, reason, name)
                    for mid, matched, reason, name in results
                ),
                [[token_button(owner, actor, "返回来源", ("source", args[0]))]],
            )
        elif action == "pending":
            await pending(owner, event, args[0])
        elif action == "view":
            await plan_card(owner, event, repo.get(actor, args[0]))
        elif action in {"approve", "ignore", "rename", "directory", "batch"}:
            plan = repo.get(actor, args[0])
            if plan["status"] != "pending" or plan["revision"] != args[1]:
                raise ValueError("计划已变化或已处理")
            if action == "approve":
                task, _ = await submit(owner, actor, *args)
                await output(
                    event,
                    f"已持久化到现有队列：任务 #{task['id']}\n最终重名后缀以任务详情为准。",
                    [[token_button(owner, actor, "返回待确认列表", ("pending", 0))]],
                )
            elif action == "ignore":
                ignored = repo.edit(actor, *args, ignore=True)
                if ignored["source"] is None:
                    owner.reactions.queue(ignored["chat"], ignored["message"], REJECTED)
                await plan_card(owner, event, ignored)
            elif action == "rename":
                await ask(
                    owner,
                    event,
                    ("rename", *args),
                    "输入本次名称；保留原媒体扩展名，不会自动保存为规则。",
                )
            elif action == "directory":
                rows = [
                    [
                        token_button(
                            owner, actor, alias, ("choose-directory", *args, alias)
                        )
                    ]
                    for alias in repo.directories(actor)
                ]
                await output(
                    event, "选择已授权目录（替换分类子目录，不重复追加）：",
                    rows + [[token_button(owner, actor, "返回计划详情", ("view", plan["id"]))]],
                )
            else:
                await output(
                    event,
                    "本批次最多 20 项；逐项重新核验权限、版本和额度，部分失败会保留待确认。",
                    [
                        [
                            token_button(
                                owner, actor, "确认本批次", ("batch-approve", *args)
                            )
                        ],
                        [
                            token_button(
                                owner, actor, "批次选择目录", ("batch-directory", *args)
                            )
                        ],
                        [
                            token_button(
                                owner, actor, "批次修改共同主题", ("batch-name", *args)
                            )
                        ],
                        [token_button(owner, actor, "返回计划详情", ("view", plan["id"]))],
                    ],
                )
        elif action == "choose-directory":
            await plan_card(
                owner,
                event,
                repo.edit(actor, args[0], args[1], directory_alias=args[2]),
            )
        elif action in {"batch-approve", "batch-directory", "batch-name"}:
            p = repo.get(actor, args[0])
            if not p["batch"] or p["revision"] != args[1] or p["status"] != "pending":
                raise ValueError("批次已变化或不可用")
            ids = [
                (r["id"], r["revision"])
                for r in owner.db._conn.execute(
                    "SELECT id,revision FROM transfer_plans WHERE owner=? AND batch=? AND status='pending' AND expires>? ORDER BY id LIMIT 21",
                    (actor, p["batch"], time.time()),
                )
            ]
            if len(ids) > 20:
                raise ValueError("批次超过 20 项，请逐项处理")
            if action == "batch-approve":
                good = 0
                for pid, rev in ids:
                    try:
                        await submit(owner, actor, pid, rev)
                        good += 1
                    except (ValueError, RuntimeError):
                        pass
                await output(
                    event,
                    f"本批次已入队 {good}/{len(ids)} 项；其余保留待确认，请核对额度、有效期和权限。",
                    [[token_button(owner, actor, "返回待确认列表", ("pending", 0))]],
                )
            else:
                if action == "batch-directory":
                    await output(event, "选择本批次已授权目录：", [[token_button(owner, actor, alias, ("batch-set-directory", ids, alias))] for alias in repo.directories(actor)] + [[token_button(owner, actor, "返回计划详情", ("view", p["id"]))]])
                else:
                    await ask(owner, event, (action, ids), "发送新的共同主题（各成员集数、章节和扩展名保留）。")
        elif action == "batch-set-directory":
            ids, alias = args
            if not ids or len(ids) > 20:
                raise PlanningError("批次数量无效。")
            with repo.transaction(actor):
                repo.directory(actor, alias)
                for pid, rev in ids:
                    repo.edit(actor, pid, rev, directory_alias=alias)
            await pending(owner, event)
        elif action == "confirmation":
            from tg2cloud.telegram import editor
            await editor.start(owner, event, "personal", page="mode")
        elif action == "history":
            source = repo.source(actor, args[0])
            history = repo.source_history(actor, args[0])
            await output(
                event,
                "选择恢复某次完整来源配置；仅作用于新计划。",
                [
                    [
                        token_button(
                            owner,
                            actor,
                            f"恢复版本 {r['revision']}",
                            ("restore-offer", source["id"], source["revision"], r["id"]),
                        )
                    ]
                    for r in history
                ] + [[token_button(owner, actor, "返回来源", ("source", source["id"]))]],
            )
        elif action == "restore-offer":
            from tg2cloud.telegram.editor import profile_summary, rule_summary
            source = repo.source(actor, args[0])
            if source["revision"] != args[1]:
                raise PlanningError("来源配置已变化，请刷新历史列表。")
            old = next((r for r in repo.source_history(actor, args[0]) if r["id"] == args[2]), None)
            if old is None:
                raise PlanningError("历史版本已失效。")
            binding = {key: source["config"].get(key, default) for key, default in
                       (("source_folder", ""), ("source_base", None))}
            candidate = repo.source_config(actor, json.loads(old["config"]) | binding)
            def describe(c):
                return rule_summary(c["rules"]) + "\n" + profile_summary(c["profile"]) + "\n目录：" + description(c) + "\n模式：" + ("确认后转存" if c["confirmation"] else "自动转存")
            await output(event, "恢复范围：筛选、命名、目录和转存模式；仅作用于新计划。\n\n当前配置：\n" + describe(source["config"]) + "\n\n拟恢复版本 " + str(old["revision"]) + "：\n" + describe(candidate),
                         [[token_button(owner, actor, "确认恢复此版本", ("restore-rule", *args))],
                          [token_button(owner, actor, "取消返回来源", ("source", source["id"]))]])
        elif action == "restore-rule":
            history = repo.source_history(actor, args[0])
            old = next((r for r in history if r["id"] == args[2]), None)
            if not old:
                raise ValueError("历史版本已失效")
            current = repo.source(actor, args[0])
            binding = {key: current["config"].get(key, default) for key, default in
                       (("source_folder", ""), ("source_base", None))}
            repo.change_source(
                actor, args[0], args[1], config=json.loads(old["config"]) | binding,
                target_base=owner.settings.cd2_target,
            )
            restored = repo.source(actor, args[0])
            if restored["config"].get("directory_mode") == "source_type":
                await owner.listener.prepare_directory(actor, restored)
            await source_card(owner, event, args[0])
        elif action == "save-feedback":
            repo.apply_feedback(actor, *args)
            await output(
                event,
                "已明确保存为此来源的前缀规则；其他来源和已提交任务保持不变，可在命名规则历史中撤销。",
            )
        elif action == "feedback":
            items = repo.feedback(actor)
            buttons = []
            if actor == owner.settings.allowed_user_id:
                from pathlib import Path

                for r in items:
                    before, after = (
                        Path(r["before_name"]).stem,
                        Path(r["after_name"]).stem,
                    )
                    if (
                        r["source"] is not None
                        and r["operation"] == "仅本次"
                        and after
                        and before.endswith(after)
                        and 1 <= len(before) - len(after) <= 80
                    ):
                        source = repo.source(actor, r["source"])
                        buttons.append(
                            [
                                token_button(
                                    owner,
                                    actor,
                                    "确认保存前缀规则 #" + str(r["id"]),
                                    ("save-feedback", r["id"], source["revision"]),
                                )
                            ]
                        )
            await output(
                event,
                "最近人工修正（只影响本次，没有自动学习规则）\n"
                + "\n".join(
                    f"#{r['id']} {r['before_name']} → {r['after_name']}" for r in items
                )
                + "\n需要保存为来源规则时，打开“命名方案”逐项设置清理前缀／后缀；历史中可预览并恢复。",
                buttons + [[token_button(owner, actor, "返回转存设置", ("settings",))]],
            )
    except (ValueError, PermissionError, RuntimeError) as exc:
        from tg2cloud.listening.service import ListenerReadError
        from tg2cloud.persistence.quotas import QuotaExceeded

        message = (
            str(exc)
            if isinstance(exc, (PlanningError, ListenerReadError, QuotaExceeded))
            else "设置、权限或记录版本不可确认；请刷新对应页面核对后重试。"
        )
        await output(event, message[:300])
    except Exception:  # noqa: BLE001 - private boundary must not expose credentials
        await output(
            event,
            "操作未完成；请检查监听账号、来源权限及限流状态后重试。未输出账号凭据。",
        )
    return True


async def text(owner, event, value):
    actor = current_user(owner.settings.allowed_user_id)
    pending_action = interactions(owner).get(actor)
    if not pending_action:
        return False
    action, *args = pending_action[1]
    if action == "editor-input":
        from tg2cloud.telegram import editor
        return await editor.text(owner, event, args, value)
    repo = store(owner)
    try:
        repo.authorize(
            actor,
            admin=action in {"add", "rules", "profile", "source-directory", "aliases"},
        )
        if len(value) > 8192:
            raise ValueError("文本过长")
        if action == "tools-name":
            from tg2cloud.telegram import listening_tools
            await listening_tools.name_input(owner, event, args, value)
            return True
        if action == "add":
            source = await owner.listener.add(
                actor,
                value,
                {"rules": rules.defaults(), "confirmation": True},
            )
            interactions(owner).pop(actor, None)
            await source_card(owner, event, source["id"])
            return True
        if action in {"rules", "profile", "source-directory"}:
            s = repo.source(actor, args[0])
            config = s["config"].copy()
            key = {
                "rules": "rules",
                "profile": "profile",
                "source-directory": "directory",
            }[action]
            config[key] = (
                ("" if value == "默认" else value)
                if action == "source-directory"
                else json.loads(value)
            )
            repo.change_source(actor, *args, config=config)
            await source_card(owner, event, args[0])
        elif action == "rename":
            await plan_card(owner, event, repo.edit(actor, *args, name=value))
        elif action in {"batch-name", "batch-directory"}:
            from tg2cloud.domain.planning import fields

            with repo.transaction(actor):
                for pid, rev in args[0]:
                    p = repo.get(actor, pid)
                    data = fields(
                        p["payload"]["original_file_name"]
                        + " "
                        + p["payload"]["file_name"]
                    )
                    name = (
                        value
                        + " "
                        + " ".join(s for s in (data["episode"], data["chapter"]) if s)
                        if action == "batch-name"
                        else None
                    )
                    repo.edit(
                        actor,
                        pid,
                        rev,
                        name=name,
                        directory_alias=value if action == "batch-directory" else None,
                    )
            await pending(owner, event)
        elif action == "preferences":
            repo.preferences(actor, {"profile": json.loads(value)})
            await settings(owner, event)
        elif action == "aliases":
            data = json.loads(value)
            repo.set_directory(actor, **data)
            await output(event, "目录别名已保存；只作用于新选择，不更改已入队任务。")
        interactions(owner).pop(actor, None)
    except PlanningError as exc:
        await output(event, "设置未保存：" + str(exc),
                     [[token_button(owner, actor, "返回监听管理" if action == "add" else "返回转存设置",
                                    ("listen",) if action == "add" else ("settings",))]])
    except (ValueError, PermissionError, TypeError):
        await output(
            event,
            "设置未保存：请检查格式、字段、目录授权或记录版本；可重新输入或 /cancelinput。",
        )
    except Exception as exc:  # noqa: BLE001 - private boundary must not expose credentials
        import sqlite3

        from tg2cloud.listening.service import source_error

        reason = ("来源记录未能保存；请检查数据库所在磁盘空间和写入权限后重试"
                  if isinstance(exc, sqlite3.Error) else source_error(exc))
        await output(event, "设置未完成：" + reason + "。可重新输入，或点击取消。",
                     [[token_button(owner, actor, "取消填写", ("cancelinput", ("listen",)))]]
                     if action == "add" else None)
    return True


async def manual(
    owner, event, message, file_name, prefs, *, created_at=None, classification_options=None
):
    repo = store(owner)
    actor = current_user(owner.settings.allowed_user_id)
    if not prefs["confirmation"] and prefs["profile"] == profile():
        return False
    item = rules.facts(message)
    # A private Bot delivery has a verified actor; no personal-client fallback is allowed.
    naming = name_plan(
        item["original"],
        item["caption"],
        file_name,
        kind=item["kind"],
        extension=item["extension"],
        entities=getattr(message, "entities", ()),
        options=prefs["profile"],
    )
    if prefs["profile"]["mode"] == "compatible" and not any(
        prefs["profile"][key] for key in ("prefixes", "suffixes", "label")
    ):
        naming["file_name"] = file_name
    plan, _ = repo.create(
        actor,
        item,
        naming,
        batch=f"bot:{event.chat_id}:{item['group'] or message.id}",
        target_base=owner.settings.cd2_target,
        created_at=created_at,
        classification_options=classification_options,
    )
    if plan["status"] == "submitted":
        owner._mark_task_delivery(event.chat_id, message.id, owner.db.get(plan["task"]), False)
    elif plan["status"] == "pending" and prefs["confirmation"]:
        owner.reactions.queue(event.chat_id, message.id, PENDING)
    elif plan["status"] == "pending":
        await submit(owner, actor, plan["id"], plan["revision"])
    else:
        owner.reactions.queue(event.chat_id, message.id, REJECTED)
    return True
