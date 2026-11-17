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
import re
import time

from jira_agent import CFG

_IDENT = re.compile(r"[A-Za-z0-9_]{1,128}")
TABLE = "skill_versions"
_LIST_LIMIT = 200
_WAIT_SECONDS = 60


class RegistryError(Exception):
    """A problem that can be explained to the user (not set up, no permission, conflict)."""


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
        resp = api.execute_statement(statement=statement, warehouse_id=self.warehouse_id, parameters=items or None,
                                     wait_timeout="30s", row_limit=_LIST_LIMIT)
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
            message = (resp.status.error.message if resp.status.error else "") or ""
            lowered = message.lower()
            if "table_or_view_not_found" in lowered or "cannot be found" in lowered:
                raise RegistryError("The skill catalog is not set up yet. An administrator must create the table "
                                    "(docs/REGISTRY.md).")
            if "permission" in lowered or "privilege" in lowered or "denied" in lowered:
                raise RegistryError("You do not have access to the skill catalog. Ask an administrator for "
                                    "SELECT (read) or MODIFY (publish) on it.")
            raise RegistryError("The skill catalog request failed.")
        return list((resp.result.data_array if resp.result else None) or [])

    @staticmethod
    def _summary(row: list) -> dict:
        return {"name": row[0], "version": int(row[1]), "beschreibung": row[2], "owner": row[3],
                "created_at": row[4], "quelle": "katalog"}

    def list_latest(self) -> list[dict]:
        rows = self._run(
            f"SELECT skill_name, version, description, owner, CAST(created_at AS STRING) FROM {self.table} "
            "WHERE status = 'published' "
            "QUALIFY ROW_NUMBER() OVER (PARTITION BY skill_name ORDER BY version DESC) = 1 "
            f"ORDER BY skill_name LIMIT {_LIST_LIMIT}")
        return [self._summary(r) for r in rows]

    def get(self, name: str, version: int | None = None) -> dict | None:
        params = [_param("name", name)]
        condition = "skill_name = :name AND status = 'published'"
        if version is not None:
            condition += " AND version = CAST(:version AS INT)"
            params.append(_param("version", str(int(version))))
        rows = self._run(
            "SELECT skill_name, version, description, owner, CAST(created_at AS STRING), instructions "
            f"FROM {self.table} WHERE {condition} ORDER BY version DESC LIMIT 1", params)
        if not rows:
            return None
        return {**self._summary(rows[0]), "anleitung": rows[0][5]}

    def publish(self, skill: dict, owner: str) -> dict:
        """Append the next version. The first publisher owns the name; others cannot add versions to it."""
        name, description, instructions = skill["name"], skill["beschreibung"], skill["anleitung"]
        digest = content_hash(name, description, instructions)
        latest = self.get(name)
        if latest and latest["owner"] != owner:
            raise RegistryError(f"/{name} is already published by {latest['owner']}. Please choose another name.")
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
