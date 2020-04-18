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
from unittest import mock

import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import keystone as k_plugin
from heat.engine import rsrc_defn
from heat.engine import stack as parser
from heat.engine import template
from heat.tests import common
from heat.tests import utils

quota_template = '''
heat_template_version: newton

description: Sample octavia quota heat template

resources:
  my_quota:
    type: OS::Octavia::Quota
    properties:
      project: demo
      healthmonitor: 5
      listener: 5
      loadbalancer: 5
      pool: 5
      member: 5
'''

valid_properties = [
    'healthmonitor', 'listener', 'loadbalancer', 'pool', 'member'
]


class OcataQuotaTest(common.HeatTestCase):
    def setUp(self):
        super(OcataQuotaTest, self).setUp()

        self.ctx = utils.dummy_context()
        self.patchobject(k_plugin.KeystoneClientPlugin, 'get_project_id',
                         return_value='some_project_id')
        tpl = template_format.parse(quota_template)
        self.stack = parser.Stack(
            self.ctx, 'ocata_quota_test_stack',
            template.Template(tpl)
        )

        self.my_quota = self.stack['my_quota']
        ocata = mock.MagicMock()
        self.ocataclient = mock.MagicMock()
        self.my_quota.client = ocata
        ocata.return_value = self.ocataclient
        self.quotas = self.ocataclient.quotas
        self.quota_set = mock.MagicMock()
        self.quotas.update.return_value = self.quota_set
        self.quotas.delete.return_value = self.quota_set

    def _test_validate(self, resource, error_msg):
        exc = self.assertRaises(exception.StackValidationFailed,
                                resource.validate)
        self.assertIn(error_msg, six.text_type(exc))

    def _test_invalid_property(self, prop_name):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        props[prop_name] = -2
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        error_msg = ('Property error: resources.my_quota.properties.%s:'
                     ' -2 is out of range (min: -1, max: None)' % prop_name)
        self._test_validate(my_quota, error_msg)

    def test_invalid_properties(self):
        for prop in valid_properties:
            self._test_invalid_property(prop)

    def test_miss_all_quotas(self):
        my_quota = self.stack['my_quota']
        props = self.stack.t.t['resources']['my_quota']['properties'].copy()
        for key in valid_properties:
            if key in props:
                del props[key]
        my_quota.t = my_quota.t.freeze(properties=props)
        my_quota.reparse()
        msg = ('At least one of the following properties must be specified: '
               'healthmonitor, listener, loadbalancer, member, pool.')
        self.assertRaisesRegex(exception.PropertyUnspecifiedError, msg,
                               my_quota.validate)

    def test_quota_handle_create(self):
        self.my_quota.physical_resource_name = mock.MagicMock(
            return_value='some_resource_id')
        self.my_quota.reparse()
        self.my_quota.handle_create()
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            healthmonitor=5,
            listener=5,
            loadbalancer=5,
            pool=5,
            member=5
        )
        self.assertEqual('some_resource_id', self.my_quota.resource_id)

    def test_quota_handle_update(self):
        tmpl_diff = mock.MagicMock()
        prop_diff = mock.MagicMock()
        props = {'project': 'some_project_id', 'pool': 1, 'member': 2,
                 'listener': 3, 'loadbalancer': 4, 'healthmonitor': 2}
        json_snippet = rsrc_defn.ResourceDefinition(
            self.my_quota.name,
            'OS::Octavia::Quota',
            properties=props)
        self.my_quota.reparse()
        self.my_quota.handle_update(json_snippet, tmpl_diff, prop_diff)
        self.quotas.update.assert_called_once_with(
            'some_project_id',
            pool=1,
            member=2,
            listener=3,
            loadbalancer=4,
            healthmonitor=2
        )

    def test_quota_handle_delete(self):
        self.my_quota.reparse()
        self.my_quota.handle_delete()
        self.quotas.delete.assert_called_once_with('some_project_id')
