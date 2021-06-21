# Copyright (c) 2018 NEC, Corp.
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

from unittest import mock

from oslo_upgradecheck.upgradecheck import Code

from heat.cmd import status
from heat.tests import common


class TestUpgradeChecks(common.HeatTestCase):

    def setUp(self):
        super(TestUpgradeChecks, self).setUp()
        self.cmd = status.Checks()

    @mock.patch('oslo_utils.fileutils.is_json')
    def test_checks(self, mock_util):
        mock_util.return_value = False
        for name, func in self.cmd._upgrade_checks:
            if isinstance(func, tuple):
                func_name, kwargs = func
                result = func_name(self, **kwargs)
            else:
                result = func(self)
            self.assertEqual(Code.SUCCESS, result.code)
