# -*- coding: utf-8 -*-
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

import importlib.metadata as importlib_metadata
from unittest import mock

from heat.common import pluginutils
from heat.tests import common


class TestPluginUtil(common.HeatTestCase):

    def test_log_fail_msg(self):
        ep = importlib_metadata.EntryPoint(
            name=None, group=None,
            value='package.module:attr [extra1, extra2]')

        exc = Exception('Something went wrong')
        pluginutils.log_fail_msg(mock.Mock(), ep, exc)
        self.assertIn("Something went wrong", self.LOG.output)
