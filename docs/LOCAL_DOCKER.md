# Run the Jira Agent locally (Windows, macOS, Linux)

## Native start (recommended)

Install Python 3.11+, [uv](https://docs.astral.sh/uv/), Git and Node.js
22.12+ (or 20.19+). Configure access to Azure OpenAI and Jira in
your local environment. If needed, set up Databricks authentication for
features using MLflow or Unity Catalog.

```sh
uv run start-app
```

Open <http://localhost:8000>. The launcher installs/builds the frontend
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
docker run --rm --name t1-jira-agent -p 8000:8000 -p 3000:3000 --env-file .env t1-jira-agent:local
```

Open <http://localhost:8000>. If your setup uses Databricks CLI profiles,
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
- `uv run start-app --no-ui` starts the API only for troubleshooting.
