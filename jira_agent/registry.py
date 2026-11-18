"""Shared skill catalog in Unity Catalog: published skills as immutable, numbered versions.

Everything runs with the permissions of the signed-in user (their workspace token). The table is created once by
an administrator (see docs/REGISTRY.md) as an append-only Delta table: published rows can be added but never changed
or deleted, so a published version stays exactly as it was reviewed. Who may read or publish is decided by Unity
Catalog grants (SELECT / MODIFY), not by the UI.

The model has no access to this module. Writes use a fixed, parameterized statement; user input is never
concatenated into SQL. Catalog and schema come from the configuration and are validated as plain identifiers.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time

from jira_agent import CFG

_log = logging.getLogger("jira_agent.registry")

_IDENT = re.compile(r"[A-Za-z0-9_]{1,128}")
TABLE = "skill_versions"
_LIST_LIMIT = 200
_WAIT_SECONDS = 60


class RegistryError(Exception):
    """A problem that can be explained to the user (not set up, no permission, conflict)."""


# Unity Catalog names the missing privilege, e.g. "does not have USE CATALOG on Catalog 'main'". Only privilege,
# object type and object name are shown to the user, and only if they match these fixed patterns.
_MISSING = re.compile(r"does not have ([A-Z][A-Z _]{1,40}?) (?:privilege )?on "
                      r"(catalog|schema|table|view|volume|function) '([A-Za-z0-9_.`-]{1,300})'", re.I)
_PRIVILEGES = {"USE CATALOG", "USE SCHEMA", "SELECT", "MODIFY", "CREATE TABLE", "READ VOLUME", "EXECUTE",
               "BROWSE", "MANAGE", "ALL PRIVILEGES"}
_WHO = {"catalog": "the owner of the catalog or someone with MANAGE on it",
        "schema": "the owner of the schema or someone with MANAGE on it"}


def missing_privileges(message: str) -> list[tuple[str, str, str]]:
    """[(privilege, object type, object name)] from a Unity Catalog error message, without duplicates."""
    found = []
    for priv, kind, name in _MISSING.findall(message or ""):
        priv = " ".join(priv.replace("_", " ").upper().split())
        item = (priv, kind.lower(), name.replace("`", ""))
        if priv in _PRIVILEGES and item not in found:
            found.append(item)
    return found


def _permission_message(missing: list[tuple[str, str, str]]) -> str:
    parts = [f"{priv} on {kind} {name}" for priv, kind, name in missing]
    kind = missing[0][1]
    return ("You are missing " + "; ".join(parts) + ". Ask "
            + _WHO.get(kind, "the owner of the skill catalog table or someone with MANAGE on its schema")
            + " to grant it.")


READ_ONLY_MESSAGE = ("Your sign-in to this app only allows reading, so the skill cannot be published. Sign out, open "
                     "the app in a new browser window and accept the requested permissions again.")
SIGN_IN_MESSAGE = ("Your sign-in to this app is missing permissions. Sign out, open the app in a new browser "
                   "window and accept the requested permissions again.")


def settings() -> dict:
    cfg = dict(CFG.get("registry") or {})
    return {"enabled": bool(cfg.get("enabled")), "catalog": str(cfg.get("catalog") or ""),
            "schema": str(cfg.get("schema") or "")}


def enabled() -> bool:
    cfg = settings()
    return cfg["enabled"] and bool(_IDENT.fullmatch(cfg["catalog"]) and _IDENT.fullmatch(cfg["schema"]))


def table_name(catalog: str, schema: str) -> str:
    if not _IDENT.fullmatch(catalog or "") or not _IDENT.fullmatch(schema or ""):
        raise ValueError("Catalog and schema must contain only letters, digits and underscores.")
    return f"`{catalog}`.`{schema}`.`{TABLE}`"


def setup_sql(catalog: str, schema: str) -> list[str]:
    """DDL for the one-time administrator setup. Append-only: UPDATE and DELETE are rejected by Delta."""
    return [
        f"CREATE TABLE IF NOT EXISTS {table_name(catalog, schema)} (\n"
        "  skill_name STRING NOT NULL,\n"
        "  version INT NOT NULL,\n"
        "  description STRING NOT NULL,\n"
        "  instructions STRING NOT NULL,\n"
        "  content_sha256 STRING NOT NULL,\n"
        "  owner STRING NOT NULL,\n"
        "  created_at TIMESTAMP NOT NULL,\n"
        "  status STRING NOT NULL\n"
        ") TBLPROPERTIES (delta.appendOnly = true)",
    ]


def content_hash(name: str, description: str, instructions: str) -> str:
    return hashlib.sha256("\n".join((name, description, instructions)).encode()).hexdigest()


def _param(name: str, value: str) -> dict:
    return {"name": name, "value": value, "type": "STRING"}


class SkillRegistry:
    def __init__(self, user_client, warehouse_id: str, catalog: str | None = None, schema: str | None = None):
        cfg = settings()
        self.w = user_client
        self.warehouse_id = warehouse_id
        self.table = table_name(catalog or cfg["catalog"], schema or cfg["schema"])

    def __repr__(self) -> str:
        return f"SkillRegistry(table={self.table})"

    def _run(self, statement: str, parameters: list[dict] | None = None) -> list[list]:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        items = [StatementParameterListItem(**p) for p in parameters or []]
        api = self.w.statement_execution
        try:
            resp = api.execute_statement(statement=statement, warehouse_id=self.warehouse_id,
                                         parameters=items or None, wait_timeout="30s", row_limit=_LIST_LIMIT)
        except Exception as exc:
            self._raise_api_error(exc)
            raise
        deadline = time.monotonic() + _WAIT_SECONDS
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.monotonic() >= deadline:
                try:
                    api.cancel_execution(resp.statement_id)
                except Exception:
                    pass
                raise RegistryError("The skill catalog did not answer in time. Please try again.")
            time.sleep(2)
            resp = api.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            error = resp.status.error
            message = (error.message if error else "") or ""
            code = getattr(getattr(error, "error_code", None), "value", None) or str(getattr(error, "error_code", "") or "")
            code = code if re.fullmatch(r"[A-Z0-9_]{1,64}", code or "") else ""
            # The full text stays in the server log; users only get a fixed message plus the short error code.
            _log.warning("Skill catalog statement failed: state=%s code=%s message=%s", resp.status.state.value, code,
                         message[:500].replace("\n", " "))
            lowered = message.lower()
            if "table_or_view_not_found" in lowered or "cannot be found" in lowered:
                raise RegistryError("The skill catalog is not set up yet. An administrator must create the table "
                                    "(docs/REGISTRY.md).")
            if "read-only session" in lowered:
                raise RegistryError(READ_ONLY_MESSAGE)
            missing = missing_privileges(message)
            if missing:
                raise RegistryError(_permission_message(missing))
            if "permission" in lowered or "privilege" in lowered or "denied" in lowered:
                raise RegistryError("You do not have access to the skill catalog. Ask an administrator for "
                                    "SELECT (read) or MODIFY (publish) on it.")
            raise RegistryError("The skill catalog request failed" + (f" ({code})." if code else "."))
        return list((resp.result.data_array if resp.result else None) or [])

    def _raise_api_error(self, exc: Exception) -> None:
        """Errors before the statement runs (HTTP 401/403): missing warehouse access or a too narrow sign-in."""
        from databricks.sdk.errors import PermissionDenied, Unauthenticated

        if not isinstance(exc, (PermissionDenied, Unauthenticated)):
            return
        message = str(exc)
        _log.warning("Skill catalog request rejected: %s %s", type(exc).__name__, message[:500].replace("\n", " "))
        lowered = message.lower()
        if "scope" in lowered or isinstance(exc, Unauthenticated):
            raise RegistryError(SIGN_IN_MESSAGE) from None
        missing = missing_privileges(message)
        if missing:
            raise RegistryError(_permission_message(missing)) from None
        raise RegistryError(f"You are missing CAN USE on the SQL warehouse {self.warehouse_id}. Ask the owner of "
                            "the warehouse to grant it.") from None

    @staticmethod
    def _summary(row: list) -> dict:
        return {"name": row[0], "version": int(row[1]), "beschreibung": row[2], "owner": row[3],
                "created_at": row[4], "quelle": "katalog"}

    def _state(self, name: str) -> dict | None:
        """Newest row of a name, whatever its status; it decides ownership and whether the skill is hidden."""
        rows = self._run(f"SELECT version, status, owner FROM {self.table} WHERE skill_name = :name "
                         "ORDER BY version DESC LIMIT 1", [_param("name", name)])
        return {"version": int(rows[0][0]), "status": rows[0][1], "owner": rows[0][2]} if rows else None

    def list_latest(self) -> list[dict]:
        # A withdrawn skill has a newer 'withdrawn' row, so only names whose newest row is 'published' are listed.
        rows = self._run(
            "SELECT skill_name, version, description, owner, CAST(created_at AS STRING) FROM ("
            f"SELECT *, ROW_NUMBER() OVER (PARTITION BY skill_name ORDER BY version DESC) AS rn FROM {self.table}"
            ") WHERE rn = 1 AND status = 'published' "
            f"ORDER BY skill_name LIMIT {_LIST_LIMIT}")
        return [self._summary(r) for r in rows]

    def get(self, name: str, version: int | None = None) -> dict | None:
        state = self._state(name)
        if not state or state["status"] != "published":
            return None     # unknown or withdrawn: all of its versions stay hidden
        params = [_param("name", name), _param("version", str(int(version if version is not None else state["version"])))]
        rows = self._run(
            "SELECT skill_name, version, description, owner, CAST(created_at AS STRING), instructions "
            f"FROM {self.table} WHERE skill_name = :name AND status = 'published' "
            "AND version = CAST(:version AS INT) LIMIT 1", params)
        if not rows:
            return None
        return {**self._summary(rows[0]), "anleitung": rows[0][5]}

    def publish(self, skill: dict, owner: str) -> dict:
        """Append the next version. The first publisher owns the name; others cannot add versions to it."""
        name, description, instructions = skill["name"], skill["beschreibung"], skill["anleitung"]
        digest = content_hash(name, description, instructions)
        state = self._state(name)
        if state and state["owner"] != owner:
            raise RegistryError(f"/{name} is already published by {state['owner']}. Please choose another name.")
        latest = self.get(name)
        if latest and content_hash(name, latest["beschreibung"], latest["anleitung"]) == digest:
            return {**latest, "unchanged": True}
        params = [_param("name", name), _param("description", description), _param("instructions", instructions),
                  _param("digest", digest), _param("owner", owner)]
        # One statement computes the next number and re-checks ownership, so two people cannot take over a name.
        affected = self._run(
            f"INSERT INTO {self.table} (skill_name, version, description, instructions, content_sha256, owner, "
            "created_at, status) "
            "SELECT :name, COALESCE(MAX(version), 0) + 1, :description, :instructions, :digest, :owner, "
            f"current_timestamp(), 'published' FROM {self.table} WHERE skill_name = :name "
            "HAVING COALESCE(MAX(version), 0) = 0 OR MAX_BY(owner, version) = :owner", params)
        if not affected or int(affected[0][0]) < 1:
            raise RegistryError(f"/{name} could not be published because someone else owns this name.")
        published = self.get(name)
        if not published or published["owner"] != owner:
            raise RegistryError("The skill was saved, but its version could not be confirmed. Please check the catalog.")
        return published

    def withdraw(self, name: str, owner: str) -> dict:
        """Hide a skill from everyone by appending a 'withdrawn' row. History stays; only the owner may do this.

        The name stays reserved for its owner, who can publish a new version later.
        """
        state = self._state(name)
        if not state:
            raise RegistryError(f"/{name} is not in the catalog.")
        if state["owner"] != owner:
            raise RegistryError(f"Only {state['owner']} can withdraw /{name} from the catalog.")
        if state["status"] != "published":
            return {"name": name, "version": state["version"], "unchanged": True}
        affected = self._run(
            f"INSERT INTO {self.table} (skill_name, version, description, instructions, content_sha256, owner, "
            "created_at, status) "
            "SELECT skill_name, version + 1, description, instructions, content_sha256, owner, "
            f"current_timestamp(), 'withdrawn' FROM {self.table} "
            "WHERE skill_name = :name AND owner = :owner AND status = 'published' "
            f"AND version = (SELECT MAX(version) FROM {self.table} WHERE skill_name = :name)",
            [_param("name", name), _param("owner", owner)])
        if not affected or int(affected[0][0]) < 1:
            raise RegistryError(f"/{name} could not be withdrawn. Reload the skill list and try again.")
        return {"name": name, "version": state["version"] + 1, "unchanged": False}
