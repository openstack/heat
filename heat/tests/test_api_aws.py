
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


from heat.api.aws import utils as api_utils
from heat.tests.common import HeatTestCase


class AWSCommonTest(HeatTestCase):
    '''
    Tests the api/aws common componenents
    '''
    # The tests
    def test_format_response(self):
        response = api_utils.format_response("Foo", "Bar")
        expected = {'FooResponse': {'FooResult': 'Bar'}}
        self.assertEqual(expected, response)

    def test_params_extract(self):
        p = {'Parameters.member.1.ParameterKey': 'foo',
             'Parameters.member.1.ParameterValue': 'bar',
             'Parameters.member.2.ParameterKey': 'blarg',
             'Parameters.member.2.ParameterValue': 'wibble'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                               keyname='ParameterKey',
                                               valuename='ParameterValue')
        self.assertEqual(2, len(params))
        self.assertIn('foo', params)
        self.assertEqual('bar', params['foo'])
        self.assertIn('blarg', params)
        self.assertEqual('wibble', params['blarg'])

    def test_params_extract_dots(self):
        p = {'Parameters.member.1.1.ParameterKey': 'foo',
             'Parameters.member.1.1.ParameterValue': 'bar',
             'Parameters.member.2.1.ParameterKey': 'blarg',
             'Parameters.member.2.1.ParameterValue': 'wibble'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                               keyname='ParameterKey',
                                               valuename='ParameterValue')
        self.assertFalse(params)

    def test_params_extract_garbage(self):
        p = {'Parameters.member.1.ParameterKey': 'foo',
             'Parameters.member.1.ParameterValue': 'bar',
             'Foo.1.ParameterKey': 'blarg',
             'Foo.1.ParameterValue': 'wibble'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                               keyname='ParameterKey',
                                               valuename='ParameterValue')
        self.assertEqual(1, len(params))
        self.assertIn('foo', params)
        self.assertEqual('bar', params['foo'])

    def test_params_extract_garbage_prefix(self):
        p = {'prefixParameters.member.Foo.Bar.ParameterKey': 'foo',
             'Parameters.member.Foo.Bar.ParameterValue': 'bar'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                               keyname='ParameterKey',
                                               valuename='ParameterValue')
        self.assertFalse(params)

    def test_params_extract_garbage_suffix(self):
        p = {'Parameters.member.1.ParameterKeysuffix': 'foo',
             'Parameters.member.1.ParameterValue': 'bar'}
        params = api_utils.extract_param_pairs(p, prefix='Parameters',
                                               keyname='ParameterKey',
                                               valuename='ParameterValue')
        self.assertFalse(params)

    def test_extract_param_list(self):
        p = {'MetricData.member.1.MetricName': 'foo',
             'MetricData.member.1.Unit': 'Bytes',
             'MetricData.member.1.Value': 234333}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(1, len(params))
        self.assertIn('MetricName', params[0])
        self.assertIn('Unit', params[0])
        self.assertIn('Value', params[0])
        self.assertEqual('foo', params[0]['MetricName'])
        self.assertEqual('Bytes', params[0]['Unit'])
        self.assertEqual(234333, params[0]['Value'])

    def test_extract_param_list_garbage_prefix(self):
        p = {'AMetricData.member.1.MetricName': 'foo',
             'MetricData.member.1.Unit': 'Bytes',
             'MetricData.member.1.Value': 234333}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(1, len(params))
        self.assertNotIn('MetricName', params[0])
        self.assertIn('Unit', params[0])
        self.assertIn('Value', params[0])
        self.assertEqual('Bytes', params[0]['Unit'])
        self.assertEqual(234333, params[0]['Value'])

    def test_extract_param_list_garbage_prefix2(self):
        p = {'AMetricData.member.1.MetricName': 'foo',
             'BMetricData.member.1.Unit': 'Bytes',
             'CMetricData.member.1.Value': 234333}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(0, len(params))

    def test_extract_param_list_garbage_suffix(self):
        p = {'MetricData.member.1.AMetricName': 'foo',
             'MetricData.member.1.Unit': 'Bytes',
             'MetricData.member.1.Value': 234333}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(1, len(params))
        self.assertNotIn('MetricName', params[0])
        self.assertIn('Unit', params[0])
        self.assertIn('Value', params[0])
        self.assertEqual('Bytes', params[0]['Unit'])
        self.assertEqual(234333, params[0]['Value'])

    def test_extract_param_list_multiple(self):
        p = {'MetricData.member.1.MetricName': 'foo',
             'MetricData.member.1.Unit': 'Bytes',
             'MetricData.member.1.Value': 234333,
             'MetricData.member.2.MetricName': 'foo2',
             'MetricData.member.2.Unit': 'Bytes',
             'MetricData.member.2.Value': 12345}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(2, len(params))
        self.assertIn('MetricName', params[0])
        self.assertIn('MetricName', params[1])
        self.assertEqual('foo', params[0]['MetricName'])
        self.assertEqual('Bytes', params[0]['Unit'])
        self.assertEqual(234333, params[0]['Value'])
        self.assertEqual('foo2', params[1]['MetricName'])
        self.assertEqual('Bytes', params[1]['Unit'])
        self.assertEqual(12345, params[1]['Value'])

    def test_extract_param_list_multiple_missing(self):
        # Handle case where there is an empty list item
        p = {'MetricData.member.1.MetricName': 'foo',
             'MetricData.member.1.Unit': 'Bytes',
             'MetricData.member.1.Value': 234333,
             'MetricData.member.3.MetricName': 'foo2',
             'MetricData.member.3.Unit': 'Bytes',
             'MetricData.member.3.Value': 12345}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(2, len(params))
        self.assertIn('MetricName', params[0])
        self.assertIn('MetricName', params[1])
        self.assertEqual('foo', params[0]['MetricName'])
        self.assertEqual('Bytes', params[0]['Unit'])
        self.assertEqual(234333, params[0]['Value'])
        self.assertEqual('foo2', params[1]['MetricName'])
        self.assertEqual('Bytes', params[1]['Unit'])
        self.assertEqual(12345, params[1]['Value'])

    def test_extract_param_list_badindex(self):
        p = {'MetricData.member.xyz.MetricName': 'foo',
             'MetricData.member.$!&^.Unit': 'Bytes',
             'MetricData.member.+.Value': 234333,
             'MetricData.member.--.MetricName': 'foo2',
             'MetricData.member._3.Unit': 'Bytes',
             'MetricData.member.-1000.Value': 12345}
        params = api_utils.extract_param_list(p, prefix='MetricData')
        self.assertEqual(0, len(params))

    def test_reformat_dict_keys(self):
        keymap = {"foo": "bar"}
        data = {"foo": 123}
        expected = {"bar": 123}
        result = api_utils.reformat_dict_keys(keymap, data)
        self.assertEqual(expected, result)

    def test_reformat_dict_keys_missing(self):
        keymap = {"foo": "bar", "foo2": "bar2"}
        data = {"foo": 123}
        expected = {"bar": 123}
        result = api_utils.reformat_dict_keys(keymap, data)
        self.assertEqual(expected, result)
