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
            (demo / 'index.html').write_text('<script src="/assets/demo.js"></script>')
            dist = root / 'dist'
            (dist / 'assets').mkdir(parents=True)
            (dist / 'assets/compiled.js').write_text('// compiled React application')
            (dist / 'index.html').write_text('<head><script type="module" src="./assets/compiled.js"></script></head><div id="root"></div>')
            output = root / 'site'
            with patch('infrastructure.aws.prepare_site.ROOT', root):
                prepare(output, dist)
            html = (output / 'index.html').read_text()
            self.assertIn('id="root"', html)
            self.assertIn('"/assets/command-center/assets/compiled.js"', html)
            self.assertIn('content="/assets/science/index.html"', html)
            self.assertEqual((output / 'assets/catalog.json').read_bytes(), (demo / 'assets/catalog.json').read_bytes())
            self.assertIn('src="../demo.js"', (output / 'assets/science/index.html').read_text())
            self.assertIn('content="../science/index.html"', (output / 'assets/command-center/index.html').read_text())
