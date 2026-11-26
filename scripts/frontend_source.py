"""The tested upstream revision and the one shared preparation path for runtime and CI."""
from pathlib import Path

FRONTEND_REVISION='7aea1f68038e7cfd0d5c89cafd31a42d1ff290b6'


def prepare_frontend(frontend: Path) -> None:
    from scripts.frontend_identity import ensure_frontend_identity
    from scripts.frontend_local_auth import ensure_frontend_local_auth
    from scripts.frontend_safety import ensure_frontend_safety
    from scripts.frontend_attachments import ensure_frontend_attachments
    from scripts.frontend_results import ensure_frontend_results
    from scripts.frontend_details import ensure_frontend_details
    ensure_frontend_identity(frontend)
    ensure_frontend_local_auth(frontend)
    ensure_frontend_safety(frontend)
    ensure_frontend_attachments(frontend)
    ensure_frontend_results(frontend)
    ensure_frontend_details(frontend)
    from scripts.frontend_input import ensure_frontend_input
    ensure_frontend_input(frontend)
    from scripts.frontend_markdown import ensure_frontend_markdown
    ensure_frontend_markdown(frontend)
