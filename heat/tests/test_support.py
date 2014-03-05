
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

from heat.engine import support

from heat.tests.common import HeatTestCase


class SupportStatusTest(HeatTestCase):
    def test_valid_status(self):
        status = support.SupportStatus(
            status=support.DEPRECATED,
            message='test_message',
            version='test_version'
        )
        self.assertEqual('DEPRECATED', status.status)
        self.assertEqual('test_message', status.message)
        self.assertEqual('test_version', status.version)
        self.assertEqual({
            'status': 'DEPRECATED',
            'message': 'test_message',
            'version': 'test_version'
        }, status.to_dict())

    def test_invalid_status(self):
        status = support.SupportStatus(
            status='RANDOM',
            message='test_message',
            version='test_version'
        )
        self.assertEqual(support.UNKNOWN, status.status)
        self.assertEqual('Specified status is invalid, defaulting to UNKNOWN',
                         status.message)
        self.assertIsNone(status.version)
        self.assertEqual({
            'status': 'UNKNOWN',
            'message': 'Specified status is invalid, defaulting to UNKNOWN',
            'version': None
        }, status.to_dict())
