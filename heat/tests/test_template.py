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

from heat.common import exception
from heat.engine.cfn.template import CfnTemplate
from heat.engine import plugin_manager
from heat.engine import template
from heat.tests.common import HeatTestCase


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


class TestTemplateVersion(HeatTestCase):

    versions = (('heat_template_version', '2013-05-23'),
                ('HeatTemplateFormatVersion', '2012-12-12'),
                ('AWSTemplateFormatVersion', '2010-09-09'))

    def test_hot_version(self):
        tmpl = {
            'heat_template_version': '2013-05-23',
            'foo': 'bar',
            'parameters': {}
        }
        self.assertEqual(('heat_template_version', '2013-05-23'),
                         template.get_version(tmpl, self.versions))

    def test_cfn_version(self):
        tmpl = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertEqual(('AWSTemplateFormatVersion', '2010-09-09'),
                         template.get_version(tmpl, self.versions))

    def test_heat_cfn_version(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertEqual(('HeatTemplateFormatVersion', '2012-12-12'),
                         template.get_version(tmpl, self.versions))

    def test_missing_version(self):
        tmpl = {
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertEqual(('HeatTemplateFormatVersion', '2012-12-12'),
                         template.get_version(tmpl, self.versions))

    def test_ambiguous_version(self):
        tmpl = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'HeatTemplateFormatVersion': '2012-12-12',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertRaises(exception.InvalidTemplateVersion,
                          template.get_version, tmpl, self.versions)


class TestTemplateValidate(HeatTestCase):

    def test_template_validate_cfn_good(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {},
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

        # test with alternate version key
        t = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {},
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_template_validate_cfn_bad_section(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameteers': {},
            'Mappings': {},
            'Resources': {},
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('Parameteers', str(err))

    def test_template_validate_hot_good(self):
        t = {
            'heat_template_version': '2013-05-23',
            'description': 'foo',
            'parameters': {},
            'resources': {},
            'outputs': {},
        }

        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_template_validate_hot_bad_section(self):
        t = {
            'heat_template_version': '2013-05-23',
            'description': 'foo',
            'parameteers': {},
            'resources': {},
            'outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('parameteers', str(err))
