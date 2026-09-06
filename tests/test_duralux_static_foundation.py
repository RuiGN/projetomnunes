"""Static foundation contracts for the Duralux migration."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.management import call_command
from django.test import override_settings

DURALUX_RUNTIME_FILES = {
    "duralux/css/bootstrap.min.css",
    "duralux/css/product-integration.css",
    "duralux/css/theme.min.css",
    "duralux/images/favicon.svg",
    "duralux/images/logo_header.webp",
    "duralux/images/logo_login.webp",
    "duralux/js/bootstrap.bundle.min.js",
    "duralux/js/dashboard-charts.js",
    "duralux/js/form-behaviors.js",
    "duralux/js/lesson-player.js",
    "duralux/js/product-shell.js",
    "duralux/js/visual-reference-charts.js",
    "duralux/vendors/apexcharts/apexcharts.min.js",
    "duralux/vendors/css/feather.min.css",
    "duralux/vendors/fonts/feather.eot",
    "duralux/vendors/fonts/feather.ttf",
    "duralux/vendors/fonts/feather.woff",
}


def _static_path(relative_path: str) -> Path:
    match = finders.find(relative_path)
    assert match is not None, f"Missing static asset: {relative_path}"
    assert isinstance(match, str)
    return Path(match)


def test_duralux_runtime_manifest_is_minimal_and_complete() -> None:
    static_root = Path(settings.BASE_DIR) / "static" / "duralux"
    observed = {
        str(path.relative_to(Path(settings.BASE_DIR) / "static"))
        for path in static_root.rglob("*")
        if path.is_file()
    }

    assert observed == DURALUX_RUNTIME_FILES
    for relative_path in DURALUX_RUNTIME_FILES:
        assert _static_path(relative_path).is_file()


def test_duralux_brand_assets_are_exact_source_copies() -> None:
    source_root = (
        Path(settings.BASE_DIR) / "design_system_duralux" / "assets" / "images"
    )

    for filename in ("favicon.svg", "logo_header.webp", "logo_login.webp"):
        assert (
            _static_path(f"duralux/images/{filename}").read_bytes()
            == (source_root / filename).read_bytes()
        )


def test_duralux_styles_are_local_and_do_not_reference_missing_maps() -> None:
    for filename in ("bootstrap.min.css", "theme.min.css", "product-integration.css"):
        stylesheet = _static_path(f"duralux/css/{filename}").read_text(encoding="utf-8")
        assert "fonts.googleapis.com" not in stylesheet
        assert "@import url(http" not in stylesheet
        assert "sourceMappingURL=" not in stylesheet
        external_urls = re.findall(r"url\([\"']?(https?://[^)\"']+)", stylesheet)
        assert external_urls == []


def test_duralux_theme_is_exact_sanitized_source_derivation() -> None:
    source = (
        Path(settings.BASE_DIR)
        / "design_system_duralux"
        / "assets"
        / "css"
        / "theme.min.css"
    ).read_text(encoding="utf-8")
    expected, substitutions = re.subn(
        r"@import url\(https://fonts\.googleapis\.com/.*?\);",
        "",
        source,
    )
    expected, map_substitutions = re.subn(
        r"\n?/\*# sourceMappingURL=theme\.min\.css\.map \*/\n?\Z",
        "\n",
        expected,
    )
    promoted = _static_path("duralux/css/theme.min.css").read_text(encoding="utf-8")

    assert substitutions == 1
    assert map_substitutions == 1
    assert promoted == expected
    assert "*/500;600" not in promoted


def test_duralux_bootstrap_css_and_javascript_use_the_same_version() -> None:
    stylesheet = _static_path("duralux/css/bootstrap.min.css").read_text(
        encoding="utf-8"
    )
    script = _static_path("duralux/js/bootstrap.bundle.min.js").read_text(
        encoding="utf-8"
    )

    assert re.search(r"Bootstrap\s+v5\.3\.3", stylesheet)
    assert re.search(r"Bootstrap\s+v5\.3\.3", script)
    assert "Licensed under MIT" in stylesheet
    assert "Licensed under MIT" in script
    assert "sourceMappingURL=" not in script

    license_text = (
        Path(settings.BASE_DIR)
        / "docs"
        / "duralux"
        / "licenses"
        / "bootstrap-5.3.3-MIT.txt"
    ).read_text(encoding="utf-8")
    assert "Copyright (c) 2011-2024 The Bootstrap Authors" in license_text
    assert "Permission is hereby granted" in license_text


def test_duralux_bootstrap_bundle_includes_popper_and_its_notice() -> None:
    script = _static_path("duralux/js/bootstrap.bundle.min.js").read_text(
        encoding="utf-8"
    )
    popper_notice = (
        Path(settings.BASE_DIR)
        / "docs"
        / "duralux"
        / "licenses"
        / "popper-2.11.8-MIT.txt"
    ).read_text(encoding="utf-8")

    assert "Bootstrap v5.3.3" in script
    assert "createPopper" in script
    assert "sourceMappingURL=" not in script
    assert script.endswith("\n")
    assert popper_notice.startswith("The MIT License (MIT)\n")
    assert "@popperjs/core@2.11.8" in (
        Path(settings.BASE_DIR)
        / "docs"
        / "duralux"
        / "runtime-asset-manifest.md"
    ).read_text(encoding="utf-8")
    assert "Copyright (c) 2019 Federico Zivolo" in popper_notice
    assert "Permission is hereby granted" in popper_notice


def test_product_integration_uses_system_fonts_and_reduced_motion() -> None:
    stylesheet = _static_path("duralux/css/product-integration.css").read_text(
        encoding="utf-8"
    )

    assert "--product-font-sans" in stylesheet
    assert "system-ui" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet


def test_product_brand_variables_drive_bootstrap_primary_secondary_controls() -> None:
    stylesheet = _static_path("duralux/css/product-integration.css").read_text(
        encoding="utf-8"
    )

    assert "--bs-primary: var(--product-primary)" in stylesheet
    assert "--bs-secondary: var(--product-secondary)" in stylesheet
    for selector in (
        ".btn-primary",
        ".btn-outline-primary",
        ".btn-secondary",
        ".btn-outline-secondary",
    ):
        assert selector in stylesheet
    assert "--bs-btn-bg: var(--product-primary)" in stylesheet
    assert "--bs-btn-bg: var(--product-secondary)" in stylesheet
    assert ":focus-visible" in stylesheet
    assert "prefers-reduced-motion: reduce" in stylesheet


def test_product_brand_preview_has_a_product_css_contract() -> None:
    stylesheet = _static_path("duralux/css/product-integration.css").read_text(
        encoding="utf-8"
    )

    assert ".product-brand-preview {" in stylesheet
    assert ".product-brand-preview__logo {" in stylesheet
    assert "--preview-primary" in stylesheet
    assert "--preview-secondary" in stylesheet


def test_promoted_duralux_code_has_no_demo_tokens_or_missing_local_urls() -> None:
    static_root = Path(settings.BASE_DIR) / "static" / "duralux"
    code_files = sorted((*static_root.rglob("*.css"), *static_root.rglob("*.js")))
    forbidden_tokens = (
        ".assets/",
        "../assets/",
        "logo-full.png",
        "logo-abbr.png",
        "favicon.ico",
        "apps-mail.html",
        "/docs/documentations",
    )

    for code_file in code_files:
        contents = code_file.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in contents, f"{code_file}: forbidden token {token}"
        if code_file.suffix != ".css":
            continue
        for raw_url in re.findall(r"url\([\"']?([^\"')]+)", contents):
            if raw_url.startswith(("data:", "http://", "https://", "#")):
                continue
            local_path = raw_url.split("?", 1)[0].split("#", 1)[0]
            assert (code_file.parent / local_path).resolve().is_file(), (
                f"{code_file}: missing local URL {raw_url}"
            )


def test_production_uses_manifest_storage_after_legacy_css_cleanup() -> None:
    production_settings = (
        Path(settings.BASE_DIR) / "config" / "settings" / "production.py"
    ).read_text(encoding="utf-8")
    progress = (
        Path(settings.BASE_DIR) / "docs" / "duralux" / "progress.md"
    ).read_text(encoding="utf-8")

    assert '"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"' in (
        production_settings
    )
    assert "nine missing local URLs" in progress
    assert "manifest storage probe passed" in progress


def test_font_namespace_is_deferred_and_vendor_is_licensed_and_scoped() -> None:
    progress = (
        Path(settings.BASE_DIR) / "docs" / "duralux" / "progress.md"
    ).read_text(encoding="utf-8")
    prd = (Path(settings.BASE_DIR) / "MUDANCALAYOUT.prd").read_text(encoding="utf-8")
    compact_progress = " ".join(progress.split())

    assert "namespace `fonts/` permanece adiado" in compact_progress
    assert "ApexCharts 3.52.0" in compact_progress
    assert "- [X] Criar os namespaces Duralux necessários" in prd
    assert not (Path(settings.BASE_DIR) / "static" / "duralux" / "fonts").exists()
    vendor_root = Path(settings.BASE_DIR) / "static" / "duralux" / "vendors"
    vendor_files = {
        path.relative_to(Path(settings.BASE_DIR) / "static" / "duralux").as_posix()
        for path in vendor_root.rglob("*")
        if path.is_file()
    }
    assert vendor_files == {
        "vendors/apexcharts/apexcharts.min.js",
        "vendors/css/feather.min.css",
        "vendors/fonts/feather.eot",
        "vendors/fonts/feather.ttf",
        "vendors/fonts/feather.woff",
    }
    assert not list(
        (Path(settings.BASE_DIR) / "static" / "duralux").rglob(".gitkeep")
    )


def test_all_static_css_supports_manifest_hashing_without_missing_local_urls() -> None:
    with tempfile.TemporaryDirectory() as static_root, override_settings(
        STATIC_ROOT=static_root,
        STORAGES={
            **settings.STORAGES,
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
            },
        },
    ):
        call_command("collectstatic", interactive=False, verbosity=0)
        collected_root = Path(static_root)
        manifest = json.loads((collected_root / "staticfiles.json").read_text())
        for relative_path in sorted(DURALUX_RUNTIME_FILES):
            hashed_path = manifest["paths"][relative_path]
            assert hashed_path != relative_path
            assert (collected_root / hashed_path).is_file()


def test_documented_runtime_hashes_match_the_published_assets() -> None:
    manifest_path = (
        Path(settings.BASE_DIR)
        / "docs"
        / "duralux"
        / "runtime-asset-manifest.md"
    )
    manifest = manifest_path.read_text(encoding="utf-8")
    documented = dict(
        re.findall(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", manifest)
    )
    runtime_root = Path(settings.BASE_DIR) / "static" / "duralux"

    assert documented
    for relative_path, expected_hash in documented.items():
        asset = runtime_root / relative_path
        if not asset.is_file():
            continue
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == expected_hash, (
            relative_path
        )
