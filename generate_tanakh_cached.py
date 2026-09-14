#!/usr/bin/env python3
"""Resumable Tanakh downloader with a validated local cache.

This wrapper keeps the existing EPUB generator unchanged. It downloads every
required Sefaria response into cache/tanakh/ first, validates the complete
set, and only then calls the original generator. Interrupted runs can resume
without downloading chapters that are already cached.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Dict

import requests

from generate_tanakh import TanakhGenerator


class CachedTanakhGenerator(TanakhGenerator):
    """TanakhGenerator backed by a persistent, validated JSON cache."""

    def __init__(self, include_rashi: bool = False, cache_dir: str = "cache/tanakh"):
        super().__init__(include_rashi=include_rashi)
        self.cache_dir = Path(cache_dir)
        self.text_cache = self.cache_dir / "texts"
        self.rashi_cache = self.cache_dir / "rashi"
        self.text_cache.mkdir(parents=True, exist_ok=True)
        if self.include_rashi:
            self.rashi_cache.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_json_read(path: Path):
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _atomic_json_write(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temp_path.replace(path)

    def _text_path(self, book: str, chapter: int) -> Path:
        return self.text_cache / book / f"{chapter}.json"

    def _rashi_path(self, book: str, chapter: int) -> Path:
        return self.rashi_cache / book / f"{chapter}.json"

    def _valid_text(self, data) -> bool:
        if not isinstance(data, dict):
            return False
        if "he" not in data or "text" not in data:
            return False
        hebrew = self._clean_verses(data.get("he"))
        english = self._clean_verses(data.get("text"))
        return bool(hebrew) and bool(english)

    @staticmethod
    def _valid_rashi(data) -> bool:
        # An empty list is valid: a chapter can legitimately have no Rashi
        # links. The important distinction is valid JSON of the expected type
        # versus a missing/truncated response.
        return isinstance(data, list)

    def _request_json(self, url: str, params: Dict, *, headers=None):
        last_error = None
        for attempt in range(1, 6):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                return data
            except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 5:
                    delay = min(2 ** (attempt - 1), 16)
                    print(f"    retry {attempt}/5 in {delay}s: {exc}")
                    time.sleep(delay)
        print(f"    ✗ API failed after 5 attempts: {last_error}")
        return None

    def _download_text(self, book: str, chapter: int):
        url = f"https://www.sefaria.org/api/texts/{book}.{chapter}"
        params = {
            "ven": "The_Koren_Jerusalem_Bible",
            "vhe": "Tanach_with_Nikkud",
            "commentary": 0,
            "context": 1,
            "pad": 0,
            "wrapLinks": 0,
            "wrapNamedEntities": 0,
            "stripmarkers": 1,
        }
        return self._request_json(url, params)

    def _download_rashi(self, book: str, chapter: int):
        url = f"https://www.sefaria.org/api/links/{book}.{chapter}"
        params = {"with_text": 1, "category": "Commentary"}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 Chrome/145 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        return self._request_json(url, params, headers=headers)

    def fetch_text(self, book: str, chapter: int) -> Dict:
        path = self._text_path(book, chapter)
        cached = self._safe_json_read(path)
        if self._valid_text(cached):
            return cached

        data = self._download_text(book, chapter)
        if not self._valid_text(data):
            return {}

        self._atomic_json_write(path, data)
        return data

    def fetch_rashi(self, book: str, chapter: int):
        path = self._rashi_path(book, chapter)
        cached = self._safe_json_read(path)
        if self._valid_rashi(cached):
            # Reuse the original generator's grouping/rendering logic.
            return self._group_rashi_links(cached)

        data = self._download_rashi(book, chapter)
        if not self._valid_rashi(data):
            return {}

        self._atomic_json_write(path, data)
        return self._group_rashi_links(data)

    def _group_rashi_links(self, links):
        grouped = {}
        for link in links:
            if not isinstance(link, dict):
                continue
            collective = link.get("collectiveTitle")
            if not isinstance(collective, dict) or collective.get("en") != "Rashi":
                continue

            anchor_verse = link.get("anchorVerse")
            if not isinstance(anchor_verse, int):
                anchor_ref = str(link.get("anchorRef", ""))
                import re
                match = re.search(r"\.(\d+)$", anchor_ref) or re.search(r":(\d+)$", anchor_ref)
                if not match:
                    continue
                anchor_verse = int(match.group(1))

            hebrew = self._clean_rashi_text(link.get("he", ""))
            english = self._clean_rashi_text(link.get("text", ""))
            if not hebrew and not english:
                continue
            grouped.setdefault(anchor_verse, []).append({"hebrew": hebrew, "english": english})
        return grouped

    def _chapters_to_process(self, test_mode: bool, test2_mode: bool):
        if test2_mode:
            books = self.books[:3]
            limit = 3
        elif test_mode:
            books = self.books
            limit = 3
        else:
            books = self.books
            limit = None

        for book, _hebrew, _translit, count in books:
            for chapter in range(1, (min(count, limit) if limit else count) + 1):
                yield book, chapter

    def preflight(self, test_mode=False, test2_mode=False) -> bool:
        chapters = list(self._chapters_to_process(test_mode, test2_mode))
        total = len(chapters)
        complete = 0
        missing = []

        print("=" * 60)
        print("Sefaria download / local cache")
        print(f"Expected chapters: {total}")
        print(f"Cache: {self.cache_dir}")
        print("=" * 60)

        for index, (book, chapter) in enumerate(chapters, 1):
            path = self._text_path(book, chapter)
            cached = self._safe_json_read(path)
            if self._valid_text(cached):
                complete += 1
                print(f"[{index}/{total}] ✓ {book} {chapter} (cache)")
                continue

            print(f"[{index}/{total}] ↓ {book} {chapter}")
            data = self._download_text(book, chapter)
            if self._valid_text(data):
                self._atomic_json_write(path, data)
                complete += 1
                print(f"    ✓ saved")
            else:
                missing.append((book, chapter))
                print(f"    ✗ incomplete")

        if self.include_rashi:
            print("\nValidating/downloading Rashi cache...")
            for index, (book, chapter) in enumerate(chapters, 1):
                path = self._rashi_path(book, chapter)
                cached = self._safe_json_read(path)
                if self._valid_rashi(cached):
                    continue

                print(f"[{index}/{total}] ↓ Rashi {book} {chapter}")
                data = self._download_rashi(book, chapter)
                if self._valid_rashi(data):
                    self._atomic_json_write(path, data)
                    print("    ✓ saved")
                else:
                    missing.append((f"Rashi:{book}", chapter))
                    print("    ✗ incomplete")

        print("\n" + "=" * 60)
        print(f"Validated text chapters: {complete}/{total}")
        print(f"Failures/pending: {len(missing)}")

        if missing:
            print("\nEPUB NOT GENERATED. Run the command again to resume:")
            for book, chapter in missing:
                print(f"  - {book} {chapter}")
            print("=" * 60)
            return False

        print("✓ DOWNLOAD COMPLETE")
        print("✓ ALL REQUIRED CONTENT VALIDATED")
        print("=" * 60)
        return True

    def generate_cached(self, output_file="tanakh.epub", test_mode=False, test2_mode=False):
        if not self.preflight(test_mode, test2_mode):
            return False

        # From this point onward the original generator reads only validated
        # cache entries through our overridden fetch_text/fetch_rashi methods.
        super().generate(output_file, test_mode, test2_mode)
        return True


def main():
    parser = argparse.ArgumentParser(description="Generate a cached Hebrew/English Tanakh EPUB")
    parser.add_argument("-o", "--output", default="tanakh.epub", help="Output filename")
    parser.add_argument("--test", action="store_true", help="Generate only 3 chapters per book")
    parser.add_argument("--test2", action="store_true", help="Generate only the first 3 books and 3 chapters each")
    parser.add_argument("--rashi", action="store_true", help="Include Rashi commentary")
    parser.add_argument("--cache-dir", default="cache/tanakh", help="Local cache directory")
    args = parser.parse_args()

    generator = CachedTanakhGenerator(
        include_rashi=args.rashi,
        cache_dir=args.cache_dir,
    )
    success = generator.generate_cached(args.output, args.test, args.test2)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
