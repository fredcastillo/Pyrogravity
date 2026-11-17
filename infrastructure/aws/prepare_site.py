"""Publish the React frontend at / and preserve the full scientific catalog."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def prepare(output: Path, frontend: Path) -> None:
    demo = ROOT / "infrastructure" / "demo" / "web"
    assets = output / "assets"
    shutil.copytree(demo / "assets", assets, dirs_exist_ok=True)
    science = assets / "science"
    science.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((frontend / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    atlas_effects = manifest["src/space/atlasEffects.ts"]["file"]
    legacy = (demo / "index.html").read_text(encoding="utf-8").replace('"/assets/', '"../')
    legacy = legacy.replace("</head>", f'<script type="module" src="../command-center/{atlas_effects}"></script>\n</head>')
    (science / "index.html").write_text(legacy, encoding="utf-8")
    shutil.copytree(frontend, assets / "command-center", dirs_exist_ok=True, ignore=shutil.ignore_patterns(".vite"))
    html = (frontend / "index.html").read_text(encoding="utf-8")
    hero_preloads = []
    for image, media in (("nasa-flame-design-small", "(max-width: 650px)"), ("nasa-flame-design", "(width > 650px)")):
        entry = manifest[f"src/assets/{image}.webp"]
        hero_preloads.append(
            f'<link rel="preload" as="image" href="./{entry["file"]}" media="{media}" fetchpriority="high">'
        )
    # Study URLs share the home HTML but do not display the home photograph.
    hero_links = "\n".join(hero_preloads)
    html = html.replace(
        "</head>",
        f'<template id="home-image-preloads">\n{hero_links}\n</template>\n'
        '<script>if (location.pathname === "/" || location.pathname === "/index.html") '
        '{ document.head.append(document.getElementById("home-image-preloads").content.cloneNode(true)); }</script>\n'
        '</head>',
    )
    root_html = html.replace('"./assets/', '"/assets/command-center/assets/')
    root_html = root_html.replace(
        '</head>',
        '<link rel="canonical" href="/">\n'
        '<meta name="pyrogravity-science" content="/assets/science/index.html">\n</head>',
    )
    (output / "index.html").write_text(root_html, encoding="utf-8")
    nested_html = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<title>Pyrogravity</title><link rel="canonical" href="/">'
        '<meta http-equiv="refresh" content="0; url=/"></head>'
        '<body><a href="/">Ir a Pyrogravity</a></body></html>'
    )
    (assets / "command-center" / "index.html").write_text(nested_html, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend", type=Path, default=ROOT / "frontend" / "dist")
    args = parser.parse_args()
    prepare(args.output, args.frontend)
