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

from glanceclient import exc
import mock

from heat.engine.clients import client_exception as exception
from heat.engine.clients.os import glance
from heat.tests import common
from heat.tests import utils


class GlanceUtilsTest(common.HeatTestCase):
    """Basic tests for :module:'heat.engine.resources.clients.os.glance'."""

    def setUp(self):
        super(GlanceUtilsTest, self).setUp()
        self.glance_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.glance_plugin = c.client_plugin('glance')
        self.glance_plugin.client = lambda: self.glance_client
        self.my_image = mock.MagicMock()

    def test_find_image_by_name_or_id(self):
        """Tests the find_image_by_name_or_id function."""
        img_id = str(uuid.uuid4())
        img_name = 'myfakeimage'
        self.my_image.id = img_id
        self.my_image.name = img_name
        self.glance_client.images.get.side_effect = [
            self.my_image,
            exc.HTTPNotFound(),
            exc.HTTPNotFound(),
            exc.HTTPNotFound()]
        self.glance_client.images.list.side_effect = [
            [self.my_image],
            [],
            [self.my_image, self.my_image]]
        self.assertEqual(img_id,
                         self.glance_plugin.find_image_by_name_or_id(img_id))
        self.assertEqual(img_id,
                         self.glance_plugin.find_image_by_name_or_id(img_name))
        self.assertRaises(exception.EntityMatchNotFound,
                          self.glance_plugin.find_image_by_name_or_id,
                          'noimage')
        self.assertRaises(exception.EntityUniqueMatchNotFound,
                          self.glance_plugin.find_image_by_name_or_id,
                          'myfakeimage')


class ImageConstraintTest(common.HeatTestCase):

    def setUp(self):
        super(ImageConstraintTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_find_image = mock.Mock()
        self.ctx.clients.client_plugin(
            'glance').find_image_by_name_or_id = self.mock_find_image
        self.constraint = glance.ImageConstraint()

    def test_validation(self):
        self.mock_find_image.side_effect = [
            "id1", exception.EntityMatchNotFound(),
            exception.EntityUniqueMatchNotFound()]
        self.assertTrue(self.constraint.validate("foo", self.ctx))
        self.assertFalse(self.constraint.validate("bar", self.ctx))
        self.assertFalse(self.constraint.validate("baz", self.ctx))
