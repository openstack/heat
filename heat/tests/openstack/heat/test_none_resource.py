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

import mock

from heat.common import template_format
from heat.engine import resource
from heat.engine.resources.openstack.heat import none_resource as none
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


class NoneResourceTest(common.HeatTestCase):

    tmpl = '''
heat_template_version: 2015-10-15
resources:
  none:
    type: OS::Heat::None
    properties:
      ignored: foo
outputs:
  anything:
    value: {get_attr: [none, anything]}
'''

    def _create_none_stack(self):
        self.t = template_format.parse(self.tmpl)
        self.stack = utils.parse_stack(self.t)
        self.rsrc = self.stack['none']
        self.assertIsNone(self.rsrc.validate())
        self.stack.create()
        self.assertEqual(self.rsrc.CREATE, self.rsrc.action)
        self.assertEqual(self.rsrc.COMPLETE, self.rsrc.status)
        self.assertEqual(self.stack.CREATE, self.stack.action)
        self.assertEqual(self.stack.COMPLETE, self.stack.status)
        self.stack._update_all_resource_data(False, True)
        self.assertIsNone(self.stack.outputs['anything'].get_value())

    def test_none_stack_create(self):
        self._create_none_stack()

    def test_none_stack_update_nochange(self):
        self._create_none_stack()
        before_refid = self.rsrc.FnGetRefId()
        self.assertIsNotNone(before_refid)
        utils.update_stack(self.stack, self.t)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(before_refid, self.stack['none'].FnGetRefId())

    def test_none_stack_update_add_prop(self):
        self._create_none_stack()
        before_refid = self.rsrc.FnGetRefId()
        self.assertIsNotNone(before_refid)
        new_t = self.t.copy()
        new_t['resources']['none']['properties']['another'] = 123
        utils.update_stack(self.stack, new_t)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(before_refid, self.stack['none'].FnGetRefId())

    def test_none_stack_update_del_prop(self):
        self._create_none_stack()
        before_refid = self.rsrc.FnGetRefId()
        self.assertIsNotNone(before_refid)
        new_t = self.t.copy()
        del(new_t['resources']['none']['properties']['ignored'])
        utils.update_stack(self.stack, new_t)
        self.assertEqual((self.stack.UPDATE, self.stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(before_refid, self.stack['none'].FnGetRefId())


class PlaceholderResourceTest(common.HeatTestCase):

    tmpl = '''
heat_template_version: 2015-10-15
resources:
  none:
    type: OS::BAR::FOO
    properties:
      ignored: foo
'''

    class FooResource(none.NoneResource):
        default_client_name = 'heat'
        entity = 'foo'

    FOO_RESOURCE_TYPE = 'OS::BAR::FOO'

    def setUp(self):
        super(PlaceholderResourceTest, self).setUp()
        resource._register_class(self.FOO_RESOURCE_TYPE, self.FooResource)
        self.t = template_format.parse(self.tmpl)
        self.stack = utils.parse_stack(self.t)
        self.rsrc = self.stack['none']
        self.client = mock.MagicMock()
        self.patchobject(self.FooResource, 'client', return_value=self.client)
        scheduler.TaskRunner(self.rsrc.create)()

    def _test_delete(self, is_placeholder=True):
        if not is_placeholder:
            delete_call_count = 1
            self.rsrc.data = mock.Mock(
                return_value={})
        else:
            delete_call_count = 0
            self.rsrc.data = mock.Mock(
                return_value={'is_placeholder': 'True'})
        scheduler.TaskRunner(self.rsrc.delete)()
        self.assertEqual((self.rsrc.DELETE, self.rsrc.COMPLETE),
                         self.rsrc.state)
        self.assertEqual(delete_call_count, self.client.foo.delete.call_count)
        self.assertEqual('foo', self.rsrc.entity)

    def test_not_placeholder_resource_delete(self):
        self._test_delete(is_placeholder=False)

    def test_placeholder_resource_delete(self):
        self._test_delete()
