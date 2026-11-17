import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from infrastructure.aws.prepare_site import prepare


class PrepareSiteTests(unittest.TestCase):
    def test_frontend_is_the_entrypoint_and_catalog_keeps_its_relative_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo = root / 'infrastructure/demo/web'
            (demo / 'assets').mkdir(parents=True)
            (demo / 'assets/catalog.json').write_bytes(b'[{"source_sha256":"source-hash"}]')
            (demo / 'assets/demo.js').write_text('fetch(new URL("catalog.json", document.currentScript.src))')
            (demo / 'index.html').write_text('<head><script src="/assets/demo.js"></script></head>')
            dist = root / 'dist'
            (dist / 'assets').mkdir(parents=True)
            (dist / 'assets/compiled.js').write_text('// compiled React application')
            (dist / 'assets/orbit.js').write_text('// compiled Atlas effects')
            (dist / '.vite').mkdir()
            (dist / '.vite/manifest.json').write_text(
                '{"src/space/atlasEffects.ts":{"file":"assets/orbit.js"},'
                '"src/assets/nasa-flame-design.webp":{"file":"assets/photo.webp"},'
                '"src/assets/nasa-flame-design-small.webp":{"file":"assets/mobile.webp"}}'
            )
            (dist / 'index.html').write_text('<head><script type="module" src="./assets/compiled.js"></script></head><div id="root"></div>')
            output = root / 'site'
            with patch('infrastructure.aws.prepare_site.ROOT', root):
                prepare(output, dist)
            html = (output / 'index.html').read_text()
            self.assertIn('id="root"', html)
            self.assertIn('<link rel="canonical" href="/">', html)
            self.assertIn('"/assets/command-center/assets/compiled.js"', html)
            self.assertIn('content="/assets/science/index.html"', html)
            self.assertIn('href="/assets/command-center/assets/mobile.webp" media="(max-width: 650px)"', html)
            self.assertIn('href="/assets/command-center/assets/photo.webp" media="(width > 650px)"', html)
            self.assertIn('<template id="home-image-preloads">', html)
            self.assertEqual((output / 'assets/catalog.json').read_bytes(), (demo / 'assets/catalog.json').read_bytes())
            atlas = (output / 'assets/science/index.html').read_text()
            self.assertIn('src="../demo.js"', atlas)
            self.assertIn('src="../command-center/assets/orbit.js"', atlas)
            self.assertTrue((output / 'assets/command-center/assets/orbit.js').is_file())
            legacy_home = (output / 'assets/command-center/index.html').read_text()
            self.assertIn('http-equiv="refresh" content="0; url=/"', legacy_home)
            self.assertIn('<a href="/">', legacy_home)
