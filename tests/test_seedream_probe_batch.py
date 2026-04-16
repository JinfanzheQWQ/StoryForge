from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probe_seedream_scene_reference_batch as probe_batch  # noqa: E402


class SeedreamProbeBatchTestCase(unittest.TestCase):
    def test_summary_from_report_and_write_batch_summary_use_json_safe_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_root = Path(tmpdir) / "20260416-124546"
            probe_root = batch_root / "single_story_ch1_seg1_end"
            probe_root.mkdir(parents=True, exist_ok=True)
            report_path = probe_root / "report.json"

            report_payload = {
                "scene_manifest": str(
                    ROOT
                    / "outputs/projects/project-1/runs/run-1/story-a/scene_image_manifest.json"
                ),
                "character_manifest": str(
                    ROOT
                    / "outputs/projects/project-1/runs/run-1/story-a/character_image_manifest.json"
                ),
                "segment_id": "ch1_seg1",
                "frame_kind": "end",
                "active_characters": ["林栀"],
                "scene_anchor_url": "https://example.com/scene-anchor.png",
                "variants": [
                    {
                        "label": "3refs_temporal_scene_active",
                        "downloaded_image_path": "outputs/debug/example.jpg",
                    }
                ],
            }
            report_path.write_text(
                json.dumps(report_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            summary = probe_batch.summary_from_report(report_path)

            self.assertEqual(summary["story"], "story-a")
            self.assertEqual(summary["mode"], "single")
            self.assertEqual(
                summary["scene_manifest"],
                "outputs/projects/project-1/runs/run-1/story-a/scene_image_manifest.json",
            )
            self.assertIsInstance(summary["report_path"], str)
            json.dumps(summary, ensure_ascii=False)

            summary_json_path = probe_batch.write_batch_summary(
                batch_root=batch_root,
                summaries=[summary],
                timestamp="20260416-124546",
                projects_root=ROOT / "outputs/projects",
            )

            written_payload = json.loads(summary_json_path.read_text(encoding="utf-8"))
            self.assertEqual(written_payload["probe_count"], 1)
            self.assertEqual(
                written_payload["probes"][0]["report_path"],
                str(report_path),
            )


if __name__ == "__main__":
    unittest.main()
