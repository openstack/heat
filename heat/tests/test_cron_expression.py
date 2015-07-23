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

from heat.engine.constraint.common import cron_expression as ce
from heat.tests import common
from heat.tests import utils


class CRONExpressionConstraint(common.HeatTestCase):

    def setUp(self):
        super(CRONExpressionConstraint, self).setUp()
        self.ctx = utils.dummy_context()
        self.constraint = ce.CRONExpressionConstraint()

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
