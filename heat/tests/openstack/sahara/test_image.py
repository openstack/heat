#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import sahara
from heat.engine.resources.openstack.sahara import image
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


sahara_image_template = """
heat_template_version: 2015-10-15
resources:
  sahara-image:
    type: OS::Sahara::ImageRegistry
    properties:
      image: sahara-icehouse-vanilla-1.2.1-ubuntu-13.10
      username: ubuntu
      tags:
        - vanilla
        - 1.2.1
"""


class SaharaImageTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaImageTest, self).setUp()
        self.tmpl = template_format.parse(sahara_image_template)
        self.stack = utils.parse_stack(self.tmpl)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['sahara-image']
        self.client = mock.Mock()
        self.patchobject(image.SaharaImageRegistry, 'client',
                         return_value=self.client)
        self.patchobject(glance.GlanceClientPlugin,
                         'find_image_by_name_or_id',
                         return_value='12345')

    def _create_resource(self, name, snippet, stack):
        img = image.SaharaImageRegistry(name, snippet, stack)
        scheduler.TaskRunner(img.create)()
        return img

    def test_create(self):
        img = self._create_resource('sahara-image', self.rsrc_defn, self.stack)
        args = ('12345', 'ubuntu', '')
        self.client.images.update_image.assert_called_once_with(*args)
        self.client.images.update_tags.assert_called_once_with(
            '12345', ['vanilla', '1.2.1'])
        self.assertEqual('12345', img.resource_id)
        expected_state = (img.CREATE, img.COMPLETE)
        self.assertEqual(expected_state, img.state)

    def test_update(self):
        img = self._create_resource('sahara-image', self.rsrc_defn, self.stack)
        props = self.tmpl['resources']['sahara-image']['properties'].copy()
        props['tags'] = []
        props['description'] = 'test image'
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(img.update, self.rsrc_defn)()
        tags_update_calls = [
            mock.call('12345', ['vanilla', '1.2.1']),
            mock.call('12345', [])
        ]
        image_update_calls = [
            mock.call('12345', 'ubuntu', ''),
            mock.call('12345', 'ubuntu', 'test image')
        ]
        self.client.images.update_image.assert_has_calls(image_update_calls)
        self.client.images.update_tags.assert_has_calls(tags_update_calls)
        self.assertEqual((img.UPDATE, img.COMPLETE), img.state)

    def test_delete(self):
        img = self._create_resource('sahara-image', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(img.delete)()
        self.assertEqual((img.DELETE, img.COMPLETE), img.state)
        self.client.images.unregister_image.assert_called_once_with(
            img.resource_id)

    def test_delete_not_found(self):
        img = self._create_resource('sahara-image', self.rsrc_defn, self.stack)
        self.client.images.unregister_image.side_effect = (
            sahara.sahara_base.APIException(error_code=404))
        scheduler.TaskRunner(img.delete)()
        self.assertEqual((img.DELETE, img.COMPLETE), img.state)
        self.client.images.unregister_image.assert_called_once_with(
            img.resource_id)

    def test_show_attribute(self):
        img = self._create_resource('sahara-image', self.rsrc_defn, self.stack)
        value = mock.MagicMock()
        value.to_dict.return_value = {'img': 'info'}
        self.client.images.get.return_value = value
        self.assertEqual({'img': 'info'}, img.FnGetAtt('show'))
