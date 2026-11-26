"""Opt-in localhost authentication for the pinned Databricks chat frontend.

No upstream production authentication is changed unless the launcher explicitly
sets JIRA_AGENT_LOCAL_MODE=1. The launcher binds both servers to loopback.
"""
from pathlib import Path

_MARKER_AUTH = "// Jira Agent: explicit localhost-only session."
_MARKER_PROVIDER = "// Jira Agent: localhost API proxy needs no Databricks OAuth."
_MARKER_BIND = "// Jira Agent: bind local development UI to loopback."


def _patch(path: Path, marker: str, anchor: str, replacement: str) -> None:
    source = path.read_text(encoding="utf-8")
    if marker in source:
        return
    if source.count(anchor) != 1:
        raise RuntimeError(f"Unexpected pinned frontend source at {path}: required anchor missing.")
    path.write_text(source.replace(anchor, replacement, 1), encoding="utf-8")


def ensure_frontend_local_auth(frontend: Path) -> None:
    """Patch at build time; also applies when the upstream frontend is already present."""
    auth = frontend / "server/src/middleware/auth.ts"
    _patch(auth, _MARKER_AUTH,
           "  try {\n    const session = await getAuthSession({",
           """  try {
    // Jira Agent: explicit localhost-only session.
    if (process.env.JIRA_AGENT_LOCAL_MODE === '1' &&
        !process.env.DATABRICKS_APP_NAME &&
        !process.env.DATABRICKS_RUNTIME_VERSION) {
      req.session = {
        user: {
          id: 'local',
          email: 'local',
          name: 'Local Developer',
          preferredUsername: 'local',
          type: 'regular',
        },
      };
      return next();
    }
    const session = await getAuthSession({""")

    provider = frontend / "packages/ai-sdk-providers/src/providers-server.ts"
    _patch(provider, _MARKER_PROVIDER,
           "  console.log('Creating new OAuth provider');\n  // Ensure we have a valid token before creating provider",
           """  // Jira Agent: localhost API proxy needs no Databricks OAuth.
  if (API_PROXY && process.env.JIRA_AGENT_LOCAL_MODE === '1' &&
      !process.env.DATABRICKS_APP_NAME &&
      !process.env.DATABRICKS_RUNTIME_VERSION) {
    const localProvider = createDatabricksProvider({
      useRemoteToolCalling: true,
      baseURL: 'http://127.0.0.1',
      formatUrl: () => API_PROXY,
      fetch: databricksFetch,
    });
    oauthProviderCache = localProvider;
    oauthProviderCacheTime = Date.now();
    return localProvider;
  }
  console.log('Creating new OAuth provider');
  // Ensure we have a valid token before creating provider""")

    index = frontend / "server/src/index.ts"
    _patch(index, _MARKER_BIND,
           "  app.listen(PORT, () => {",
           """  // Jira Agent: bind local development UI to loopback.
  // The explicit container override is only for host-loopback Docker port mappings.
  const localOnly = process.env.JIRA_AGENT_LOCAL_MODE === '1' &&
    !process.env.DATABRICKS_APP_NAME &&
    !process.env.DATABRICKS_RUNTIME_VERSION;
  const listenHost = localOnly
    ? (process.env.JIRA_AGENT_LOCAL_BIND_ALL === '1' ? '0.0.0.0' : '127.0.0.1')
    : '0.0.0.0';
  app.listen(PORT, listenHost, () => {""")
