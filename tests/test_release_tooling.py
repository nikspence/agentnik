"""Offline release planning, clean-environment gates, and real ZIP verification."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import build_release


class ReleaseTooling(unittest.TestCase):
    def test_plan_never_builds_or_creates_output(self):
        with patch.object(build_release.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(build_release.main(['--label','offline-plan-check']),0)
            self.assertFalse(json.loads(out.getvalue())['build']);run.assert_not_called()
            self.assertFalse((build_release.ROOT/'dist'/'build-offline-plan-check').exists())

    def test_shared_site_packages_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'pyvenv.cfg').write_text('include-system-site-packages = true\n')
            with patch.object(build_release.sys,'prefix',directory),patch.object(build_release.sys,'base_prefix',directory+'/base'):
                with self.assertRaisesRegex(ValueError,'system site packages'):build_release.clean_environment()

    def test_missing_or_unpinned_dependencies_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'pyvenv.cfg').write_text('include-system-site-packages = false\n')
            with patch.object(build_release.sys,'prefix',directory),patch.object(build_release.sys,'base_prefix',directory+'/base'),patch.object(build_release.importlib.metadata,'version',return_value='unexpected'):
                with self.assertRaisesRegex(ValueError,'requirements-build'):build_release.clean_environment()

    def bundle(self,root):
        bundle=Path(root)/'Agentnik';bundle.mkdir()
        for name in ('Agentnik.exe','LICENSE','README.md','DISCLAIMER.md','VALIDATION.md','RELEASE_NOTES.md'): (bundle/name).write_text('fixture')
        (bundle/'BUILD-MANIFEST.json').write_text('{}');(bundle/'THIRD_PARTY_LICENSES').mkdir()
        assets=bundle/'_internal'/'agentnik'/'assets';assets.mkdir(parents=True)
        for item in (build_release.ROOT/'agentnik'/'assets').iterdir():
            if item.suffix in ('.svg','.png','.ico'): (assets/item.name).write_bytes(b'fixture')
        catalogs=bundle/'_internal'/'agentnik'/'translations';catalogs.mkdir(parents=True)
        for item in (build_release.ROOT/'agentnik'/'translations').glob('*.qm'): (catalogs/item.name).write_bytes(item.read_bytes())
        qt=bundle/'_internal'/'PySide6'/'plugins'/'platforms';qt.mkdir(parents=True);(qt/'qwindows.dll').write_bytes(b'fixture')
        regex_dir=bundle/'_internal'/'regex';regex_dir.mkdir(parents=True);(regex_dir/'_regex.fixture.pyd').write_bytes(b'fixture')
        return bundle

    def test_archive_contents_checksum_and_non_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle=self.bundle(directory);archive=Path(directory)/'fixture.zip'
            digest=build_release.package_bundle(bundle,archive,{})
            self.assertEqual(digest,hashlib.sha256(archive.read_bytes()).hexdigest())
            self.assertIn(digest,archive.with_suffix('.zip.sha256').read_text())
            with zipfile.ZipFile(archive) as z:
                self.assertIsNone(z.testzip());self.assertIn('Agentnik/LICENSE',z.namelist())
                self.assertEqual(z.read('Agentnik/_internal/agentnik/translations/agentnik_ko.qm'),(build_release.ROOT/'agentnik'/'translations'/'agentnik_ko.qm').read_bytes())
            original=archive.read_bytes()
            with self.assertRaises(ValueError):build_release.package_bundle(bundle,archive,{})
            self.assertEqual(archive.read_bytes(),original)

    def test_build_manifest_keeps_revision_when_documentation_images_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Path(directory)/'source';repo.mkdir()
            for name in ('LICENSE','README.md','DISCLAIMER.md','VALIDATION.md','RELEASE_NOTES.md','AGENTNIK_PLAN.md','DEVELOPMENT_VALIDATION.md','MILESTONE_D_LIVE_TEST_PLAN.md','MILESTONE_D_LIVE_RESULTS.md','CODING_BACKEND_PLAN.md','CODING_GUIDE.md','FEATURES.md','SEARCH_PROVIDERS.md'):
                (repo/name).write_text('fixture')
            for assets in (repo/'assets',repo/'agentnik'/'assets'):
                assets.mkdir(parents=True);(assets/'fixture.png').write_bytes(b'fixture')
            (repo/'agentnik'/'translations').mkdir();(repo/'agentnik'/'translations'/'agentnik_ko.qm').write_bytes(b'catalog')
            revision={'commit':'release-source','dirty':False}
            def build(*args,**kwargs):
                destination=repo/'dist'/'build-v0.2.0'/'dist';destination.mkdir(parents=True)
                self.bundle(destination)
            with patch.object(build_release,'ROOT',repo),patch.object(build_release,'os') as system,patch.object(build_release.platform,'machine',return_value='AMD64'),patch.object(build_release,'clean_environment'),patch.object(build_release,'revision',return_value=revision),patch.object(build_release.subprocess,'run',side_effect=build),patch.object(build_release,'copy_notices',return_value=[]),contextlib.redirect_stdout(io.StringIO()):
                system.name='nt'
                self.assertEqual(build_release.main(['--label','v0.2.0','--build']),0)
            manifest=json.loads((repo/'dist'/'build-v0.2.0'/'dist'/'Agentnik'/'BUILD-MANIFEST.json').read_text())
            self.assertEqual(manifest['source'],revision)
            self.assertTrue((repo/'dist'/'build-v0.2.0'/'dist'/'Agentnik'/'FEATURES.md').is_file())
            self.assertTrue((repo/'dist'/'build-v0.2.0'/'Agentnik-v0.2.0-windows-x64.zip').is_file())

    def test_missing_assets_and_unexpected_local_data_fail_before_archiving(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle=self.bundle(directory);archive=Path(directory)/'fixture.zip'
            plugin=bundle/'_internal'/'PySide6'/'plugins'/'platforms'/'qwindows.dll';plugin.unlink()
            with self.assertRaisesRegex(ValueError,'platform plugin'):build_release.package_bundle(bundle,archive,{})
            self.assertFalse(archive.exists());plugin.write_bytes(b'fixture')
            regex_bin=bundle/'_internal'/'regex'/'_regex.fixture.pyd';regex_bin.unlink()
            with self.assertRaisesRegex(ValueError,'regex native module'):build_release.package_bundle(bundle,archive,{})
            self.assertFalse(archive.exists());regex_bin.write_bytes(b'fixture')
            (bundle/'history.sqlite3').write_bytes(b'private')
            with self.assertRaisesRegex(ValueError,'local data'):build_release.package_bundle(bundle,archive,{})
            self.assertFalse(archive.exists())

    def test_missing_or_mismatched_catalog_fails_before_archiving(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle=self.bundle(directory);archive=Path(directory)/'fixture.zip'
            catalog=bundle/'_internal'/'agentnik'/'translations'/'agentnik_ko.qm';catalog.unlink()
            with self.assertRaisesRegex(ValueError,'translation catalog'):build_release.package_bundle(bundle,archive,{})
            self.assertFalse(archive.exists());catalog.write_bytes(b'wrong')
            with self.assertRaisesRegex(ValueError,'translation catalog'):build_release.package_bundle(bundle,archive,{})
            self.assertFalse(archive.exists())


if __name__=='__main__':unittest.main()
