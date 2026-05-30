"""``forgejudge`` command-line entrypoint (the ``[project.scripts]`` console script).

Kept dependency-light: every subcommand lazy-imports what it needs, so
``forgejudge --version`` / ``forgejudge info`` work even without the optional
``mcp`` / ``playground`` / ``harness`` extras installed.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import sys

HOMEPAGE = "https://forgejudge.ahmedhobeishy.tech"
REPO = "https://github.com/ahmedEid1/forgejudge"


def _version() -> str:
    try:
        return md.version("forgejudge")
    except md.PackageNotFoundError:  # running from a source checkout
        return "0.0.0+local"


def _cmd_info(_: argparse.Namespace) -> int:
    print(f"forgejudge {_version()}")
    print("Open, always-on leaderboard + CI gate for autonomous coding agents.")
    print(f"  leaderboard : {HOMEPAGE}")
    print(f"  source      : {REPO}")
    print("  subcommands : selftest | mcp | info  (run `forgejudge <cmd> -h`)")
    return 0


def _cmd_selftest(args: argparse.Namespace) -> int:
    """Deterministic harness self-test: grade the gold patches (no API key, no network)."""
    from forgejudge.harness import runner_actions

    sys.argv = ["forgejudge-selftest", "--patch-source", args.patch_source]
    runner_actions.main()
    return 0


def _cmd_mcp(_: argparse.Namespace) -> int:
    """Run the ForgeJudge MCP server over stdio (requires the `mcp` extra)."""
    try:
        from forgejudge.mcp import server
    except ModuleNotFoundError as exc:  # pragma: no cover - optional extra
        print(f"the MCP server needs the 'mcp' extra: pip install 'forgejudge[mcp]' ({exc})", file=sys.stderr)
        return 1
    server.main()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forgejudge", description="ForgeJudge — execution-as-judge for autonomous coding agents")
    parser.add_argument("--version", action="version", version=f"forgejudge {_version()}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("info", help="print package info + links").set_defaults(func=_cmd_info)

    st = sub.add_parser("selftest", help="grade the gold patches (deterministic, $0)")
    st.add_argument("--patch-source", default="gold")
    st.set_defaults(func=_cmd_selftest)

    sub.add_parser("mcp", help="run the MCP server over stdio (needs the 'mcp' extra)").set_defaults(func=_cmd_mcp)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        return _cmd_info(args)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
