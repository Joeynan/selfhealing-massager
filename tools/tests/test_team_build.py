"""Pinned build environment and exact, repeatable component patch application."""
import hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('team_build',ROOT/'tools/build_watcher.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RuntimeTests(unittest.TestCase):
    def test_windows_checkout_line_endings_keep_locked_template_valid(self):
        self.assertTrue(callable(getattr(m,'locked_template',None)), 'Locked template content must support Windows checkout line endings')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config';path.write_bytes(m.CONFIG_TEMPLATE.read_bytes().replace(b'\n',b'\r\n'))
            self.assertEqual(m.locked_template(path).replace(b'\r\n',b'\n'),m.CONFIG_TEMPLATE.read_bytes())
    def test_activated_windows_environment_uses_windows_python_and_path_ninja(self):
        self.assertTrue(callable(getattr(m,'select_build_runtime',None)), 'Fresh clones use an activated, pinned SDK')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);sdk=root/'external-sdk';sdk.mkdir();venv=root/'idf-python';(venv/'Scripts').mkdir(parents=True)
            python=venv/'Scripts/python.exe';python.touch();ninja=root/'ninja.exe';ninja.touch()
            result=m.select_build_runtime(root,{'IDF_PATH':str(sdk),'IDF_PYTHON_ENV_PATH':str(venv),'PATH':str(root)},'win32')
            self.assertEqual(result['python'],python);self.assertEqual(result['sdk'],sdk)
            self.assertEqual(result['ninja'],ninja)
    def test_missing_activated_sdk_has_actionable_error(self):
        self.assertTrue(callable(getattr(m,'select_build_runtime',None)), 'Fresh clones use an activated, pinned SDK')
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'ESP-IDF'):m.select_build_runtime(Path(temp),{},'darwin')

class PatchTests(unittest.TestCase):
    def support(self):
        path=ROOT/'tools/watcher_build_support.py'
        self.assertTrue(path.is_file(),'Patch application must be available without local vendor copies')
        spec=importlib.util.spec_from_file_location('build_support',path);support=importlib.util.module_from_spec(spec);spec.loader.exec_module(support)
        return support
    @unittest.skipUnless((ROOT/'work/xiaozhi-esp32/managed_components/wvirgil123__sscma_client/src/sscma_client_ops.c').exists(),'Full pinned component replay is checked after SDK dependency acquisition')
    def test_known_current_component_patch_is_idempotent(self):
        support=self.support()
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);metadata=json.loads((ROOT/'tools/config/build-baseline.json').read_text())
            for entry in metadata['sscma_files']:
                path=target/entry['path'];path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes((ROOT/'work/xiaozhi-esp32'/entry['path']).read_bytes())
            self.assertEqual(support.apply_managed_patches(target,ROOT)['changed'],[])
    @unittest.skipUnless((ROOT/'work/xiaozhi-esp32/managed_components/wvirgil123__sscma_client/src/sscma_client_ops.c').exists(),'Full pinned component replay is checked after SDK dependency acquisition')
    def test_pristine_component_is_patched_to_exact_verified_content(self):
        support=self.support()
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);metadata=json.loads((ROOT/'tools/config/build-baseline.json').read_text())
            diffs=support.parse_unified_patch((ROOT/'tools/patches/sscma-client-hardening.patch').read_text())
            for entry in metadata['sscma_files']:
                patched=(ROOT/'work/xiaozhi-esp32'/entry['path']).read_text()
                source=support.apply_file_diff(patched,diffs[entry['path']],reverse=True)
                self.assertEqual(hashlib.sha256(source.encode()).hexdigest(),entry['baseline_sha256'])
                path=target/entry['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(source)
            self.assertEqual(len(support.apply_managed_patches(target,ROOT)['changed']),3)
            self.assertEqual(support.apply_managed_patches(target,ROOT)['changed'],[])
    def test_unknown_component_source_is_rejected_without_mutation(self):
        support=self.support()
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp);metadata=json.loads((ROOT/'tools/config/build-baseline.json').read_text())
            for entry in metadata['sscma_files']:
                path=target/entry['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text('unknown source\n')
            with self.assertRaisesRegex(ValueError,'unknown|未知'):support.apply_managed_patches(target,ROOT)
            self.assertEqual((target/metadata['sscma_files'][0]['path']).read_text(),'unknown source\n')
    def test_wrong_sdk_file_cannot_be_trusted_without_git_metadata(self):
        support=self.support()
        with tempfile.TemporaryDirectory() as temp:
            sdk=Path(temp);path=sdk/'tools/cmake/version.cmake';path.parent.mkdir(parents=True);path.write_text('IDF 5.4\n')
            with self.assertRaisesRegex(ValueError,'baseline|基线'):support.validate_sdk(sdk,ROOT)

if __name__=='__main__':unittest.main()
