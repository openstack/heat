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
import uuid

from glanceclient import exc as glance_exceptions

from heat.common import exception
from heat.tests.common import HeatTestCase
from heat.tests import utils


class GlanceUtilsTests(HeatTestCase):
    """
    Basic tests for the helper methods in
    :module:'heat.engine.resources.clients.os.glance'.
    """

    def setUp(self):
        super(GlanceUtilsTests, self).setUp()
        self.glance_client = self.m.CreateMockAnything()
        con = utils.dummy_context()
        c = con.clients
        self.glance_plugin = c.client_plugin('glance')
        self.glance_plugin._client = self.glance_client

    def test_get_image_id(self):
        """Tests the get_image_id function."""
        my_image = self.m.CreateMockAnything()
        img_id = str(uuid.uuid4())
        img_name = 'myfakeimage'
        my_image.id = img_id
        my_image.name = img_name
        self.glance_client.images = self.m.CreateMockAnything()
        self.glance_client.images.get(img_id).AndReturn(my_image)
        filters = {'name': img_name}
        self.glance_client.images.list(filters=filters).AndReturn([my_image])
        filters = {'name': 'noimage'}
        self.glance_client.images.list(filters=filters).AndReturn([])
        self.m.ReplayAll()
        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_id))
        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_name))
        self.assertRaises(exception.ImageNotFound,
                          self.glance_plugin.get_image_id, 'noimage')
        self.m.VerifyAll()

    def test_get_image_id_by_name_in_uuid(self):
        """Tests the get_image_id function by name in uuid."""
        my_image = self.m.CreateMockAnything()
        img_id = str(uuid.uuid4())
        img_name = str(uuid.uuid4())
        my_image.id = img_id
        my_image.name = img_name
        self.glance_client.images = self.m.CreateMockAnything()
        self.glance_client.images.get(img_name).AndRaise(
            glance_exceptions.HTTPNotFound())
        filters = {'name': img_name}
        self.glance_client.images.list(filters=filters).MultipleTimes().\
            AndReturn([my_image])
        self.m.ReplayAll()

        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_name))
        self.m.VerifyAll()

    def test_get_image_id_glance_exception(self):
        """Test get_image_id when glance raises an exception."""
        # Simulate HTTP exception
        self.glance_client.images = self.m.CreateMockAnything()
        img_name = str(uuid.uuid4())
        filters = {'name': img_name}
        self.glance_client.images.list(filters=filters).AndRaise(
            glance_exceptions.ClientException("Error"))
        self.m.ReplayAll()

        expected_error = "Error retrieving image list from glance: Error"
        e = self.assertRaises(exception.Error,
                              self.glance_plugin.get_image_id_by_name,
                              img_name)
        self.assertEqual(expected_error, six.text_type(e))
        self.m.VerifyAll()

    def test_get_image_id_not_found(self):
        """Tests the get_image_id function while image is not found."""
        my_image = self.m.CreateMockAnything()
        img_name = str(uuid.uuid4())
        my_image.name = img_name
        self.glance_client.images = self.m.CreateMockAnything()
        self.glance_client.images.get(img_name).AndRaise(
            glance_exceptions.HTTPNotFound())
        filters = {'name': img_name}
        self.glance_client.images.list(filters=filters).MultipleTimes().\
            AndReturn([])
        self.m.ReplayAll()

        self.assertRaises(exception.ImageNotFound,
                          self.glance_plugin.get_image_id, img_name)
        self.m.VerifyAll()

    def test_get_image_id_name_ambiguity(self):
        """Tests the get_image_id function while name ambiguity ."""
        my_image = self.m.CreateMockAnything()
        img_name = 'ambiguity_name'
        my_image.name = img_name
        image_list = [my_image, my_image]

        self.glance_client.images = self.m.CreateMockAnything()
        filters = {'name': img_name}
        self.glance_client.images.list(filters=filters).MultipleTimes().\
            AndReturn(image_list)
        self.m.ReplayAll()
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          self.glance_plugin.get_image_id, img_name)
        self.m.VerifyAll()
