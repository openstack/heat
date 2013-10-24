# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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


import fixtures

from heat.common import exception
from heat.tests import common


class TestException(exception.HeatException):
    msg_fmt = _("Testing message %(text)s")


class TestHeatException(common.HeatTestCase):

    def test_fatal_exception_error(self):
        self.useFixture(fixtures.MonkeyPatch(
            'heat.common.exception._FATAL_EXCEPTION_FORMAT_ERRORS',
            True))
        self.assertRaises(KeyError, TestException)
