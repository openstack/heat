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


from heat.tests.common import HeatTestCase
import heat.engine.api as api


class EngineApiTest(HeatTestCase):
    def test_timeout_extract(self):
        p = {'timeout_mins': '5'}
        args = api.extract_args(p)
        self.assertEqual(args['timeout_mins'], 5)

    def test_timeout_extract_zero(self):
        p = {'timeout_mins': '0'}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_garbage(self):
        p = {'timeout_mins': 'wibble'}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_none(self):
        p = {'timeout_mins': None}
        args = api.extract_args(p)
        self.assertTrue('timeout_mins' not in args)

    def test_timeout_extract_not_present(self):
        args = api.extract_args({})
        self.assertTrue('timeout_mins' not in args)

    def test_disable_rollback_extract_true(self):
        args = api.extract_args({'disable_rollback': True})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'True'})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'true'})
        self.assertTrue('disable_rollback' in args)
        self.assertTrue(args.get('disable_rollback'))

    def test_disable_rollback_extract_false(self):
        args = api.extract_args({'disable_rollback': False})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'False'})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

        args = api.extract_args({'disable_rollback': 'false'})
        self.assertTrue('disable_rollback' in args)
        self.assertFalse(args.get('disable_rollback'))

    def test_disable_rollback_extract_bad(self):
        self.assertRaises(ValueError, api.extract_args,
                          {'disable_rollback': 'bad'})
