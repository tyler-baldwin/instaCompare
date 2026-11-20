"""Single-command CLI to run all Instagram archive analyses and write one Markdown report."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from insta_archive import (
    all_account_histories,
    attribute_unfollows,
    classify_reappearances,
    compare_snapshot,
    load_archive,
    one_sided_history,
)
from report_generator import generate_markdown_report


def _configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="instaCompare.py",
        description=(
            "Run all bug-free Instagram followers/following cross-reference analyses and "
            "generate one complete Markdown report."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        default="insta_report.md",
        help="Output Markdown report path (default: 'insta_report.md').",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Rows per loyalty ranking table (default: 25).",
    )
    parser.add_argument(
        "--archive-dir",
        default="archival follwers",
        help="Path to archival JSON exports directory (default: 'archival follwers').",
    )
    parser.add_argument(
        "--root-dir",
        default=".",
        help="Path to root directory containing latest followers_1.json / following.json (default: '.').",
    )
    parser.add_argument(
        "--no-root",
        action="store_true",
        help="Only read --archive-dir and skip JSON files in --root-dir.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    root_dir = None if args.no_root else Path(args.root_dir)
    archive_dir = Path(args.archive_dir) if args.archive_dir else None
    archive = load_archive(archive_dir=archive_dir, root_dir=root_dir)

    if not archive.snapshots:
        print("Error: No paired followers/following snapshots were found.", file=sys.stderr)
        return 1

    out_path = generate_markdown_report(archive, Path(args.output), top_n=args.top)

    first = archive.snapshots[0]
    latest = archive.snapshots[-1]
    breakdown = compare_snapshot(archive, -1)
    one_sided = one_sided_history(archive)
    reappearances = classify_reappearances(archive, side="both")
    attributions = attribute_unfollows(archive)
    matched_unfollows = sum(len(a.intentionally_unfollowed) for a in attributions)
    double_verified = sum(1 for r in archive.renames if r.double_verified)
    total_accounts = len(all_account_histories(archive))

    print(f"Loaded {len(archive.snapshots)} paired snapshots ({first.date_str} -> {latest.date_str}).")
    print(
        f"Latest (#{latest.index}, {latest.date_str}): "
        f"{len(latest.followers):,} followers | {len(latest.following):,} following | "
        f"{len(breakdown.mutuals):,} mutuals | {len(breakdown.not_following_back):,} not following back "
        f"({len(one_sided.quietly_unfollowed_you)} quiet unfollowers, "
        f"{len(one_sided.never_followed_back)} never followed back) | "
        f"{len(breakdown.fans_not_followed_back):,} fans."
    )
    print(
        f"History: {len(archive.renames)} renames ({double_verified} double-verified) | "
        f"{len(reappearances)} deactivation/re-follow events | "
        f"{len(archive.unfollowed_records)} unfollow log records ({matched_unfollows} matched to drops) | "
        f"{total_accounts:,} unique accounts indexed."
    )
    print(f"Full Markdown report written to: {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
