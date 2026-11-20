"""GitHub-Flavored Markdown report formatter for insta_archive analyses."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from insta_archive import (
    AccountHistory,
    ArchiveData,
    SnapshotDiff,
    all_account_histories,
    attribute_unfollows,
    classify_reappearances,
    compare_snapshot,
    diff_snapshots,
    loyalty_rankings,
    one_sided_history,
    timeline_summary,
)


def md_handle(username: str) -> str:
    """Wrap an Instagram handle in backticks so underscores do not become italics."""
    return f"`@{username}`"


def md_escape(text: str) -> str:
    """Escape pipe characters and normalize whitespace for Markdown table cells."""
    if not text:
        return ""
    return text.replace("\r\n", " ").replace("\n", " ").replace("|", "\\|").strip()


def fmt_ts(ts: int | None, *, include_time: bool = False) -> str:
    """Format a Unix epoch timestamp into a readable date string."""
    if ts is None or ts <= 0:
        return "-"
    fmt = "%Y-%m-%d %H:%M" if include_time else "%Y-%m-%d"
    return datetime.fromtimestamp(ts).strftime(fmt)


def fmt_duration(days: float | None) -> str:
    """Format a day count into a readable years/months/days string."""
    if days is None:
        return "-"
    total_days = max(0, int(round(days)))
    if total_days >= 365:
        years = total_days // 365
        months = (total_days % 365) // 30
        if months > 0:
            return f"{years}y {months}m ({total_days:,}d)"
        return f"{years}y ({total_days:,}d)"
    return f"{total_days:,}d"


def fmt_lag(seconds: int | None) -> str:
    """Format a follow-back lag in seconds into a compact human-readable string."""
    if seconds is None:
        return "-"
    s = max(0, int(seconds))
    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


def _fmt_signed(val: int | None) -> str:
    if val is None:
        return "-"
    if val > 0:
        return f"+{val}"
    return str(val)


def _format_handle_list(handles: list[str], limit: int = 200) -> str:
    if not handles:
        return "_None_"
    shown = handles[:limit]
    text = ", ".join(md_handle(h) for h in shown)
    if len(handles) > limit:
        text += f" _(+{len(handles) - limit} more)_"
    return text


def _append_diff_bullets(add: object, d: SnapshotDiff) -> None:
    add_fn = add  # type: ignore[assignment]
    add_fn(
        f"- **New Followers ({len(d.new_followers)}):** "
        f"{_format_handle_list(d.new_followers)}"
    )
    add_fn(
        f"- **Pure Unfollowers ({len(d.pure_unfollowers)} — unfollowed you, you still follow):** "
        f"{_format_handle_list(d.pure_unfollowers)}"
    )
    add_fn(
        f"- **Mutual Drops ({len(d.mutual_drops)} — both sides dropped):** "
        f"{_format_handle_list(d.mutual_drops)}"
    )
    add_fn(
        f"- **Newly Followed by You ({len(d.newly_followed)}):** "
        f"{_format_handle_list(d.newly_followed)}"
    )
    add_fn(
        f"- **Unfollowed by You Only ({len(d.pure_unfollowed_by_you)}):** "
        f"{_format_handle_list(d.pure_unfollowed_by_you)}"
    )
    add_fn(
        f"- **Renames Linked in Window ({len(d.renames_in_window)}):** "
        + (
            ", ".join(
                f"{md_handle(r.old_username)} -> {md_handle(r.new_username)}"
                for r in d.renames_in_window
            )
            if d.renames_in_window
            else "_None_"
        )
    )


def _format_history_events_cell(h: AccountHistory) -> str:
    parts: list[str] = []
    if h.renames:
        parts.append(f"{len(h.renames)} rename{'s' if len(h.renames) != 1 else ''}")
    if h.reappearances:
        deact = sum(1 for e in h.reappearances if e.kind == "deactivated_and_reactivated")
        refollow = len(h.reappearances) - deact
        if deact:
            parts.append(f"{deact} deact")
        if refollow:
            parts.append(f"{refollow} refollow")
    if h.unfollowed_log_events:
        parts.append(f"{len(h.unfollowed_log_events)} unfollow log")
    return ", ".join(parts) if parts else "-"


def generate_markdown_report(
    archive: ArchiveData,
    output_path: Path | str,
    top_n: int = 25,
) -> Path:
    """Generate a single self-contained GitHub-Flavored Markdown report covering all analyses."""
    if not archive.snapshots:
        raise ValueError("Cannot generate report: archive contains no paired snapshots.")

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    timeline = timeline_summary(archive)
    first_snap = archive.snapshots[0]
    latest_snap = archive.snapshots[-1]
    latest_breakdown = compare_snapshot(archive, -1)
    earliest_breakdown = compare_snapshot(archive, 1)
    one_sided = one_sided_history(archive)
    attributions = attribute_unfollows(archive)
    reappearances = classify_reappearances(archive, side="both")
    loyalty = loyalty_rankings(archive, top_n=top_n)
    histories = all_account_histories(archive)

    double_verified_renames = sum(1 for r in archive.renames if r.double_verified)
    single_side_renames = len(archive.renames) - double_verified_renames
    multi_hop_chains = [
        aliases for aliases in archive.canonical_to_aliases.values() if len(aliases) > 2
    ]

    empty_usernames = sum(
        sum(1 for u in s.followers if not u) + sum(1 for u in s.following if not u)
        for s in archive.snapshots
    )
    lower_alias_to_canon = {k.lower(): v for k, v in archive.alias_to_canonical.items()}

    lines: list[str] = []
    add = lines.append

    # Header & Executive Summary
    add("# Instagram Historical Archive Report")
    add("")
    add(f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    add(
        f"- **Coverage:** {len(archive.snapshots)} paired snapshots "
        f"({first_snap.date_str} to {latest_snap.date_str})"
    )
    add(
        f"- **Latest Snapshot (#{latest_snap.index}, {latest_snap.date_str}):** "
        f"{len(latest_snap.followers):,} followers | "
        f"{len(latest_snap.following):,} following | "
        f"{len(latest_breakdown.mutuals):,} mutuals | "
        f"{len(latest_breakdown.not_following_back):,} not following back "
        f"({len(one_sided.quietly_unfollowed_you)} quiet unfollowers, "
        f"{len(one_sided.never_followed_back)} never followed back) | "
        f"{len(latest_breakdown.fans_not_followed_back):,} fans not followed back"
    )
    add(
        f"- **Longitudinal Net Change (#{first_snap.index} -> #{latest_snap.index}):** "
        f"Followers {_fmt_signed(len(latest_snap.followers) - len(first_snap.followers))} "
        f"({len(first_snap.followers):,} -> {len(latest_snap.followers):,}), "
        f"Following {_fmt_signed(len(latest_snap.following) - len(first_snap.following))} "
        f"({len(first_snap.following):,} -> {len(latest_snap.following):,}), "
        f"Mutuals {_fmt_signed(len(latest_breakdown.mutuals) - len(earliest_breakdown.mutuals))}"
    )
    add(
        f"- **Detected Handle Changes:** {len(archive.renames)} rename transitions "
        f"({double_verified_renames} double-verified in both followers & following, "
        f"{single_side_renames} single-side, {len(multi_hop_chains)} multi-hop chains)"
    )
    add(
        f"- **Deactivations & Re-follows:** {len(reappearances)} events across followers & following"
    )
    add(
        f"- **Unfollow Logs Loaded:** {len(archive.unfollowed_records)} records across "
        f"{len({r.source_file for r in archive.unfollowed_records})} file(s)"
    )
    add(f"- **Accounts Indexed:** {len(histories):,} unique canonical accounts across history")
    add(
        f"- **Data Integrity:** {empty_usernames} empty usernames parsed across all snapshots | "
        f"{len(archive.skipped_files)} skipped/unpaired file(s)"
    )
    add("")

    # Table of Contents
    add("## Table of Contents")
    add("")
    add("1. [Timeline Summary](#1-timeline-summary)")
    add("2. [Latest Snapshot Breakdown and One-Sided Tracker](#2-latest-snapshot-breakdown-and-one-sided-tracker)")
    add("3. [Period-by-Period Diffs](#3-period-by-period-diffs)")
    add("4. [Unfollow Attribution](#4-unfollow-attribution)")
    add("5. [Handle Changes and Detected Renames](#5-handle-changes-and-detected-renames)")
    add("6. [Deactivations vs. Unfollow-and-Refollows](#6-deactivations-vs-unfollow-and-refollows)")
    add("7. [Loyalty Rankings](#7-loyalty-rankings)")
    add("8. [Complete Account History Directory](#8-complete-account-history-directory)")
    add("")

    # Section 1: Timeline Summary
    add("## 1. Timeline Summary")
    add("")
    add(
        "Each interval diff resolves detected username changes so renamed accounts do not appear "
        "as false unfollowers or false new followers."
    )
    add("")
    add(
        "| # | Date | Followers | Following | Mutuals | Not Back | Fans | "
        "Net Δ (F / G) | New F | Lost F | New G | Unfollowed G | Renames | Mutual Drops |"
    )
    add(
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for row in timeline:
        net_delta = (
            "-"
            if row.net_followers_delta is None
            else f"{_fmt_signed(row.net_followers_delta)} / {_fmt_signed(row.net_following_delta)}"
        )
        add(
            f"| {row.index} | {row.date_str} | {row.followers_count:,} | {row.following_count:,} | "
            f"{row.mutuals_count:,} | {row.not_following_back_count:,} | {row.fans_count:,} | "
            f"{net_delta} | "
            f"{'-' if row.true_new_followers is None else row.true_new_followers} | "
            f"{'-' if row.true_lost_followers is None else row.true_lost_followers} | "
            f"{'-' if row.true_newly_followed is None else row.true_newly_followed} | "
            f"{'-' if row.true_unfollowed is None else row.true_unfollowed} | "
            f"{'-' if row.renames_count is None else row.renames_count} | "
            f"{'-' if row.mutual_drops_count is None else row.mutual_drops_count} |"
        )
    add("")

    # Section 2: Latest Snapshot Breakdown & One-Sided Tracker
    add("## 2. Latest Snapshot Breakdown and One-Sided Tracker")
    add("")
    add(
        f"As of **#{latest_snap.index} ({latest_snap.date_str})**, out of "
        f"**{one_sided.total_not_following_back}** accounts you follow that do not follow you back: "
        f"**{len(one_sided.quietly_unfollowed_you)}** used to follow you and quietly unfollowed later, "
        f"while **{len(one_sided.never_followed_back)}** have never followed you back across recorded snapshots."
    )
    add("")

    add(f"### 2.1 Former Mutuals Who Quietly Unfollowed You ({len(one_sided.quietly_unfollowed_you)})")
    add("")
    if one_sided.quietly_unfollowed_you:
        add(
            "| Handle | You Followed | They Followed | Last Seen Following You | "
            "First Missing | Mutual Duration | One-Sided For |"
        )
        add("|---|---|---|---|---|---:|---:|")
        for entry in one_sided.quietly_unfollowed_you:
            add(
                f"| {md_handle(entry.current_handle)} | {fmt_ts(entry.you_followed_at)} | "
                f"{fmt_ts(entry.followed_you_at)} | {entry.last_seen_follower_date or '-'} | "
                f"{entry.first_missing_follower_date or '-'} | "
                f"{fmt_duration(entry.mutual_duration_days)} | "
                f"{fmt_duration(entry.one_sided_since_days)} |"
            )
    else:
        add("_None._")
    add("")

    add(f"### 2.2 Never Followed Back ({len(one_sided.never_followed_back)})")
    add("")
    if one_sided.never_followed_back:
        add("| Handle | You Followed | Following Duration |")
        add("|---|---|---:|")
        for entry in one_sided.never_followed_back:
            add(
                f"| {md_handle(entry.current_handle)} | {fmt_ts(entry.you_followed_at)} | "
                f"{fmt_duration(entry.following_days)} |"
            )
    else:
        add("_None._")
    add("")

    add(f"### 2.3 Fans You Don't Follow Back ({len(latest_breakdown.fans_not_followed_back)})")
    add("")
    if latest_breakdown.fans_not_followed_back:
        add("| Handle | Followed You | Duration |")
        add("|---|---|---:|")
        for rel in latest_breakdown.fans_not_followed_back:
            add(
                f"| {md_handle(rel.username)} | {fmt_ts(rel.followed_you_at)} | "
                f"{fmt_duration(rel.follower_days)} |"
            )
    else:
        add("0 fans — you currently follow back everyone who follows you.")
    add("")

    # Section 3: Period-by-Period Diffs
    add("## 3. Period-by-Period Diffs")
    add("")
    if len(archive.snapshots) >= 2:
        prev_snap = archive.snapshots[-2]
        latest_diff = diff_snapshots(archive, prev_snap.index, latest_snap.index, resolve_renames=True)
        add(
            f"### 3.1 Latest Period Diff (#{prev_snap.index} {prev_snap.date_str} -> "
            f"#{latest_snap.index} {latest_snap.date_str})"
        )
        add("")
        _append_diff_bullets(add, latest_diff)
        add("")

        if len(archive.snapshots) >= 3:
            add(
                f"### 3.2 All Earlier Period Diffs (#1 {first_snap.date_str} -> "
                f"#{prev_snap.index} {prev_snap.date_str})"
            )
            add("")
            for snap_a, snap_b in zip(archive.snapshots[:-2], archive.snapshots[1:-1]):
                d = diff_snapshots(archive, snap_a.index, snap_b.index, resolve_renames=True)
                summary_line = (
                    f"#{snap_a.index} ({snap_a.date_str}) -> #{snap_b.index} ({snap_b.date_str}) | "
                    f"+{len(d.new_followers)}/-{len(d.lost_followers)} followers, "
                    f"+{len(d.newly_followed)}/-{len(d.unfollowed_by_you)} following, "
                    f"{len(d.mutual_drops)} mutual drops, {len(d.renames_in_window)} renames"
                )
                add("<details>")
                add(f"<summary>{summary_line}</summary>")
                add("")
                _append_diff_bullets(add, d)
                add("")
                add("</details>")
                add("")
    else:
        add("_At least two snapshots are required to compute period diffs._")
        add("")

    # Section 4: Unfollow Attribution
    add("## 4. Unfollow Attribution")
    add("")
    add(
        "Cross-references dropped accounts against Instagram's `recently_unfollowed_profiles` exports "
        "to separate accounts you intentionally removed from organic unfollows or unattributed drops."
    )
    add("")
    add(
        "| Interval | Window | Unfollow Log Coverage | Intentionally Unfollowed | "
        "Unattributed Mutual Drops | Unfollowed You Only | Unfollowed By You (Unlogged) |"
    )
    add("|---|---|---|---:|---:|---:|---:|")
    for att in attributions:
        cov = "Yes" if att.has_unfollow_log_coverage else "No"
        add(
            f"| #{att.snap_a.index} -> #{att.snap_b.index} | "
            f"{att.snap_a.date_str} .. {att.snap_b.date_str} | {cov} | "
            f"{len(att.intentionally_unfollowed)} | {len(att.unattributed_mutual_drops)} | "
            f"{len(att.unfollowed_you_only)} | {len(att.unfollowed_by_you_unlogged)} |"
        )
    add("")

    for att in attributions:
        if not att.has_unfollow_log_coverage:
            continue
        a_ts = att.snap_a.taken_at.timestamp()
        b_ts = att.snap_b.taken_at.timestamp()
        recs_in_window = [r for r in archive.unfollowed_records if a_ts < r.timestamp <= b_ts]
        matched_keys = {
            (a.canonical_username.lower(), a.unfollowed_at)
            for a in att.intentionally_unfollowed
        }
        transient_recs = [
            r for r in recs_in_window
            if (lower_alias_to_canon.get(r.username.lower(), r.username).lower(), r.timestamp) not in matched_keys
        ]

        add(
            f"### 4.{att.snap_a.index} Covered Window: #{att.snap_a.index} ({att.snap_a.date_str}) -> "
            f"#{att.snap_b.index} ({att.snap_b.date_str})"
        )
        add("")
        if transient_recs:
            add(
                f"_Note: {len(recs_in_window)} log entries fell in this window; "
                f"{len(att.intentionally_unfollowed)} matched drops from #{att.snap_a.index}, and "
                f"{len(transient_recs)} were followed/unfollowed or re-followed entirely between snapshots._"
            )
            add("")

        add(f"#### Intentionally Unfollowed ({len(att.intentionally_unfollowed)})")
        add("")
        if att.intentionally_unfollowed:
            add("| Handle at Drop | Display Name | Unfollowed On | Also Left Followers? | Source File |")
            add("|---|---|---|---|---|")
            for item in att.intentionally_unfollowed:
                handle_disp = md_handle(item.handle_at_drop)
                if item.canonical_username != item.handle_at_drop:
                    handle_disp += f" (-> {md_handle(item.canonical_username)})"
                add(
                    f"| {handle_disp} | {md_escape(item.display_name) or '-'} | "
                    f"{fmt_ts(item.unfollowed_at, include_time=True)} | "
                    f"{'Yes' if item.dropped_from_followers else 'No'} | "
                    f"`{item.source_file or '-'}` |"
                )
        else:
            add("_None._")
        add("")

        if transient_recs:
            add("<details>")
            add(f"<summary>Transient / Re-followed Unfollow Log Entries in Window ({len(transient_recs)})</summary>")
            add("")
            add("| Handle | Display Name | Unfollowed On | Present in End Snapshot? | Source File |")
            add("|---|---|---|---|---|")
            for rec in sorted(transient_recs, key=lambda r: (-r.timestamp, r.username.lower())):
                canon = lower_alias_to_canon.get(rec.username.lower(), rec.username)
                aliases = archive.canonical_to_aliases.get(canon, [canon])
                in_end = any(a in att.snap_b.following for a in aliases)
                add(
                    f"| {md_handle(rec.username)} | {md_escape(rec.display_name) or '-'} | "
                    f"{fmt_ts(rec.timestamp, include_time=True)} | "
                    f"{'Yes (re-followed)' if in_end else 'No'} | `{rec.source_file}` |"
                )
            add("")
            add("</details>")
            add("")

        add(
            f"- **Unattributed Mutual Drops ({len(att.unattributed_mutual_drops)}):** "
            + _format_handle_list([a.canonical_username for a in att.unattributed_mutual_drops])
        )
        add(
            f"- **Unfollowed You Only ({len(att.unfollowed_you_only)}):** "
            + _format_handle_list([a.canonical_username for a in att.unfollowed_you_only])
        )
        add(
            f"- **Unfollowed By You (Unlogged) ({len(att.unfollowed_by_you_unlogged)}):** "
            + _format_handle_list([a.canonical_username for a in att.unfollowed_by_you_unlogged])
        )
        add("")

    # Section 5: Handle Changes / Detected Renames
    add("## 5. Handle Changes and Detected Renames")
    add("")
    add(
        f"Detected **{len(archive.renames)}** handle transitions across snapshots "
        f"(**{double_verified_renames}** double-verified across followers and following, "
        f"**{single_side_renames}** single-side)."
    )
    add("")
    if multi_hop_chains:
        add(f"### 5.1 Multi-Hop Rename Chains ({len(multi_hop_chains)})")
        add("")
        for chain in sorted(multi_hop_chains, key=lambda c: c[-1]):
            add("- " + " -> ".join(md_handle(h) for h in chain))
        add("")

    add(f"### 5.2 All Detected Rename Transitions ({len(archive.renames)})")
    add("")
    if archive.renames:
        add("| Window | Old Handle | New Handle | Follower Since | Following Since | Verification |")
        add("|---|---|---|---|---|---|")
        for r in archive.renames:
            window = f"#{r.from_snapshot} ({r.from_date}) -> #{r.to_snapshot} ({r.to_date})"
            if r.gap_snapshots > 0:
                window += f" [gap {r.gap_snapshots}]"
            ver = "Double-verified" if r.double_verified else (
                "Followers only" if r.follower_timestamp else "Following only"
            )
            add(
                f"| {window} | {md_handle(r.old_username)} | {md_handle(r.new_username)} | "
                f"{fmt_ts(r.follower_timestamp)} | {fmt_ts(r.following_timestamp)} | {ver} |"
            )
    else:
        add("_No renames detected._")
    add("")

    # Section 6: Reappearances (Deactivations vs Unfollow+Refollow)
    deactivated = [e for e in reappearances if e.kind == "deactivated_and_reactivated"]
    unfollowed_refollowed = [e for e in reappearances if e.kind == "unfollowed_and_refollowed"]
    between_snaps = [e for e in reappearances if e.kind == "refollowed_between_snapshots"]

    add("## 6. Deactivations vs. Unfollow-and-Refollows")
    add("")
    add(
        f"Total events: **{len(reappearances)}**\n\n"
        f"- **Deactivated & Reactivated (same follow timestamp after gap):** {len(deactivated)}\n"
        f"- **Unfollowed & Re-followed (new follow timestamp after gap):** {len(unfollowed_refollowed)}\n"
        f"- **Re-followed Between Consecutive Snapshots (timestamp changed):** {len(between_snaps)}"
    )
    add("")

    for heading, subset in (
        ("6.1 Deactivated & Reactivated", deactivated),
        ("6.2 Unfollowed & Re-followed", unfollowed_refollowed),
        ("6.3 Re-followed Between Consecutive Snapshots", between_snaps),
    ):
        add(f"### {heading} ({len(subset)})")
        add("")
        if subset:
            add("| Handle | Side | Last Seen | Reappeared | Missing Snaps | Old Follow Date | New Follow Date |")
            add("|---|---|---|---|---:|---|---|")
            for ev in subset:
                handle_disp = md_handle(ev.canonical_username)
                if ev.username != ev.canonical_username:
                    handle_disp += f" (seen as {md_handle(ev.username)})"
                add(
                    f"| {handle_disp} | {ev.side} | "
                    f"#{ev.last_seen_snapshot} ({ev.last_seen_date}) | "
                    f"#{ev.reappeared_snapshot} ({ev.reappeared_date}) | "
                    f"{ev.missing_snapshots} | {fmt_ts(ev.old_timestamp)} | {fmt_ts(ev.new_timestamp)} |"
                )
        else:
            add("_None._")
        add("")

    # Section 7: Loyalty Rankings
    add("## 7. Loyalty Rankings")
    add("")
    add(f"Showing top **{top_n}** per category as of **{loyalty.as_of_date}**.")
    add("")

    add(f"### 7.1 Longest-Standing Current Followers (Top {len(loyalty.longest_current_followers)})")
    add("")
    add("| Rank | Handle | Followed You Since | Tenure | Mutual? |")
    add("|---:|---|---|---:|---|")
    for rank, item in enumerate(loyalty.longest_current_followers, start=1):
        add(
            f"| {rank} | {md_handle(item.current_handle)} | {fmt_ts(item.started_at)} | "
            f"{fmt_duration(item.duration_days)} | {'Yes' if item.is_mutual else 'No'} |"
        )
    add("")

    add(f"### 7.2 Longest-Standing Current Mutuals (Top {len(loyalty.longest_current_mutuals)})")
    add("")
    add("| Rank | Handle | Mutual Since | Mutual Tenure |")
    add("|---:|---|---|---:|")
    for rank, item in enumerate(loyalty.longest_current_mutuals, start=1):
        add(
            f"| {rank} | {md_handle(item.current_handle)} | {fmt_ts(item.started_at)} | "
            f"{fmt_duration(item.duration_days)} |"
        )
    add("")

    add(f"### 7.3 Longest-Standing Former Followers Who Left (Top {len(loyalty.longest_former_followers)})")
    add("")
    if loyalty.longest_former_followers:
        add("| Rank | Handle | Followed Since | Tenure Before Drop | Lost Between | In Your Unfollow Log? |")
        add("|---:|---|---|---:|---|---|")
        for rank, item in enumerate(loyalty.longest_former_followers, start=1):
            attr_str = (
                f"Yes ({md_escape(item.display_name)})" if item.attributed_to_you and item.display_name
                else ("Yes" if item.attributed_to_you else "No")
            )
            add(
                f"| {rank} | {md_handle(item.current_handle)} | {fmt_ts(item.started_at)} | "
                f"{fmt_duration(item.duration_days)} | {item.lost_between or '-'} | {attr_str} |"
            )
    else:
        add("_None._")
    add("")

    # Section 8: Complete Account History Directory
    status_counts = Counter(h.current_status for h in histories)
    add("## 8. Complete Account History Directory")
    add("")
    add(
        f"Indexed **{len(histories):,}** unique canonical accounts across all {len(archive.snapshots)} "
        f"snapshots and {len(archive.unfollowed_records)} unfollow log records:"
    )
    add("")
    status_labels = (
        ("not_following_back", "Not following back"),
        ("fan_only", "Fans you don't follow back"),
        ("mutual", "Active mutuals"),
        ("former_mutual", "Former mutuals"),
        ("former_follower", "Former followers only"),
        ("former_following", "Former following only"),
        ("unfollowed_log_only", "Transient unfollow-log only"),
    )
    add("| Status | Label | Accounts |")
    add("|---|---|---:|")
    for status_key, label in status_labels:
        add(f"| `{status_key}` | {label} | {status_counts.get(status_key, 0):,} |")
    add("")

    add("<details>")
    add(
        f"<summary>Expand full searchable account history directory ({len(histories):,} accounts — "
        f"use Ctrl+F for any current or former handle)</summary>"
    )
    add("")
    add(
        "| Handle | Former Handle(s) | Display Name | Status | Followed You | "
        "You Followed | First / Lag | Events | Summary |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for h in histories:
        former = (
            ", ".join(md_handle(a) for a in h.all_handles[:-1])
            if len(h.all_handles) > 1
            else "-"
        )
        first_lag = (
            f"{h.who_followed_first} ({fmt_lag(h.follow_back_lag_seconds)})"
            if h.who_followed_first
            else "-"
        )
        add(
            f"| {md_handle(h.canonical_username)} | {former} | "
            f"{md_escape(h.display_name) or '-'} | `{h.current_status}` | "
            f"{fmt_ts(h.followed_you_first_ts)} | {fmt_ts(h.you_followed_first_ts)} | "
            f"{first_lag} | {_format_history_events_cell(h)} | {md_escape(h.ended_summary)} |"
        )
    add("")
    add("</details>")
    add("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def format_account_history_markdown(history: AccountHistory) -> str:
    """Format a single account's complete longitudinal history as Markdown."""
    lines: list[str] = []
    add = lines.append

    add(f"# Account History: {md_handle(history.canonical_username)}")
    add("")
    if history.display_name:
        add(f"- **Display Name (from unfollow log):** {md_escape(history.display_name)}")
    add(f"- **Current Status:** `{history.current_status}`")
    add(f"- **Summary:** {history.ended_summary}")
    add(
        "- **All Known Handles:** "
        + ", ".join(md_handle(h) for h in history.all_handles)
    )
    add(
        f"- **Followed You:** earliest `{fmt_ts(history.followed_you_first_ts, include_time=True)}` "
        f"| latest `{fmt_ts(history.followed_you_latest_ts, include_time=True)}`"
    )
    add(
        f"- **You Followed:** earliest `{fmt_ts(history.you_followed_first_ts, include_time=True)}` "
        f"| latest `{fmt_ts(history.you_followed_latest_ts, include_time=True)}`"
    )
    if history.who_followed_first:
        add(
            f"- **Initiation:** `{history.who_followed_first}` followed first "
            f"(follow-back lag: {fmt_lag(history.follow_back_lag_seconds)})"
        )
    add("")

    if history.renames:
        add("## Rename Transitions")
        add("")
        for r in history.renames:
            ver = "double-verified" if r.double_verified else "single-side"
            add(
                f"- {md_handle(r.old_username)} -> {md_handle(r.new_username)} "
                f"(#{r.from_snapshot} {r.from_date} -> #{r.to_snapshot} {r.to_date}, {ver})"
            )
        add("")

    if history.reappearances:
        add("## Deactivations & Re-follows")
        add("")
        for ev in history.reappearances:
            add(
                f"- `{ev.side}` `{ev.kind}`: last seen #{ev.last_seen_snapshot} ({ev.last_seen_date}), "
                f"reappeared #{ev.reappeared_snapshot} ({ev.reappeared_date}), "
                f"ts `{fmt_ts(ev.old_timestamp)}` -> `{fmt_ts(ev.new_timestamp)}`"
            )
        add("")

    if history.unfollowed_log_events:
        add("## `recently_unfollowed_profiles` Log Matches")
        add("")
        for rec in history.unfollowed_log_events:
            add(
                f"- Unfollowed {md_handle(rec.username)} "
                f"({md_escape(rec.display_name) or 'no name'}) on "
                f"`{fmt_ts(rec.timestamp, include_time=True)}` (`{rec.source_file}`)"
            )
        add("")

    add("## Snapshot Presence")
    add("")
    add("| # | Date | Handle | Follower? | Following? | Followed You | You Followed |")
    add("|---:|---|---|---|---|---|---|")
    for p in history.snapshot_presence:
        add(
            f"| {p.snapshot_index} | {p.date_str} | "
            f"{md_handle(p.handle) if p.handle else '-'} | "
            f"{'Yes' if p.is_follower else '-'} | "
            f"{'Yes' if p.is_following else '-'} | "
            f"{fmt_ts(p.follower_timestamp)} | {fmt_ts(p.following_timestamp)} |"
        )
    add("")
    return "\n".join(lines)
