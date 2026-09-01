from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from context_access import ContextCatalog, compact_ai_context  # noqa: E402
from memory_repo import MemoryRemote, empty_snapshot, merge_snapshots, sanitize_snapshot  # noqa: E402


class ContextAccessTests(unittest.TestCase):
    def test_question_loads_only_relevant_items(self):
        selected = ContextCatalog().select("BLE 能连接，为什么扫描不到 MPU6050？")
        ids = {item["id"] for item in selected}
        self.assertIn("mpu6050", ids)
        self.assertIn("transport", ids)
        self.assertLessEqual(len(selected), 4)
        self.assertLessEqual(sum(len(item.get("detail", "")) for item in selected), 4000)

    def test_live_context_is_preserved(self):
        value = compact_ai_context("屏幕", {"connected": True, "samples": 12})
        self.assertTrue(value["connected"])
        self.assertEqual(value["samples"], 12)
        self.assertEqual(value["knowledge"][0]["id"], "st7789")


class MemorySyncTests(unittest.TestCase):
    def test_repository_requires_slug_and_token(self):
        MemoryRemote("owner/private-memory", "token").validate()
        with self.assertRaises(ValueError):
            MemoryRemote("https://github.com/owner/repo", "token").validate()
        with self.assertRaises(ValueError):
            MemoryRemote("owner/repo", "").validate()

    def test_snapshot_redacts_secrets_and_is_bounded(self):
        snapshot = empty_snapshot("lc-001122aabbcc")
        snapshot["facts"] = ["API key=sk-secret-value", "喜欢中文界面"] * 100
        clean = sanitize_snapshot(snapshot, "lc-001122aabbcc")
        self.assertNotIn("sk-secret-value", json.dumps(clean, ensure_ascii=False))
        self.assertLessEqual(len(clean["facts"]), 80)

    def test_merge_keeps_unique_facts_and_newer_character(self):
        local = empty_snapshot("lc-001122aabbcc", "hiyori-free")
        local.update(revision=3, facts=["偏好 100 Hz"])
        remote = empty_snapshot("lc-001122aabbcc", "old")
        remote.update(revision=2, facts=["默认中文"])
        merged = merge_snapshots(local, remote)
        self.assertEqual(merged["revision"], 4)
        self.assertEqual(merged["characterId"], "hiyori-free")
        self.assertEqual(set(merged["facts"]), {"偏好 100 Hz", "默认中文"})


if __name__ == "__main__":
    unittest.main()
