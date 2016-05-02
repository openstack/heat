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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.resources.openstack.sahara import data_source
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


data_source_template = """
heat_template_version: 2015-10-15
resources:
  data-source:
    type: OS::Sahara::DataSource
    properties:
      name: my-ds
      type: swift
      url: swift://container.sahara/text
      credentials:
          user: admin
          password: swordfish
"""


class SaharaDataSourceTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaDataSourceTest, self).setUp()
        t = template_format.parse(data_source_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['data-source']
        self.client = mock.Mock()
        self.patchobject(data_source.DataSource, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        ds = data_source.DataSource(name, snippet, stack)
        value = mock.MagicMock(id='12345')
        self.client.data_sources.create.return_value = value
        scheduler.TaskRunner(ds.create)()
        return ds

    def test_create(self):
        ds = self._create_resource('data-source', self.rsrc_defn, self.stack)
        args = self.client.data_sources.create.call_args[1]
        expected_args = {
            'name': 'my-ds',
            'description': '',
            'data_source_type': 'swift',
            'url': 'swift://container.sahara/text',
            'credential_user': 'admin',
            'credential_pass': 'swordfish'
        }
        self.assertEqual(expected_args, args)
        self.assertEqual('12345', ds.resource_id)
        expected_state = (ds.CREATE, ds.COMPLETE)
        self.assertEqual(expected_state, ds.state)

    def test_update(self):
        ds = self._create_resource('data-source', self.rsrc_defn,
                                   self.stack)
        props = self.stack.t.t['resources']['data-source']['properties'].copy()
        props['type'] = 'hdfs'
        props['url'] = 'my/path'
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(ds.update, self.rsrc_defn)()
        data = {
            'name': 'my-ds',
            'description': '',
            'type': 'hdfs',
            'url': 'my/path',
            'credentials': {
                'user': 'admin',
                'password': 'swordfish'
            }
        }
        self.client.data_sources.update.assert_called_once_with(
            '12345', data)
        self.assertEqual((ds.UPDATE, ds.COMPLETE), ds.state)

    def test_show_attribute(self):
        ds = self._create_resource('data-source', self.rsrc_defn, self.stack)
        value = mock.MagicMock()
        value.to_dict.return_value = {'ds': 'info'}
        self.client.data_sources.get.return_value = value
        self.assertEqual({'ds': 'info'}, ds.FnGetAtt('show'))

    def test_validate_password_without_user(self):
        props = self.stack.t.t['resources']['data-source']['properties'].copy()
        del props['credentials']['user']
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        ds = data_source.DataSource('data-source', self.rsrc_defn, self.stack)
        ex = self.assertRaises(exception.StackValidationFailed, ds.validate)
        error_msg = ('Property error: resources.data-source.properties.'
                     'credentials: Property user not assigned')
        self.assertEqual(error_msg, six.text_type(ex))
