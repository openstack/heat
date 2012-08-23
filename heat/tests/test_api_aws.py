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


import sys
import socket
import nose
import json
import unittest
from nose.plugins.attrib import attr

import re
from heat.api.aws import utils as api_utils


@attr(tag=['unit', 'api-aws', 'AWSCommon'])
@attr(speed='fast')
class AWSCommon(unittest.TestCase):
    '''
    Tests the api/aws common componenents
    '''
    # The tests
    def test_format_response(self):
        response = api_utils.format_response("Foo", "Bar")
        expected = {'FooResponse': {'FooResult': 'Bar'}}
        self.assert_(response == expected)

    def test_params_extract(self):
        p = {'Parameters.member.Foo.ParameterKey': 'foo',
             'Parameters.member.Foo.ParameterValue': 'bar',
             'Parameters.member.Blarg.ParameterKey': 'blarg',
             'Parameters.member.Blarg.ParameterValue': 'wibble'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                              keyname='ParameterKey',
                                              valuename='ParameterValue')
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
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                              keyname='ParameterKey',
                                              valuename='ParameterValue')
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
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                              keyname='ParameterKey',
                                              valuename='ParameterValue')
        self.assertEqual(len(params), 1)
        self.assertTrue('foo' in params)
        self.assertEqual(params['foo'], 'bar')

    def test_params_extract_garbage_prefix(self):
        p = {'prefixParameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                              keyname='ParameterKey',
                                              valuename='ParameterValue')
        self.assertFalse(params)

    def test_params_extract_garbage_suffix(self):
        p = {'Parameters.member.Foo.Bar.ParameterKeysuffix': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                              keyname='ParameterKey',
                                              valuename='ParameterValue')
        self.assertFalse(params)

    def test_reformat_dict_keys(self):
        keymap = {"foo": "bar"}
        data = {"foo": 123}
        expected = {"bar": 123}
        result = api_utils.reformat_dict_keys(keymap, data)
        self.assertEqual(result, expected)

    def setUp(self):
        print "setup complete"

    def tearDown(self):
        print "teardown complete"


if __name__ == '__main__':
    sys.argv.append(__file__)
    nose.main()
