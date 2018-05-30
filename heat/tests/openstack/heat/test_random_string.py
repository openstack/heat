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

import mock
import six
from testtools import matchers

from heat.common import exception
from heat.common import template_format
from heat.engine import node_data
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class TestRandomString(common.HeatTestCase):

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
  secret4:
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
  secret5:
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

    def assert_min(self, pattern, string, minimum):
        self.assertGreaterEqual(len(re.findall(pattern, string)), minimum)

    def test_random_string(self):
        stack = self.create_stack(self.template_random_string)
        secret1 = stack['secret1']

        random_string = secret1.FnGetAtt('value')
        self.assert_min('[a-zA-Z0-9]', random_string, 32)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          secret1.FnGetAtt, 'foo')
        self.assertEqual(secret1.FnGetRefId(), random_string)

        secret2 = stack['secret2']
        random_string = secret2.FnGetAtt('value')
        self.assert_min('[a-zA-Z0-9]', random_string, 10)
        self.assertEqual(secret2.FnGetRefId(), random_string)

        secret3 = stack['secret3']
        random_string = secret3.FnGetAtt('value')
        self.assertEqual(32, len(random_string))
        self.assert_min('[0-9]', random_string, 1)
        self.assert_min('[A-Z]', random_string, 1)
        self.assert_min('[a-z]', random_string, 20)
        self.assert_min(r'[(),\[\]{}]', random_string, 1)
        self.assert_min('[$_]', random_string, 2)
        self.assert_min('@', random_string, 5)
        self.assertEqual(secret3.FnGetRefId(), random_string)

        secret4 = stack['secret4']
        random_string = secret4.FnGetAtt('value')
        self.assertEqual(25, len(random_string))
        self.assert_min('[0-9]', random_string, 1)
        self.assert_min('[A-Z]', random_string, 1)
        self.assert_min('[a-z]', random_string, 20)
        self.assertEqual(secret4.FnGetRefId(), random_string)

        secret5 = stack['secret5']
        random_string = secret5.FnGetAtt('value')
        self.assertEqual(10, len(random_string))
        self.assert_min(r'[(),\[\]{}]', random_string, 1)
        self.assert_min('[$_]', random_string, 2)
        self.assert_min('@', random_string, 5)
        self.assertEqual(secret5.FnGetRefId(), random_string)

        # Prove the name is returned before create sets the ID
        secret5.resource_id = None
        self.assertEqual('secret5', secret5.FnGetRefId())

    def test_hidden_sequence_property(self):
        hidden_prop_templ = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 100
      sequence: octdigits
        '''
        stack = self.create_stack(hidden_prop_templ)
        secret = stack['secret']
        random_string = secret.FnGetAtt('value')
        self.assert_min('[0-7]', random_string, 100)
        self.assertEqual(secret.FnGetRefId(), random_string)
        # check, that property was translated according to the TranslationRule
        self.assertIsNone(secret.properties['sequence'])
        expected = [{'class': u'octdigits', 'min': 1}]
        self.assertEqual(expected, secret.properties['character_classes'])

    def test_random_string_refid_convergence_cache_data(self):
        t = template_format.parse(self.template_random_string)
        cache_data = {'secret1': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'reference_id': 'xyz'
        })}
        stack = utils.parse_stack(t, cache_data=cache_data)
        rsrc = stack.defn['secret1']
        self.assertEqual('xyz', rsrc.FnGetRefId())

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

    def test_max_length(self):
        template_random_string = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 512
'''
        stack = self.create_stack(template_random_string)
        secret = stack['secret']
        random_string = secret.FnGetAtt('value')
        self.assertEqual(512, len(random_string))
        self.assertEqual(secret.FnGetRefId(), random_string)

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
        self.assertIn('513 is out of range (min: 1, max: 512)',
                      six.text_type(exc))


class TestGenerateRandomString(common.HeatTestCase):
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

    template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
'''

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = template.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.validate()
        stack.store()
        return stack

    # test was saved to test backward compatibility with old behavior
    def test_generate_random_string_backward_compatible(self):
        stack = self.parse_stack(template_format.parse(self.template_rs))
        secret = stack['secret']
        char_classes = secret.properties['character_classes']
        for char_cl in char_classes:
            char_cl['class'] = self.seq
        # run each test multiple times to confirm random generator
        # doesn't generate a matching pattern by chance
        for i in range(1, 32):
            r = secret._generate_random_string([], char_classes, self.length)

            self.assertThat(r, matchers.HasLength(self.length))
            regex = '%s{%s}' % (self.pattern, self.length)
            self.assertThat(r, matchers.MatchesRegex(regex))


class TestGenerateRandomStringDistribution(common.HeatTestCase):
    def run_test(self, tmpl, iterations=5):
        stack = utils.parse_stack(template_format.parse(tmpl))
        secret = stack['secret']
        secret.data_set = mock.Mock()

        for i in range(iterations):
            secret.handle_create()

        return [call[1][1] for call in secret.data_set.mock_calls]

    def char_counts(self, random_strings, char):
        return [rs.count(char) for rs in random_strings]

    def check_stats(self, char_counts, expected_mean, allowed_variance,
                    expected_minimum=0):
        mean = float(sum(char_counts)) / len(char_counts)
        self.assertLess(mean, expected_mean + allowed_variance)
        self.assertGreater(mean, max(0, expected_mean - allowed_variance))
        if expected_minimum:
            self.assertGreaterEqual(min(char_counts), expected_minimum)

    def test_class_uniformity(self):
        template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 66
      character_classes:
        - class: lettersdigits
      character_sequences:
        - sequence: "*$"
'''

        results = self.run_test(template_rs, 10)
        for char in '$*':
            self.check_stats(self.char_counts(results, char), 1.5, 2)

    def test_repeated_sequence(self):
        template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 40
      character_classes: []
      character_sequences:
        - sequence: "**********$*****************************"
'''

        results = self.run_test(template_rs)
        for char in '$*':
            self.check_stats(self.char_counts(results, char), 20, 6)

    def test_overlapping_classes(self):
        template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 624
      character_classes:
        - class: lettersdigits
        - class: digits
        - class: octdigits
        - class: hexdigits
'''

        results = self.run_test(template_rs, 20)
        self.check_stats(self.char_counts(results, '0'), 10.3, 3)

    def test_overlapping_sequences(self):
        template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 60
      character_classes: []
      character_sequences:
        - sequence: "01"
        - sequence: "02"
        - sequence: "03"
        - sequence: "04"
        - sequence: "05"
        - sequence: "06"
        - sequence: "07"
        - sequence: "08"
        - sequence: "09"
'''

        results = self.run_test(template_rs)
        self.check_stats(self.char_counts(results, '0'), 10, 5)

    def test_overlapping_class_sequence(self):
        template_rs = '''
HeatTemplateFormatVersion: '2012-12-12'
Resources:
  secret:
    Type: OS::Heat::RandomString
    Properties:
      length: 402
      character_classes:
        - class: octdigits
      character_sequences:
        - sequence: "0"
'''

        results = self.run_test(template_rs, 10)
        self.check_stats(self.char_counts(results, '0'), 51.125, 8, 1)
