#!/usr/bin/env python3
"""Query manifest.yaml, the single source of truth for this repo's releases:
which charms are released from which branch, on which Charmhub track.

Subcommands:
  charms BRANCH       JSON matrix [{"charm-path", "charm-name", "track",
                      "terraform-tag-prefix"?}] for every charm with a
                      release on BRANCH (consumed by charms-release.yaml's
                      set-charms job).
                      --only NAMES restricts it to the given charms; each
                      value is a charm name or a JSON array of names (e.g.
                      dorny/paths-filter output). Names without a release
                      on BRANCH are dropped.
  track BRANCH CHARM  The Charmhub track CHARM releases to from BRANCH; exits 1
                      if CHARM has no release on BRANCH.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "manifest.yaml"


def releases_on_branch(manifest: dict, branch: str):
    """Yield (charm, release) for each charm with a release on ``branch``."""
    for charm in manifest["artifacts"]["charms"]:
        for release in charm.get("releases") or []:
            if release.get("branch") == branch:
                yield charm, release
                break


def only_names(values: list[str]) -> set[str]:
    """Collect charm names from --only values: a name or a JSON array of names."""
    names: set[str] = set()
    for value in values:
        if not value.startswith("["):
            names.add(value)
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"error: --only {value} is not valid JSON: {exc}")
        if not isinstance(parsed, list) or not all(isinstance(n, str) for n in parsed):
            raise SystemExit(f"error: --only {value} must be a JSON array of charm names")
        names.update(parsed)
    return names


def charms_command(manifest: dict, args: argparse.Namespace) -> None:
    """Print the release matrix for every charm on ``args.branch``."""
    entries = []
    for charm, release in releases_on_branch(manifest, args.branch):
        entry = {
            "charm-path": charm["path"],
            "charm-name": charm["name"],
            "track": str(release["name"]),
        }
        if release.get("terraform-tag-prefix"):
            entry["terraform-tag-prefix"] = release["terraform-tag-prefix"]
        entries.append(entry)
    if args.only:
        only = only_names(args.only)
        entries = [e for e in entries if e["charm-name"] in only]
    print(json.dumps(entries))


def track_command(manifest: dict, args: argparse.Namespace) -> None:
    """Print the track of ``args.charm`` on ``args.branch``."""
    for charm, release in releases_on_branch(manifest, args.branch):
        if charm["name"] == args.charm:
            print(release["name"])
            return
    raise SystemExit(
        f"error: no release for charm '{args.charm}' on branch "
        f"'{args.branch}' in {args.manifest}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)

    p_charms = sub.add_parser(
        "charms", help="JSON matrix of charms released from BRANCH"
    )
    p_charms.add_argument("branch")
    p_charms.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        help="restrict the matrix to these charms: a charm name or a JSON array of names (e.g. dorny/paths-filter output)",
    )
    p_charms.set_defaults(func=charms_command)

    p_track = sub.add_parser("track", help="Charmhub track of CHARM on BRANCH")
    p_track.add_argument("branch")
    p_track.add_argument("charm")
    p_track.set_defaults(func=track_command)

    return parser


def load_manifest(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main() -> None:
    args = build_parser().parse_args()
    manifest = load_manifest(args.manifest)
    args.func(manifest, args)


if __name__ == "__main__":
    main()
