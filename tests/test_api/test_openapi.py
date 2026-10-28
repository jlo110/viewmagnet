"""Regression tests for the customized OpenAPI document.

The public ``/docs`` page (Scalar) is *entirely* driven by the
schema returned from ``app.openapi()`` — if any of the
customizations below silently drop, the rendered docs page
degrades to a generic FastAPI dump. These tests pin the contract.
"""
from __future__ import annotations

from src.api.main import app
from src.api.openapi import UNTYPED_RESPONSE_MARKER


def test_openapi_carries_branded_metadata() -> None:
    """Title, version, contact, license and x-logo must be set so
    Scalar's docs hero renders our branding instead of "FastAPI".
    """
    spec = app.openapi()

    info = spec["info"]
    assert info["title"] == "ViewMagnet API"
    assert info["version"]  # don't pin a literal — bumps are fine.
    assert "ViewMagnet REST API" in info["description"]
    assert "MCP server" in info["description"]
    assert info["contact"]["name"] == "ViewMagnet Support"
    assert info["license"]["name"] == "Proprietary"
    assert "x-logo" in info, "Scalar relies on x-logo for the hero image"
    assert info["x-logo"]["url"].startswith("https://viewmagnet.io")


def test_openapi_lists_both_servers() -> None:
    """Scalar's request-builder reads `servers` to populate its
    base-URL dropdown — production and local must both be present
    so users can ``Try it`` against either."""
    spec = app.openapi()
    urls = {s["url"] for s in spec["servers"]}
    assert "https://api.viewmagnet.com" in urls
    assert "http://localhost:8000" in urls


def test_openapi_declares_pat_security_scheme() -> None:
    """PAT auth is the recommended path for the MCP server + CI
    scripts, so the rendered docs must surface it (with prose) as a
    first-class scheme — not the bare HTTPBearer FastAPI emits by
    default."""
    spec = app.openapi()
    schemes = spec["components"]["securitySchemes"]

    assert "PersonalAccessToken" in schemes
    pat = schemes["PersonalAccessToken"]
    assert pat["type"] == "http"
    assert pat["scheme"] == "bearer"
    assert pat["bearerFormat"].startswith("vm_pat_")
    assert "Personal Access Token" in pat["description"]

    assert "SessionJWT" in schemes
    jwt = schemes["SessionJWT"]
    assert jwt["bearerFormat"] == "JWT"


def test_openapi_tags_drive_sidebar_groups() -> None:
    """Scalar renders its left nav from ``tags``. The list must be
    non-empty and include the journey-ordering tags so the docs
    sidebar reads top-to-bottom as ``login → analyze → write →
    distribute``."""
    spec = app.openapi()
    tag_names = [t["name"] for t in spec["tags"]]

    expected_order = [
        "Authentication",
        "API Tokens",
        "analyze",
        "scripts",
        "hooks",
        "studio",
        "distribution",
    ]
    last_index = -1
    for name in expected_order:
        assert name in tag_names, f"missing tag: {name}"
        idx = tag_names.index(name)
        assert idx > last_index, (
            f"tags must keep user-journey order — {name} appears "
            f"at index {idx} but should be after the previous "
            f"expected tag (last index {last_index})"
        )
        last_index = idx


def test_openapi_paths_are_not_empty() -> None:
    """Sanity guard: if FastAPI ever returns an empty paths dict
    (e.g. due to a broken router import), the docs page silently
    shows nothing. Fail loudly here instead."""
    spec = app.openapi()
    assert len(spec["paths"]) >= 100, (
        f"expected ≥100 paths (got {len(spec['paths'])}) — likely a "
        "broken router import"
    )


def test_openapi_external_docs_present() -> None:
    """Scalar renders an "External documentation" link in its
    header from this field. Without it the docs page has no
    backwards-link to the marketing site."""
    spec = app.openapi()
    assert spec["externalDocs"]["url"] == "https://viewmagnet.io/docs"


def test_no_empty_2xx_response_schemas() -> None:
    """Hard contract: no 2xx response may ship an empty ``{}``
    schema. Scalar interprets ``{}`` as ``null`` in its rendered
    example body, which makes endpoints look like they return
    nothing (this was the original "successful response: null"
    bug). The OpenAPI customization layer upgrades empties to
    ``{type: object, additionalProperties: true}`` — if the upgrade
    ever regresses, this test fails first."""
    spec = app.openapi()
    offenders: list[str] = []
    for path, methods in spec["paths"].items():
        for verb, op in methods.items():
            if verb not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, response in op.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                for media_type, media in response.get("content", {}).items():
                    sch = media.get("schema")
                    if sch == {} or sch is None:
                        offenders.append(
                            f"{verb.upper()} {path} -> {code} ({media_type})"
                        )
    assert not offenders, (
        "Found 2xx responses with empty schemas — Scalar will render "
        "their example body as `null`:\n  - "
        + "\n  - ".join(offenders)
    )


def test_untyped_response_count_is_tracked() -> None:
    """Counts (but doesn't fail on) endpoints still using the
    untyped-object fallback. Reading the count in CI gives us a
    moving baseline as endpoints grow real ``response_model=``
    declarations — when the count hits zero we can drop the
    fallback entirely and tighten the contract.

    NB: the *current* baseline at the time this test was written
    was 76 — significantly higher counts in a future run mean
    someone added an untyped endpoint, lower counts mean someone
    typed one.
    """
    spec = app.openapi()
    untyped = 0
    for methods in spec["paths"].values():
        for verb, op in methods.items():
            if verb not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, response in op.get("responses", {}).items():
                if not code.startswith("2"):
                    continue
                for media in response.get("content", {}).values():
                    if media.get("schema", {}).get(UNTYPED_RESPONSE_MARKER):
                        untyped += 1

    # Hard ceiling well above today's baseline so genuine
    # regressions (someone wires a new untyped endpoint without
    # noticing) trip the alarm but day-to-day refactors don't
    # constantly snap this assertion.
    assert untyped < 120, (
        f"{untyped} endpoints are still using the untyped-object "
        "fallback. Add Pydantic response_models to the worst "
        "offenders — see ``_upgrade_untyped_response_schemas`` in "
        "src/api/openapi.py."
    )


def test_openapi_tag_declarations_match_endpoint_usage() -> None:
    """The bug class this guards against:

    1. We declare a tag in ``OPENAPI_TAGS`` (so it gets a sidebar
       entry with a description) but no endpoint is tagged with it
       — the sidebar shows an empty section that looks "not done".
    2. An endpoint uses a tag we forgot to declare — the tag still
       appears in the sidebar but with no description and no
       guaranteed position in the journey order.

    Both regress the docs page silently. Pinning them as a test
    means a router rename ("ai_writer" → "ai-writer") fails CI
    instead of shipping a half-broken docs page.
    """
    spec = app.openapi()
    declared = {t["name"] for t in spec["tags"]}

    used: set[str] = set()
    for methods in spec["paths"].values():
        for verb, op in methods.items():
            if verb not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                continue
            used.update(op.get("tags", []))

    undeclared = used - declared
    assert not undeclared, (
        "Endpoints use tags that aren't declared in OPENAPI_TAGS — "
        "they'll render in an undescribed sidebar group on the docs "
        f"page. Add them to src/api/openapi.py: {sorted(undeclared)}"
    )

    empty = declared - used
    assert not empty, (
        "OPENAPI_TAGS declares sidebar sections that no endpoint "
        "uses — they'll render as empty 'not done'-looking sections. "
        f"Either rename to match the router or drop: {sorted(empty)}"
    )
