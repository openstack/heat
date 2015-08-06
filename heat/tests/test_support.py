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

import six

from heat.engine import support
from heat.tests import common


class SupportStatusTest(common.HeatTestCase):
    def test_valid_status(self):
        for sstatus in support.SUPPORT_STATUSES:
            previous = support.SupportStatus(version='test_version')
            status = support.SupportStatus(
                status=sstatus,
                message='test_message',
                version='test_version',
                previous_status=previous,
            )
            self.assertEqual(sstatus, status.status)
            self.assertEqual('test_message', status.message)
            self.assertEqual('test_version', status.version)
            self.assertEqual(previous, status.previous_status)
            self.assertEqual({
                'status': sstatus,
                'message': 'test_message',
                'version': 'test_version',
                'previous_status': {'status': 'SUPPORTED',
                                    'message': None,
                                    'version': 'test_version',
                                    'previous_status': None},
            }, status.to_dict())

    def test_invalid_status(self):
        status = support.SupportStatus(
            status='RANDOM',
            message='test_message',
            version='test_version',
            previous_status=support.SupportStatus()
        )
        self.assertEqual(support.UNKNOWN, status.status)
        self.assertEqual('Specified status is invalid, defaulting to UNKNOWN',
                         status.message)
        self.assertIsNone(status.version)
        self.assertIsNone(status.previous_status)
        self.assertEqual({
            'status': 'UNKNOWN',
            'message': 'Specified status is invalid, defaulting to UNKNOWN',
            'version': None,
            'previous_status': None,
        }, status.to_dict())

    def test_previous_status(self):
        sstatus = support.SupportStatus(
            status=support.DEPRECATED,
            version='5.0.0',
            previous_status=support.SupportStatus(
                status=support.SUPPORTED,
                version='2015.1'
            )
        )

        self.assertEqual(support.DEPRECATED, sstatus.status)
        self.assertEqual('5.0.0', sstatus.version)
        self.assertEqual(support.SUPPORTED, sstatus.previous_status.status)
        self.assertEqual('2015.1', sstatus.previous_status.version)

        self.assertEqual({'status': 'DEPRECATED',
                          'version': '5.0.0',
                          'message': None,
                          'previous_status': {'status': 'SUPPORTED',
                                              'version': '2015.1',
                                              'message': None,
                                              'previous_status': None}},
                         sstatus.to_dict())

    def test_invalid_previous_status(self):
        ex = self.assertRaises(ValueError,
                               support.SupportStatus, previous_status='YARRR')
        self.assertEqual('previous_status must be SupportStatus '
                         'instead of %s' % str, six.text_type(ex))
