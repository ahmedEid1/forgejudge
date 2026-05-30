"""The `forgejudge` console-script entrypoint (forgejudge.cli)."""

import forgejudge.cli as cli


def test_version_matches_package():
    assert cli._version()  # resolvable (installed) or the source fallback


def test_info_prints_links(capsys):
    rc = cli.main(["info"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "forgejudge" in out
    assert "forgejudge.ahmedhobeishy.tech" in out
    assert "github.com/ahmedEid1/forgejudge" in out


def test_no_subcommand_defaults_to_info(capsys):
    rc = cli.main([])
    assert rc == 0
    assert "leaderboard" in capsys.readouterr().out


def test_version_flag_exits_zero(capsys):
    import pytest
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "forgejudge" in capsys.readouterr().out
