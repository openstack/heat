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

from heat.common import exception
from heat.engine.clients.os import glance
from heat.tests.common import HeatTestCase
from heat.tests import utils


class ImageConstraintTest(HeatTestCase):

    def setUp(self):
        super(ImageConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get_image = mock.Mock()
        self.ctx.clients.client_plugin(
            'glance').get_image_id = self.mock_get_image
        self.constraint = glance.ImageConstraint()

    def test_validation(self):
        self.mock_get_image.return_value = "id1"
        self.assertTrue(self.constraint.validate("foo", self.ctx))

    def test_validation_error(self):
        self.mock_get_image.side_effect = exception.ImageNotFound(
            image_name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))
