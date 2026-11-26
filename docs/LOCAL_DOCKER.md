# Run the Jira Agent locally (Windows, macOS, Linux)

## Native start (recommended)

Install Python 3.11+, [uv](https://docs.astral.sh/uv/), Git and Node.js
22.12+ (or 20.19+). Configure access to Azure OpenAI and Jira in
your local environment. If needed, set up Databricks authentication for
features using MLflow or Unity Catalog.

```sh
uv run start-app --local
```

Open <http://localhost:8000>. The `--local` flag enables an isolated local
session: no Databricks Apps sign-in and no Databricks CLI/SCIM authentication
for the chat UI. Jira still needs your personal access token. The shared
Unity Catalog skill table requires Databricks permissions/OBO and is not
automatically available in local mode. Local settings and personal skills
are kept in memory; they are not synchronized to your Databricks account.

Local mode is deliberately opt-in; `uv run start-app` without `--local`
keeps production authentication behavior. The launcher installs/builds the frontend
and starts the Python backend and the Node server. The upstream npm
`start` script uses POSIX-only syntax; this repository starts the Node
entrypoint directly so it also runs on Windows. No `cross-env` needed.

## Docker Desktop (optional)

Install Docker Desktop and ensure Docker is running.

Build the image:

```sh
docker build -t t1-jira-agent:local .
```

Create a local `.env` with the required credentials and endpoints. Do not
commit it to Git. For a minimal local run, a valid Azure model key and Jira
connectivity are still required. Databricks-backed features require the
appropriate Databricks credentials/permissions.

Windows PowerShell / macOS / Linux:

```sh
docker run --rm --name t1-jira-agent -p 127.0.0.1:8000:8000 -p 127.0.0.1:3000:3000 -e JIRA_AGENT_LOCAL_BIND_ALL=1 --env-file .env t1-jira-agent:local
```

Open <http://localhost:8000>. Keep both published ports bound to **127.0.0.1**:
local mode does not authenticate browser users and must not be exposed on a
public network. If your setup uses Databricks CLI profiles,
mount the profile file inside the container or provide the supported
Databricks environment-based authentication variables.

The first container startup downloads the pinned Databricks chat frontend
and installs/builds its Node dependencies. This can take several minutes.
The container requires network access to GitHub, your model endpoint,
Jira and optionally Databricks. Docker packages the application but does
not eliminate those external requirements.

## Troubleshooting

- `npm` not found: install Node.js and reopen your terminal.
- `UnicodeDecodeError` on Windows: update the repository; subprocesses
  use UTF-8 with replacement for undecodable bytes.
- `NODE_ENV is not recognized`: update the repository; the Node server
  is now started directly instead of through the POSIX npm script.
- Port 8000 or 3000 in use: stop the existing process/container.
- `uv run start-app --local --no-ui` starts the API only for troubleshooting.
