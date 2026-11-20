"""Core data models, bug-free Instagram archive loaders, and historical analysis functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


@dataclass(frozen=True)
class FollowRecord:
    """A single follower or following entry from an Instagram export."""

    username: str
    timestamp: int
    href: str


@dataclass(frozen=True)
class UnfollowRecord:
    """An entry from Instagram's recently_unfollowed_profiles export."""

    username: str
    timestamp: int
    display_name: str
    url: str
    fbid: str | None
    source_file: str


@dataclass
class Snapshot:
    """A chronologically paired followers + following snapshot."""

    index: int
    date_str: str
    taken_at: datetime
    followers_path: Path
    following_path: Path
    followers: dict[str, FollowRecord]
    following: dict[str, FollowRecord]


@dataclass(frozen=True)
class RenameEvent:
    """A detected username/handle change inferred from preserved follow timestamps."""

    old_username: str
    new_username: str
    from_snapshot: int
    to_snapshot: int
    from_date: str
    to_date: str
    follower_timestamp: int | None
    following_timestamp: int | None
    double_verified: bool
    gap_snapshots: int


@dataclass(frozen=True)
class ReappearanceEvent:
    """An account that disappeared and returned, or changed follow timestamp."""

    username: str
    canonical_username: str
    side: str
    kind: str
    last_seen_snapshot: int
    last_seen_date: str
    reappeared_snapshot: int
    reappeared_date: str
    old_timestamp: int
    new_timestamp: int
    missing_snapshots: int


@dataclass(frozen=True)
class RelationshipEntry:
    """Relationship state and follow duration within a single snapshot."""

    username: str
    followed_you_at: int | None
    you_followed_at: int | None
    follower_days: float | None
    following_days: float | None


@dataclass
class SnapshotBreakdown:
    """Set breakdown of a single snapshot into mutuals, one-sided, and fans."""

    snapshot: Snapshot
    mutuals: list[RelationshipEntry]
    not_following_back: list[RelationshipEntry]
    fans_not_followed_back: list[RelationshipEntry]


@dataclass
class SnapshotDiff:
    """Rename-aware diff between two snapshots."""

    snap_a: Snapshot
    snap_b: Snapshot
    new_followers: list[str]
    lost_followers: list[str]
    newly_followed: list[str]
    unfollowed_by_you: list[str]
    mutual_drops: list[str]
    pure_unfollowers: list[str]
    pure_unfollowed_by_you: list[str]
    renames_in_window: list[RenameEvent]


@dataclass(frozen=True)
class AttributedAccount:
    """A dropped account cross-referenced with recently_unfollowed_profiles."""

    canonical_username: str
    handle_at_drop: str
    category: str
    display_name: str
    unfollowed_at: int | None
    dropped_from_followers: bool
    dropped_from_following: bool
    source_file: str | None


@dataclass
class IntervalAttribution:
    """Attribution breakdown for drops across a snapshot interval."""

    snap_a: Snapshot
    snap_b: Snapshot
    has_unfollow_log_coverage: bool
    intentionally_unfollowed: list[AttributedAccount]
    unattributed_mutual_drops: list[AttributedAccount]
    unfollowed_you_only: list[AttributedAccount]
    unfollowed_by_you_unlogged: list[AttributedAccount]


@dataclass(frozen=True)
class SnapshotPresence:
    """Per-snapshot presence record for a single account."""

    snapshot_index: int
    date_str: str
    handle: str | None
    is_follower: bool
    is_following: bool
    follower_timestamp: int | None
    following_timestamp: int | None


@dataclass
class AccountHistory:
    """Complete longitudinal timeline for a single Instagram account."""

    query: str
    canonical_username: str
    all_handles: list[str]
    display_name: str
    current_status: str
    renames: list[RenameEvent]
    followed_you_first_ts: int | None
    followed_you_latest_ts: int | None
    you_followed_first_ts: int | None
    you_followed_latest_ts: int | None
    who_followed_first: str | None
    follow_back_lag_seconds: int | None
    reappearances: list[ReappearanceEvent]
    unfollowed_log_events: list[UnfollowRecord]
    snapshot_presence: list[SnapshotPresence]
    ended_summary: str


@dataclass(frozen=True)
class TimelineRow:
    """Longitudinal metrics for one snapshot in the archive timeline."""

    index: int
    date_str: str
    followers_count: int
    following_count: int
    mutuals_count: int
    not_following_back_count: int
    fans_count: int
    net_followers_delta: int | None
    net_following_delta: int | None
    true_new_followers: int | None
    true_lost_followers: int | None
    true_newly_followed: int | None
    true_unfollowed: int | None
    renames_count: int | None
    mutual_drops_count: int | None


@dataclass(frozen=True)
class LoyaltyEntry:
    """A longest-standing current or former follower/mutual."""

    canonical_username: str
    current_handle: str
    started_at: int
    duration_days: float
    is_mutual: bool
    lost_between: str | None = None
    attributed_to_you: bool = False
    display_name: str = ""


@dataclass
class LoyaltyReport:
    """Rankings of longest-standing followers, mutuals, and former followers."""

    as_of_date: str
    longest_current_followers: list[LoyaltyEntry]
    longest_current_mutuals: list[LoyaltyEntry]
    longest_former_followers: list[LoyaltyEntry]


@dataclass(frozen=True)
class OneSidedEntry:
    """A followed account not following back, classified by history."""

    canonical_username: str
    current_handle: str
    you_followed_at: int
    following_days: float
    category: str
    ever_followed_you: bool
    followed_you_at: int | None = None
    last_seen_follower_date: str | None = None
    first_missing_follower_date: str | None = None
    mutual_duration_days: float | None = None
    one_sided_since_days: float | None = None


@dataclass
class OneSidedReport:
    """Breakdown of one-sided follows into quiet unfollowers vs never followed back."""

    as_of_date: str
    total_not_following_back: int
    quietly_unfollowed_you: list[OneSidedEntry]
    never_followed_back: list[OneSidedEntry]


@dataclass
class ArchiveData:
    """Loaded, paired, and identity-linked Instagram export archive."""

    snapshots: list[Snapshot]
    unfollowed_records: list[UnfollowRecord]
    renames: list[RenameEvent]
    alias_to_canonical: dict[str, str]
    canonical_to_aliases: dict[str, list[str]]
    skipped_files: list[str] = field(default_factory=list)


@dataclass
class _ParsedSideFile:
    kind: str
    path: Path
    mtime: float
    max_ts: int
    records: dict[str, FollowRecord]


def decode_meta_text(text: str) -> str:
    """Fix Meta/Instagram UTF-8-encoded-as-Latin-1 mojibake when present."""
    if not text:
        return ""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _username_from_href(href: str) -> str:
    if not href:
        return ""
    path = urlparse(href.strip()).path.strip("/")
    if path.startswith("_u/"):
        path = path[3:]
    if not path:
        return ""
    return path.split("/")[0].strip()


def extract_username(entry: dict) -> str:
    """Extract a username across both old and new Instagram JSON schemas."""
    title = entry.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    sld_list = entry.get("string_list_data")
    if isinstance(sld_list, list) and sld_list:
        sld = sld_list[0]
        if isinstance(sld, dict):
            value = sld.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
            href = sld.get("href")
            if isinstance(href, str) and href.strip():
                return _username_from_href(href)

    return ""


