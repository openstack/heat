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

import mock
import six

from heat.engine.constraint import common_constraints as cc
from heat.tests import common
from heat.tests import utils


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
            None,
            123,
            '1.1',
            '1.1.',
            '1.1.1',
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
        ]
        for cidr in validate_format:
            self.assertTrue(self.constraint.validate(cidr, None))

    def test_invalid_cidr_format(self):
        invalidate_format = [
            '::/129',
            'Invalid cidr',
            '300.0.0.0/24',
            '10.0.0.0/33',
            '10.0.0/24',
            '10.0/24',
            '10.0.a.10/24',
            '8.8.8.0/ 24',
            '8.8.8.8'
        ]
        for cidr in invalidate_format:
            self.assertFalse(self.constraint.validate(cidr, None))

    @mock.patch('neutron_lib.api.validators.validate_subnet')
    def test_validate(self, mock_validate_subnet):
        test_formats = [
            '10.0.0/24',
            '10.0/24',
        ]
        self.assertFalse(self.constraint.validate('10.0.0.0/33', None))

        for cidr in test_formats:
            self.assertFalse(self.constraint.validate(cidr, None))

        mock_validate_subnet.assert_any_call('10.0.0/24')
        mock_validate_subnet.assert_called_with('10.0/24')
        self.assertEqual(mock_validate_subnet.call_count, 2)


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


class CRONExpressionConstraint(common.HeatTestCase):

    def setUp(self):
        super(CRONExpressionConstraint, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.CRONExpressionConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("0 23 * * *", self.ctx))

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))

    def test_validation_out_of_range_error(self):
        cron_expression = "* * * * * 100"
        expect = ("Invalid CRON expression: [%s] "
                  "is not acceptable, out of range") % cron_expression
        self.assertFalse(self.constraint.validate(cron_expression, self.ctx))
        self.assertEqual(expect,
                         six.text_type(self.constraint._error_message))

    def test_validation_columns_length_error(self):
        cron_expression = "* *"
        expect = ("Invalid CRON expression: Exactly 5 "
                  "or 6 columns has to be specified for "
                  "iteratorexpression.")
        self.assertFalse(self.constraint.validate(cron_expression, self.ctx))
        self.assertEqual(expect,
                         six.text_type(self.constraint._error_message))


class TimezoneConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(TimezoneConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.TimezoneConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("Asia/Taipei", self.ctx))

    def test_validation_error(self):
        timezone = "wrong_timezone"
        expected = "Invalid timezone: '%s'" % timezone

        self.assertFalse(self.constraint.validate(timezone, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))


class DNSNameConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(DNSNameConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.DNSNameConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("openstack.org.", self.ctx))

    def test_validation_error_hyphen(self):
        dns_name = "-openstack.org"
        expected = ("'%s' not in valid format. Reason: Name "
                    "'%s' must not start or end with a "
                    "hyphen.") % (dns_name, dns_name.split('.')[0])

        self.assertFalse(self.constraint.validate(dns_name, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_error_empty_component(self):
        dns_name = ".openstack.org"
        expected = ("'%s' not in valid format. Reason: "
                    "Encountered an empty component.") % dns_name

        self.assertFalse(self.constraint.validate(dns_name, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_error_special_char(self):
        dns_name = "$openstack.org"
        expected = ("'%s' not in valid format. Reason: Name "
                    "'%s' must be 1-63 characters long, each "
                    "of which can only be alphanumeric or a "
                    "hyphen.") % (dns_name, dns_name.split('.')[0])

        self.assertFalse(self.constraint.validate(dns_name, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_error_tld_allnumeric(self):
        dns_name = "openstack.123."
        expected = ("'%s' not in valid format. Reason: TLD "
                    "'%s' must not be all numeric.") % (dns_name,
                                                        dns_name.split('.')[1])

        self.assertFalse(self.constraint.validate(dns_name, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))


class DNSDomainConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(DNSDomainConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.DNSDomainConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("openstack.org.", self.ctx))

    def test_validation_error_no_end_period(self):
        dns_domain = "openstack.org"
        expected = ("'%s' must end with '.'.") % dns_domain

        self.assertFalse(self.constraint.validate(dns_domain, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))


class FIPDNSNameConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(FIPDNSNameConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.RelativeDNSNameConstraint()

    def test_validation(self):
        self.assertTrue(self.constraint.validate("myvm.openstack", self.ctx))

    def test_validation_error_end_period(self):
        dns_name = "myvm.openstack."
        expected = ("'%s' is a FQDN. It should be a relative "
                    "domain name.") % dns_name
        self.assertFalse(self.constraint.validate(dns_name, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))


class ExpirationConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ExpirationConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = cc.ExpirationConstraint()

    def test_validate_date_format(self):
        date = '2050-01-01'
        self.assertTrue(self.constraint.validate(date, None))

    def test_validation_error(self):
        expiration = "Fri 13th, 2050"
        expected = ("Expiration {0} is invalid: Unable to parse "
                    "date string '{0}'".format(expiration))

        self.assertFalse(self.constraint.validate(expiration, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_before_current_time(self):
        expiration = "1970-01-01"
        expected = ("Expiration %s is invalid: Expiration time "
                    "is out of date." % expiration)

        self.assertFalse(self.constraint.validate(expiration, self.ctx))
        self.assertEqual(
            expected,
            six.text_type(self.constraint._error_message)
        )

    def test_validation_none(self):
        self.assertTrue(self.constraint.validate(None, self.ctx))
