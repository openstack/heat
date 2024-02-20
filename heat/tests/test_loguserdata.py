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
from unittest import mock


from heat.cloudinit import loguserdata
from heat.tests import common


class LoguserdataTest(common.HeatTestCase):

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

    @mock.patch('os.chmod')
    @mock.patch('heat.cloudinit.loguserdata.call')
    def test_main(self, mock_call, mock_chmod):
        # Setup
        mock_call.return_value = 10

        # Test
        return_code = loguserdata.main()

        # Verify
        expected_path = os.path.join(loguserdata.VAR_PATH, 'cfn-userdata')
        mock_chmod.assert_called_once_with(expected_path, int('700', 8))
        self.assertEqual(10, return_code)
