"""Regression checks for packaging patterns that commonly trigger endpoint protection."""
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DistributionSafety(unittest.TestCase):
    def test_runtime_has_no_hidden_script_interpreter_or_self_replacement(self):
        sources = '\n'.join(path.read_text(encoding='utf-8') for path in (ROOT / 'mailbrief').rglob('*.py'))
        for forbidden in ('ExecutionPolicy', 'EncodedCommand', "['powershell'", "['powershell.exe'",
                          'shutil.copyfile(sys.executable', "'--replace'"):
            self.assertNotIn(forbidden, sources)

    def test_release_uses_inspectable_onedir_artifacts(self):
        build = (ROOT / 'build.ps1').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
        installer = (ROOT / 'installer/mailbrief.iss').read_text(encoding='utf-8')
        for source in (build, workflow):
            self.assertIn('--onedir', source)
            self.assertIn('--noupx', source)
            self.assertNotIn('--onefile', source)
        self.assertIn('dist\\MailBrief\\*', installer)
        self.assertIn('recursesubdirs', installer)
        self.assertIn('MailBrief-Portable.zip', workflow)
        self.assertNotIn('dist/MailBrief.exe', workflow)

    def test_uninstaller_removes_tasks_notifications_and_protocol(self):
        installer = (ROOT / 'installer/mailbrief.iss').read_text(encoding='utf-8')
        cli = (ROOT / 'mailbrief/cli.py').read_text(encoding='utf-8')
        for task in ('MailBrief', 'MailBrief Alerts', 'MailBrief Today'):
            self.assertIn(f'/Delete /TN ""{task}"" /F', installer)
        self.assertIn('uninsdeletekey', installer)
        self.assertIn('clear()', cli)

    def test_release_supports_authenticode_signing(self):
        workflow = (ROOT / '.github/workflows/release.yml').read_text(encoding='utf-8')
        self.assertIn('WINDOWS_SIGNING_CERTIFICATE', workflow)
        self.assertIn('signtool.exe', workflow)
        self.assertIn('/tr http://timestamp.digicert.com', workflow)


if __name__ == '__main__':
    unittest.main()
