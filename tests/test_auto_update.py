"""Official installer verification, opt-out and startup-only installation."""
import hashlib
import io
import os
import sys
import unittest
from unittest import mock

from mailbrief import config, storage
from mailbrief.features import auto_update
from tests.test_mailbrief import Isolated


class AutomaticUpdates(Isolated):
    def setUp(self):
        super().setUp()
        self.patch = mock.patch.object(config, 'INSTALLED', True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.data = b'MZ' + b'x' * 500000
        self.release = {'version': '99.0.0', 'url': 'https://github.com/ayal408/mailbrief/releases/download/v99.0.0/MailBrief-Setup.exe',
                        'size': len(self.data), 'sha256': hashlib.sha256(self.data).hexdigest()}

    def stage(self):
        with mock.patch.object(auto_update, 'update_available', return_value=self.release), \
                mock.patch.object(auto_update.urllib.request, 'urlopen', return_value=io.BytesIO(self.data)):
            self.assertTrue(auto_update.stage_latest())

    def test_download_does_not_install_and_launches_once_at_startup(self):
        with mock.patch.object(auto_update.subprocess, 'Popen') as launch:
            self.stage()
            launch.assert_not_called()
            self.assertTrue(auto_update.launch_staged())
            args = launch.call_args.args[0]
            self.assertEqual(args[0], auto_update.installer_path('99.0.0'))
            self.assertIn('/AUTOUPDATE=1', args)
            self.assertFalse(auto_update.launch_staged())
            launch.assert_called_once()

    def test_opt_out_prevents_download_and_already_staged_install(self):
        self.stage()
        storage.save_json(config.SETTINGS_FILE, {'auto_update': False})
        with mock.patch.object(auto_update, 'update_available') as check, mock.patch.object(auto_update.subprocess, 'Popen') as launch:
            self.assertFalse(auto_update.stage_latest())
            self.assertFalse(auto_update.launch_staged())
            check.assert_not_called()
            launch.assert_not_called()

    def test_modified_installer_is_never_run(self):
        self.stage()
        with open(auto_update.installer_path('99.0.0'), 'wb') as f:
            f.write(b'MZ' + b'y' * 500000)
        with mock.patch.object(auto_update.subprocess, 'Popen') as launch:
            self.assertFalse(auto_update.launch_staged())
            launch.assert_not_called()

    def test_wrong_origin_or_missing_digest_is_not_downloaded(self):
        for fields in ({'url': 'https://example.com/installer.exe'}, {'sha256': ''}):
            with mock.patch.object(auto_update, 'update_available', return_value=self.release | fields), \
                    mock.patch.object(auto_update.urllib.request, 'urlopen') as request:
                self.assertFalse(auto_update.stage_latest())
                request.assert_not_called()

    def test_incomplete_download_is_removed(self):
        with mock.patch.object(auto_update, 'update_available', return_value=self.release), \
                mock.patch.object(auto_update.urllib.request, 'urlopen', return_value=io.BytesIO(b'MZ')):
            self.assertFalse(auto_update.stage_latest())
        self.assertFalse(os.path.exists(auto_update.installer_path('99.0.0')))
        self.assertFalse(os.path.exists(auto_update.installer_path('99.0.0') + '.part'))

    def test_source_or_portable_never_installs(self):
        with mock.patch.object(config, 'INSTALLED', False), mock.patch.object(auto_update.subprocess, 'Popen') as launch:
            self.assertFalse(auto_update.stage_latest())
            self.assertFalse(auto_update.launch_staged())
            launch.assert_not_called()

    def test_invalid_saved_state_does_not_block_startup(self):
        for state in ([], {'version': 99}, {'version': '../../bad'}):
            storage.save_json(config.UPDATE_STATE_FILE, state)
            self.assertFalse(auto_update.launch_staged())

    def test_launch_failure_keeps_app_usable(self):
        self.stage()
        with mock.patch.object(auto_update.subprocess, 'Popen', side_effect=OSError('cannot run')):
            self.assertFalse(auto_update.launch_staged())
        self.assertIn('cannot run', auto_update.read_state()['error'])
        self.assertFalse(auto_update.read_state()['launched'])

    @unittest.skipUnless(sys.platform == 'win32', 'Native app startup is Windows-only')
    def test_startup_does_not_open_a_window_after_handing_off_to_installer(self):
        from mailbrief.web import server
        with mock.patch.object(server, 'first_instance', return_value=True), \
                mock.patch.object(auto_update, 'launch_staged', return_value=True), \
                mock.patch.object(server, '_claim') as claim, \
                mock.patch.object(server.window, 'run_app') as app:
            server.serve()
            claim.assert_not_called()
            app.assert_not_called()
