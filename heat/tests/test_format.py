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

import json
import mox
import nose
from nose.plugins.attrib import attr
import os
import re
import unittest
import yaml

from heat.common import context
from heat.engine import format
from heat.engine import parser


@attr(tag=['unit'])
class JsonToYamlTest(unittest.TestCase):

    def setUp(self):
        self.expected_test_count = 10
        self.longMessage = True
        self.maxDiff = None

    def test_convert_all_templates(self):
        path = os.path.dirname(os.path.realpath(__file__)).\
            replace('heat/tests', 'templates')

        template_test_count = 0
        for (json_str,
            yml_str,
            file_name) in self.convert_all_json_to_yaml(path):

            self.compare_json_vs_yaml(json_str, yml_str, file_name)
            template_test_count += 1
            if template_test_count >= self.expected_test_count:
                break

        self.assertTrue(template_test_count >= self.expected_test_count,
            'Expected at least %d templates to be tested' %
            self.expected_test_count)

    def compare_json_vs_yaml(self, json_str, yml_str, file_name):
        yml = format.parse_to_template(yml_str)

        self.assertEqual(u'2012-12-12', yml[u'HeatTemplateFormatVersion'],
            file_name)
        self.assertFalse(u'AWSTemplateFormatVersion' in yml, file_name)
        del(yml[u'HeatTemplateFormatVersion'])

        jsn = format.parse_to_template(json_str)
        format.default_for_missing(jsn, 'AWSTemplateFormatVersion',
            format.CFN_VERSIONS)

        if u'AWSTemplateFormatVersion' in jsn:
            del(jsn[u'AWSTemplateFormatVersion'])

        self.assertEqual(yml, jsn, file_name)

    def convert_all_json_to_yaml(self, dirpath):
        for path in os.listdir(dirpath):
            if not path.endswith('.template') and not path.endswith('.json'):
                continue
            f = open(os.path.join(dirpath, path), 'r')
            json_str = f.read()

            yml_str = format.convert_json_to_yaml(json_str)
            yield (json_str, yml_str, f.name)


@attr(tag=['unit'])
class YamlMinimalTest(unittest.TestCase):

    def test_minimal_yaml(self):
        yaml1 = ''
        yaml2 = '''HeatTemplateFormatVersion: '2012-12-12'
Parameters: {}
Mappings: {}
Resources: {}
Outputs: {}
'''
        tpl1 = format.parse_to_template(yaml1)
        tpl2 = format.parse_to_template(yaml2)
        self.assertEqual(tpl1, tpl2)
