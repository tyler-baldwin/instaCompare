"""Unit and integration tests for insta_archive, report_generator, and instaCompare CLI."""

from __future__ import annotations

from datetime import datetime
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import instaCompare
from insta_archive import (
    account_history,
    all_account_histories,
    attribute_unfollows,
    classify_reappearances,
    compare_snapshot,
    decode_meta_text,
    diff_snapshots,
    extract_username,
    load_archive,
    loyalty_rankings,
    one_sided_history,
    timeline_summary,
)
from report_generator import format_account_history_markdown, generate_markdown_report


def _ts(dt_str: str) -> int:
    return int(datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").timestamp())


def _write_json(path: Path, payload: object, mtime_ts: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if mtime_ts is not None:
        os.utime(path, (mtime_ts, mtime_ts))


def _follower_entry(username: str, ts: int) -> dict:
    return {
        "title": "",
        "media_list_data": [],
        "string_list_data": [
            {
                "href": f"https://www.instagram.com/{username}",
                "value": username,
                "timestamp": ts,
            }
        ],
    }


def _following_entry_old(username: str, ts: int) -> dict:
    return {
        "title": "",
        "media_list_data": [],
        "string_list_data": [
            {
                "href": f"https://www.instagram.com/{username}",
                "value": username,
                "timestamp": ts,
            }
        ],
    }


def _following_entry_new(username: str, ts: int) -> dict:
    return {
        "title": username,
        "string_list_data": [
            {
                "href": f"https://www.instagram.com/_u/{username}",
                "timestamp": ts,
            }
        ],
    }


def _following_entry_href_only(username: str, ts: int) -> dict:
    return {
        "title": "",
        "string_list_data": [
            {
                "href": f"https://www.instagram.com/_u/{username}/?igsh=abc",
                "timestamp": ts,
            }
        ],
    }


def _unfollowed_label_entry(
    username: str,
    name: str,
    ts: int,
    *,
    with_fbid: bool = True,
) -> dict:
    entry: dict = {
        "timestamp": ts,
        "media": [],
        "label_values": [
            {"label": "URL", "value": f"https://www.instagram.com/{username}"},
            {"label": "Name", "value": name},
            {"label": "Username", "value": username},
        ],
    }
    if with_fbid:
        entry["fbid"] = "17841400000000000"
    return entry


class TestParsingAndBugs(unittest.TestCase):
    def test_extract_username_handles_old_new_and_href_fallback(self) -> None:
        self.assertEqual(extract_username(_following_entry_old("old_user", 100)), "old_user")
        self.assertEqual(extract_username(_following_entry_new("new_user", 100)), "new_user")
        self.assertEqual(extract_username(_following_entry_href_only("href_user", 100)), "href_user")
        self.assertEqual(extract_username({"title": "", "string_list_data": []}), "")

    def test_decode_meta_text_fixes_mojibake_and_preserves_utf8(self) -> None:
        mojibake_accent = "JosÃ© GarcÃ\xada"
        self.assertEqual(decode_meta_text(mojibake_accent), "José García")

        mojibake_emoji = "Alex ð\x9f\x98\x80"
        self.assertEqual(decode_meta_text(mojibake_emoji), "Alex 😀")

        clean_utf8 = "Māori 🌟"
        self.assertEqual(decode_meta_text(clean_utf8), "Māori 🌟")

    def test_out_of_order_pairing_and_root_vs_archive_same_names(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            arch = root / "archival follwers"
            arch.mkdir()

            t1 = _ts("2024-07-28 09:00:00")
            t2 = _ts("2024-09-30 09:00:00")
            t3 = _ts("2026-11-20 09:00:00")

            # Snap 1 (oldest): followers_2.json + following.json (old schema)
            _write_json(arch / "followers_2.json", [_follower_entry("alice", 1000)], t1)
            _write_json(
                arch / "following.json",
                {"relationships_following": [_following_entry_old("alice", 1010)]},
                t1 + 0.01,
            )

            # Snap 2: followers_1.json + lol1.json (old schema)
            _write_json(arch / "followers_1.json", [_follower_entry("alice", 1000), _follower_entry("bob", 2000)], t2)
            _write_json(
                arch / "lol1.json",
                {"relationships_following": [_following_entry_old("alice", 1010)]},
                t2 + 0.01,
            )

            # Snap 3 (latest, at root with colliding filenames followers_1.json + following.json, new schema)
            _write_json(
                root / "followers_1.json",
                [_follower_entry("alice", 1000), _follower_entry("bob", 2000)],
                t3,
            )
            _write_json(
                root / "following.json",
                {"relationships_following": [_following_entry_new("alice", 1010), _following_entry_new("carol", 3000)]},
                t3 + 0.01,
            )

            archive = load_archive(archive_dir=arch, root_dir=root)
            self.assertEqual(len(archive.snapshots), 3)
            self.assertEqual([s.date_str for s in archive.snapshots], ["2024-07-28", "2024-09-30", "2026-11-20"])
            self.assertEqual(archive.snapshots[0].followers_path.name, "followers_2.json")
            self.assertEqual(archive.snapshots[0].following_path.name, "following.json")
            self.assertEqual(archive.snapshots[1].followers_path.name, "followers_1.json")
            self.assertEqual(archive.snapshots[1].following_path.name, "lol1.json")
            self.assertEqual(archive.snapshots[2].followers_path.parent, root)
            self.assertEqual(archive.snapshots[2].following_path.parent, root)
            self.assertIn("carol", archive.snapshots[2].following)


class TestHistoricalAnalyses(unittest.TestCase):
    def _build_synthetic_archive(self, root: Path):
        arch = root / "archival follwers"
        arch.mkdir()

        s1 = _ts("2025-01-01 10:00:00")
        s2 = _ts("2025-02-01 10:00:00")
        s3 = _ts("2025-03-01 10:00:00")
        s4 = _ts("2025-04-01 10:00:00")

        # Accounts & behaviors across 4 snapshots:
        # - alice_v1 -> alice_v2 (snap 2) -> alice_v3 (snap 3): double-verified 3-hop chain (ts_f=100, ts_g=200)
        # - single_fan_old -> single_fan_new (snap 2): single-side rename on followers (ts_f=300)
        # - twin1, twin2: coexisting accounts sharing timestamp 400 (MUST NOT link as rename!)
        # - deact_user: present snap 1 (ts=500), gone snap 2, returns snap 3 (ts=500) -> deactivated_and_reactivated
        # - refollow_user: present snap 1 (ts=600), gone snap 2, returns snap 3 (ts=650) -> unfollowed_and_refollowed
        # - quick_refollow: present snap 1 (ts=700), present snap 2 (ts=750) -> refollowed_between_snapshots
        # - quiet_unfollower: mutual snap 1-2 (ts_f=800, ts_g=810), drops followers at snap 3 (you still follow at snap 4)
        # - never_back: in following snap 1..4 (ts_g=900), never in followers
        # - int_drop: mutual snap 1-2 (ts_f=1000, ts_g=1010), drops both at snap 3 AND in recently_unfollowed_profiles (s2 < ts <= s3)
        # - org_unfollower: mutual snap 1-2 (ts_f=1100, ts_g=1110), drops followers only at snap 3
        # - mut_drop: mutual snap 1-2 (ts_f=1200, ts_g=1210), drops both at snap 3 WITHOUT log entry
        # - classic_drop: following snap 3 (ts_g=1300), drops snap 4 AND logged in classic relationships_unfollowed_users
        # - revert_a -> revert_b (snap 2) -> revert_a (snap 3): revert rename cycle test (ts=1400)

        # Snap 1
        _write_json(
            arch / "followers_1.json",
            [
                _follower_entry("alice_v1", 100),
                _follower_entry("single_fan_old", 300),
                _follower_entry("twin1", 400),
                _follower_entry("twin2", 400),
                _follower_entry("deact_user", 500),
                _follower_entry("refollow_user", 600),
                _follower_entry("quick_refollow", 700),
                _follower_entry("quiet_unfollower", 800),
                _follower_entry("int_drop", 1000),
                _follower_entry("org_unfollower", 1100),
                _follower_entry("mut_drop", 1200),
                _follower_entry("revert_a", 1400),
            ],
            s1,
        )
        _write_json(
            arch / "following1.json",
            {
                "relationships_following": [
                    _following_entry_old("alice_v1", 200),
                    _following_entry_old("twin1", 400),
                    _following_entry_old("twin2", 400),
                    _following_entry_old("quiet_unfollower", 810),
                    _following_entry_old("never_back", 900),
                    _following_entry_old("int_drop", 1010),
                    _following_entry_old("org_unfollower", 1110),
                    _following_entry_old("mut_drop", 1210),
                    _following_entry_old("revert_a", 1400),
                ]
            },
            s1 + 0.01,
        )

        # Snap 2
        _write_json(
            arch / "followers_2.json",
            [
                _follower_entry("alice_v2", 100),
                _follower_entry("single_fan_new", 300),
                _follower_entry("twin1", 400),
                _follower_entry("twin2", 400),
                _follower_entry("quick_refollow", 750),
                _follower_entry("quiet_unfollower", 800),
                _follower_entry("int_drop", 1000),
                _follower_entry("org_unfollower", 1100),
                _follower_entry("mut_drop", 1200),
                _follower_entry("revert_b", 1400),
            ],
            s2,
        )
        _write_json(
            arch / "following2.json",
            {
                "relationships_following": [
                    _following_entry_old("alice_v2", 200),
                    _following_entry_old("twin1", 400),
                    _following_entry_old("twin2", 400),
                    _following_entry_old("quiet_unfollower", 810),
                    _following_entry_old("never_back", 900),
                    _following_entry_old("int_drop", 1010),
                    _following_entry_old("org_unfollower", 1110),
                    _following_entry_old("mut_drop", 1210),
                    _following_entry_old("revert_b", 1400),
                ]
            },
            s2 + 0.01,
        )

        # Snap 3
        _write_json(
            arch / "followers_3.json",
            [
                _follower_entry("alice_v3", 100),
                _follower_entry("single_fan_new", 300),
                _follower_entry("twin1", 400),
                _follower_entry("twin2", 400),
                _follower_entry("deact_user", 500),
                _follower_entry("refollow_user", 650),
                _follower_entry("quick_refollow", 750),
                _follower_entry("revert_a", 1400),
            ],
            s3,
        )
        _write_json(
            arch / "following3.json",
            {
                "relationships_following": [
                    _following_entry_new("alice_v3", 200),
                    _following_entry_new("twin1", 400),
                    _following_entry_new("twin2", 400),
                    _following_entry_new("quiet_unfollower", 810),
                    _following_entry_new("never_back", 900),
                    _following_entry_new("org_unfollower", 1110),
                    _following_entry_new("classic_drop", 1300),
                    _following_entry_new("revert_a", 1400),
                ]
            },
            s3 + 0.01,
        )

        # Snap 4 (at root)
        _write_json(
            root / "followers_1.json",
            [
                _follower_entry("alice_v3", 100),
                _follower_entry("single_fan_new", 300),
                _follower_entry("twin1", 400),
                _follower_entry("twin2", 400),
                _follower_entry("deact_user", 500),
                _follower_entry("refollow_user", 650),
                _follower_entry("quick_refollow", 750),
                _follower_entry("revert_a", 1400),
            ],
            s4,
        )
        _write_json(
            root / "following.json",
            {
                "relationships_following": [
                    _following_entry_new("alice_v3", 200),
                    _following_entry_new("twin1", 400),
                    _following_entry_new("twin2", 400),
                    _following_entry_new("quiet_unfollower", 810),
                    _following_entry_new("never_back", 900),
                    _following_entry_new("org_unfollower", 1110),
                    _following_entry_new("revert_a", 1400),
                ]
            },
            s4 + 0.01,
        )

        # Unfollow log files (modern label_values + classic relationships_unfollowed_users)
        _write_json(
            arch / "recently_unfollowed_profiles.json",
            [
                _unfollowed_label_entry(
                    "int_drop",
                    "Int\u00c3\u00a9ntional Drop",
                    _ts("2025-02-15 12:00:00"),
                    with_fbid=False,
                )
            ],
            s3 + 0.02,
        )
        _write_json(
            arch / "recently_unfollowed_classic.json",
            {
                "relationships_unfollowed_users": [
                    {
                        "title": "",
                        "string_list_data": [
                            {
                                "href": "https://www.instagram.com/classic_drop",
                                "value": "classic_drop",
                                "timestamp": _ts("2025-03-15 12:00:00"),
                            }
                        ],
                    }
                ]
            },
            s4 + 0.02,
        )

        return load_archive(archive_dir=arch, root_dir=root)

    def test_renames_chains_collision_guard_and_reappearances(self) -> None:
        with TemporaryDirectory() as tmp:
            archive = self._build_synthetic_archive(Path(tmp))
            self.assertEqual(len(archive.snapshots), 4)

            pairs = [(r.old_username, r.new_username, r.double_verified) for r in archive.renames]
            self.assertIn(("alice_v1", "alice_v2", True), pairs)
            self.assertIn(("alice_v2", "alice_v3", True), pairs)
            self.assertIn(("single_fan_old", "single_fan_new", False), pairs)
            # Collision guard: twin1 and twin2 share timestamp 400 but coexist -> NOT a rename
            self.assertFalse(any("twin" in r.old_username or "twin" in r.new_username for r in archive.renames))

            self.assertEqual(archive.alias_to_canonical["alice_v1"], "alice_v3")
            self.assertEqual(archive.canonical_to_aliases["alice_v3"], ["alice_v1", "alice_v2", "alice_v3"])
            self.assertEqual(archive.alias_to_canonical["single_fan_old"], "single_fan_new")
            self.assertEqual(archive.alias_to_canonical["revert_b"], "revert_a")

            reapps = {(e.canonical_username, e.kind) for e in classify_reappearances(archive, side="followers")}
            self.assertIn(("deact_user", "deactivated_and_reactivated"), reapps)
            self.assertIn(("refollow_user", "unfollowed_and_refollowed"), reapps)
            self.assertIn(("quick_refollow", "refollowed_between_snapshots"), reapps)

    def test_compare_diff_attribution_and_account_history(self) -> None:
        with TemporaryDirectory() as tmp:
            archive = self._build_synthetic_archive(Path(tmp))

            # Diff 1 -> 2 must NOT count alice or single_fan renames as unfollowers/new followers
            d12 = diff_snapshots(archive, 1, 2, resolve_renames=True)
            self.assertEqual(d12.new_followers, [])
            self.assertEqual(d12.lost_followers, ["deact_user", "refollow_user"])
            self.assertEqual(len(d12.renames_in_window), 3)

            # Diff 2 -> 3
            d23 = diff_snapshots(archive, 2, 3, resolve_renames=True)
            self.assertEqual(len(d23.renames_in_window), 2)
            self.assertIn("int_drop", d23.mutual_drops)
            self.assertIn("mut_drop", d23.mutual_drops)
            self.assertIn("org_unfollower", d23.pure_unfollowers)
            self.assertIn("quiet_unfollower", d23.pure_unfollowers)
            self.assertIn("classic_drop", d23.newly_followed)

            # Attribution across intervals
            atts = attribute_unfollows(archive)
            att23 = atts[1]  # #2 -> #3
            self.assertTrue(att23.has_unfollow_log_coverage)
            self.assertEqual([a.canonical_username for a in att23.intentionally_unfollowed], ["int_drop"])
            self.assertEqual(att23.intentionally_unfollowed[0].display_name, "Inténtional Drop")
            self.assertEqual([a.canonical_username for a in att23.unattributed_mutual_drops], ["mut_drop"])
            self.assertEqual(
                [a.canonical_username for a in att23.unfollowed_you_only],
                ["org_unfollower", "quiet_unfollower"],
            )

            att34 = atts[2]  # #3 -> #4
            self.assertTrue(att34.has_unfollow_log_coverage)
            self.assertEqual([a.canonical_username for a in att34.intentionally_unfollowed], ["classic_drop"])

            # Account history queried via OLD alias resolves full timeline & lag
            hist = account_history(archive, "@alice_v1")
            self.assertIsNotNone(hist)
            assert hist is not None
            self.assertEqual(hist.canonical_username, "alice_v3")
            self.assertEqual(hist.all_handles, ["alice_v1", "alice_v2", "alice_v3"])
            self.assertEqual(hist.current_status, "mutual")
            self.assertEqual(hist.who_followed_first, "them")
            self.assertEqual(hist.follow_back_lag_seconds, 100)

            hist_int = account_history(archive, "int_drop")
            assert hist_int is not None
            self.assertEqual(hist_int.current_status, "former_mutual")
            self.assertEqual(hist_int.display_name, "Inténtional Drop")
            self.assertEqual(len(hist_int.unfollowed_log_events), 1)
            self.assertIn("recently_unfollowed_profiles.json", hist_int.ended_summary)

            self.assertIsNone(account_history(archive, "does_not_exist_123"))

    def test_timeline_loyalty_one_sided_and_markdown_report(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self._build_synthetic_archive(root)

            tl = timeline_summary(archive)
            self.assertEqual(len(tl), 4)
            self.assertIsNone(tl[0].net_followers_delta)
            self.assertEqual(tl[1].renames_count, 3)

            bd = compare_snapshot(archive, -1)
            not_back_names = {r.username for r in bd.not_following_back}
            self.assertEqual(not_back_names, {"never_back", "org_unfollower", "quiet_unfollower"})

            one_sided = one_sided_history(archive)
            self.assertEqual(one_sided.total_not_following_back, 3)
            self.assertEqual(
                {e.canonical_username for e in one_sided.quietly_unfollowed_you},
                {"org_unfollower", "quiet_unfollower"},
            )
            self.assertEqual([e.canonical_username for e in one_sided.never_followed_back], ["never_back"])

            loyalty = loyalty_rankings(archive, top_n=5)
            self.assertEqual(loyalty.longest_current_followers[0].canonical_username, "alice_v3")
            self.assertEqual(loyalty.longest_current_mutuals[0].canonical_username, "alice_v3")
            former_names = {e.canonical_username for e in loyalty.longest_former_followers}
            self.assertIn("int_drop", former_names)
            int_loy = next(e for e in loyalty.longest_former_followers if e.canonical_username == "int_drop")
            self.assertTrue(int_loy.attributed_to_you)

            report_path = generate_markdown_report(archive, root / "out_report.md", top_n=5)
            content = report_path.read_text(encoding="utf-8")
            self.assertIn("# Instagram Historical Archive Report", content)
            self.assertIn("## Table of Contents", content)
            self.assertIn("## 1. Timeline Summary", content)
            self.assertIn("## 2. Latest Snapshot Breakdown and One-Sided Tracker", content)
            self.assertIn("## 3. Period-by-Period Diffs", content)
            self.assertIn("### 3.1 Latest Period Diff", content)
            self.assertIn("### 3.2 All Earlier Period Diffs", content)
            self.assertIn("## 4. Unfollow Attribution", content)
            self.assertIn("## 5. Handle Changes and Detected Renames", content)
            self.assertIn("## 6. Deactivations vs. Unfollow-and-Refollows", content)
            self.assertIn("## 7. Loyalty Rankings", content)
            self.assertIn("## 8. Complete Account History Directory", content)
            self.assertIn("`@alice_v1` -> `@alice_v2` -> `@alice_v3`", content)
            self.assertIn("Inténtional Drop", content)
            self.assertIn("`@alice_v3`", content)

            hist = account_history(archive, "alice_v2")
            assert hist is not None
            hist_md = format_account_history_markdown(hist)
            self.assertIn("# Account History: `@alice_v3`", hist_md)

            cli_report = root / "cli_report.md"
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                rc = instaCompare.main([
                    "--archive-dir", str(root / "archival follwers"),
                    "--root-dir", str(root),
                    "--output", str(cli_report),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue(cli_report.exists())
            self.assertIn("Loaded 4 paired snapshots", buf.getvalue())
            self.assertIn("unique accounts indexed", buf.getvalue())

    def test_all_account_histories_parity_and_log_only(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = self._build_synthetic_archive(root)

            # Inject an extra transient unfollow-log-only record cleanly into another synthetic dir
            arch2 = root / "arch2"
            root2 = root / "root2"
            arch2.mkdir()
            root2.mkdir()
            s1 = _ts("2025-01-01 10:00:00")
            s2 = _ts("2025-02-01 10:00:00")
            _write_json(arch2 / "followers_1.json", [_follower_entry("alice", 100)], s1)
            _write_json(arch2 / "following1.json", {"relationships_following": [_following_entry_new("alice", 110)]}, s1 + 0.01)
            _write_json(root2 / "followers_1.json", [_follower_entry("alice", 100)], s2)
            _write_json(root2 / "following.json", {"relationships_following": [_following_entry_new("alice", 110)]}, s2 + 0.01)
            _write_json(
                arch2 / "recently_unfollowed_profiles.json",
                [_unfollowed_label_entry("transient_only", "Transient User", _ts("2025-01-15 12:00:00"))],
                s2 + 0.02,
            )
            archive2 = load_archive(archive_dir=arch2, root_dir=root2)
            h2 = all_account_histories(archive2)
            self.assertEqual([h.canonical_username for h in h2], ["alice", "transient_only"])
            self.assertEqual(h2[1].current_status, "unfollowed_log_only")
            self.assertEqual(h2[1].display_name, "Transient User")

            # Verify full parity between all_account_histories and single-account account_history
            all_h = all_account_histories(archive)
            self.assertEqual(len(all_h), len(archive.canonical_to_aliases))
            for h in all_h:
                single = account_history(archive, h.canonical_username)
                self.assertIsNotNone(single)
                assert single is not None
                self.assertEqual(h.canonical_username, single.canonical_username)
                self.assertEqual(h.all_handles, single.all_handles)
                self.assertEqual(h.display_name, single.display_name)
                self.assertEqual(h.current_status, single.current_status)
                self.assertEqual(h.renames, single.renames)
                self.assertEqual(h.who_followed_first, single.who_followed_first)
                self.assertEqual(h.follow_back_lag_seconds, single.follow_back_lag_seconds)
                self.assertEqual(h.reappearances, single.reappearances)
                self.assertEqual(h.unfollowed_log_events, single.unfollowed_log_events)
                self.assertEqual(h.snapshot_presence, single.snapshot_presence)
                self.assertEqual(h.ended_summary, single.ended_summary)


class TestRealWorkspaceArchiveIntegration(unittest.TestCase):
    def test_real_workspace_archive_read_only(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        archive_dir = repo_root / "archival follwers"
        if not archive_dir.exists():
            self.skipTest("Workspace archive folder not present.")

        archive = load_archive(archive_dir=archive_dir, root_dir=repo_root)
        self.assertEqual(len(archive.snapshots), 16)
        self.assertEqual(archive.skipped_files, [])
        self.assertEqual(archive.snapshots[0].date_str, "2024-07-28")
        self.assertEqual(archive.snapshots[-1].date_str, "2026-11-20")
        self.assertEqual(len(archive.unfollowed_records), 207)

        # Ensure snapshots are strictly chronological and contain zero empty usernames
        for prev, curr in zip(archive.snapshots, archive.snapshots[1:]):
            self.assertLess(prev.taken_at, curr.taken_at)
        for snap in archive.snapshots:
            self.assertTrue(all(bool(u) for u in snap.followers))
            self.assertTrue(all(bool(u) for u in snap.following))

        # Smoke-check all analysis functions on real data
        self.assertGreater(len(archive.renames), 80)
        self.assertGreater(len(classify_reappearances(archive, side="both")), 0)
        latest_bd = compare_snapshot(archive, -1)
        self.assertEqual(len(latest_bd.mutuals), 684)
        self.assertEqual(len(latest_bd.not_following_back), 45)
        self.assertEqual(len(latest_bd.fans_not_followed_back), 0)

        d_last = diff_snapshots(archive, -2, -1)
        self.assertEqual(len(d_last.renames_in_window), 6)

        atts = attribute_unfollows(archive)
        self.assertEqual(len(atts), 15)
        # #12 -> #13 matches 189 of 190 recently_unfollowed_profiles.json entries
        self.assertEqual(len(atts[11].intentionally_unfollowed), 189)
        # #11 -> #12 must NOT falsely pick up post-snap-12 unfollows
        self.assertFalse(atts[10].has_unfollow_log_coverage)
        self.assertEqual(len(atts[10].intentionally_unfollowed), 0)

        tl = timeline_summary(archive)
        self.assertEqual(len(tl), 16)

        loy = loyalty_rankings(archive, top_n=10)
        self.assertEqual(len(loy.longest_current_followers), 10)
        self.assertEqual(len(loy.longest_current_mutuals), 10)
        self.assertEqual(len(loy.longest_former_followers), 10)

        os_rep = one_sided_history(archive)
        self.assertEqual(os_rep.total_not_following_back, 45)
        self.assertEqual(len(os_rep.quietly_unfollowed_you) + len(os_rep.never_followed_back), 45)

        sample_handle = latest_bd.not_following_back[0].username
        hist = account_history(archive, sample_handle)
        self.assertIsNotNone(hist)

        all_h = all_account_histories(archive)
        self.assertGreater(len(all_h), 1100)

        with TemporaryDirectory() as tmp:
            out_md = Path(tmp) / "real_test_report.md"
            with patch("sys.stdout", io.StringIO()):
                rc = instaCompare.main([
                    "--archive-dir", str(archive_dir),
                    "--root-dir", str(repo_root),
                    "--output", str(out_md),
                ])
            self.assertEqual(rc, 0)
            text = out_md.read_text(encoding="utf-8")
            self.assertIn("## 8. Complete Account History Directory", text)


if __name__ == "__main__":
    unittest.main()
