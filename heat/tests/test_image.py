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
from heat.engine import clients
from heat.engine.resources import image
from heat.engine.resources import nova_utils

from heat.tests.common import HeatTestCase


class ImageConstraintTest(HeatTestCase):

    @mock.patch.object(nova_utils, 'get_image_id')
    def test_validation(self, mock_get_image):
        with mock.patch.object(clients, "OpenStackClients"):
            constraint = image.ImageConstraint()
            mock_get_image.return_value = "id1"
            self.assertTrue(constraint.validate("foo", None))

    @mock.patch.object(nova_utils, 'get_image_id')
    def test_validation_error(self, mock_get_image):
        with mock.patch.object(clients, "OpenStackClients"):
            constraint = image.ImageConstraint()
            mock_get_image.side_effect = exception.ImageNotFound(
                image_name='bar')
            self.assertFalse(constraint.validate("bar", None))
