#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import errno
import os
import subprocess

import mock

from heat.cloudinit import loguserdata
from heat.tests import common


class FakeCiVersion(object):
    def __init__(self, version):
        self.version = version


class LoguserdataTest(common.HeatTestCase):

    @mock.patch('pkg_resources.get_distribution')
    def test_ci_version_with_pkg_resources(self, mock_get):
        # Setup
        returned_versions = [
            FakeCiVersion('0.5.0'),
            FakeCiVersion('0.5.9'),
            FakeCiVersion('0.6.0'),
            FakeCiVersion('0.7.0'),
            FakeCiVersion('1.0'),
            FakeCiVersion('2.0'),
        ]
        mock_get.side_effect = returned_versions

        # Test & Verify
        self.assertFalse(loguserdata.chk_ci_version())
        self.assertFalse(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertEqual(6, mock_get.call_count)

    @mock.patch('pkg_resources.get_distribution')
    @mock.patch('subprocess.Popen')
    def test_ci_version_with_subprocess(self, mock_popen,
                                        mock_get_distribution):
        # Setup
        mock_get_distribution.side_effect = Exception()

        popen_return = [
            [None, 'cloud-init 0.0.5\n'],
            [None, 'cloud-init 0.7.5\n'],
        ]
        mock_popen.return_value = mock.MagicMock()
        mock_popen.return_value.communicate.side_effect = popen_return

        # Test & Verify
        self.assertFalse(loguserdata.chk_ci_version())
        self.assertTrue(loguserdata.chk_ci_version())
        self.assertEqual(2, mock_get_distribution.call_count)

    @mock.patch('pkg_resources.get_distribution')
    @mock.patch('subprocess.Popen')
    def test_ci_version_with_subprocess_exception(self, mock_popen,
                                                  mock_get_distribution):
        # Setup
        mock_get_distribution.side_effect = Exception()
        mock_popen.return_value = mock.MagicMock()
        mock_popen.return_value.communicate.return_value = ['non-empty',
                                                            'irrelevant']

        # Test
        self.assertRaises(Exception, loguserdata.chk_ci_version)  # noqa
        self.assertEqual(1, mock_get_distribution.call_count)

    @mock.patch('subprocess.Popen')
    def test_call(self, mock_popen):
        # Setup
        mock_popen.return_value = mock.MagicMock()
        mock_popen.return_value.communicate.return_value = ['a', 'b']
        mock_popen.return_value.returncode = 0

        # Test
        return_code = loguserdata.call(['foo', 'bar'])

        # Verify
        mock_popen.assert_called_once_with(['foo', 'bar'],
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        self.assertEqual(0, return_code)

    @mock.patch('sys.exc_info')
    @mock.patch('subprocess.Popen')
    def test_call_oserror_enoexec(self, mock_popen, mock_exc_info):
        # Setup
        mock_popen.side_effect = OSError()
        no_exec = mock.MagicMock(errno=errno.ENOEXEC)
        mock_exc_info.return_value = None, no_exec, None

        # Test
        return_code = loguserdata.call(['foo', 'bar'])

        # Verify
        self.assertEqual(os.EX_OK, return_code)

    @mock.patch('sys.exc_info')
    @mock.patch('subprocess.Popen')
    def test_call_oserror_other(self, mock_popen, mock_exc_info):
        # Setup
        mock_popen.side_effect = OSError()
        no_exec = mock.MagicMock(errno='foo')
        mock_exc_info.return_value = None, no_exec, None

        # Test
        return_code = loguserdata.call(['foo', 'bar'])

        # Verify
        self.assertEqual(os.EX_OSERR, return_code)

    @mock.patch('sys.exc_info')
    @mock.patch('subprocess.Popen')
    def test_call_exception(self, mock_popen, mock_exc_info):
        # Setup
        mock_popen.side_effect = Exception()
        no_exec = mock.MagicMock(errno='irrelevant')
        mock_exc_info.return_value = None, no_exec, None

        # Test
        return_code = loguserdata.call(['foo', 'bar'])

        # Verify
        self.assertEqual(os.EX_SOFTWARE, return_code)

    @mock.patch('pkg_resources.get_distribution')
    @mock.patch('os.chmod')
    @mock.patch('heat.cloudinit.loguserdata.call')
    def test_main(self, mock_call, mock_chmod, mock_get):
        # Setup
        mock_get.return_value = FakeCiVersion('1.0')
        mock_call.return_value = 10

        # Test
        return_code = loguserdata.main()

        # Verify
        expected_path = os.path.join(loguserdata.VAR_PATH, 'cfn-userdata')
        mock_chmod.assert_called_once_with(expected_path, int('700', 8))
        self.assertEqual(10, return_code)

    @mock.patch('pkg_resources.get_distribution')
    def test_main_failed_ci_version(self, mock_get):
        # Setup
        mock_get.return_value = FakeCiVersion('0.0.0')

        # Test
        return_code = loguserdata.main()

        # Verify
        self.assertEqual(-1, return_code)
