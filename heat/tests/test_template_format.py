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

import os

import mock
import re
import six
import yaml

from heat.common import config
from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.tests import common
from heat.tests import utils


class JsonToYamlTest(common.HeatTestCase):

    def setUp(self):
        super(JsonToYamlTest, self).setUp()
        self.expected_test_count = 2
        self.longMessage = True
        self.maxDiff = None

    def test_convert_all_templates(self):
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'templates')

        template_test_count = 0
        for (json_str,
             yml_str) in self.convert_all_json_to_yaml(path):

            self.compare_json_vs_yaml(json_str, yml_str)
            template_test_count += 1
            if template_test_count >= self.expected_test_count:
                break

        self.assertGreaterEqual(
            template_test_count, self.expected_test_count,
            'Expected at least %d templates to be tested, not %d' %
            (self.expected_test_count, template_test_count))

    def compare_json_vs_yaml(self, json_str, yml_str):
        yml = template_format.parse(yml_str)

        self.assertEqual(u'2012-12-12', yml[u'HeatTemplateFormatVersion'])
        self.assertNotIn(u'AWSTemplateFormatVersion', yml)
        del(yml[u'HeatTemplateFormatVersion'])

        jsn = template_format.parse(json_str)

        if u'AWSTemplateFormatVersion' in jsn:
            del(jsn[u'AWSTemplateFormatVersion'])

        self.assertEqual(yml, jsn)

    def convert_all_json_to_yaml(self, dirpath):
        for path in os.listdir(dirpath):
            if not path.endswith('.template') and not path.endswith('.json'):
                continue
            with open(os.path.join(dirpath, path), 'r') as f:
                json_str = f.read()

            yml_str = template_format.convert_json_to_yaml(json_str)
            yield (json_str, yml_str)

    def test_integer_only_keys_get_translated_correctly(self):
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            'templates/WordPress_Single_Instance.template')
        with open(path, 'r') as f:
            json_str = f.read()
            yml_str = template_format.convert_json_to_yaml(json_str)
            match = re.search(r'[\s,{]\d+\s*:', yml_str)
            # Check that there are no matches of integer-only keys
            # lacking explicit quotes
            self.assertIsNone(match)


class YamlMinimalTest(common.HeatTestCase):

    def _parse_template(self, tmpl_str, msg_str):
        parse_ex = self.assertRaises(ValueError,
                                     template_format.parse,
                                     tmpl_str)
        self.assertIn(msg_str, six.text_type(parse_ex))

    def test_long_yaml(self):
        template = {'HeatTemplateFormatVersion': '2012-12-12'}
        config.cfg.CONF.set_override('max_template_size', 10)
        template['Resources'] = ['a'] * int(
            config.cfg.CONF.max_template_size / 3)
        limit = config.cfg.CONF.max_template_size
        long_yaml = yaml.safe_dump(template)
        self.assertGreater(len(long_yaml), limit)
        ex = self.assertRaises(exception.RequestLimitExceeded,
                               template_format.parse, long_yaml)
        msg = ('Request limit exceeded: Template size (%(actual_len)s '
               'bytes) exceeds maximum allowed size (%(limit)s bytes).') % {
                   'actual_len': len(str(long_yaml)),
                   'limit': config.cfg.CONF.max_template_size}
        self.assertEqual(msg, six.text_type(ex))

    def test_parse_no_version_format(self):
        yaml = ''
        self._parse_template(yaml, 'Template format version not found')
        yaml2 = '''Parameters: {}
Mappings: {}
Resources: {}
Outputs: {}
'''
        self._parse_template(yaml2, 'Template format version not found')

    def test_parse_string_template(self):
        tmpl_str = 'just string'
        msg = 'The template is not a JSON object or YAML mapping.'
        self._parse_template(tmpl_str, msg)

    def test_parse_invalid_yaml_and_json_template(self):
        tmpl_str = '{test'
        msg = 'line 1, column 1'
        self._parse_template(tmpl_str, msg)

    def test_parse_json_document(self):
        tmpl_str = '["foo" , "bar"]'
        msg = 'The template is not a JSON object or YAML mapping.'
        self._parse_template(tmpl_str, msg)

    def test_parse_empty_json_template(self):
        tmpl_str = '{}'
        msg = 'Template format version not found'
        self._parse_template(tmpl_str, msg)

    def test_parse_yaml_template(self):
        tmpl_str = 'heat_template_version: 2013-05-23'
        expected = {'heat_template_version': '2013-05-23'}
        self.assertEqual(expected, template_format.parse(tmpl_str))


class YamlParseExceptions(common.HeatTestCase):

    scenarios = [
        ('scanner', dict(raised_exception=yaml.scanner.ScannerError())),
        ('parser', dict(raised_exception=yaml.parser.ParserError())),
        ('reader',
         dict(raised_exception=yaml.reader.ReaderError(
             '', 42, six.b('x'), '', ''))),
    ]

    def test_parse_to_value_exception(self):
        text = 'not important'

        with mock.patch.object(yaml, 'load') as yaml_loader:
            yaml_loader.side_effect = self.raised_exception

            err = self.assertRaises(ValueError,
                                    template_format.parse, text,
                                    'file://test.yaml')

            self.assertIn('Error parsing template file://test.yaml',
                          six.text_type(err))


class JsonYamlResolvedCompareTest(common.HeatTestCase):

    def setUp(self):
        super(JsonYamlResolvedCompareTest, self).setUp()
        self.longMessage = True
        self.maxDiff = None

    def load_template(self, file_name):
        filepath = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                'templates', file_name)
        f = open(filepath)
        t = template_format.parse(f.read())
        f.close()
        return t

    def compare_stacks(self, json_file, yaml_file, parameters):
        t1 = self.load_template(json_file)
        t2 = self.load_template(yaml_file)
        del(t1[u'AWSTemplateFormatVersion'])
        t1[u'HeatTemplateFormatVersion'] = t2[u'HeatTemplateFormatVersion']
        stack1 = utils.parse_stack(t1, parameters)
        stack2 = utils.parse_stack(t2, parameters)

        # compare resources separately so that resolved static data
        # is compared
        t1nr = dict(stack1.t.t)
        del(t1nr['Resources'])

        t2nr = dict(stack2.t.t)
        del(t2nr['Resources'])
        self.assertEqual(t1nr, t2nr)

        self.assertEqual(set(stack1), set(stack2))
        for key in stack1:
            self.assertEqual(stack1[key].t, stack2[key].t)

    def test_neutron_resolved(self):
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.compare_stacks('Neutron.template', 'Neutron.yaml', {})

    def test_wordpress_resolved(self):
        self.compare_stacks('WordPress_Single_Instance.template',
                            'WordPress_Single_Instance.yaml',
                            {'KeyName': 'test'})
