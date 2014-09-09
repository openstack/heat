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

import fixtures
from oslotest import mockpatch
import six
from stevedore import extension

from heat.common import exception
from heat.common import template_format
from heat.engine import function
from heat.engine import template
from heat.tests import common


class TemplatePluginFixture(fixtures.Fixture):
    def __init__(self, templates={}):
        super(TemplatePluginFixture, self).__init__()
        self.templates = [extension.Extension(k, None, v, None)
                          for (k, v) in templates.items()]

    def _get_template_extension_manager(self):
        return extension.ExtensionManager.make_test_instance(self.templates)

    def setUp(self):
        super(TemplatePluginFixture, self).setUp()

        def clear_template_classes():
            template._template_classes = None

        clear_template_classes()
        self.useFixture(mockpatch.PatchObject(
            template,
            '_get_template_extension_manager',
            new=self._get_template_extension_manager))
        self.addCleanup(clear_template_classes)


class TestTemplatePluginManager(common.HeatTestCase):
    def test_template_NEW_good(self):
        class NewTemplate(template.Template):
            SECTIONS = (VERSION, MAPPINGS) = ('NEWTemplateFormatVersion',
                                              '__undefined__')
            RESOURCES = 'thingies'

            def param_schemata(self):
                pass

            def parameters(self, stack_identifier, user_params):
                pass

            def resource_definitions(self, stack):
                pass

            def add_resource(self, definition, name=None):
                pass

            def __getitem__(self, section):
                return {}

            def functions(self):
                return {}

        class NewTemplatePrint(function.Function):
            def result(self):
                return 'always this'

        self.useFixture(TemplatePluginFixture(
            {'NEWTemplateFormatVersion.2345-01-01': NewTemplate}))

        t = {'NEWTemplateFormatVersion': '2345-01-01'}
        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)


class TestTemplateVersion(common.HeatTestCase):

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
        ex = self.assertRaises(exception.InvalidTemplateVersion,
                               template.get_version, tmpl, self.versions)
        self.assertEqual('The template version is invalid: Template version '
                         'was not provided', six.text_type(ex))

    def test_ambiguous_version(self):
        tmpl = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'HeatTemplateFormatVersion': '2012-12-12',
            'foo': 'bar',
            'Parameters': {}
        }
        self.assertRaises(exception.InvalidTemplateVersion,
                          template.get_version, tmpl, self.versions)


class TestTemplateValidate(common.HeatTestCase):

    def test_template_validate_cfn_good(self):
        t = {
            'AWSTemplateFormatVersion': '2010-09-09',
            'Description': 'foo',
            'Parameters': {},
            'Mappings': {},
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
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
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
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
            'Resources': {
                'server': {
                    'Type': 'OS::Nova::Server'
                }
            },
            'Outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('Parameteers', six.text_type(err))

    def test_template_validate_cfn_empty(self):
        t = template_format.parse('''
AWSTemplateFormatVersion: 2010-09-09
Parameters:
Resources:
Outputs:
''')
        tmpl = template.Template(t)
        err = tmpl.validate()
        self.assertIsNone(err)

    def test_template_validate_hot_good(self):
        t = {
            'heat_template_version': '2013-05-23',
            'description': 'foo',
            'parameters': {},
            'resources': {
                'server': {
                    'type': 'OS::Nova::Server'
                }
            },
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
            'resources': {
                'server': {
                    'type': 'OS::Nova::Server'
                }
            },
            'outputs': {},
        }

        tmpl = template.Template(t)
        err = self.assertRaises(exception.InvalidTemplateSection,
                                tmpl.validate)
        self.assertIn('parameteers', six.text_type(err))
