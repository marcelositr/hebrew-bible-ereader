#!/usr/bin/env python3
"""
Tanakh EPUB Generator

Generates a Hebrew/English Tanakh EPUB from Sefaria.
The generated book is text-only except for the optional cover image.

The output is deliberately reflowable and Kindle-friendly:
- one XHTML content file per biblical book, keeping the full edition below
  Amazon's 300-HTML-file limit;
- Hebrew and English remain separately directional inside each chapter;
- chapters are linked from the EPUB navigation/NCX;
- only the cover image is embedded;
- no interior artwork, illustration index, or attribution page is generated.
"""

import argparse
import html
import re
import time
from pathlib import Path
from typing import Dict

import requests
from ebooklib import epub


class TanakhGenerator:
    """Build a complete Hebrew/English Tanakh EPUB."""

    def __init__(self):
        self.books = [
            # TORAH
            ("Genesis", "בראשית", "Bereshit", 50),
            ("Exodus", "שמות", "Shemot", 40),
            ("Leviticus", "ויקרא", "Vayikra", 27),
            ("Numbers", "במדבר", "Bamidbar", 36),
            ("Deuteronomy", "דברים", "Devarim", 34),
            # NEVI'IM
            ("Joshua", "יהושע", "Yehoshua", 24),
            ("Judges", "שופטים", "Shoftim", 21),
            ("I_Samuel", "שמואל א", "Shmuel_Aleph", 31),
            ("II_Samuel", "שמואל ב", "Shmuel_Bet", 24),
            ("I_Kings", "מלכים א", "Melachim_Aleph", 22),
            ("II_Kings", "מלכים ב", "Melachim_Bet", 25),
            ("Isaiah", "ישעיהו", "Yeshayahu", 66),
            ("Jeremiah", "ירמיהו", "Yirmeyahu", 52),
            ("Ezekiel", "יחזקאל", "Yechezkel", 48),
            ("Hosea", "הושע", "Hoshea", 14),
            ("Joel", "יואל", "Yoel", 4),
            ("Amos", "עמוס", "Amos", 9),
            ("Obadiah", "עובדיה", "Ovadiah", 1),
            ("Jonah", "יונה", "Yonah", 4),
            ("Micah", "מיכה", "Michah", 7),
            ("Nahum", "נחום", "Nachum", 3),
            ("Habakkuk", "חבקוק", "Chavakuk", 3),
            ("Zephaniah", "צפניה", "Tzefaniah", 3),
            ("Haggai", "חגי", "Chaggai", 2),
            ("Zechariah", "זכריה", "Zechariah", 14),
            ("Malachi", "מלאכי", "Malachi", 3),
            # KETUVIM
            ("Psalms", "תהילים", "Tehillim", 150),
            ("Proverbs", "משלי", "Mishlei", 31),
            ("Job", "איוב", "Iyov", 42),
            ("Song_of_Songs", "שיר השירים", "Shir_HaShirim", 8),
            ("Ruth", "רות", "Rut", 4),
            ("Lamentations", "איכה", "Eicha", 5),
            ("Ecclesiastes", "קהלת", "Kohelet", 12),
            ("Esther", "אסתר", "Esther", 10),
            ("Daniel", "דניאל", "Daniel", 12),
            ("Ezra", "עזרא", "Ezra", 10),
            ("Nehemiah", "נחמיה", "Nechemya", 13),
            ("I_Chronicles", "דברי הימים א", "Divrei_HaYamim_Aleph", 29),
            ("II_Chronicles", "דברי הימים ב", "Divrei_HaYamim_Bet", 36),
        ]

    def get_css(self) -> str:
        """Load the project's CSS, with a safe fallback."""
        css_path = Path("templates/style_minimal.css")
        if css_path.exists():
            return css_path.read_text(encoding="utf-8")

        return """
        @font-face {
            font-family: "NotoSerifHebrew";
            src: url("fonts/NotoSerifHebrew-Regular.ttf");
        }
        body { font-family: Georgia, serif; line-height: 1.6; margin: 1em; }
        .chapter-container { margin: 0 auto; padding: 1em 0; }
        .chapter-container + .chapter-container {
            page-break-before: always;
            break-before: page;
        }
        .chapter-header { margin-bottom: 1.5em; text-align: center; }
        .hebrew-verse {
            direction: rtl;
            text-align: right;
            font-family: "NotoSerifHebrew", serif;
            font-size: 1.2em;
            line-height: 1.8;
            margin-bottom: 0.5em;
        }
        .english-verse {
            direction: ltr;
            text-align: left;
            font-size: 1em;
            line-height: 1.7;
            margin-bottom: 1em;
        }
        .verse-number { font-size: 0.85em; margin: 0 0.5em; }
        """

    @staticmethod
    def _clean_verses(values) -> list[str]:
        """Remove API HTML fragments and normalize whitespace."""
        if isinstance(values, str):
            values = [values]

        result = []
        for value in values or []:
            if not value:
                continue
            clean = re.sub(r"<[^>]+>", "", value)
            clean = re.sub(r"\s+", " ", clean).strip()
            if clean:
                result.append(clean)
        return result

    def fetch_text(self, book: str, chapter: int) -> Dict:
        """Fetch Hebrew and English text from Sefaria."""
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

        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == 2:
                    print(f"  ⚠ Failed to fetch {book} {chapter}: {exc}")
                else:
                    time.sleep(2)
        return {}

    @staticmethod
    def _verse_html(hebrew_verses: list[str], english_verses: list[str]) -> str:
        """Render paired Hebrew/English verses as safe XHTML fragments."""
        parts = []
        max_verses = max(len(hebrew_verses), len(english_verses))

        for index in range(max_verses):
            verse_number = index + 1
            if index < len(hebrew_verses):
                parts.append(
                    f'''            <div class="hebrew-verse" dir="rtl">
                <span class="verse-number">{verse_number}</span>{html.escape(hebrew_verses[index])}
            </div>
'''
                )
            if index < len(english_verses):
                parts.append(
                    f'''            <div class="english-verse" dir="ltr">
                <span class="verse-number">{verse_number}</span>{html.escape(english_verses[index])}
            </div>
'''
                )

        return "".join(parts)

    def create_book_content(
        self,
        book_name: str,
        hebrew_name: str,
        chapter_count: int,
        css: epub.EpubItem,
        test_limit: int | None = None,
    ) -> tuple[epub.EpubHtml, list[epub.Link]]:
        """Create one XHTML file containing every chapter of one biblical book."""
        filename = f"{book_name}.xhtml"
        item = epub.EpubHtml(
            title=f"{book_name} - {hebrew_name}",
            file_name=filename,
            lang="he",
        )

        limit = min(chapter_count, test_limit) if test_limit else chapter_count
        chapter_links = []
        sections = []

        for chapter_num in range(1, limit + 1):
            print(f"  Chapter {chapter_num}/{limit}")
            data = self.fetch_text(book_name, chapter_num)
            if not data or "he" not in data or "text" not in data:
                print(f"  ⚠ Skipping {book_name} {chapter_num}: missing text")
                continue

            hebrew_verses = self._clean_verses(data["he"])
            english_verses = self._clean_verses(data["text"])
            anchor = f"{book_name.lower().replace('_', '-')}-chapter-{chapter_num}"

            sections.append(
                f'''        <section class="chapter-container" id="{anchor}" epub:type="chapter">
            <div class="chapter-header">
                <h1>{html.escape(book_name)} {chapter_num}</h1>
                <h2 lang="he" dir="rtl">{html.escape(hebrew_name)} פרק {self.to_hebrew_numeral(chapter_num)}</h2>
            </div>
            <div class="verses-container">
{self._verse_html(hebrew_verses, english_verses)}            </div>
        </section>
'''
            )
            chapter_links.append(
                epub.Link(
                    f"{filename}#{anchor}",
                    f"{book_name} {chapter_num}",
                    anchor,
                )
            )

        item.content = f'''<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="he">
<head>
    <meta charset="utf-8" />
    <title>{html.escape(book_name)} - {html.escape(hebrew_name)}</title>
    <link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body>
    <main>
{''.join(sections)}    </main>
</body>
</html>
'''
        item.add_item(css)
        return item, chapter_links

    @staticmethod
    def to_hebrew_numeral(num: int) -> str:
        """Convert a chapter number to a simple Hebrew numeral."""
        ones = ["", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט"]
        tens = ["", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ"]
        hundreds = ["", "ק", "ר", "ש", "ת"]

        if num >= 1000:
            return str(num)

        result = ""
        if num >= 100:
            result += hundreds[num // 100]
            num %= 100
        if num >= 10:
            result += tens[num // 10]
            num %= 10
        if num:
            result += ones[num]

        if len(result) > 1:
            result = result[:-1] + "״" + result[-1]
        elif len(result) == 1:
            result += "׳"
        return result

    def generate(
        self,
        output_file: str = "tanakh.epub",
        test_mode: bool = False,
        test2_mode: bool = False,
    ):
        """Generate the complete Tanakh EPUB.

        Artwork policy:
        - The cover is kept when images/chagall_moses_tablets_cover.jpg exists.
        - No other image is embedded, referenced, or added to the TOC/spine.

        Kindle policy:
        - One XHTML file is generated per biblical book, not per chapter.
        - Chapter anchors are linked from the generated EPUB TOC/NCX.
        """
        print("=" * 60)
        print("Tanakh EPUB Generator")
        print("Kindle-friendly reflowable edition")
        print("Text-only interior + optional cover")
        print("=" * 60)

        book = epub.EpubBook()
        book.set_identifier("tanakh-hebrew-english-2026")
        book.set_title("Tanakh - Hebrew Bible")
        book.set_language("he")
        book.add_metadata("DC", "language", "en")
        book.add_author("Sefaria.org")

        # Keep only the cover artwork.
        cover_path = Path("images/chagall_moses_tablets_cover.jpg")
        if cover_path.exists():
            book.set_cover("cover.jpg", cover_path.read_bytes())
            print("  ✓ Added cover image")
        else:
            print("  • No cover image found; continuing without a cover")

        css = epub.EpubItem(
            uid="style",
            file_name="style.css",
            media_type="text/css",
            content=self.get_css(),
        )
        book.add_item(css)

        # Keep the Hebrew font. It is not artwork and is useful for consistent
        # Hebrew rendering, especially when the reading system lacks the glyphs.
        font_path = Path("NotoSerifHebrew-Regular.ttf")
        if font_path.exists():
            font_item = epub.EpubItem(
                uid="hebrew-font",
                file_name="fonts/NotoSerifHebrew-Regular.ttf",
                media_type="application/x-font-ttf",
                content=font_path.read_bytes(),
            )
            book.add_item(font_item)
            print("  ✓ Embedded Hebrew font")

        dedication_html = """<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
<head>
    <meta charset="utf-8" />
    <title>Dedication</title>
    <link rel="stylesheet" type="text/css" href="style.css" />
    <style>
        .dedication { margin: 30% auto; text-align: center; font-style: italic; max-width: 80%; }
        .dedication h2 { font-size: 1.5em; margin-bottom: 1em; font-weight: normal; }
        .dedication p { font-size: 1.1em; line-height: 1.8; margin: 0.5em 0; }
        .dedication .name { font-size: 1.2em; margin-top: 2em; font-weight: bold; }
        .dedication .link { font-size: 0.9em; margin-top: 1em; }
    </style>
</head>
<body>
    <div class="dedication">
        <h2>Dedication</h2>
        <p>This edition of the Tanakh is dedicated with love to</p>
        <p class="name">Bruno &quot;DaVenzia&quot; Naphtali</p>
        <p>He saved my life</p>
        <p class="link"><a href="https://www.instagram.com/brunodavenzia/">@brunodavenzia</a></p>
    </div>
</body>
</html>
"""

        dedication = epub.EpubHtml(
            title="Dedication",
            file_name="dedication.xhtml",
            lang="en",
        )
        dedication.content = dedication_html
        dedication.add_item(css)
        book.add_item(dedication)

        spine = ["nav", dedication]
        toc = [dedication]

        if test2_mode:
            books_to_process = self.books[:3]
            test_limit = 3
            print("TEST2 MODE: first 3 books, first 3 chapters each")
        elif test_mode:
            books_to_process = self.books
            test_limit = 3
            print("TEST MODE: first 3 chapters of every book")
        else:
            books_to_process = self.books
            test_limit = None

        for english_name, hebrew_name, transliteration, chapter_count in books_to_process:
            print(f"Processing {english_name}...")
            book_item, chapter_links = self.create_book_content(
                english_name,
                hebrew_name,
                chapter_count,
                css,
                test_limit,
            )

            if chapter_links:
                book.add_item(book_item)
                spine.append(book_item)
                toc.append(
                    (
                        epub.Section(f"{english_name} - {hebrew_name}"),
                        chapter_links,
                    )
                )

        # EbookLib generates both EPUB 3 navigation and the NCX used by Kindle
        # navigation. The TOC contains direct chapter-anchor links even though
        # chapters are grouped into one XHTML file per biblical book.
        book.toc = toc
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        print(f"\nWriting to {output_file}...")
        epub.write_epub(output_file, book, {})
        print(f"Generated: {output_file}\n")


def main():
    parser = argparse.ArgumentParser(description="Generate a Hebrew/English Tanakh EPUB")
    parser.add_argument("-o", "--output", default="tanakh.epub", help="Output filename")
    parser.add_argument("--test", action="store_true", help="Generate only 3 chapters per book")
    parser.add_argument(
        "--test2",
        action="store_true",
        help="Generate only the first 3 books and 3 chapters each",
    )
    args = parser.parse_args()

    TanakhGenerator().generate(args.output, args.test, args.test2)


if __name__ == "__main__":
    main()
