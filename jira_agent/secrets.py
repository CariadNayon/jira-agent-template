"""Secrets aus einem Databricks Secret Scope lesen (übernommen aus mdb-reporter-app/utils/secrets.py).

- Auf einem Cluster / im Notebook: dbutils.secrets.get()
- In einer Databricks App: WorkspaceClient().secrets.get_secret() als Service Principal der App.
  Die REST-API liefert den Wert Base64-kodiert, dbutils dekodiert automatisch, das SDK nicht.
"""
from __future__ import annotations

import base64
import os

_DATABRICKS_CLUSTER = os.getenv("DATABRICKS_RUNTIME_VERSION") is not None


def get_app_secret(key: str, scope: str) -> str:
    if _DATABRICKS_CLUSTER:
        from databricks.sdk.runtime import dbutils  # type: ignore
        return dbutils.secrets.get(scope=scope, key=key)

    from databricks.sdk import WorkspaceClient

    response = WorkspaceClient().secrets.get_secret(scope=scope, key=key)
    return base64.b64decode(response.value).decode("utf-8")
