"""The skill manifest is the shelf the compiler sees: name and description
from every SKILL.md across the configured roots, nothing loaded. The denylist
is reach control: a skill that sends, publishes, pays, deploys, or touches
secrets never enters a proposal or an install, whatever Jev scores it."""
import json
from pathlib import Path

from caduceus import manifest

ROOT = Path(__file__).resolve().parent.parent


def _skill(root, cat, name, desc, extra=""):
    d = root / cat / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n{extra}---\n# body\n")


def test_scan_two_roots_with_shadowing(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _skill(a, "productivity", "retro", "Look back at a session.")
    _skill(a, "x", "quiet", "")
    _skill(b, "ops", "retro", "duplicate elsewhere")
    _skill(b, "ops", "wizard", "'Guides a human.'", "disable-model-invocation: true\n")
    m = manifest.scan(roots=[("a", a, 3), ("b", b, 3), ("missing", tmp_path / "nope", 3)])
    names = {e.name: e for e in m.entries}
    assert set(names) == {"retro", "quiet", "wizard"}
    assert names["retro"].root == "a"
    assert m.shadowed == [("retro", str(b / "ops" / "retro" / "SKILL.md"))]
    assert names["wizard"].user_invoked and names["wizard"].description == "Guides a human."
    assert names["quiet"].empty_description and not names["retro"].empty_description
    assert m.skipped_roots == ["missing"] and m.counts == {"a": 2, "b": 1}
    assert len(names["retro"].sha256) == 64 and names["retro"].category == "productivity"
    assert names["retro"].path.endswith("productivity/retro/SKILL.md")


def test_depth_limit_respected(tmp_path):
    a = tmp_path / "a"
    _skill(a, "cat", "shallow", "d")
    deep = a / "cat" / "sub" / "deeper" / "deepest"
    deep.mkdir(parents=True)
    (deep / "SKILL.md").write_text("---\nname: deep\ndescription: d\n---\n")
    assert {e.name for e in manifest.scan(roots=[("a", a, 2)]).entries} == {"shallow"}
    assert {e.name for e in manifest.scan(roots=[("a", a, 5)]).entries} == {"shallow", "deep"}


def test_missing_root_skipped(tmp_path):
    m = manifest.scan(roots=[("gone", tmp_path / "gone", 2)])
    assert m.entries == [] and m.skipped_roots == ["gone"]


def test_name_falls_back_to_directory(tmp_path):
    a = tmp_path / "a"
    d = a / "cat" / "nameless"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# no frontmatter at all\n")
    e = manifest.scan(roots=[("a", a, 3)]).entries[0]
    assert e.name == "nameless" and e.empty_description


def test_frontmatter_block_scalar():
    fm = manifest.parse_frontmatter("---\nname: x\ndescription: >\n  first line\n  second\nversion: 1\n---\n")
    assert fm["description"] == "first line second" and fm["version"] == "1"
    fm2 = manifest.parse_frontmatter('---\nname: "q"\ndescription: |\n  a\n  b\n---\n')
    assert fm2["name"] == "q" and fm2["description"] == "a\nb"
    assert manifest.parse_frontmatter("no frontmatter") == {}


def test_denylist_patterns(tmp_path):
    (tmp_path / "seats").mkdir()
    (tmp_path / "seats" / "DENYLIST.json").write_text(
        '{"names": ["ship"], "patterns": ["send*", "*email*", "pay*"]}')
    d = manifest.Denylist.load(tmp_path)
    assert d.denies("send-message") and d.denies("inbox-email-triage")
    assert d.denies("ship") and d.denies("payroll-prep") and d.denies("vercel:ship")
    assert not d.denies("retro") and not d.denies("shipping-estimates-only")


def test_denylist_filter_and_missing_file(tmp_path):
    d = manifest.Denylist.load(tmp_path)  # no seats/DENYLIST.json → denies nothing
    assert d.denies("send-anything") is False
    entries = [manifest.Entry("a", "d", "r", "/x/a/SKILL.md", "c", False, "0" * 64, False),
               manifest.Entry("send-b", "d", "r", "/x/b/SKILL.md", "c", False, "0" * 64, False)]
    dl = manifest.Denylist(names=set(), patterns=["send*"])
    kept, denied = dl.filter(entries)
    assert [e.name for e in kept] == ["a"] and [e.name for e in denied] == ["send-b"]


def test_shipped_denylist_denies_risky_names():
    d = manifest.Denylist.load(ROOT)
    risky = ["send_message", "gmail-reply", "publish-brand-template", "pay-the-bills",
             "payroll-prep", "invoice-chase", "buy_domain", "vercel:deploy", "ship",
             "land-and-deploy", "update-config", "plugin-settings", "keys_remove",
             "credential-requests_create", "clear_graph", "trash_thread", "delete_file",
             "commit-push-pr", "slack_send_message", "create_deployment"]
    for n in risky:
        assert d.denies(n), n
    safe = ["retro", "grilling", "systematic-debugging", "code-review", "research-synthesis",
            "caduceus-council", "writing-for-agents", "test-driven-development", "firecrawl-search"]
    for n in safe:
        assert not d.denies(n), n


def test_save_and_load_roundtrip(tmp_path):
    a = tmp_path / "a"
    _skill(a, "c", "one", "d")
    m = manifest.scan(roots=[("a", a, 3)])
    out = tmp_path / "m.json"
    m.save(out)
    m2 = manifest.load(out)
    assert [e.name for e in m2.entries] == ["one"]
    assert m2.entries[0].sha256 == m.entries[0].sha256 and m2.counts == {"a": 1}
    assert json.loads(out.read_text())["schema"] == manifest.MANIFEST_SCHEMA


def test_default_roots_are_four_labels():
    labels = [r[0] for r in manifest.default_roots()]
    assert labels == ["global", "plugins", "hermes", "repo"]


def test_unsafe_frontmatter_name_falls_back_to_directory(tmp_path):
    a = tmp_path / "a"
    d = a / "cat" / "fine-dir"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: ../../escape\ndescription: d\n---\n")
    e = manifest.scan(roots=[("a", a, 3)]).entries[0]
    assert e.name == "fine-dir"


def test_safe_name_rules():
    assert manifest.safe_name("retro") and manifest.safe_name("a.b_c-9")
    for bad in ["", ".", "..", "../x", "a/b", "a\\b", ".hidden", "x" * 65, "sp ace", "é"]:
        assert not manifest.safe_name(bad), bad
