#!/usr/bin/env python3
"""Tests for discord.py's cache reading, store merge and search — on a synthetic Chromium
simple-cache entry, so they run without Discord. Run: python3 -m unittest test_discord.py"""

import gzip
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discord  # noqa: E402


def message(mid, ts, content, author="anna", **extra):
    return {"id": mid, "timestamp": ts + ".000000+00:00", "content": content,
            "author": {"username": author, "global_name": author.title()}, "type": 0, **extra}


def cache_entry(path, url, body, compress=True):
    """Header (magic, version, key length, key hash, padding), key, body — and a trailing
    record, as Chromium writes it, which the reader must ignore."""
    key = f"1/0/_dk_https://discord.com https://discord.com {url}".encode()
    data = gzip.compress(json.dumps(body).encode()) if compress else json.dumps(body).encode()
    header = struct.pack("<QIII4x", discord.SIMPLE_CACHE_MAGIC, 5, len(key), 0)
    path.write_bytes(header + key + data + b"\xd8\x41\x0d\x97\x45\x6f\xfa\xf4" + b"\0" * 16)


class DiscordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cache = root / "discord" / "Cache" / "Cache_Data"
        self.cache.mkdir(parents=True)
        patches = [mock.patch.object(discord, "STORE", root / "store"),
                   mock.patch.object(discord, "CACHE_DIRS", [self.cache])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_gzip_page_and_ignores_other_endpoints(self):
        url = "https://discord.com/api/v9/channels/111/messages?before=5&limit=22"
        cache_entry(self.cache / "a_0", url, [message("2", "2026-11-01T10:00:00", "hej")])
        cache_entry(self.cache / "b_0", "https://discord.com/api/v9/users/@me/profile", {"id": "1"})
        added, seen = discord.harvest(quiet=True)
        self.assertEqual(added, {"111": 1})
        self.assertEqual(seen, {"111": "2026-11-01T10:00:00"})
        stored = discord.load_channel("111")["2"]
        self.assertEqual((stored["author"], stored["content"]), ("Anna", "hej"))

    def test_harvest_skips_unchanged_files_and_keeps_edits(self):
        url = "https://discord.com/api/v9/channels/111/messages?limit=50"
        cache_entry(self.cache / "a_0", url, [message("2", "2026-11-01T10:00:00", "old")])
        discord.harvest(quiet=True)
        self.assertEqual(discord.harvest(quiet=True), ({}, {}))  # nothing changed
        edited = message("2", "2026-11-01T10:00:00", "new", edited_timestamp="2026-11-01T11:00:00")
        cache_entry(self.cache / "c_0", url, [edited])
        discord.harvest(quiet=True)
        self.assertEqual(discord.load_channel("111")["2"]["content"], "new")

    def test_search_matches_all_words_within_dates(self):
        url = "https://discord.com/api/v9/channels/111/messages?limit=50"
        cache_entry(self.cache / "a_0", url, [
            message("1", "2026-10-01T10:00:00", "Invoice for hosting"),
            message("2", "2026-11-02T10:00:00", "hosting invoice paid"),
            message("3", "2026-11-03T10:00:00", "only hosting"),
        ], compress=False)
        discord.harvest(quiet=True)
        args = mock.Mock(query="invoice hosting", regex=False, channel=None, server=None,
                         since="2026-11-01", until=None, author=None, n=10, width=0)
        with mock.patch("builtins.print") as out:
            discord.cmd_search(args)
        printed = "\n".join(c.args[0] for c in out.call_args_list)
        self.assertIn("paid", printed)
        self.assertNotIn("only", printed)
        self.assertNotIn("Invoice for", printed)

    def test_relative_since(self):
        self.assertRegex(discord.parse_when("7d"), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$")
        self.assertEqual(discord.parse_when("2026-11-01"), "2026-11-01")


if __name__ == "__main__":
    unittest.main()
