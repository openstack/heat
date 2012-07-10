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


import nose
import unittest
from nose.plugins.attrib import attr

from heat.common.config import HeatConfigOpts
import heat.api.v1.stacks as stacks


@attr(tag=['unit', 'api-v1-stacks', 'StackController'])
@attr(speed='fast')
class StackControllerTest(unittest.TestCase):
    '''
    Tests the API class which acts as the WSGI controller,
    the endpoint processing API requests after they are routed
    '''
    def test_params_extract(self):
        p = {'Parameters.member.Foo.ParameterKey': 'foo',
             'Parameters.member.Foo.ParameterValue': 'bar',
             'Parameters.member.Blarg.ParameterKey': 'blarg',
             'Parameters.member.Blarg.ParameterValue': 'wibble'}
        params = self.controller._extract_user_params(p)
        self.assertEqual(len(params), 2)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')
        self.assertTrue('blarg' in params)
        self.assertEqual(params['blarg'], 'wibble')

    def test_params_extract_dots(self):
        p = {'Parameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar',
             'Parameters.member.Foo.Baz.ParameterKey': 'blarg',
             'Parameters.member.Foo.Baz.ParameterValue': 'wibble'}
        params = self.controller._extract_user_params(p)
        self.assertEqual(len(params), 2)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')
        self.assertTrue('blarg' in params)
        self.assertEqual(params['blarg'], 'wibble')

    def test_params_extract_garbage(self):
        p = {'Parameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar',
             'Foo.Baz.ParameterKey': 'blarg',
             'Foo.Baz.ParameterValue': 'wibble'}
        params = self.controller._extract_user_params(p)
        self.assertEqual(len(params), 1)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')

    def test_params_extract_garbage_prefix(self):
        p = {'prefixParameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = self.controller._extract_user_params(p)
        self.assertFalse(params)

    def test_params_extract_garbage_suffix(self):
        p = {'Parameters.member.Foo.Bar.ParameterKeysuffix': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = self.controller._extract_user_params(p)
        self.assertFalse(params)

    # TODO : lots more StackController tests..

    def setUp(self):
        # Create WSGI controller instance
        options = HeatConfigOpts()
        self.controller = stacks.StackController(options)
        print "setup complete"

    def tearDown(self):
        print "teardown complete"


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
