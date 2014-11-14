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

import re

import six
from testtools.matchers import HasLength
from testtools.matchers import MatchesRegex

from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources.random_string import RandomString
from heat.engine import template
from heat.tests.common import HeatTestCase
from heat.tests import utils


class TestRandomString(HeatTestCase):

    template_random_string = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret1:
    Type: OS::Heat::RandomString
  secret2:
    Type: OS::Heat::RandomString
    Properties:
      length: 10
  secret3:
    Type: OS::Heat::RandomString
    Properties:
      length: 100
      sequence: octdigits
  secret4:
    Type: OS::Heat::RandomString
    Properties:
      length: 32
      character_classes:
        - class: digits
          min: 1
        - class: uppercase
          min: 1
        - class: lowercase
          min: 20
      character_sequences:
        - sequence: (),[]{}
          min: 1
        - sequence: $_
          min: 2
        - sequence: '@'
          min: 5
  secret5:
    Type: OS::Heat::RandomString
    Properties:
      length: 25
      character_classes:
        - class: digits
          min: 1
        - class: uppercase
          min: 1
        - class: lowercase
          min: 20
  secret6:
    Type: OS::Heat::RandomString
    Properties:
      length: 10
      character_sequences:
        - sequence: (),[]{}
          min: 1
        - sequence: $_
          min: 2
        - sequence: '@'
          min: 5
'''

    def setUp(self):
        super(TestRandomString, self).setUp()
        self.ctx = utils.dummy_context()

    def create_stack(self, templ):
        self.stack = self.parse_stack(template_format.parse(templ))
        self.assertIsNone(self.stack.create())
        return self.stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.validate()
        stack.store()
        return stack

    def test_random_string(self):
        stack = self.create_stack(self.template_random_string)
        secret1 = stack['secret1']

        def assert_min(pattern, string, minimum):
            self.assertTrue(len(re.findall(pattern, string)) >= minimum)

        random_string = secret1.FnGetAtt('value')
        assert_min('[a-zA-Z0-9]', random_string, 32)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          secret1.FnGetAtt, 'foo')
        self.assertEqual(random_string, secret1.FnGetRefId())

        secret2 = stack['secret2']
        random_string = secret2.FnGetAtt('value')
        assert_min('[a-zA-Z0-9]', random_string, 10)
        self.assertEqual(random_string, secret2.FnGetRefId())

        secret3 = stack['secret3']
        random_string = secret3.FnGetAtt('value')
        assert_min('[0-7]', random_string, 100)
        self.assertEqual(random_string, secret3.FnGetRefId())

        secret4 = stack['secret4']
        random_string = secret4.FnGetAtt('value')
        self.assertEqual(len(random_string), 32)
        assert_min('[0-9]', random_string, 1)
        assert_min('[A-Z]', random_string, 1)
        assert_min('[a-z]', random_string, 20)
        assert_min('[(),\[\]{}]', random_string, 1)
        assert_min('[$_]', random_string, 2)
        assert_min('@', random_string, 5)
        self.assertEqual(random_string, secret4.FnGetRefId())

        secret5 = stack['secret5']
        random_string = secret5.FnGetAtt('value')
        self.assertEqual(len(random_string), 25)
        assert_min('[0-9]', random_string, 1)
        assert_min('[A-Z]', random_string, 1)
        assert_min('[a-z]', random_string, 20)
        self.assertEqual(random_string, secret5.FnGetRefId())

        secret6 = stack['secret6']
        random_string = secret6.FnGetAtt('value')
        self.assertEqual(len(random_string), 10)
        assert_min('[(),\[\]{}]', random_string, 1)
        assert_min('[$_]', random_string, 2)
        assert_min('@', random_string, 5)
        self.assertEqual(random_string, secret6.FnGetRefId())

    def test_invalid_property_combination(self):
        template_random_string = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 32
      sequence: octdigits
      character_classes:
        - class: digits
          min: 1
      character_sequences:
        - sequence: (),[]{}
          min: 1
'''
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.create_stack, template_random_string)
        self.assertEqual("Cannot use deprecated 'sequence' property along "
                         "with 'character_sequences' or 'character_classes' "
                         "properties", six.text_type(exc))

    def test_invalid_length(self):
        template_random_string = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 5
      character_classes:
        - class: digits
          min: 5
      character_sequences:
        - sequence: (),[]{}
          min: 1
'''
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.create_stack, template_random_string)
        self.assertEqual("Length property cannot be smaller than combined "
                         "character class and character sequence minimums",
                         six.text_type(exc))

    def test_exceeds_max_length(self):
        template_random_string = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 513
'''
        exc = self.assertRaises(exception.StackValidationFailed,
                                self.create_stack, template_random_string)
        self.assertIn('length 513 is out of range (min: 1, max: 512)',
                      six.text_type(exc))


class TestGenerateRandomString(HeatTestCase):

    scenarios = [
        ('lettersdigits', dict(
            length=1, seq='lettersdigits', pattern='[a-zA-Z0-9]')),
        ('letters', dict(
            length=10, seq='letters', pattern='[a-zA-Z]')),
        ('lowercase', dict(
            length=100, seq='lowercase', pattern='[a-z]')),
        ('uppercase', dict(
            length=50, seq='uppercase', pattern='[A-Z]')),
        ('digits', dict(
            length=512, seq='digits', pattern='[0-9]')),
        ('hexdigits', dict(
            length=16, seq='hexdigits', pattern='[A-F0-9]')),
        ('octdigits', dict(
            length=32, seq='octdigits', pattern='[0-7]'))
    ]

    def test_generate_random_string(self):
        # run each test multiple times to confirm random generator
        # doesn't generate a matching pattern by chance
        for i in range(1, 32):
            sequence = RandomString._sequences[self.seq]
            r = RandomString._deprecated_random_string(sequence, self.length)

            self.assertThat(r, HasLength(self.length))
            regex = '%s{%s}' % (self.pattern, self.length)
            self.assertThat(r, MatchesRegex(regex))
