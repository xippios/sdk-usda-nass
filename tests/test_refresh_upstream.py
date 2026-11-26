"""``scripts/refresh_upstream.py``'s declaration to core's snapshot frame, offline.

The frame, ``xippios.core.refresh``, fetches through the client it is given, checks the
attribution, writes ``FETCHED.md``, its row of ``OBSERVED.md`` among them, and the files,
and compares them in ``--check``; core's own tests hold each of those (sdk-core ADR-0062).
What stays the package's is what its ``Snapshot`` declares and its hook ``reduce``. Nothing
here sends a request.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

from xippios.core.refresh import Snapshot

from xippios.usda.nass._client import client

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_upstream.py"
API = "https://quickstats.nass.usda.gov/api"
PARAM_DEFINE = "https://quickstats.nass.usda.gov/param_define"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("refresh_upstream", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def test_the_snapshot_declares_the_two_pages_with_the_converter() -> None:
    """The api page and the column definitions, each kept as Markdown by ``reduce``, the
    snapshot written under ``docs/upstream/`` of the repository and fetched through the
    package's own client, which sends no key, since no page is a keyed sample: a run sends
    2 requests."""
    snapshot = script.SNAPSHOT
    assert isinstance(snapshot, Snapshot)
    assert (snapshot.name, snapshot.slug) == ("USDA NASS Quick Stats", "usda-nass")
    assert [(page.url, page.file, page.status) for page in snapshot.pages] == [
        (API, "api.md", 200),
        (PARAM_DEFINE, "param_define.md", 200),
    ]
    assert snapshot.reduce is script.reduce
    assert snapshot.out == ROOT / "docs/upstream"
    assert snapshot.not_fetched == ()
    assert snapshot.client is client
    assert snapshot.variables == ()
    assert not any(page.keyed for page in snapshot.pages)


def test_the_attribution_and_the_words_that_state_nothing() -> None:
    """The api page prints the NASS API Terms of Service and the notice its Attribution
    section asks for; param_define states none. The check reads past the api page's own
    references to those terms and two phrases of the terms themselves, each in its context,
    since core's search reads "terms and conditions" too (sdk-core ADR-0062)."""
    snapshot = script.SNAPSHOT
    assert [(item.text, item.source) for item in snapshot.attribution] == [
        ("NASS API Terms of Service", API),
        ("This product uses the NASS API but is not endorsed or certified by NASS.", API),
    ]
    for words in snapshot.vocabulary:
        assert words.casefold() not in {"terms of service", "terms and conditions"}, words
    assert "agree to the NASS Terms of Service" in snapshot.vocabulary
    assert "subject to the terms and conditions of this Agreement" in snapshot.vocabulary
