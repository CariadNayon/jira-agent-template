"""Windows/macOS/Linux launcher regressions."""
from unittest.mock import patch

import pytest

from scripts.start_app import executable


def test_executable_resolves_windows_cmd_shim():
    with patch("scripts.start_app.shutil.which", return_value=r"C:\\Program Files\\nodejs\\npm.cmd"):
        assert executable("npm").endswith("npm.cmd")


def test_executable_resolves_unix_executable():
    with patch("scripts.start_app.shutil.which", return_value="/usr/local/bin/node"):
        assert executable("node") == "/usr/local/bin/node"


def test_missing_executable_has_actionable_error():
    with patch("scripts.start_app.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Install it and restart your terminal"):
            executable("npm")
