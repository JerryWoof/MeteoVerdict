import re

from typer.testing import CliRunner

import meteoverdict
from meteoverdict.cli import app

runner = CliRunner()


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", meteoverdict.__version__)


def test_cli_version_flag():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"mvd {meteoverdict.__version__}"
