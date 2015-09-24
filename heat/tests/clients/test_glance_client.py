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

import uuid

from glanceclient import exc as glance_exceptions
import mock
import six

from heat.common import exception
from heat.engine.clients.os import glance
from heat.tests import common
from heat.tests import utils


class GlanceUtilsTests(common.HeatTestCase):
    """Basic tests for :module:'heat.engine.resources.clients.os.glance'."""

    def setUp(self):
        super(GlanceUtilsTests, self).setUp()
        self.glance_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.glance_plugin = c.client_plugin('glance')
        self.glance_plugin._client = self.glance_client
        self.my_image = mock.MagicMock()

    def test_get_image_id(self):
        """Tests the get_image_id function."""
        img_id = str(uuid.uuid4())
        img_name = 'myfakeimage'
        self.my_image.id = img_id
        self.my_image.name = img_name
        self.glance_client.images.get.return_value = self.my_image
        self.glance_client.images.list.side_effect = ([self.my_image], [])
        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_id))
        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_name))
        self.assertRaises(exception.EntityNotFound,
                          self.glance_plugin.get_image_id, 'noimage')

        calls = [mock.call(filters={'name': img_name}),
                 mock.call(filters={'name': 'noimage'})]
        self.glance_client.images.get.assert_called_once_with(img_id)
        self.glance_client.images.list.assert_has_calls(calls)

    def test_get_image_id_by_name_in_uuid(self):
        """Tests the get_image_id function by name in uuid."""
        img_id = str(uuid.uuid4())
        img_name = str(uuid.uuid4())
        self.my_image.id = img_id
        self.my_image.name = img_name
        self.glance_client.images.get.side_effect = [
            glance_exceptions.HTTPNotFound()]
        self.glance_client.images.list.return_value = [self.my_image]

        self.assertEqual(img_id, self.glance_plugin.get_image_id(img_name))
        self.glance_client.images.get.assert_called_once_with(img_name)
        self.glance_client.images.list.assert_called_once_with(
            filters={'name': img_name})

    def test_get_image_id_glance_exception(self):
        """Test get_image_id when glance raises an exception."""
        # Simulate HTTP exception
        img_name = str(uuid.uuid4())
        self.glance_client.images.list.side_effect = [
            glance_exceptions.ClientException("Error")]

        expected_error = "Error retrieving image list from glance: Error"
        e = self.assertRaises(exception.Error,
                              self.glance_plugin.get_image_id_by_name,
                              img_name)
        self.assertEqual(expected_error, six.text_type(e))
        self.glance_client.images.list.assert_called_once_with(
            filters={'name': img_name})

    def test_get_image_id_not_found(self):
        """Tests the get_image_id function while image is not found."""
        img_name = str(uuid.uuid4())
        self.glance_client.images.get.side_effect = [
            glance_exceptions.HTTPNotFound()]
        self.glance_client.images.list.return_value = []

        self.assertRaises(exception.EntityNotFound,
                          self.glance_plugin.get_image_id, img_name)
        self.glance_client.images.get.assert_called_once_with(img_name)
        self.glance_client.images.list.assert_called_once_with(
            filters={'name': img_name})

    def test_get_image_id_name_ambiguity(self):
        """Tests the get_image_id function while name ambiguity ."""
        img_name = 'ambiguity_name'
        self.my_image.name = img_name

        self.glance_client.images.list.return_value = [self.my_image,
                                                       self.my_image]
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          self.glance_plugin.get_image_id, img_name)
        self.glance_client.images.list.assert_called_once_with(
            filters={'name': img_name})


class ImageConstraintTest(common.HeatTestCase):

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
        self.mock_get_image.side_effect = exception.EntityNotFound(
            entity='Image', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))
