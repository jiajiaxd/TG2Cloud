"""Plans and source inbox share the task database and its transaction lock."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

from tg2cloud.domain.classification import (
    MANUAL_MEDIA,
    media_directories,
    safe_directory,
)
from tg2cloud.domain.planning import PlanningError, corrected_name, profile
from tg2cloud.domain.source_directories import (
    CATEGORIES,
    MAX_BYTES,
    MAX_COLUMNS,
    columns,
    folder_name,
    media_directory,
)
from tg2cloud.listening.rules import validate

TTL = 7 * 86400
MAINTENANCE_BATCH = 500


def create_schema(c):
    for sql in (
        "CREATE TABLE IF NOT EXISTS transfer_preferences(owner INTEGER PRIMARY KEY, options TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS transfer_directories(alias TEXT PRIMARY KEY, path TEXT NOT NULL, owners TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS listener_sources(id INTEGER PRIMARY KEY, account INTEGER NOT NULL, chat INTEGER NOT NULL, title TEXT NOT NULL, config TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0, cursor INTEGER NOT NULL, status TEXT NOT NULL DEFAULT '暂停', next_retry REAL NOT NULL DEFAULT 0, polled_at REAL NOT NULL DEFAULT 0, gap INTEGER NOT NULL DEFAULT 0, UNIQUE(account,chat))",
        "CREATE TABLE IF NOT EXISTS listener_events(account INTEGER NOT NULL, chat INTEGER NOT NULL, message INTEGER NOT NULL, source INTEGER NOT NULL REFERENCES listener_sources(id), result TEXT NOT NULL, plan INTEGER, created REAL NOT NULL, is_attachment INTEGER NOT NULL DEFAULT 0, matched INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(account,chat,message))",
        "CREATE TABLE IF NOT EXISTS transfer_plans(id INTEGER PRIMARY KEY, owner INTEGER NOT NULL, source INTEGER REFERENCES listener_sources(id), identity TEXT NOT NULL, chat INTEGER NOT NULL, message INTEGER NOT NULL, batch TEXT NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL, task INTEGER REFERENCES tasks(id), created REAL NOT NULL, expires REAL NOT NULL, UNIQUE(identity,chat,message))",
        "CREATE INDEX IF NOT EXISTS idx_plans_owner_status ON transfer_plans(owner,status,id)",
        "CREATE INDEX IF NOT EXISTS idx_events_age ON listener_events(created)",
        "CREATE INDEX IF NOT EXISTS idx_listener_events_plan ON listener_events(plan) WHERE plan IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_plans_expiry ON transfer_plans(expires,id) WHERE status='pending'",
        "CREATE INDEX IF NOT EXISTS idx_plans_retention ON transfer_plans(created,id) WHERE status!='pending'",
        "CREATE TABLE IF NOT EXISTS listener_revisions(id INTEGER PRIMARY KEY, source INTEGER NOT NULL, revision INTEGER NOT NULL, config TEXT NOT NULL, operator INTEGER NOT NULL, created REAL NOT NULL)",
        "CREATE TABLE IF NOT EXISTS naming_feedback(id INTEGER PRIMARY KEY, owner INTEGER NOT NULL, source INTEGER, plan INTEGER NOT NULL, before_name TEXT NOT NULL, after_name TEXT NOT NULL, rule_revision INTEGER, operation TEXT NOT NULL, created REAL NOT NULL)",
    ):
        c.execute(sql)


class Plans:
    def __init__(self, db, admin):
        self.db, self.admin = db, admin
        self.c = db._conn

    def authorize(self, actor, *, admin=False):
        if type(actor) is not int or actor <= 0:
            raise PermissionError("无权操作")
        if actor == self.admin:
            return
        if admin or not any(
            u["id"] == actor and u["enabled"]
            for u in self.db.family_users(self.admin)["users"]
        ):
            raise PermissionError("此操作仅限已授权用户")

    @contextmanager
    def transaction(self, actor, *, admin=False):
        with self.db._lock:
            nested = self.c.in_transaction
            self.c.execute("SAVEPOINT plan_operation" if nested else "BEGIN IMMEDIATE")
            try:
                self.authorize(actor, admin=admin)
                yield
                self.c.execute("RELEASE plan_operation" if nested else "COMMIT")
            except BaseException:
                self.c.execute("ROLLBACK TO plan_operation" if nested else "ROLLBACK")
                if nested:
                    self.c.execute("RELEASE plan_operation")
                raise

    def preferences(self, actor, updates=None):
        with self.transaction(actor):
            row = self.c.execute(
                "SELECT options FROM transfer_preferences WHERE owner=?", (actor,)
            ).fetchone()
            value = (
                json.loads(row[0])
                if row
                else {"confirmation": False, "profile": profile()}
            )
            value.setdefault("auto_classify", False)
            if updates is not None:
                if not isinstance(updates, dict) or set(updates) - {
                    "confirmation",
                    "profile",
                    "auto_classify",
                }:
                    raise PlanningError("未知转存设置")
                value.update(updates)
                if type(value["confirmation"]) is not bool:
                    raise PlanningError("确认模式应为布尔值")
                if type(value["auto_classify"]) is not bool:
                    raise PlanningError("自动分类应为布尔值")
                value["profile"] = profile(value["profile"])
                # Profiles cannot create another route around the directory allowlist.
                if (
                    value["profile"]["directory"]
                    and value["profile"]["directory"]
                    not in self.directories(actor).values()
                ):
                    raise PlanningError("请选择管理员授权的目录别名")
                if value["auto_classify"]:
                    media_directories(value["profile"]["directory"])
                self.c.execute(
                    "INSERT OR REPLACE INTO transfer_preferences VALUES(?,?)",
                    (actor, json.dumps(value)),
                )
            return value

    def directories(self, actor):
        self.authorize(actor)
        return {
            r["alias"]: r["path"]
            for r in self.c.execute(
                "SELECT * FROM transfer_directories ORDER BY alias LIMIT 32"
            )
            if actor == self.admin or actor in json.loads(r["owners"])
        }

    def directory(self, actor, alias):
        if not alias:
            return None
        values = self.directories(actor)
        if alias not in values:
            raise PlanningError("目录别名不存在或未授权")
        return values[alias]

    def personal_directory(self, actor, preferences):
        path = preferences["profile"]["directory"]
        if not path:
            return "", ()
        aliases = tuple(alias for alias, directory in self.directories(actor).items() if directory == path)
        if not aliases:
            raise PlanningError("保存目录未获授权，请重新选择目录别名")
        return path, aliases

    def set_directory(self, actor, alias, path, owners):
        with self.transaction(actor, admin=True):
            if (
                not isinstance(alias, str)
                or not 1 <= len(alias) <= 32
                or any(ord(c) < 32 or c in "/:%" for c in alias)
            ):
                raise PlanningError("目录别名无效")
            if (
                not isinstance(owners, list)
                or len(owners) > 32
                or any(type(i) is not int or i <= 0 for i in owners)
            ):
                raise PlanningError("目录授权用户无效")
            if self.c.execute("SELECT count(*) FROM transfer_directories").fetchone()[
                0
            ] >= 32 and alias not in self.directories(actor):
                raise PlanningError("目录别名已达上限")
            self.c.execute(
                "INSERT OR REPLACE INTO transfer_directories VALUES(?,?,?)",
                (alias, safe_directory(path), json.dumps(owners)),
            )

    def sources(self, actor):
        self.authorize(actor, admin=True)
        return [
            dict(row) | {"config": json.loads(row["config"])}
            for row in self.c.execute(
                "SELECT * FROM listener_sources WHERE deleted=0 ORDER BY id LIMIT 32"
            )
        ]

    def source(self, actor, source_id):
        self.authorize(actor, admin=True)
        row = self.c.execute(
            "SELECT * FROM listener_sources WHERE id=?", (source_id,)
        ).fetchone()
        if not row:
            raise PlanningError("来源不存在")
        return dict(row) | {"config": json.loads(row["config"])}

    def save_source(self, actor, *, account, chat, title, cursor, config, target_base=None):
        config = self.source_config(actor, config)
        with self.transaction(actor, admin=True):
            if len(self.sources(actor)) >= 32:
                raise PlanningError("监听来源最多 32 个")
            old = self.c.execute(
                "SELECT id FROM listener_sources WHERE account=? AND chat=?",
                (account, chat),
            ).fetchone()
            if old:
                previous = self.source(actor, old["id"])
                if not previous["deleted"]:
                    raise PlanningError("来源已经登记；请在原来源中修改或恢复")
                # Re-adding the same source keeps its established folder and base.
                if target_base is not None:
                    config.update({key: previous["config"].get(key, default) for key, default in
                                   (("source_folder", ""), ("source_base", None))})
                    config["directory_mode"] = "source_type"
                    config = self._bind_source_folder(config, old["id"], title, chat, target_base)
                self.c.execute(
                    "UPDATE listener_sources SET config=?,cursor=?,title=?,deleted=0,enabled=0,revision=revision+1,status='暂停',gap=0,polled_at=? WHERE id=?",
                    (json.dumps(config), cursor, title[:100], time.time(), old["id"]),
                )
                return self.source(actor, old["id"])
            result = self.c.execute(
                "INSERT INTO listener_sources(account,chat,title,config,cursor,polled_at) VALUES(?,?,?,?,?,?)",
                (account, chat, title[:100], json.dumps(config), cursor, time.time()),
            )
            if target_base is not None:
                config = self._bind_source_folder(config | {"directory_mode": "source_type"},
                                                  result.lastrowid, title, chat, target_base)
                self.c.execute("UPDATE listener_sources SET config=? WHERE id=?",
                               (json.dumps(config), result.lastrowid))
            return self.source(actor, result.lastrowid)

    def _bind_source_folder(self, config, source_id, title, chat, base):
        if not config.get("source_folder"):
            # Transactional reservations include deleted sources: old data never changes owners.
            used = {json.loads(row[0]).get("source_folder", "").casefold() for row in
                    self.c.execute("SELECT config FROM listener_sources WHERE id!=?", (source_id,))}
            used.update(x.casefold() for x in CATEGORIES)
            used.update(row[0].split("/", 1)[0].casefold() for row in
                        self.c.execute("SELECT path FROM transfer_directories"))
            candidate = folder_name(title, chat)
            counter = 0
            while candidate.casefold() in used:
                counter += 1
                candidate = folder_name(title, chat, f"-来源{source_id}" + (f"-{counter}" if counter > 1 else ""))
            config = config | {"source_folder": candidate, "source_base": base}
        return self.source_config(self.admin, config)

    def source_config(self, actor, config):
        self.authorize(actor, admin=True)
        if not isinstance(config, dict) or set(config) - {
            "rules",
            "profile",
            "directory",
            "confirmation", "directory_mode", "source_folder", "source_base",
        }:
            raise PlanningError("未知来源配置")
        result = {"profile": profile(), "directory": "", "confirmation": True,
                  "directory_mode": "legacy", "source_folder": "", "source_base": None, **config}
        if result["directory_mode"] not in {"legacy", "source_type"}:
            raise PlanningError("未知来源目录模式")
        folder = safe_directory(result["source_folder"])
        if "/" in folder or columns(folder) > MAX_COLUMNS or len(folder.encode("utf-8")) > MAX_BYTES:
            raise PlanningError("来源目录名称过长或不是单级目录")
        if result["source_base"] is not None and (not isinstance(result["source_base"], str)
                                                   or "\0" in result["source_base"]):
            raise PlanningError("来源保存根目录无效")
        if bool(folder) != (result["source_base"] is not None):
            raise PlanningError("来源目录绑定不完整")
        result["rules"] = validate(result.get("rules", {}))
        result["profile"] = profile(result["profile"])
        self.directory(actor, result["directory"])
        if (
            result["profile"]["directory"]
            and result["profile"]["directory"] not in self.directories(actor).values()
        ):
            raise PlanningError("命名方案目录未授权")
        if type(result["confirmation"]) is not bool:
            raise PlanningError("确认模式无效")
        return result

    def change_source(
        self,
        actor,
        source_id,
        revision,
        *,
        config=None,
        enabled=None,
        delete=False,
        cursor=None,
        target_base=None,
    ):
        with self.transaction(actor, admin=True):
            old = self.source(actor, source_id)
            if old["revision"] != revision or old["deleted"]:
                raise PlanningError("来源已变化，请刷新")
            if config is not None:
                # Historical revisions before folder support have no binding fields.
                config = {key: old["config"].get(key, default) for key, default in
                          (("source_folder", ""), ("source_base", None))} | config
            value = (
                self.source_config(actor, config)
                if config is not None
                else old["config"]
            )
            if config is not None:
                for key, default in (("source_folder", ""), ("source_base", None)):
                    if value.get(key, default) != old["config"].get(key, default):
                        raise PlanningError("已绑定的来源目录不可改名或改换根目录")
                if value["directory_mode"] == "source_type" and not value["source_folder"]:
                    if target_base is None:
                        raise PlanningError("切换来源目录需要核对当前 Bot 保存根目录")
                    value = self._bind_source_folder(value, source_id, old["title"], old["chat"], target_base)
            if target_base is not None and value.get("directory_mode") == "source_type":
                media_directory(value, base=target_base)
            if value.get("directory_mode", "legacy") != old["config"].get("directory_mode", "legacy"):
                enabled = False  # A changed destination always needs explicit review and re-enabling.
            self.c.execute(
                "INSERT INTO listener_revisions(source,revision,config,operator,created) VALUES(?,?,?,?,?)",
                (
                    source_id,
                    old["revision"],
                    json.dumps(old["config"]),
                    actor,
                    time.time(),
                ),
            )
            self.c.execute(
                "DELETE FROM listener_revisions WHERE source=? AND id NOT IN (SELECT id FROM listener_revisions WHERE source=? ORDER BY id DESC LIMIT 20)",
                (source_id, source_id),
            )
            if cursor is not None:
                if type(cursor) is not int or cursor < 0:
                    raise PlanningError("接收进度无效")
                self.c.execute(
                    "UPDATE listener_sources SET cursor=?,gap=0,polled_at=? WHERE id=?",
                    (cursor, time.time(), source_id),
                )
            if delete:
                enabled = False
                self.c.execute(
                    "UPDATE transfer_plans SET status='ignored',revision=revision+1 WHERE source=? AND status='pending'",
                    (source_id,),
                )
            self.c.execute(
                "UPDATE listener_sources SET config=?,enabled=?,deleted=?,revision=revision+1,status=? WHERE id=?",
                (
                    json.dumps(value),
                    int(enabled if enabled is not None else old["enabled"]),
                    int(delete),
                    "已删除" if delete else "等待检查",
                    source_id,
                ),
            )

    def expire_pending(self, owner=None):
        """Caller holds the transaction; admission only expires this owner's plans."""
        query = "UPDATE transfer_plans SET status='expired',revision=revision+1 WHERE status='pending' AND expires<?"
        params = (time.time(),)
        if owner is not None:
            query += " AND owner=?"
            params += (owner,)
        self.c.execute(query, params)

    def expire(self):
        """One atomic bounded batch; True asks the loop to revisit a possible backlog.

        Retention and pending/reference protection are unchanged. LIMIT bounds
        mutations, not wall time: protected history can still require scanning.
        """
        now = time.time()
        counts = []
        counts.append(self.c.execute(
            "UPDATE transfer_plans SET status='expired',revision=revision+1 WHERE id IN "
            "(SELECT id FROM transfer_plans WHERE status='pending' AND expires<? "
            "ORDER BY expires,id LIMIT ?)", (now, MAINTENANCE_BATCH),
        ).rowcount)
        counts.append(self.c.execute(
            "DELETE FROM listener_events WHERE rowid IN (SELECT e.rowid FROM listener_events e "
            "WHERE e.created<? AND (e.plan IS NULL OR EXISTS "
            "(SELECT 1 FROM transfer_plans p WHERE p.id=e.plan AND p.status!='pending')) "
            "ORDER BY e.created LIMIT ?)", (now - TTL, MAINTENANCE_BATCH),
        ).rowcount)
        counts.append(self.c.execute(
            "DELETE FROM naming_feedback WHERE id IN (SELECT id FROM naming_feedback "
            "WHERE created<? OR id NOT IN (SELECT id FROM naming_feedback ORDER BY id DESC LIMIT 2000) "
            "ORDER BY id LIMIT ?)", (now - 30 * 86400, MAINTENANCE_BATCH),
        ).rowcount)
        counts.append(self.c.execute(
            "DELETE FROM transfer_plans WHERE id IN (SELECT p.id FROM transfer_plans p "
            "WHERE p.status!='pending' AND p.created<? AND NOT EXISTS "
            "(SELECT 1 FROM listener_events e WHERE e.plan=p.id) "
            "ORDER BY p.created,p.id LIMIT ?)", (now - 30 * 86400, MAINTENANCE_BATCH),
        ).rowcount)
        return any(count == MAINTENANCE_BATCH for count in counts)

    def create(
        self,
        actor,
        item,
        naming,
        *,
        identity="bot",
        source=None,
        batch="",
        directory_alias="",
        target_base=None,
        created_at=None,
        classification_options=None,
    ):
        with self.transaction(actor, admin=source is not None):
            self.expire_pending(actor)
            if source is not None:
                saved = self.source(actor, source)
                if (
                    identity != "listener:" + str(saved["account"])
                    or saved["deleted"]
                    or not saved["enabled"]
                ):
                    raise PlanningError("监听来源或读取身份已变化")
            elif identity != "bot":
                raise PermissionError("手动任务不得借用监听身份")
            old = self.c.execute(
                "SELECT * FROM transfer_plans WHERE identity=? AND chat=? AND message=?",
                (identity, item["chat_id"], item["message_id"]),
            ).fetchone()
            if old:
                return self.get(actor, old["id"]), False
            if (
                self.c.execute(
                    "SELECT count(*) FROM transfer_plans WHERE owner=? AND status='pending'",
                    (actor,),
                ).fetchone()[0]
                >= 200
            ):
                raise PlanningError("待确认已达 200 项；请先处理")
            source_directory = media_directory(saved["config"], kind=item["kind"], mime=item["mime"],
                                               extension=item["extension"], base=target_base) if source is not None else None
            directory = self.directory(actor, directory_alias)
            directory = (
                directory
                if directory is not None
                else naming["profile"]["directory"] or None
            )
            if (
                directory is not None
                and directory not in self.directories(actor).values()
            ):
                raise PlanningError("计划目录已不在授权范围")
            from tg2cloud.domain.classification import directory as classified_directory

            now = time.time() if created_at is None else created_at
            classification_options = (
                classification_options or self.db.feature_settings()
            )
            origin = "alias" if directory is not None else "classification"
            if source_directory is not None:
                directory, origin = source_directory, "source"
            if classification_options["classification"] == MANUAL_MEDIA:
                media_directories(directory or "")
            elif directory is None:
                directory = classified_directory(
                    classification_options,
                    now,
                    kind=item["kind"],
                    mime=item["mime"],
                    extension=item["extension"],
                )
            data = {
                "file_name": naming["file_name"],
                "candidate": naming["file_name"],
                "basis": naming["basis"],
                "original_file_name": item["original"],
                "file_size": item["size"],
                "media_key": item["media_key"],
                "media_kind": item["kind"],
                "mime_type": item["mime"],
                "media_extension": item["extension"],
                "target_base": target_base,
                "directory_override": directory,
                "profile": naming["profile"],
                "classification_options": classification_options,
                "created_at": now,
                "directory_origin": origin,
                "source_revision": saved["revision"] if source is not None else None,
                "rule_snapshot": saved["config"]["rules"]
                if source is not None
                else None,
            }
            now = time.time()
            result = self.c.execute(
                "INSERT INTO transfer_plans(owner,source,identity,chat,message,batch,payload,status,created,expires) VALUES(?,?,?,?,?,?,?,'pending',?,?)",
                (
                    actor,
                    source,
                    identity,
                    item["chat_id"],
                    item["message_id"],
                    batch[:100],
                    json.dumps(data),
                    now,
                    now + TTL,
                ),
            )
            if source is not None:
                self.c.execute(
                    "INSERT INTO listener_events(account,chat,message,source,result,plan,created,is_attachment,matched) VALUES(?,?,?,?,?,?,?,1,1)",
                    (
                        saved["account"],
                        item["chat_id"],
                        item["message_id"],
                        source,
                        "等待审批",
                        result.lastrowid,
                        now,
                    ),
                )
            return self.get(actor, result.lastrowid), True

    def get(self, actor, plan_id):
        self.authorize(actor)
        row = self.c.execute(
            "SELECT * FROM transfer_plans WHERE id=? AND owner=?", (plan_id, actor)
        ).fetchone()
        if not row or row["source"] is not None and actor != self.admin:
            raise PermissionError("没有找到这个计划")
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        if result["status"] == "pending" and result["expires"] < time.time():
            result["status"] = "expired"
        return result

    def pending(self, actor, after=0):
        self.authorize(actor)
        return [
            self.get(actor, r[0])
            for r in self.c.execute(
                "SELECT id FROM transfer_plans WHERE owner=? AND status='pending' AND expires>? AND id>? ORDER BY id LIMIT 10",
                (actor, time.time(), after),
            )
        ]

    def edit(
        self, actor, plan_id, revision, *, name=None, directory_alias=None, ignore=False
    ):
        with self.transaction(actor):
            p = self.get(actor, plan_id)
            if p["revision"] != revision or p["status"] != "pending":
                raise PlanningError("计划已处理、过期或变化，请刷新")
            data = p["payload"]
            if name is not None:
                updated = corrected_name(name, data["file_name"])
                source_revision = data["source_revision"]
                self.c.execute(
                    "INSERT INTO naming_feedback(owner,source,plan,before_name,after_name,rule_revision,operation,created) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        actor,
                        p["source"],
                        plan_id,
                        data["file_name"],
                        updated,
                        source_revision,
                        "仅本次",
                        time.time(),
                    ),
                )
                data["file_name"] = updated
            if directory_alias is not None:
                data["directory_override"] = self.directory(actor, directory_alias)
                if data["classification_options"]["classification"] == MANUAL_MEDIA:
                    media_directories(data["directory_override"] or "")
                data["directory_origin"] = "alias"
            self.c.execute(
                "UPDATE transfer_plans SET payload=?,status=?,revision=revision+1 WHERE id=?",
                (json.dumps(data), "ignored" if ignore else "pending", plan_id),
            )
            return self.get(actor, plan_id)

    def submit(self, actor, plan_id, revision):
        with self.transaction(actor):
            p = self.get(actor, plan_id)
            if p["status"] == "submitted":
                return self.db.get(p["task"]), False
            if p["status"] != "pending" or p["revision"] != revision:
                raise PlanningError("计划已变化或过期")
            if p["source"] is not None:
                self.authorize(actor, admin=True)
                if self.source(actor, p["source"])["deleted"]:
                    raise PlanningError("来源已删除，不再提交待确认计划")
            data = p["payload"].copy()
            if data["directory_origin"] == "source":
                if p["source"] is None:
                    raise PermissionError("来源目录缺少监听身份")
                source = self.source(actor, p["source"])
                expected = media_directory(source["config"] | {"directory_mode": "source_type"},
                                           kind=data["media_kind"], mime=data["mime_type"],
                                           extension=data["media_extension"], base=data["target_base"])
                if data["directory_override"] != expected:
                    raise PermissionError("计划的来源目录绑定不匹配")
            if (
                data["directory_origin"] == "alias"
                and data["directory_override"] not in self.directories(actor).values()
            ):
                raise PermissionError("目录授权已撤销")
            for key in (
                "candidate",
                "basis",
                "profile",
                "directory_origin",
                "source_revision",
                "rule_snapshot",
            ):
                data.pop(key)
            task, created = self.db.create_task(
                chat_id=p["chat"],
                message_id=p["message"],
                sender_id=actor,
                read_identity=p["identity"],
                source_id=p["source"],
                **data,
            )
            self.c.execute(
                "UPDATE transfer_plans SET status='submitted',task=?,revision=revision+1 WHERE id=?",
                (task["id"], plan_id),
            )
            if p["source"] is not None:
                self.c.execute(
                    "UPDATE listener_events SET result=? WHERE plan=?",
                    ("已入队" if created else "重复文件（沿用原任务）", plan_id),
                )
            return task, created

    def feedback(self, actor):
        self.authorize(actor)
        return [
            dict(r)
            for r in self.c.execute(
                "SELECT * FROM naming_feedback WHERE owner=? ORDER BY id DESC LIMIT 20",
                (actor,),
            )
        ]

    def source_history(self, actor, source_id):
        self.authorize(actor, admin=True)
        self.source(actor, source_id)
        return [
            dict(row)
            for row in self.c.execute(
                "SELECT * FROM listener_revisions WHERE source=? ORDER BY id DESC LIMIT 20",
                (source_id,),
            )
        ]

    def apply_feedback(self, actor, feedback_id, revision):
        with self.transaction(actor, admin=True):
            self.authorize(actor, admin=True)
            row = self.c.execute(
                "SELECT * FROM naming_feedback WHERE id=? AND owner=?",
                (feedback_id, actor),
            ).fetchone()
            if not row or row["source"] is None or row["operation"] != "仅本次":
                raise PlanningError("此修正不能自动概括为来源规则")
            from pathlib import Path

            before, after = Path(row["before_name"]).stem, Path(row["after_name"]).stem
            prefix = before[: -len(after)] if after and before.endswith(after) else ""
            if not 1 <= len(prefix) <= 80:
                raise PlanningError("无法概括固定前缀；本次修改保持独立")
            source = self.source(actor, row["source"])
            config = source["config"]
            config["profile"]["prefixes"] = list(
                dict.fromkeys([*config["profile"]["prefixes"], prefix])
            )
            # This method is invoked only by an explicit one-use confirmation button.
            self.change_source(actor, source["id"], revision, config=config)
            self.c.execute(
                "UPDATE naming_feedback SET operation='明确保存为来源前缀规则' WHERE id=?",
                (feedback_id,),
            )
