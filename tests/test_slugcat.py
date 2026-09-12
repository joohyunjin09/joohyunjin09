"""Offline, dependency-free regression tests: python -m unittest discover -s tests -v."""
from datetime import date, timedelta
import hashlib
import json
from math import hypot, isfinite
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from tools.slugcat.contributions import (atomic_write, empty_layout, from_graphql,
    load_calendar, make_calendar, valid_user)
from tools.slugcat.generate import generate
from tools.slugcat.motion import (DURATION, FLOOR, HEIGHT, TAIL_LENGTHS, TAIL_RADII,
    WIDTH, pose_vector, simulate)
from tools.slugcat.render import NS, render, simplify, validate_svg

TODAY = date(2026, 9, 12)
USER = "joohyunjin09"


def fixture(stamp=TODAY):
    # Synthetic counts are test fixtures only; never publish them as the user's data.
    layout = empty_layout(USER, stamp)
    return make_calendar(USER, stamp, [[str(d.date), (i * 7) % 19,
        0 if (i * 7) % 19 == 0 else 1 + ((i * 7) % 19 - 1) // 5]
        for i, d in enumerate(layout.days)], "github")


class CalendarTests(unittest.TestCase):
    def test_empty_is_not_fabricated_activity(self):
        c = empty_layout(USER, TODAY)
        self.assertEqual(c.source, "layout")
        self.assertEqual(c.total, 0)
        self.assertEqual(len(c.days), 365)
        self.assertEqual(c.sunday.weekday(), 6)

    def test_all_week_start_offsets_and_leap_day(self):
        for offset in range(370):
            c = empty_layout(USER, date(2024, 2, 29) + timedelta(days=offset))
            self.assertTrue(all(0 <= c.position(d)[0] <= 52 and 0 <= c.position(d)[1] <= 6 for d in c.days))

    def test_bad_user(self):
        for value in ("../bad", "a/b", "$(echo bad)", "<svg>", "", "-bad", "bad-", "a" * 40):
            with self.subTest(value=value), self.assertRaises(ValueError):
                valid_user(value)

    def test_duplicate_missing_and_bad_counts(self):
        base = json.loads(fixture().serialize())["days"]
        variants = [base[:-1], [base[0]] + base[:-1]]
        for bad in (True, -1, "5", 1e20):
            rows = [row[:] for row in base]
            rows[1][1] = bad
            variants.append(rows)
        for rows in variants:
            with self.assertRaises(ValueError):
                make_calendar(USER, TODAY, rows, "github")

    def test_graphql_errors_and_null_user(self):
        for payload in ({"errors": [{"message": "sensitive server message"}]}, {"data": {"user": None}}, []):
            with self.assertRaises(ValueError):
                from_graphql(payload, USER, TODAY)

    def test_graphql_calendar(self):
        c = fixture()
        levels = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
        days = [{"date": str(d.date), "contributionCount": d.count, "contributionLevel": levels[d.level]} for d in c.days]
        days.insert(0, {"date": str(c.start - timedelta(days=1)), "contributionCount": 0, "contributionLevel": "NONE"})
        result = from_graphql({"data": {"user": {"contributionsCollection": {"contributionCalendar": {
            "weeks": [{"contributionDays": days}]}}}}}, USER, TODAY)
        self.assertEqual(result.serialize(), c.serialize())

    def test_cache_outage_retains_real_snapshot_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            old = fixture(TODAY - timedelta(days=2))
            atomic_write(path, old.serialize())
            with patch.dict("os.environ", {"GH_TOKEN": "test-secret"}), patch(
                    "tools.slugcat.contributions.fetch_calendar", side_effect=RuntimeError("unavailable")):
                c, notice = load_calendar(USER, TODAY, path, True)
            self.assertEqual(c.as_of, old.as_of)
            self.assertEqual(c.source, "cache")
            self.assertNotIn("test-secret", notice)
            self.assertEqual(path.read_text(), old.serialize())

    def test_cache_wrong_user_future_and_corrupt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            for content in ("{bad json", fixture(TODAY + timedelta(days=1)).serialize(), fixture().serialize().replace(USER, "someone-else")):
                path.write_text(content)
                c, _ = load_calendar(USER, TODAY, path)
                self.assertEqual(c.source, "layout")

    def test_live_success_is_not_saved_before_render(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            with patch.dict("os.environ", {"GH_TOKEN": "secret"}), patch(
                    "tools.slugcat.contributions.fetch_calendar", return_value=fixture()):
                c, _ = load_calendar(USER, TODAY, path, True)
            self.assertEqual(c.source, "github")
            self.assertFalse(path.exists())


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = fixture()
        cls.animation = simulate(cls.calendar)

    def test_states_and_one_character(self):
        self.assertTrue({"Idle", "Walk", "Turn", "Hop", "Inspect", "Land"}.issubset({p.state for p in self.animation.frames}))
        self.assertEqual(len(self.animation.frames), int(DURATION * 24) + 1)
        self.assertAlmostEqual(sum(b.duration for b in self.animation.plan.beats), DURATION)

    def test_all_coordinates_finite_and_inside_scene(self):
        for p in self.animation.frames:
            self.assertTrue(all(isfinite(value) for value in pose_vector(p)))
            points = (p.hips, p.chest, p.head, *p.tail, *p.feet, *p.hands)
            for x, y in points:
                self.assertTrue(16 < p.root[0] + x < WIDTH - 16)
                self.assertTrue(16 < p.root[1] + y < HEIGHT - 16)

    def test_closed_loop_position_and_velocity(self):
        frames = self.animation.frames
        self.assertLess(self.animation.seam_error, 0.08)
        self.assertEqual(pose_vector(frames[0]), pose_vector(frames[-1]))
        # Every pose component's derivative also joins at the resting boundary.
        before, start, after = map(pose_vector, (frames[-2], frames[0], frames[1]))
        self.assertLess(max(abs((b - a) - (c - b)) for a, b, c in zip(before, start, after)), 0.15)

    def test_tail_is_connected_tapered_and_above_floor(self):
        self.assertTrue(all(a > b for a, b in zip(TAIL_RADII, TAIL_RADII[1:])))
        for pose in self.animation.frames:
            self.assertEqual(len(pose.tail), 8)
            for i, (a, b) in enumerate(zip(pose.tail, pose.tail[1:])):
                self.assertLess(abs(hypot(b[0] - a[0], b[1] - a[1]) - TAIL_LENGTHS[i]), 1.5)
                self.assertLessEqual(pose.root[1] + b[1] + TAIL_RADII[i + 1], FLOOR + 0.02)

    def test_feet_do_not_slide_while_planted(self):
        for first, second in zip(self.animation.frames, self.animation.frames[1:]):
            for side in range(2):
                if first.planted[side] and second.planted[side]:
                    self.assertAlmostEqual(first.root[0] + first.feet[side][0], second.root[0] + second.feet[side][0], places=6)

    def test_jump_and_blink_are_present(self):
        self.assertGreater(max(p.elevation for p in self.animation.frames), 22)
        self.assertLess(min(p.blink for p in self.animation.frames), 0.1)

    def test_deterministic(self):
        other = simulate(self.calendar)
        self.assertEqual(self.animation.frames, other.frames)

    def test_sampling_does_not_change_physics(self):
        other = simulate(self.calendar, fps=12)
        self.assertEqual(self.animation.frames[::2], other.frames)

    def test_bad_fps(self):
        with self.assertRaises(ValueError):
            simulate(self.calendar, fps=29)

    def test_multiple_daily_seeds(self):
        for offset in (1, 3, 7, 14, 45):
            animation = simulate(fixture(TODAY - timedelta(days=offset)))
            self.assertLess(animation.seam_error, 0.08)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calendar = fixture()
        cls.animation = simulate(cls.calendar)

    def test_all_variants_valid_and_bounded(self):
        for theme in ("light", "dark"):
            for animated in (True, False):
                svg = render(self.calendar, self.animation, theme, animated)
                validate_svg(svg)
                tree = ET.fromstring(svg)
                self.assertEqual(tree.attrib["viewBox"], "0 0 896 238")
                self.assertLess(len(svg.encode()), 900_000)
                self.assertEqual(len(tree.findall(f".//{{{NS}}}g[@id='slugcat']")), 1)
                tracks = tree.findall(f".//{{{NS}}}animate") + tree.findall(f".//{{{NS}}}animateTransform")
                self.assertEqual(bool(tracks), animated)
                if animated:
                    self.assertIn("prefers-reduced-motion", svg)

    def test_no_script_external_asset_or_foreign_object(self):
        for tag in ("script", "foreignObject", "image", "iframe"):
            with self.assertRaises(ValueError):
                validate_svg(f'<svg xmlns="{NS}"><{tag}/></svg>')
        with self.assertRaises(ValueError):
            validate_svg(f'<svg xmlns="{NS}" onload="bad()"/>')

    def test_layout_is_clearly_labelled(self):
        calendar = empty_layout(USER, TODAY)
        svg = render(calendar, simulate(calendar), "dark", False)
        self.assertIn("Layout preview / GitHub data not loaded", svg)
        self.assertNotIn("0 contributions / 365 days", svg)

    def test_reducer_preserves_error_bound(self):
        values = [(i / 100, ((i - 20) / 30) ** 2) for i in range(80)]
        keys = simplify(values, 0.02)
        for a, b in zip(keys, keys[1:]):
            for i in range(a, b + 1):
                q = (i - a) / (b - a)
                self.assertLessEqual(max(abs(value - (x + (y - x) * q)) for value, x, y in zip(values[i], values[a], values[b])), 0.020001)

    def test_manifest_files_match_and_generator_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            first = generate(USER, out, TODAY)
            contents = {p.name: p.read_bytes() for p in out.iterdir()}
            second = generate(USER, out, TODAY)
            self.assertEqual(first, second)
            self.assertEqual(contents, {p.name: p.read_bytes() for p in out.iterdir()})
            self.assertIsNone(first["total_contributions"])
            for name, info in first["files"].items():
                self.assertEqual(hashlib.sha256((out / name).read_bytes()).hexdigest(), info["sha256"])
            self.assertFalse((out / "contributions.json").exists())

    def test_render_failure_preserves_published_files_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            generate(USER, out, TODAY)
            before = {p.name: p.read_bytes() for p in out.iterdir()}
            with patch.dict("os.environ", {"GH_TOKEN": "secret"}), patch(
                    "tools.slugcat.contributions.fetch_calendar", return_value=fixture()), patch(
                    "tools.slugcat.generate.render", side_effect=ValueError("invalid render")):
                with self.assertRaises(ValueError):
                    generate(USER, out, TODAY, fetch=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})


if __name__ == "__main__":
    unittest.main()
