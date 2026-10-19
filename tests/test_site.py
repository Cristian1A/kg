"""The project site (docs/index.html, #41): links, images and anchors resolve.

GitHub Pages serves docs/ at https://cristian1a.github.io/kg/, so a renamed
example or document should break CI, not the site.
"""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INDEX = DOCS / "index.html"
REPO_URL = "https://github.com/Cristian1A/kg"


class _Page(HTMLParser):
    """Collects what the checks need from one HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: list[str] = []
        self.imgs: list[dict[str, str | None]] = []
        self.scripts: list[dict[str, str | None]] = []
        self.stylesheets: list[str] = []
        self.headings: list[int] = []
        self.html_lang: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if a.get("id"):
            self.ids.append(a["id"])
        if tag == "html":
            self.html_lang = a.get("lang")
        elif tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "img":
            self.imgs.append(a)
            self.links.append(a.get("src") or "")
        elif tag == "script":
            self.scripts.append(a)
        elif tag == "link" and a.get("rel") == "stylesheet":
            self.stylesheets.append(a.get("href") or "")
        elif re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))


@pytest.fixture(scope="module")
def page() -> _Page:
    parser = _Page()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser


def _github_slugs(markdown: str) -> set[str]:
    """Heading anchors as GitHub renders them (enough for these docs)."""
    slugs = set()
    for line in markdown.splitlines():
        match = re.match(r"#{1,6}\s+(.*)", line)
        if match:
            text = match.group(1).strip().lower()
            text = re.sub(r"[^\w\- ]", "", text)
            slugs.add(text.replace(" ", "-"))
    return slugs


def test_page_basics(page: _Page) -> None:
    assert page.html_lang == "en"
    assert page.headings.count(1) == 1
    jumps = [b - a for a, b in zip(page.headings, page.headings[1:], strict=False)]
    assert all(step <= 1 for step in jumps), "heading levels must not skip"
    duplicates = {i for i in page.ids if page.ids.count(i) > 1}
    assert not duplicates


def test_page_is_self_contained(page: _Page) -> None:
    assert all("src" not in s for s in page.scripts), "no external scripts"
    assert not page.stylesheets, "no external stylesheets"


def test_no_root_relative_links(page: _Page) -> None:
    # Pages serves the site under /kg/: "/examples/x.html" would 404
    bad = [u for u in page.links if u.startswith("/") and not u.startswith("//")]
    assert not bad


def test_local_links_and_images_exist(page: _Page) -> None:
    for url in page.links:
        parts = urlsplit(url)
        if parts.scheme or parts.netloc:
            continue
        if not parts.path:
            assert parts.fragment in page.ids, f"missing anchor #{parts.fragment}"
            continue
        target = DOCS / unquote(parts.path)
        assert target.is_file(), f"{url} does not exist in docs/"
        if parts.fragment.startswith("node="):
            node_id = parts.fragment.removeprefix("node=")
            text = target.read_text(encoding="utf-8")
            assert f'"{node_id}"' in text, f"{url}: no node {node_id}"


def test_repo_links_point_to_existing_files(page: _Page) -> None:
    for url in page.links:
        match = re.match(rf"{re.escape(REPO_URL)}/(?:blob|tree)/main/([^#]+)", url)
        if not match:
            continue
        target = ROOT / match.group(1)
        assert target.exists(), f"{url}: {match.group(1)} is not in the repo"
        fragment = urlsplit(url).fragment
        if fragment and target.suffix == ".md":
            slugs = _github_slugs(target.read_text(encoding="utf-8"))
            assert fragment in slugs, f"{url}: no heading #{fragment}"


def test_readme_anchors_exist(page: _Page) -> None:
    slugs = _github_slugs((ROOT / "README.md").read_text(encoding="utf-8"))
    for url in page.links:
        if url.startswith(f"{REPO_URL}#") and url != f"{REPO_URL}#readme":
            assert urlsplit(url).fragment in slugs, url


def test_every_example_graph_is_linked(page: _Page) -> None:
    linked = {urlsplit(u).path for u in page.links}
    for html in sorted((DOCS / "examples").glob("*.html")):
        assert f"examples/{html.name}" in linked, f"{html.name} is not on the site"


def test_images_have_alt_and_size(page: _Page) -> None:
    assert page.imgs
    for img in page.imgs:
        assert img.get("alt") is not None, img
        assert img.get("width") and img.get("height"), img
