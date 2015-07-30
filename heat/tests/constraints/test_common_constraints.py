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

from heat.engine.constraint import common_constraints as cc
from heat.tests import common


class TestIPConstraint(common.HeatTestCase):

    def setUp(self):
        super(TestIPConstraint, self).setUp()
        self.constraint = cc.IPConstraint()

    def test_validate_ipv4_format(self):
        validate_format = [
            '1.1.1.1',
            '1.0.1.1',
            '255.255.255.255'
        ]
        for ip in validate_format:
            self.assertTrue(self.constraint.validate(ip, None))

    def test_invalidate_ipv4_format(self):
        invalidate_format = [
            '1.1.1.',
            '1.1.1.256',
            'invalidate format',
            '1.a.1.1'
        ]
        for ip in invalidate_format:
            self.assertFalse(self.constraint.validate(ip, None))

    def test_validate_ipv6_format(self):
        validate_format = [
            '2002:2002::20c:29ff:fe7d:811a',
            '::1',
            '2002::',
            '2002::1',
        ]
        for ip in validate_format:
            self.assertTrue(self.constraint.validate(ip, None))

    def test_invalidate_ipv6_format(self):
        invalidate_format = [
            '2002::2001::1',
            '2002::g',
            'invalidate format',
            '2001::0::',
            '20c:29ff:fe7d:811a'
        ]
        for ip in invalidate_format:
            self.assertFalse(self.constraint.validate(ip, None))


class TestMACConstraint(common.HeatTestCase):

    def setUp(self):
        super(TestMACConstraint, self).setUp()
        self.constraint = cc.MACConstraint()

    def test_valid_mac_format(self):
        validate_format = [
            '01:23:45:67:89:ab',
            '01-23-45-67-89-ab',
            '0123.4567.89ab'
        ]
        for mac in validate_format:
            self.assertTrue(self.constraint.validate(mac, None))

    def test_invalid_mac_format(self):
        invalidate_format = [
            '8.8.8.8',
            '0a-1b-3c-4d-5e-6f-1f',
            '0a-1b-3c-4d-5e-xx'
        ]
        for mac in invalidate_format:
            self.assertFalse(self.constraint.validate(mac, None))


class TestCIDRConstraint(common.HeatTestCase):

    def setUp(self):
        super(TestCIDRConstraint, self).setUp()
        self.constraint = cc.CIDRConstraint()

    def test_valid_cidr_format(self):
        validate_format = [
            '10.0.0.0/24',
            '6000::/64',
            '8.8.8.8'
        ]
        for cidr in validate_format:
            self.assertTrue(self.constraint.validate(cidr, None))

    def test_invalid_cidr_format(self):
        invalidate_format = [
            '::/129',
            'Invalid cidr',
            '300.0.0.0/24',
            '10.0.0.0/33',
            '8.8.8.0/ 24'
        ]
        for cidr in invalidate_format:
            self.assertFalse(self.constraint.validate(cidr, None))


class TestISO8601Constraint(common.HeatTestCase):

    def setUp(self):
        super(TestISO8601Constraint, self).setUp()
        self.constraint = cc.ISO8601Constraint()

    def test_validate_date_format(self):
        date = '2050-01-01'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_datetime_format(self):
        self.assertTrue(self.constraint.validate('2050-01-01T23:59:59', None))

    def test_validate_datetime_format_with_utc_offset(self):
        date = '2050-01-01T23:59:59+00:00'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_datetime_format_with_utc_offset_alternate(self):
        date = '2050-01-01T23:59:59+0000'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validate_refuses_other_formats(self):
        self.assertFalse(self.constraint.validate('Fri 13th, 2050', None))