def _parse_follow_items(items: Iterable[dict]) -> tuple[dict[str, FollowRecord], int]:
    records: dict[str, FollowRecord] = {}
    max_ts = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        username = extract_username(item)
        if not username:
            continue
        sld_list = item.get("string_list_data")
        sld = sld_list[0] if isinstance(sld_list, list) and sld_list and isinstance(sld_list[0], dict) else {}
        raw_ts = sld.get("timestamp")
        ts = int(raw_ts) if raw_ts is not None else 0
        href = str(sld.get("href") or "")
        if ts > max_ts:
            max_ts = ts
        records[username] = FollowRecord(username=username, timestamp=ts, href=href)
    return records, max_ts


def _parse_label_values_unfollowed(items: Iterable[dict], source_file: str) -> list[UnfollowRecord]:
    out: list[UnfollowRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        labels: dict[str, str] = {}
        for lv in item.get("label_values") or []:
            if isinstance(lv, dict) and lv.get("label"):
                labels[str(lv["label"])] = str(lv.get("value") or "")
        url = labels.get("URL", "").strip()
        username = labels.get("Username", "").strip() or _username_from_href(url)
        if not username:
            continue
        display_name = decode_meta_text(labels.get("Name", "").strip())
        raw_ts = item.get("timestamp")
        ts = int(raw_ts) if raw_ts is not None else 0
        fbid = str(item["fbid"]) if item.get("fbid") is not None else None
        out.append(
            UnfollowRecord(
                username=username,
                timestamp=ts,
                display_name=display_name,
                url=url,
                fbid=fbid,
                source_file=source_file,
            )
        )
    return out


def _parse_classic_unfollowed(items: Iterable[dict], source_file: str) -> list[UnfollowRecord]:
    out: list[UnfollowRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        username = extract_username(item)
        if not username:
            continue
        sld_list = item.get("string_list_data")
        sld = sld_list[0] if isinstance(sld_list, list) and sld_list and isinstance(sld_list[0], dict) else {}
        raw_ts = sld.get("timestamp")
        ts = int(raw_ts) if raw_ts is not None else 0
        url = str(sld.get("href") or "")
        display_name = decode_meta_text(str(item.get("title") or "").strip())
        out.append(
            UnfollowRecord(
                username=username,
                timestamp=ts,
                display_name=display_name,
                url=url,
                fbid=None,
                source_file=source_file,
            )
        )
    return out


def classify_and_parse_json(
    path: Path,
) -> tuple[str, _ParsedSideFile | list[UnfollowRecord] | None]:
    """Read a JSON file safely with UTF-8 and classify by schema rather than filename."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return "unknown", None

    mtime = path.stat().st_mtime

    if isinstance(data, dict):
        if isinstance(data.get("relationships_following"), list):
            records, max_ts = _parse_follow_items(data["relationships_following"])
            return "following", _ParsedSideFile("following", path, mtime, max_ts, records)
        if isinstance(data.get("relationships_unfollowed_users"), list):
            records_u = _parse_classic_unfollowed(data["relationships_unfollowed_users"], path.name)
            return "recently_unfollowed", records_u
        return "unknown", None

    if isinstance(data, list):
        dict_items = [x for x in data if isinstance(x, dict)]
        if any("string_list_data" in x for x in dict_items):
            records, max_ts = _parse_follow_items(dict_items)
            return "followers", _ParsedSideFile("followers", path, mtime, max_ts, records)
        if any("label_values" in x for x in dict_items):
            records_u = _parse_label_values_unfollowed(dict_items, path.name)
            return "recently_unfollowed", records_u
        return "unknown", None

    return "unknown", None


def _pair_side_files(
    followers_files: list[_ParsedSideFile],
    following_files: list[_ParsedSideFile],
) -> tuple[list[tuple[_ParsedSideFile, _ParsedSideFile]], list[Path]]:
    """Pair followers and following files by capture time, falling back to max follow timestamp."""
    if not followers_files or not following_files:
        unpaired = [f.path for f in followers_files] + [g.path for g in following_files]
        return [], unpaired

    used_f: set[int] = set()
    used_g: set[int] = set()
    pairs: list[tuple[_ParsedSideFile, _ParsedSideFile]] = []

    # Primary pass: pair files saved in the same export window (<= 3600s apart).
    # Treat mtime differences <= 2.0s as tied on mtime so synthetic test files created
    # in the same second still pair deterministically via max_ts.
    close_candidates: list[tuple[tuple[float, int, float], int, int]] = []
    for fi, f in enumerate(followers_files):
        for gi, g in enumerate(following_files):
            mtime_diff = abs(f.mtime - g.mtime)
            if mtime_diff <= 3600.0:
                bucket = 0.0 if mtime_diff <= 2.0 else mtime_diff
                ts_diff = abs(f.max_ts - g.max_ts)
                close_candidates.append(((bucket, ts_diff, mtime_diff), fi, gi))
    close_candidates.sort(key=lambda item: item[0])

    for _, fi, gi in close_candidates:
        if fi not in used_f and gi not in used_g:
            used_f.add(fi)
            used_g.add(gi)
            pairs.append((followers_files[fi], following_files[gi]))

    # Fallback pass for copied files whose mtimes diverged: match by closest max follow timestamp.
    rem_f = [fi for fi in range(len(followers_files)) if fi not in used_f]
    rem_g = [gi for gi in range(len(following_files)) if gi not in used_g]
    if rem_f and rem_g:
        fallback_candidates: list[tuple[tuple[int, float], int, int]] = []
        for fi in rem_f:
            for gi in rem_g:
                f = followers_files[fi]
                g = following_files[gi]
                fallback_candidates.append(((abs(f.max_ts - g.max_ts), abs(f.mtime - g.mtime)), fi, gi))
        fallback_candidates.sort(key=lambda item: item[0])
        for _, fi, gi in fallback_candidates:
            if fi not in used_f and gi not in used_g:
                used_f.add(fi)
                used_g.add(gi)
                pairs.append((followers_files[fi], following_files[gi]))

    unpaired_paths = [
        followers_files[fi].path for fi in range(len(followers_files)) if fi not in used_f
    ] + [
        following_files[gi].path for gi in range(len(following_files)) if gi not in used_g
    ]

    # Sort pairs chronologically. Cluster mtimes within 2 seconds to avoid jitter when
    # multiple synthetic test files are created back-to-back in the same second.
    pairs_with_time = [
        (max(f.mtime, g.mtime), max(f.max_ts, g.max_ts), f, g) for f, g in pairs
    ]
    pairs_with_time.sort(key=lambda item: (item[0], item[1]))

    clustered: list[tuple[float, int, float, _ParsedSideFile, _ParsedSideFile]] = []
    cluster_anchor = None
    prev_mtime = None
    for raw_mtime, max_ts, f, g in pairs_with_time:
        if prev_mtime is None or (raw_mtime - prev_mtime) > 2.0:
            cluster_anchor = raw_mtime
        prev_mtime = raw_mtime
        assert cluster_anchor is not None
        clustered.append((cluster_anchor, max_ts, raw_mtime, f, g))

    clustered.sort(key=lambda item: (item[0], item[1], item[2]))
    ordered_pairs = [(f, g) for _, _, _, f, g in clustered]
    return ordered_pairs, unpaired_paths


def detect_renames(snapshots: list[Snapshot]) -> list[RenameEvent]:
    """Detect username changes across snapshots via preserved follow timestamps."""
    if len(snapshots) < 2:
        return []

    # Guard against timestamps that collide within any single snapshot.
    ambiguous_follower_ts: set[int] = set()
    ambiguous_following_ts: set[int] = set()
    for snap in snapshots:
        seen_f: set[int] = set()
        for rec in snap.followers.values():
            if rec.timestamp:
                if rec.timestamp in seen_f:
                    ambiguous_follower_ts.add(rec.timestamp)
                seen_f.add(rec.timestamp)
        seen_g: set[int] = set()
        for rec in snap.following.values():
            if rec.timestamp:
                if rec.timestamp in seen_g:
                    ambiguous_following_ts.add(rec.timestamp)
                seen_g.add(rec.timestamp)

    def ever_coexisted(user_a: str, user_b: str) -> bool:
        for snap in snapshots:
            if user_a in snap.followers and user_b in snap.followers:
                return True
            if user_a in snap.following and user_b in snap.following:
                return True
        return False

    # Transitions keyed by (old_username, new_username) per side
    side_transitions: dict[str, dict[tuple[str, str], tuple[int, int, str, str, int]]] = {
        "followers": {},
        "following": {},
    }

    for side in ("followers", "following"):
        ambiguous = ambiguous_follower_ts if side == "followers" else ambiguous_following_ts
        last_seen_by_ts: dict[int, tuple[str, int, str]] = {}
        for snap in snapshots:
            records = snap.followers if side == "followers" else snap.following
            for username, rec in records.items():
                ts = rec.timestamp
                if not ts or ts in ambiguous:
                    continue
                if ts in last_seen_by_ts:
                    prev_user, prev_idx, prev_date = last_seen_by_ts[ts]
                    if (
                        prev_user != username
                        and prev_user not in records
                        and not ever_coexisted(prev_user, username)
                    ):
                        key = (prev_user, username)
                        if key not in side_transitions[side]:
                            side_transitions[side][key] = (
                                prev_idx,
                                snap.index,
                                prev_date,
                                snap.date_str,
                                ts,
                            )
                last_seen_by_ts[ts] = (username, snap.index, snap.date_str)

    all_pairs = set(side_transitions["followers"]) | set(side_transitions["following"])
    events: list[RenameEvent] = []
    for old_user, new_user in all_pairs:
        f_info = side_transitions["followers"].get((old_user, new_user))
        g_info = side_transitions["following"].get((old_user, new_user))
        double_verified = f_info is not None and g_info is not None

        if f_info is not None and g_info is not None:
            # Prefer whichever side observed the rename in the earlier window.
            if (f_info[1], -f_info[0]) <= (g_info[1], -g_info[0]):
                from_idx, to_idx, from_date, to_date, _ = f_info
            else:
                from_idx, to_idx, from_date, to_date, _ = g_info
            f_ts: int | None = f_info[4]
            g_ts: int | None = g_info[4]
        elif f_info is not None:
            from_idx, to_idx, from_date, to_date, f_ts = f_info
            g_ts = None
        else:
            assert g_info is not None
            from_idx, to_idx, from_date, to_date, g_ts = g_info
            f_ts = None

        events.append(
            RenameEvent(
                old_username=old_user,
                new_username=new_user,
                from_snapshot=from_idx,
                to_snapshot=to_idx,
                from_date=from_date,
                to_date=to_date,
                follower_timestamp=f_ts,
                following_timestamp=g_ts,
                double_verified=double_verified,
                gap_snapshots=max(0, to_idx - from_idx - 1),
            )
        )

    events.sort(key=lambda e: (e.to_snapshot, e.from_snapshot, e.old_username, e.new_username))
    return events


def build_identity_maps(
    renames: list[RenameEvent],
    all_usernames: Iterable[str],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Collapse rename chains (including revert cycles) into canonical identity maps."""
    chains: dict[str, list[str]] = {}
    alias_to_canonical: dict[str, str] = {}

    ordered_renames = sorted(renames, key=lambda r: (r.to_snapshot, r.from_snapshot, r.old_username))
    for r in ordered_renames:
        old_u = r.old_username
        new_u = r.new_username
        canon_old = alias_to_canonical.get(old_u, old_u)
        old_chain = chains.pop(canon_old, [old_u])

        canon_new = alias_to_canonical.get(new_u)
        if canon_new is not None and canon_new != canon_old and canon_new in chains:
            new_chain = chains.pop(canon_new)
            merged = list(old_chain)
            for item in new_chain:
                if item not in merged:
                    merged.append(item)
        else:
            merged = list(old_chain)

        if new_u not in merged:
            merged.append(new_u)
        elif merged[-1] != new_u:
            # Handle rare revert renames (A -> B -> A) safely without duplicating or cycling.
            merged = [x for x in merged if x != new_u] + [new_u]

        chains[new_u] = merged
        for alias in merged:
            alias_to_canonical[alias] = new_u

    for user in sorted(set(all_usernames)):
        if user not in alias_to_canonical:
            alias_to_canonical[user] = user
            chains[user] = [user]

    return alias_to_canonical, chains


def load_archive(
    archive_dir: Path | str | None = Path("archival follwers"),
    root_dir: Path | str | None = Path("."),
) -> ArchiveData:
    """Load, classify, pair, and identity-link all Instagram JSON exports."""
    candidate_paths: list[Path] = []
    seen_resolved: set[Path] = set()

    for directory in (root_dir, archive_dir):
        if directory is None:
            continue
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            continue
        for json_path in sorted(dir_path.glob("*.json")):
            resolved = json_path.resolve()
            if resolved not in seen_resolved:
                seen_resolved.add(resolved)
                candidate_paths.append(json_path)

    followers_files: list[_ParsedSideFile] = []
    following_files: list[_ParsedSideFile] = []
    raw_unfollowed: list[UnfollowRecord] = []
    skipped_files: list[str] = []

    for path in candidate_paths:
        kind, payload = classify_and_parse_json(path)
        if kind == "followers" and isinstance(payload, _ParsedSideFile):
            followers_files.append(payload)
        elif kind == "following" and isinstance(payload, _ParsedSideFile):
            following_files.append(payload)
        elif kind == "recently_unfollowed" and isinstance(payload, list):
            raw_unfollowed.extend(payload)
        else:
            skipped_files.append(str(path))

    paired, unpaired_paths = _pair_side_files(followers_files, following_files)
    skipped_files.extend(str(p) for p in unpaired_paths)

    snapshots: list[Snapshot] = []
    all_usernames: set[str] = set()
    for idx, (f_side, g_side) in enumerate(paired, start=1):
        taken_at = datetime.fromtimestamp(max(f_side.mtime, g_side.mtime))
        all_usernames.update(f_side.records.keys())
        all_usernames.update(g_side.records.keys())
        snapshots.append(
            Snapshot(
                index=idx,
                date_str=taken_at.strftime("%Y-%m-%d"),
                taken_at=taken_at,
                followers_path=f_side.path,
                following_path=g_side.path,
                followers=f_side.records,
                following=g_side.records,
            )
        )

    dedup_unfollowed: dict[tuple[str, int], UnfollowRecord] = {}
    for rec in raw_unfollowed:
        key = (rec.username.lower(), rec.timestamp)
        existing = dedup_unfollowed.get(key)
        if existing is None or (not existing.display_name and rec.display_name):
            dedup_unfollowed[key] = rec
    unfollowed_records = sorted(
        dedup_unfollowed.values(),
        key=lambda r: (r.timestamp, r.username.lower()),
    )

    renames = detect_renames(snapshots)
    alias_to_canonical, canonical_to_aliases = build_identity_maps(renames, all_usernames)

    return ArchiveData(
        snapshots=snapshots,
        unfollowed_records=unfollowed_records,
        renames=renames,
        alias_to_canonical=alias_to_canonical,
        canonical_to_aliases=canonical_to_aliases,
        skipped_files=skipped_files,
    )


def resolve_snapshot(archive: ArchiveData, ref: int | str) -> Snapshot:
    """Resolve a 1-based positive index, negative index, or YYYY-MM-DD prefix to a Snapshot."""
    if not archive.snapshots:
        raise ValueError("Archive contains no paired snapshots.")

    if isinstance(ref, int):
        if ref == 0:
            raise ValueError("Snapshot index 0 is invalid; use 1-based positive index or negative index (e.g. -1).")
        if ref < 0:
            pos = len(archive.snapshots) + ref
            if not (0 <= pos < len(archive.snapshots)):
                raise ValueError(f"Snapshot index {ref} out of range for {len(archive.snapshots)} snapshots.")
            return archive.snapshots[pos]
        pos = ref - 1
        if not (0 <= pos < len(archive.snapshots)):
            raise ValueError(f"Snapshot #{ref} out of range (1..{len(archive.snapshots)}).")
        return archive.snapshots[pos]

    raw = str(ref).strip()
    if raw.startswith("#"):
        raw = raw[1:].strip()
    try:
        return resolve_snapshot(archive, int(raw))
    except ValueError:
        pass

    matches = [s for s in archive.snapshots if s.date_str == raw or s.date_str.startswith(raw)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        options = ", ".join(f"#{s.index} ({s.date_str})" for s in matches)
        raise ValueError(f"Ambiguous date prefix '{ref}'; matches: {options}")
    raise ValueError(f"No snapshot matches '{ref}'.")


def _days_since(snap_ts: float, follow_ts: int | None) -> float | None:
    if follow_ts is None or follow_ts <= 0:
        return None
    return max(0.0, (snap_ts - follow_ts) / 86400.0)


def _canonical(archive: ArchiveData, username: str) -> str:
    return archive.alias_to_canonical.get(username, username)


def _canonical_map(
    archive: ArchiveData,
    records: dict[str, FollowRecord],
    *,
    resolve_renames: bool,
) -> dict[str, FollowRecord]:
    if not resolve_renames:
        return records
    out: dict[str, FollowRecord] = {}
    for handle, rec in records.items():
        out[_canonical(archive, handle)] = rec
    return out


def classify_reappearances(archive: ArchiveData, side: str = "followers") -> list[ReappearanceEvent]:
    """Distinguish deactivation/reactivation (same timestamp) from unfollow+refollow (new timestamp)."""
    valid_sides = {"followers", "following", "both"}
    if side not in valid_sides:
        raise ValueError(f"side must be one of {sorted(valid_sides)}, got {side!r}")

    sides_to_check = ("followers", "following") if side == "both" else (side,)
    events: list[ReappearanceEvent] = []

    for current_side in sides_to_check:
        last_seen: dict[str, tuple[int, str, str, int]] = {}
        for snap in archive.snapshots:
            records = snap.followers if current_side == "followers" else snap.following
            for handle, rec in records.items():
                canon = _canonical(archive, handle)
                if canon in last_seen:
                    prev_idx, prev_date, _, prev_ts = last_seen[canon]
                    missing = snap.index - prev_idx - 1
                    if missing >= 1:
                        kind = (
                            "deactivated_and_reactivated"
                            if rec.timestamp == prev_ts
                            else "unfollowed_and_refollowed"
                        )
                        events.append(
                            ReappearanceEvent(
                                username=handle,
                                canonical_username=canon,
                                side=current_side,
                                kind=kind,
                                last_seen_snapshot=prev_idx,
                                last_seen_date=prev_date,
                                reappeared_snapshot=snap.index,
                                reappeared_date=snap.date_str,
                                old_timestamp=prev_ts,
                                new_timestamp=rec.timestamp,
                                missing_snapshots=missing,
                            )
                        )
                    elif missing == 0 and rec.timestamp != prev_ts:
                        events.append(
                            ReappearanceEvent(
                                username=handle,
                                canonical_username=canon,
                                side=current_side,
                                kind="refollowed_between_snapshots",
                                last_seen_snapshot=prev_idx,
                                last_seen_date=prev_date,
                                reappeared_snapshot=snap.index,
                                reappeared_date=snap.date_str,
                                old_timestamp=prev_ts,
                                new_timestamp=rec.timestamp,
                                missing_snapshots=0,
                            )
                        )
                last_seen[canon] = (snap.index, snap.date_str, handle, rec.timestamp)

    events.sort(key=lambda e: (e.reappeared_snapshot, e.side, e.canonical_username))
    return events


def compare_snapshot(archive: ArchiveData, snapshot_index: int | str = -1) -> SnapshotBreakdown:
    """Break a snapshot into mutuals, not-following-back, and fans using O(1) set operations."""
    snap = resolve_snapshot(archive, snapshot_index)
    snap_ts = snap.taken_at.timestamp()

    followers_set = set(snap.followers.keys())
    following_set = set(snap.following.keys())

    mutual_names = followers_set & following_set
    not_back_names = following_set - followers_set
    fan_names = followers_set - following_set

    mutuals = [
        RelationshipEntry(
            username=u,
            followed_you_at=snap.followers[u].timestamp,
            you_followed_at=snap.following[u].timestamp,
            follower_days=_days_since(snap_ts, snap.followers[u].timestamp),
            following_days=_days_since(snap_ts, snap.following[u].timestamp),
        )
        for u in mutual_names
    ]
    mutuals.sort(key=lambda r: (max(r.followed_you_at or 0, r.you_followed_at or 0), r.username))

    not_following_back = [
        RelationshipEntry(
            username=u,
            followed_you_at=None,
            you_followed_at=snap.following[u].timestamp,
            follower_days=None,
            following_days=_days_since(snap_ts, snap.following[u].timestamp),
        )
        for u in not_back_names
    ]
    not_following_back.sort(key=lambda r: (r.you_followed_at or 0, r.username))

    fans_not_followed_back = [
        RelationshipEntry(
            username=u,
            followed_you_at=snap.followers[u].timestamp,
            you_followed_at=None,
            follower_days=_days_since(snap_ts, snap.followers[u].timestamp),
            following_days=None,
        )
        for u in fan_names
    ]
    fans_not_followed_back.sort(key=lambda r: (r.followed_you_at or 0, r.username))

    return SnapshotBreakdown(
        snapshot=snap,
        mutuals=mutuals,
        not_following_back=not_following_back,
        fans_not_followed_back=fans_not_followed_back,
    )


def diff_snapshots(
    archive: ArchiveData,
    snap_a_idx: int | str,
    snap_b_idx: int | str,
    *,
    resolve_renames: bool = True,
) -> SnapshotDiff:
    """Compute a rename-aware diff between two snapshots."""
    snap_a = resolve_snapshot(archive, snap_a_idx)
    snap_b = resolve_snapshot(archive, snap_b_idx)

    f_a = set(_canonical_map(archive, snap_a.followers, resolve_renames=resolve_renames).keys())
    f_b = set(_canonical_map(archive, snap_b.followers, resolve_renames=resolve_renames).keys())
    g_a = set(_canonical_map(archive, snap_a.following, resolve_renames=resolve_renames).keys())
    g_b = set(_canonical_map(archive, snap_b.following, resolve_renames=resolve_renames).keys())

    new_followers = sorted(f_b - f_a)
    lost_followers = sorted(f_a - f_b)
    newly_followed = sorted(g_b - g_a)
    unfollowed_by_you = sorted(g_a - g_b)

    lost_set = set(lost_followers)
    unfollowed_set = set(unfollowed_by_you)

    mutual_drops = sorted(lost_set & unfollowed_set)
    pure_unfollowers = sorted(lost_set - unfollowed_set)
    pure_unfollowed_by_you = sorted(unfollowed_set - lost_set)

    if snap_a.index < snap_b.index:
        renames_in_window = [
            r for r in archive.renames if snap_a.index < r.to_snapshot <= snap_b.index
        ]
    else:
        renames_in_window = []

    return SnapshotDiff(
        snap_a=snap_a,
        snap_b=snap_b,
        new_followers=new_followers,
        lost_followers=lost_followers,
        newly_followed=newly_followed,
        unfollowed_by_you=unfollowed_by_you,
        mutual_drops=mutual_drops,
        pure_unfollowers=pure_unfollowers,
        pure_unfollowed_by_you=pure_unfollowed_by_you,
        renames_in_window=renames_in_window,
    )


def _handle_in_snapshot(archive: ArchiveData, canonical: str, snap: Snapshot) -> str:
    aliases = archive.canonical_to_aliases.get(canonical, [canonical])
    for alias in aliases:
        if alias in snap.following or alias in snap.followers:
            return alias
    return canonical


def attribute_unfollows(
    archive: ArchiveData,
    snap_a_idx: int | str | None = None,
    snap_b_idx: int | str | None = None,
) -> list[IntervalAttribution]:
    """Cross-reference dropped accounts against recently_unfollowed_profiles logs."""
    if (snap_a_idx is None) != (snap_b_idx is None):
        raise ValueError("Provide both snap_a_idx and snap_b_idx, or neither to analyze all intervals.")

    if snap_a_idx is not None and snap_b_idx is not None:
        intervals = [(resolve_snapshot(archive, snap_a_idx), resolve_snapshot(archive, snap_b_idx))]
    else:
        intervals = list(zip(archive.snapshots, archive.snapshots[1:]))

    # Index unfollow records by canonical username and lowercase alias for fast lookup.
    log_by_canon: dict[str, list[UnfollowRecord]] = {}
    log_by_lower: dict[str, list[UnfollowRecord]] = {}
    for rec in archive.unfollowed_records:
        canon = _canonical(archive, rec.username)
        log_by_canon.setdefault(canon, []).append(rec)
        log_by_lower.setdefault(rec.username.lower(), []).append(rec)

    results: list[IntervalAttribution] = []
    for snap_a, snap_b in intervals:
        diff = diff_snapshots(archive, snap_a.index, snap_b.index, resolve_renames=True)
        a_ts = snap_a.taken_at.timestamp()
        b_ts = snap_b.taken_at.timestamp()

        has_coverage = any(a_ts < r.timestamp <= b_ts for r in archive.unfollowed_records)

        lost_set = set(diff.lost_followers)
        unfollowed_set = set(diff.unfollowed_by_you)
        all_dropped = sorted(lost_set | unfollowed_set)

        intentionally_unfollowed: list[AttributedAccount] = []
        unattributed_mutual_drops: list[AttributedAccount] = []
        unfollowed_you_only: list[AttributedAccount] = []
        unfollowed_by_you_unlogged: list[AttributedAccount] = []

        for canon in all_dropped:
            handle_at_drop = _handle_in_snapshot(archive, canon, snap_a)
            dropped_f = canon in lost_set
            dropped_g = canon in unfollowed_set

            matched_log: UnfollowRecord | None = None
            if dropped_g:
                candidates = list(log_by_canon.get(canon, []))
                if not candidates:
                    candidates = list(log_by_lower.get(handle_at_drop.lower(), []))
                window_matches = [
                    r for r in candidates if a_ts < r.timestamp <= b_ts
                ]
                matched_log = window_matches[-1] if window_matches else None

            if matched_log is not None:
                intentionally_unfollowed.append(
                    AttributedAccount(
                        canonical_username=canon,
                        handle_at_drop=handle_at_drop,
                        category="intentionally_unfollowed",
                        display_name=matched_log.display_name,
                        unfollowed_at=matched_log.timestamp,
                        dropped_from_followers=dropped_f,
                        dropped_from_following=dropped_g,
                        source_file=matched_log.source_file,
                    )
                )
            elif dropped_f and dropped_g:
                unattributed_mutual_drops.append(
                    AttributedAccount(
                        canonical_username=canon,
                        handle_at_drop=handle_at_drop,
                        category="unattributed_mutual_drop",
                        display_name="",
                        unfollowed_at=None,
                        dropped_from_followers=True,
                        dropped_from_following=True,
                        source_file=None,
                    )
                )
            elif dropped_f:
                unfollowed_you_only.append(
                    AttributedAccount(
                        canonical_username=canon,
                        handle_at_drop=handle_at_drop,
                        category="unfollowed_you_only",
                        display_name="",
                        unfollowed_at=None,
                        dropped_from_followers=True,
                        dropped_from_following=False,
                        source_file=None,
                    )
                )
            else:
                unfollowed_by_you_unlogged.append(
                    AttributedAccount(
                        canonical_username=canon,
                        handle_at_drop=handle_at_drop,
                        category="unfollowed_by_you_unlogged",
                        display_name="",
                        unfollowed_at=None,
                        dropped_from_followers=False,
                        dropped_from_following=True,
                        source_file=None,
                    )
                )

        intentionally_unfollowed.sort(key=lambda a: (-(a.unfollowed_at or 0), a.canonical_username))
        results.append(
            IntervalAttribution(
                snap_a=snap_a,
                snap_b=snap_b,
                has_unfollow_log_coverage=has_coverage,
                intentionally_unfollowed=intentionally_unfollowed,
                unattributed_mutual_drops=unattributed_mutual_drops,
                unfollowed_you_only=unfollowed_you_only,
                unfollowed_by_you_unlogged=unfollowed_by_you_unlogged,
            )
        )

    return results


def _find_first_missing_after(
    presence: list[SnapshotPresence],
    side: str,
) -> tuple[SnapshotPresence | None, SnapshotPresence | None]:
    """Return (last_present, first_missing_after_last_present) for 'followers' or 'following'."""
    attr = "is_follower" if side == "followers" else "is_following"
    last_present_idx: int | None = None
    for idx, p in enumerate(presence):
        if getattr(p, attr):
            last_present_idx = idx
    if last_present_idx is None:
        return None, None
    last_p = presence[last_present_idx]
    if last_present_idx + 1 < len(presence):
        return last_p, presence[last_present_idx + 1]
    return last_p, None


_ACCOUNT_STATUS_ORDER = {
    "not_following_back": 0,
    "fan_only": 1,
    "mutual": 2,
    "former_mutual": 3,
    "former_follower": 4,
    "former_following": 5,
    "unfollowed_log_only": 6,
}


def _build_account_history(
    *,
    query: str,
    canonical: str,
    all_handles: list[str],
    rel_renames: list[RenameEvent],
    unfollowed_log_events: list[UnfollowRecord],
    reappearances: list[ReappearanceEvent],
    snapshot_presence: list[SnapshotPresence],
    f_timestamps: list[int],
    g_timestamps: list[int],
) -> AccountHistory:
    display_name = ""
    for log_ev in reversed(unfollowed_log_events):
        if log_ev.display_name:
            display_name = log_ev.display_name
            break

    followed_you_first_ts = min(f_timestamps) if f_timestamps else None
    followed_you_latest_ts = f_timestamps[-1] if f_timestamps else None
    you_followed_first_ts = min(g_timestamps) if g_timestamps else None
    you_followed_latest_ts = g_timestamps[-1] if g_timestamps else None

    who_followed_first: str | None = None
    follow_back_lag_seconds: int | None = None
    if followed_you_first_ts is not None and you_followed_first_ts is not None:
        if followed_you_first_ts < you_followed_first_ts:
            who_followed_first = "them"
            follow_back_lag_seconds = you_followed_first_ts - followed_you_first_ts
        elif you_followed_first_ts < followed_you_first_ts:
            who_followed_first = "you"
            follow_back_lag_seconds = followed_you_first_ts - you_followed_first_ts
        else:
            who_followed_first = "simultaneous"
            follow_back_lag_seconds = 0

    latest = snapshot_presence[-1] if snapshot_presence else None
    ever_f = any(p.is_follower for p in snapshot_presence)
    ever_g = any(p.is_following for p in snapshot_presence)

    if latest and latest.is_follower and latest.is_following:
        current_status = "mutual"
    elif latest and latest.is_following:
        current_status = "not_following_back"
    elif latest and latest.is_follower:
        current_status = "fan_only"
    elif ever_f and ever_g:
        current_status = "former_mutual"
    elif ever_f:
        current_status = "former_follower"
    elif ever_g:
        current_status = "former_following"
    else:
        current_status = "unfollowed_log_only"

    last_f, miss_f = _find_first_missing_after(snapshot_presence, "followers")
    last_g, miss_g = _find_first_missing_after(snapshot_presence, "following")

    if current_status == "mutual":
        ended_summary = "Active mutual relationship."
    elif current_status == "not_following_back":
        if last_f and miss_f:
            ended_summary = (
                f"Unfollowed you between {last_f.date_str} (#{last_f.snapshot_index}) "
                f"and {miss_f.date_str} (#{miss_f.snapshot_index}); you still follow them."
            )
        else:
            ended_summary = "You follow them; they have never followed you back in recorded snapshots."
    elif current_status == "fan_only":
        if last_g and miss_g:
            ended_summary = (
                f"You unfollowed them between {last_g.date_str} (#{last_g.snapshot_index}) "
                f"and {miss_g.date_str} (#{miss_g.snapshot_index}); they still follow you."
            )
        else:
            ended_summary = "They follow you; you have never followed them in recorded snapshots."
    elif current_status == "unfollowed_log_only":
        log_dates = ", ".join(datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d") for r in unfollowed_log_events)
        ended_summary = f"Recorded only in recently_unfollowed_profiles ({log_dates})."
    else:
        parts: list[str] = []
        if last_f and miss_f:
            parts.append(
                f"left followers between {last_f.date_str} (#{last_f.snapshot_index}) "
                f"and {miss_f.date_str} (#{miss_f.snapshot_index})"
            )
        if last_g and miss_g:
            parts.append(
                f"left following between {last_g.date_str} (#{last_g.snapshot_index}) "
                f"and {miss_g.date_str} (#{miss_g.snapshot_index})"
            )
        if unfollowed_log_events:
            log_dt = datetime.fromtimestamp(unfollowed_log_events[-1].timestamp).strftime("%Y-%m-%d")
            parts.append(f"logged in {unfollowed_log_events[-1].source_file} on {log_dt}")
        ended_summary = "; ".join(parts).capitalize() + "." if parts else "No longer present."

    return AccountHistory(
        query=query,
        canonical_username=canonical,
        all_handles=all_handles,
        display_name=display_name,
        current_status=current_status,
        renames=rel_renames,
        followed_you_first_ts=followed_you_first_ts,
        followed_you_latest_ts=followed_you_latest_ts,
        you_followed_first_ts=you_followed_first_ts,
        you_followed_latest_ts=you_followed_latest_ts,
        who_followed_first=who_followed_first,
        follow_back_lag_seconds=follow_back_lag_seconds,
        reappearances=reappearances,
        unfollowed_log_events=unfollowed_log_events,
        snapshot_presence=snapshot_presence,
        ended_summary=ended_summary,
    )


def account_history(archive: ArchiveData, username: str) -> AccountHistory | None:
    """Trace complete cross-snapshot history for any current or former username."""
    cleaned = username.strip().lstrip("@")
    if not cleaned:
        return None

    lower_map = {k.lower(): v for k, v in archive.alias_to_canonical.items()}
    canonical = lower_map.get(cleaned.lower())

    matching_logs_direct = [
        r for r in archive.unfollowed_records if r.username.lower() == cleaned.lower()
    ]
    if canonical is None:
        if not matching_logs_direct:
            return None
        canonical = matching_logs_direct[-1].username

    all_handles = list(archive.canonical_to_aliases.get(canonical, [canonical]))
    handle_set = set(all_handles)
    handle_lower_set = {h.lower() for h in all_handles}

    rel_renames = [
        r for r in archive.renames if r.old_username in handle_set or r.new_username in handle_set
    ]
    unfollowed_log_events = [
        r for r in archive.unfollowed_records
        if r.username in handle_set or r.username.lower() in handle_lower_set
    ]

    snapshot_presence: list[SnapshotPresence] = []
    f_timestamps: list[int] = []
    g_timestamps: list[int] = []

    for snap in archive.snapshots:
        f_rec: FollowRecord | None = None
        g_rec: FollowRecord | None = None
        matched_handle: str | None = None

        for h in all_handles:
            if f_rec is None and h in snap.followers:
                f_rec = snap.followers[h]
                matched_handle = h
            if g_rec is None and h in snap.following:
                g_rec = snap.following[h]
                matched_handle = matched_handle or h

        if f_rec is not None and f_rec.timestamp:
            f_timestamps.append(f_rec.timestamp)
        if g_rec is not None and g_rec.timestamp:
            g_timestamps.append(g_rec.timestamp)

        snapshot_presence.append(
            SnapshotPresence(
                snapshot_index=snap.index,
                date_str=snap.date_str,
                handle=matched_handle,
                is_follower=f_rec is not None,
                is_following=g_rec is not None,
                follower_timestamp=f_rec.timestamp if f_rec else None,
                following_timestamp=g_rec.timestamp if g_rec else None,
            )
        )

    reappearances = [
        ev for ev in classify_reappearances(archive, side="both")
        if ev.canonical_username == canonical
    ]

    return _build_account_history(
        query=username,
        canonical=canonical,
        all_handles=all_handles,
        rel_renames=rel_renames,
        unfollowed_log_events=unfollowed_log_events,
        reappearances=reappearances,
        snapshot_presence=snapshot_presence,
        f_timestamps=f_timestamps,
        g_timestamps=g_timestamps,
    )


def all_account_histories(archive: ArchiveData) -> list[AccountHistory]:
    """Build complete histories for every known account (snapshots + unfollow logs) in a single pass."""
    lower_alias_to_canon = {k.lower(): v for k, v in archive.alias_to_canonical.items()}

    reapp_by_canon: dict[str, list[ReappearanceEvent]] = {}
    for ev in classify_reappearances(archive, side="both"):
        reapp_by_canon.setdefault(ev.canonical_username, []).append(ev)

    renames_by_canon: dict[str, list[RenameEvent]] = {}
    for r in archive.renames:
        c_old = archive.alias_to_canonical.get(r.old_username, r.old_username)
        c_new = archive.alias_to_canonical.get(r.new_username, r.new_username)
        renames_by_canon.setdefault(c_old, []).append(r)
        if c_new != c_old:
            renames_by_canon.setdefault(c_new, []).append(r)

    unlogged_canon_by_lower: dict[str, str] = {}
    for rec in archive.unfollowed_records:
        low = rec.username.lower()
        if low not in lower_alias_to_canon:
            unlogged_canon_by_lower[low] = rec.username

    logs_by_canon: dict[str, list[UnfollowRecord]] = {}
    for rec in archive.unfollowed_records:
        low = rec.username.lower()
        canon = lower_alias_to_canon.get(low) or unlogged_canon_by_lower[low]
        logs_by_canon.setdefault(canon, []).append(rec)

    all_canons: list[str] = list(archive.canonical_to_aliases.keys())
    seen_canons = set(all_canons)
    for canon in logs_by_canon:
        if canon not in seen_canons:
            seen_canons.add(canon)
            all_canons.append(canon)

    # Pre-index follower/following records per snapshot by canonical identity, preserving alias order.
    snap_f_by_canon: list[dict[str, tuple[str, FollowRecord]]] = []
    snap_g_by_canon: list[dict[str, tuple[str, FollowRecord]]] = []
    for snap in archive.snapshots:
        f_map: dict[str, tuple[str, FollowRecord]] = {}
        for handle, rec in snap.followers.items():
            canon = archive.alias_to_canonical.get(handle, handle)
            if canon not in f_map:
                f_map[canon] = (handle, rec)
        snap_f_by_canon.append(f_map)

        g_map: dict[str, tuple[str, FollowRecord]] = {}
        for handle, rec in snap.following.items():
            canon = archive.alias_to_canonical.get(handle, handle)
            if canon not in g_map:
                g_map[canon] = (handle, rec)
        snap_g_by_canon.append(g_map)

    histories: list[AccountHistory] = []
    for canon in all_canons:
        all_handles = list(archive.canonical_to_aliases.get(canon, [canon]))
        snapshot_presence: list[SnapshotPresence] = []
        f_timestamps: list[int] = []
        g_timestamps: list[int] = []

        for snap_idx, snap in enumerate(archive.snapshots):
            f_entry = snap_f_by_canon[snap_idx].get(canon)
            g_entry = snap_g_by_canon[snap_idx].get(canon)

            f_rec = f_entry[1] if f_entry else None
            g_rec = g_entry[1] if g_entry else None
            matched_handle = (f_entry[0] if f_entry else None) or (g_entry[0] if g_entry else None)

            if f_rec is not None and f_rec.timestamp:
                f_timestamps.append(f_rec.timestamp)
            if g_rec is not None and g_rec.timestamp:
                g_timestamps.append(g_rec.timestamp)

            snapshot_presence.append(
                SnapshotPresence(
                    snapshot_index=snap.index,
                    date_str=snap.date_str,
                    handle=matched_handle,
                    is_follower=f_rec is not None,
                    is_following=g_rec is not None,
                    follower_timestamp=f_rec.timestamp if f_rec else None,
                    following_timestamp=g_rec.timestamp if g_rec else None,
                )
            )

        histories.append(
            _build_account_history(
                query=canon,
                canonical=canon,
                all_handles=all_handles,
                rel_renames=list(renames_by_canon.get(canon, [])),
                unfollowed_log_events=list(logs_by_canon.get(canon, [])),
                reappearances=list(reapp_by_canon.get(canon, [])),
                snapshot_presence=snapshot_presence,
                f_timestamps=f_timestamps,
                g_timestamps=g_timestamps,
            )
        )

    histories.sort(
        key=lambda h: (_ACCOUNT_STATUS_ORDER.get(h.current_status, 99), h.canonical_username.lower())
    )
    return histories


def timeline_summary(archive: ArchiveData) -> list[TimelineRow]:
    """Generate a chronological summary table across all paired snapshots."""
    rows: list[TimelineRow] = []
    prev_snap: Snapshot | None = None

    for snap in archive.snapshots:
        breakdown = compare_snapshot(archive, snap.index)
        f_count = len(snap.followers)
        g_count = len(snap.following)

        if prev_snap is None:
            rows.append(
                TimelineRow(
                    index=snap.index,
                    date_str=snap.date_str,
                    followers_count=f_count,
                    following_count=g_count,
                    mutuals_count=len(breakdown.mutuals),
                    not_following_back_count=len(breakdown.not_following_back),
                    fans_count=len(breakdown.fans_not_followed_back),
                    net_followers_delta=None,
                    net_following_delta=None,
                    true_new_followers=None,
                    true_lost_followers=None,
                    true_newly_followed=None,
                    true_unfollowed=None,
                    renames_count=None,
                    mutual_drops_count=None,
                )
            )
        else:
            diff = diff_snapshots(archive, prev_snap.index, snap.index, resolve_renames=True)
            rows.append(
                TimelineRow(
                    index=snap.index,
                    date_str=snap.date_str,
                    followers_count=f_count,
                    following_count=g_count,
                    mutuals_count=len(breakdown.mutuals),
                    not_following_back_count=len(breakdown.not_following_back),
                    fans_count=len(breakdown.fans_not_followed_back),
                    net_followers_delta=f_count - len(prev_snap.followers),
                    net_following_delta=g_count - len(prev_snap.following),
                    true_new_followers=len(diff.new_followers),
                    true_lost_followers=len(diff.lost_followers),
                    true_newly_followed=len(diff.newly_followed),
                    true_unfollowed=len(diff.unfollowed_by_you),
                    renames_count=len(diff.renames_in_window),
                    mutual_drops_count=len(diff.mutual_drops),
                )
            )
        prev_snap = snap

    return rows


def loyalty_rankings(archive: ArchiveData, top_n: int = 25) -> LoyaltyReport:
    """Rank longest-standing current followers, current mutuals, and former followers."""
    if not archive.snapshots:
        raise ValueError("Archive contains no paired snapshots.")

    latest = archive.snapshots[-1]
    latest_ts = latest.taken_at.timestamp()

    current_followers: list[LoyaltyEntry] = []
    for handle, rec in latest.followers.items():
        canon = _canonical(archive, handle)
        current_followers.append(
            LoyaltyEntry(
                canonical_username=canon,
                current_handle=handle,
                started_at=rec.timestamp,
                duration_days=_days_since(latest_ts, rec.timestamp) or 0.0,
                is_mutual=handle in latest.following,
            )
        )
    current_followers.sort(key=lambda e: (e.started_at, e.current_handle))

    current_mutuals: list[LoyaltyEntry] = []
    for handle in set(latest.followers.keys()) & set(latest.following.keys()):
        f_rec = latest.followers[handle]
        g_rec = latest.following[handle]
        mutual_start = max(f_rec.timestamp, g_rec.timestamp)
        canon = _canonical(archive, handle)
        current_mutuals.append(
            LoyaltyEntry(
                canonical_username=canon,
                current_handle=handle,
                started_at=mutual_start,
                duration_days=_days_since(latest_ts, mutual_start) or 0.0,
                is_mutual=True,
            )
        )
    current_mutuals.sort(key=lambda e: (e.started_at, e.current_handle))

    # Build lookup for unfollow attribution of former followers
    log_by_canon: dict[str, UnfollowRecord] = {}
    for rec in archive.unfollowed_records:
        log_by_canon[_canonical(archive, rec.username)] = rec

    latest_follower_canons = {_canonical(archive, h) for h in latest.followers}

    # Track earliest follower timestamp and last seen follower snapshot per canonical former follower
    former_stats: dict[str, tuple[int, str, Snapshot, Snapshot | None, bool]] = {}
    for idx, snap in enumerate(archive.snapshots):
        for handle, rec in snap.followers.items():
            canon = _canonical(archive, handle)
            if canon in latest_follower_canons:
                continue
            next_snap = archive.snapshots[idx + 1] if idx + 1 < len(archive.snapshots) else None
            was_mutual_at_last = handle in snap.following
            if canon not in former_stats:
                former_stats[canon] = (rec.timestamp, handle, snap, next_snap, was_mutual_at_last)
            else:
                earliest_ts, _, _, _, _ = former_stats[canon]
                min_ts = (
                    rec.timestamp
                    if (not earliest_ts or (rec.timestamp and rec.timestamp < earliest_ts))
                    else earliest_ts
                )
                former_stats[canon] = (
                    min_ts,
                    handle,
                    snap,
                    next_snap,
                    was_mutual_at_last,
                )

    former_followers: list[LoyaltyEntry] = []
    for canon, (earliest_ts, last_handle, last_snap, next_snap, was_mutual) in former_stats.items():
        if earliest_ts <= 0:
            continue
        duration_days = max(0.0, (last_snap.taken_at.timestamp() - earliest_ts) / 86400.0)
        lost_between = (
            f"{last_snap.date_str} (#{last_snap.index}) -> {next_snap.date_str} (#{next_snap.index})"
            if next_snap is not None
            else last_snap.date_str
        )
        log_rec = log_by_canon.get(canon)
        former_followers.append(
            LoyaltyEntry(
                canonical_username=canon,
                current_handle=last_handle,
                started_at=earliest_ts,
                duration_days=duration_days,
                is_mutual=was_mutual,
                lost_between=lost_between,
                attributed_to_you=log_rec is not None,
                display_name=log_rec.display_name if log_rec else "",
            )
        )
    former_followers.sort(key=lambda e: (-e.duration_days, e.started_at, e.canonical_username))

    return LoyaltyReport(
        as_of_date=latest.date_str,
        longest_current_followers=current_followers[:top_n],
        longest_current_mutuals=current_mutuals[:top_n],
        longest_former_followers=former_followers[:top_n],
    )


def one_sided_history(archive: ArchiveData) -> OneSidedReport:
    """Classify current non-followers into former mutuals who quietly unfollowed vs never followed back."""
    breakdown = compare_snapshot(archive, -1)
    latest = breakdown.snapshot
    latest_ts = latest.taken_at.timestamp()

    # Map canonical -> list of (snap_index, snap, handle, follower_timestamp)
    follower_sightings: dict[str, list[tuple[Snapshot, str, int]]] = {}
    for snap in archive.snapshots:
        for handle, rec in snap.followers.items():
            canon = _canonical(archive, handle)
            follower_sightings.setdefault(canon, []).append((snap, handle, rec.timestamp))

    snap_by_index = {s.index: s for s in archive.snapshots}

    quietly_unfollowed_you: list[OneSidedEntry] = []
    never_followed_back: list[OneSidedEntry] = []

    for rel in breakdown.not_following_back:
        handle = rel.username
        canon = _canonical(archive, handle)
        you_followed_at = rel.you_followed_at or 0
        following_days = rel.following_days or 0.0

        sightings = follower_sightings.get(canon, [])
        if sightings:
            earliest_f_ts = min(ts for _, _, ts in sightings)
            last_snap, _, _ = sightings[-1]
            next_snap = snap_by_index.get(last_snap.index + 1)
            mutual_start = max(earliest_f_ts, you_followed_at) if you_followed_at else earliest_f_ts
            mutual_days = max(0.0, (last_snap.taken_at.timestamp() - mutual_start) / 86400.0)
            one_sided_since = (
                max(0.0, (latest_ts - next_snap.taken_at.timestamp()) / 86400.0)
                if next_snap is not None
                else 0.0
            )
            quietly_unfollowed_you.append(
                OneSidedEntry(
                    canonical_username=canon,
                    current_handle=handle,
                    you_followed_at=you_followed_at,
                    following_days=following_days,
                    category="quietly_unfollowed_you",
                    ever_followed_you=True,
                    followed_you_at=earliest_f_ts,
                    last_seen_follower_date=last_snap.date_str,
                    first_missing_follower_date=next_snap.date_str if next_snap else None,
                    mutual_duration_days=mutual_days,
                    one_sided_since_days=one_sided_since,
                )
            )
        else:
            never_followed_back.append(
                OneSidedEntry(
                    canonical_username=canon,
                    current_handle=handle,
                    you_followed_at=you_followed_at,
                    following_days=following_days,
                    category="never_followed_back",
                    ever_followed_you=False,
                )
            )

    quietly_unfollowed_you.sort(key=lambda e: e.current_handle)
    quietly_unfollowed_you.sort(key=lambda e: e.mutual_duration_days or 0.0, reverse=True)
    quietly_unfollowed_you.sort(key=lambda e: e.first_missing_follower_date or "", reverse=True)
    never_followed_back.sort(key=lambda e: (-e.following_days, e.current_handle))

    return OneSidedReport(
        as_of_date=latest.date_str,
        total_not_following_back=len(breakdown.not_following_back),
        quietly_unfollowed_you=quietly_unfollowed_you,
        never_followed_back=never_followed_back,
    )
