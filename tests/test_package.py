import re

import meteoverdict
from meteoverdict import cli


def test_version_is_semver_like():
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", meteoverdict.__version__)


def test_cli_version_flag(capsys):
    assert cli.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"mvd {meteoverdict.__version__}"


def test_cli_without_args_points_to_roadmap(capsys):
    assert cli.main([]) == 0
    assert "ROADMAP" in capsys.readouterr().out


def test_cli_rejects_unknown_arguments():
    assert cli.main(["fetch-obs"]) == 2
