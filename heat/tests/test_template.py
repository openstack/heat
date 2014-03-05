# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.tests.common import HeatTestCase

from heat.engine import plugin_manager
from heat.engine import template
from heat.engine.cfn.template import CfnTemplate


class TestTemplatePluginManager(HeatTestCase):

    def test_pkg_name(self):
        cfn_tmpl_pkg = template.TemplatePluginManager.package_name(CfnTemplate)
        self.assertEqual('heat.engine.cfn', cfn_tmpl_pkg)

    def test_get(self):

        tpm = template.TemplatePluginManager()

        self.assertFalse(tpm.plugin_managers)

        class Test(object):
            plugins = tpm

        test_pm = Test().plugins

        self.assertTrue(isinstance(test_pm, plugin_manager.PluginManager))
        self.assertEqual(tpm.plugin_managers['heat.tests'], test_pm)
