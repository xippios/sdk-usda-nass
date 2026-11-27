"""``docs/upstream/OBSERVED.md`` as committed: what Quick Stats does but never documents.

sdk-core's conventions §3 keep these notes in one file written by hand, which the capture
script neither writes nor checks and ``FETCHED.md`` lists in a row of its own, and give each
note its evidence: the probe's date, its operation and its sample, a recording under
``tests/fixtures/``, a packaged list or its request where the probe kept no answer. Core's
family check holds the file's row in ``FETCHED.md``, the label and the date that open each
note's last paragraph and the files its code spans cite (sdk-core ADR-0044, decision 1).
The tests here hold the rest, the package's own (ADR-0044, decision 3): each probe's
operation and sample, the dates of its samples, and that no dated note of what Quick Stats
answered stands outside the file.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "xippios" / "usda" / "nass"
OBSERVED = ROOT / "docs" / "upstream" / "OBSERVED.md"
OPERATIONS = ("api_GET", "get_counts", "get_param_values")
"""The three resources of ``docs/upstream/api.md``, as a probe names them."""
DATE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
SAMPLE = re.compile(r"`((?:tests/fixtures|src/xippios/usda/nass/reference)/[^`\s]+\.json)`")
"""A recording under ``tests/fixtures/`` or a packaged list, cited from the repository's root."""
REQUEST = re.compile(r"`GET (/api/(?:api_GET|get_counts|get_param_values)/[^`\s]*)`")
"""A request that kept no answer, cited by its method and path."""
REFERENCE = re.compile(r"^\[[^\]\n]+\]: \S+\n?", re.MULTILINE)
"""A link reference definition, which renders as nothing and is no note's paragraph."""
CITED_DATE = re.compile(r"\b(?:decisions? of|amendment) 20\d\d-\d\d-\d\d\b")
"""A date that cites a record, the maintainer's decision or an ADR's amendment, and dates
no answer of Quick Stats."""
PACKAGE_TEXT = sorted(
    [
        ROOT / "README.md",
        ROOT / "CLAUDE.md",
        ROOT / "docs" / "layout.md",
        ROOT / "scripts" / "refresh_reference.py",
        ROOT / "scripts" / "refresh_upstream.py",
        *PACKAGE.rglob("*.py"),
    ]
)
"""The package's own text: its README, ``CLAUDE.md``, its layout, its scripts and modules."""


def notes() -> dict[str, list[str]]:
    """Each note's heading and its paragraphs, each paragraph's lines joined by a space.

    A ``##`` heading groups notes and is none itself.
    """
    text = REFERENCE.sub("", OBSERVED.read_text(encoding="utf-8"))
    parts = re.split(r"^(##|###) (.+)$", text, flags=re.MULTILINE)
    return {
        heading: [" ".join(block.split()) for block in body.split("\n\n") if block.strip()]
        for level, heading, body in zip(parts[1::3], parts[2::3], parts[3::3], strict=True)
        if level == "###"
    }


def sample_date(path: str) -> str:
    """The day a sample was taken: a recording's ``recorded_at``, a packaged list's ``fetched``."""
    sample = json.loads((ROOT / path).read_text(encoding="utf-8"))
    return str(sample.get("recorded_at") or sample["fetched"])[:10]


def test_every_note_ends_with_its_probe() -> None:
    """The probe names an operation of Quick Stats, in a code span, and a sample of it or
    the request whose answer was not kept."""
    found = notes()
    assert found
    for heading, paragraphs in found.items():
        probe = paragraphs[-1]
        assert re.match(r"(?:Probe|Observed): 20\d\d-\d\d-\d\d\b", probe), heading
        assert any(f"`{operation}`" in probe for operation in OPERATIONS), heading
        assert SAMPLE.search(probe) or REQUEST.search(probe), heading


def test_every_sample_a_probe_names_was_taken_on_a_date_it_gives() -> None:
    """A recording's day, from its ``recorded_at``, and a packaged list's, from its
    ``fetched``, is a date of the probe; a request that kept no answer has a date in its
    own sentence."""
    for heading, paragraphs in notes().items():
        probe = paragraphs[-1]
        dates = DATE.findall(probe)
        for path in SAMPLE.findall(probe):
            assert sample_date(path) in dates, f"{heading}: {path}"
        for sentence in re.split(r"(?<=\.) (?=[A-Z])", probe):
            if REQUEST.search(sentence):
                assert DATE.search(sentence), f"{heading}: {sentence}"


def test_the_package_points_to_the_notes() -> None:
    """``CLAUDE.md`` says what the package does with what Quick Stats does, and the README
    lists the file among its documents (https://github.com/xippios/sdk-usda-nass/issues/52)."""
    for path in (ROOT / "CLAUDE.md", ROOT / "README.md"):
        assert "docs/upstream/OBSERVED.md" in path.read_text(encoding="utf-8"), path.name
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    documents = readme.split("\n## Documents\n", 1)[1].split("\n## ", 1)[0]
    observed = "https://github.com/xippios/sdk-usda-nass/blob/main/docs/upstream/OBSERVED.md"
    assert f"({observed})" in documents


def test_no_dated_note_stands_outside_the_notes() -> None:
    """What Quick Stats was seen to do stands once, in ``OBSERVED.md``, each note with its
    probe: the package's own text points to a note and dates no answer. A date there cites
    a record, the maintainer's decision or an ADR's amendment. The tests are not read: each
    gives the day its recordings were taken, the provenance of what it replays."""
    found = [
        f"{path.relative_to(ROOT)}: {date}"
        for path in PACKAGE_TEXT
        for date in DATE.findall(CITED_DATE.sub("", " ".join(path.read_text("utf-8").split())))
    ]
    assert found == []
