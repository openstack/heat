
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

from testtools.matchers import HasLength
from testtools.matchers import MatchesRegex

from heat.common import exception
from heat.common import template_format
from heat.engine import parser
from heat.engine.resources.random_string import RandomString

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
'''

    def setUp(self):
        super(HeatTestCase, self).setUp()
        utils.setup_dummy_db()
        self.ctx = utils.dummy_context()

    def create_stack(self, template):
        t = template_format.parse(template)
        self.stack = self.parse_stack(t)
        self.assertIsNone(self.stack.create())
        return self.stack

    def parse_stack(self, t):
        stack_name = 'test_stack'
        tmpl = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(), stack_name, tmpl)
        stack.validate()
        stack.store()
        return stack

    def test_random_string(self):
        stack = self.create_stack(self.template_random_string)
        secret1 = stack['secret1']

        random_string = secret1.FnGetAtt('value')
        self.assertThat(random_string, MatchesRegex('[a-zA-Z0-9]{32}'))
        self.assertRaises(exception.InvalidTemplateAttribute,
                          secret1.FnGetAtt, 'foo')
        self.assertEqual(random_string, secret1.FnGetRefId())

        secret2 = stack['secret2']
        random_string = secret2.FnGetAtt('value')
        self.assertThat(random_string, MatchesRegex('[a-zA-Z0-9]{10}'))
        self.assertEqual(random_string, secret2.FnGetRefId())

        secret3 = stack['secret3']
        random_string = secret3.FnGetAtt('value')
        self.assertThat(random_string, MatchesRegex('[0-7]{100}'))
        self.assertEqual(random_string, secret3.FnGetRefId())


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
            r = RandomString._generate_random_string(sequence, self.length)

            self.assertThat(r, HasLength(self.length))
            regex = '%s{%s}' % (self.pattern, self.length)
            self.assertThat(r, MatchesRegex(regex))
