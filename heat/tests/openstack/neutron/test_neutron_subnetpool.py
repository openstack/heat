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

from neutronclient.common import exceptions as qe
from neutronclient.neutron import v2_0 as neutronV20
from neutronclient.v2_0 import client as neutronclient
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.resources.openstack.neutron import subnetpool
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests.openstack.neutron import inline_templates
from heat.tests import utils


class NeutronSubnetPoolTest(common.HeatTestCase):

    def setUp(self):
        super(NeutronSubnetPoolTest, self).setUp()
        self.patchobject(neutron.NeutronClientPlugin, 'has_extension',
                         return_value=True)
        self.find_resource = self.patchobject(neutronV20,
                                              'find_resourceid_by_name_or_id',
                                              return_value='new_test')

    def create_subnetpool(self, status='COMPLETE', tags=None):
        self.t = template_format.parse(inline_templates.SPOOL_TEMPLATE)
        if tags:
            self.t['resources']['sub_pool']['properties']['tags'] = tags
        self.stack = utils.parse_stack(self.t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        rsrc = subnetpool.SubnetPool('sub_pool', resource_defns['sub_pool'],
                                     self.stack)
        if status == 'FAILED':
            self.patchobject(neutronclient.Client, 'create_subnetpool',
                             side_effect=qe.NeutronClientException(
                                 status_code=500))
            error = self.assertRaises(exception.ResourceFailure,
                                      scheduler.TaskRunner(rsrc.create))
            self.assertEqual(
                'NeutronClientException: resources.sub_pool: '
                'An unknown exception occurred.',
                six.text_type(error))
        else:
            self.patchobject(neutronclient.Client, 'create_subnetpool',
                             return_value={'subnetpool': {
                                 'id': 'fc68ea2c-b60b-4b4f-bd82-94ec81110766'
                             }})
            scheduler.TaskRunner(rsrc.create)()

        self.assertEqual((rsrc.CREATE, status), rsrc.state)
        if tags:
            self.set_tag_mock.assert_called_once_with('subnetpools',
                                                      rsrc.resource_id,
                                                      {'tags': tags})
        return rsrc

    def test_validate_prefixlen_min_gt_max(self):
        self.t = template_format.parse(inline_templates.SPOOL_TEMPLATE)
        props = self.t['resources']['sub_pool']['properties']
        props['min_prefixlen'] = 28
        props['max_prefixlen'] = 24
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['sub_pool']
        errMessage = ('Illegal prefix bounds: max_prefixlen=24, '
                      'min_prefixlen=28.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMessage, six.text_type(error))

    def test_validate_prefixlen_default_gt_max(self):
        self.t = template_format.parse(inline_templates.SPOOL_TEMPLATE)
        props = self.t['resources']['sub_pool']['properties']
        props['default_prefixlen'] = 28
        props['max_prefixlen'] = 24
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['sub_pool']
        errMessage = ('Illegal prefix bounds: max_prefixlen=24, '
                      'default_prefixlen=28.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMessage, six.text_type(error))

    def test_validate_prefixlen_min_gt_default(self):
        self.t = template_format.parse(inline_templates.SPOOL_TEMPLATE)
        props = self.t['resources']['sub_pool']['properties']
        props['min_prefixlen'] = 28
        props['default_prefixlen'] = 24
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['sub_pool']
        errMessage = ('Illegal prefix bounds: min_prefixlen=28, '
                      'default_prefixlen=24.')
        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.validate)
        self.assertEqual(errMessage, six.text_type(error))

    def test_validate_minimal(self):
        self.t = template_format.parse(inline_templates.SPOOL_MINIMAL_TEMPLATE)
        self.stack = utils.parse_stack(self.t)
        rsrc = self.stack['sub_pool']
        self.assertIsNone(rsrc.validate())

    def test_create_subnetpool(self):
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

    def test_create_subnetpool_with_tags(self):
        tags = ['for_test']
        self.set_tag_mock = self.patchobject(neutronclient.Client,
                                             'replace_tag')
        rsrc = self.create_subnetpool(tags=tags)
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)

    def test_create_subnetpool_failed(self):
        self.create_subnetpool('FAILED')

    def test_delete_subnetpool(self):
        self.patchobject(neutronclient.Client, 'delete_subnetpool')
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_delete_subnetpool_not_found(self):
        self.patchobject(neutronclient.Client, 'delete_subnetpool',
                         side_effect=qe.NotFound(status_code=404))
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        self.assertEqual((rsrc.DELETE, rsrc.COMPLETE), rsrc.state)

    def test_delete_subnetpool_resource_id_none(self):
        delete_pool = self.patchobject(neutronclient.Client,
                                       'delete_subnetpool')
        rsrc = self.create_subnetpool()
        rsrc.resource_id = None
        self.assertIsNone(scheduler.TaskRunner(rsrc.delete)())
        delete_pool.assert_not_called()

    def test_update_subnetpool(self):
        update_subnetpool = self.patchobject(neutronclient.Client,
                                             'update_subnetpool')
        self.set_tag_mock = self.patchobject(neutronclient.Client,
                                             'replace_tag')
        old_tags = ['old_tag']
        rsrc = self.create_subnetpool(tags=old_tags)
        self.patchobject(rsrc, 'physical_resource_name',
                         return_value='the_new_sp')
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        new_tags = ['new_tag']
        props = {
            'name': 'the_new_sp',
            'prefixes': [
                '10.1.0.0/16',
                '10.2.0.0/16'],
            'address_scope': 'new_test',
            'default_quota': '16',
            'default_prefixlen': '24',
            'min_prefixlen': '24',
            'max_prefixlen': '28',
            'is_default': False,
            'tags': new_tags
        }
        update_dict = props.copy()
        update_dict['name'] = 'the_new_sp'
        update_dict['address_scope_id'] = update_dict.pop('address_scope')
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        # with name
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, props))
        self.set_tag_mock.assert_called_with('subnetpools',
                                             rsrc.resource_id,
                                             {'tags': new_tags})

        # without name
        props['name'] = None
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, props))

        self.assertEqual(2, update_subnetpool.call_count)
        update_dict.pop('tags')
        update_subnetpool.assert_called_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'subnetpool': update_dict})

    def test_update_subnetpool_no_prop_diff(self):
        update_subnetpool = self.patchobject(neutronclient.Client,
                                             'update_subnetpool')
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      rsrc.t._properties)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, {}))
        update_subnetpool.assert_not_called()

    def test_update_subnetpool_validate_prefixes(self):
        update_subnetpool = self.patchobject(neutronclient.Client,
                                             'update_subnetpool')
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        prefix_old = rsrc.properties['prefixes']
        props = {
            'name': 'the_new_sp',
            'prefixes': ['10.5.0.0/16']
        }
        prefix_new = props['prefixes']
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        errMessage = ('Property prefixes updated value %(value1)s '
                      'should be superset of existing value %(value2)s.'
                      % dict(value1=sorted(prefix_new),
                             value2=sorted(prefix_old)))

        error = self.assertRaises(exception.StackValidationFailed,
                                  rsrc.handle_update,
                                  update_snippet, {}, props)

        self.assertEqual(errMessage, six.text_type(error))
        update_subnetpool.assert_not_called()

        props = {
            'name': 'the_new_sp',
            'prefixes': ['10.0.0.0/8',
                         '10.6.0.0/16'],
        }

        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, props))
        update_subnetpool.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'subnetpool': props})

    def test_update_subnetpool_update_address_scope(self):
        update_subnetpool = self.patchobject(neutronclient.Client,
                                             'update_subnetpool')
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        props = {
            'name': 'the_new_sp',
            'address_scope': 'new_test',
            'prefixes': ['10.0.0.0/8',
                         '10.6.0.0/16'],
        }
        update_dict = {
            'name': 'the_new_sp',
            'address_scope_id': 'new_test',
            'prefixes': ['10.0.0.0/8',
                         '10.6.0.0/16'],
        }
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, props))
        self.assertEqual(3, self.find_resource.call_count)
        update_subnetpool.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'subnetpool': update_dict})

    def test_update_subnetpool_remove_address_scope(self):
        update_subnetpool = self.patchobject(neutronclient.Client,
                                             'update_subnetpool')
        rsrc = self.create_subnetpool()
        ref_id = rsrc.FnGetRefId()
        self.assertEqual('fc68ea2c-b60b-4b4f-bd82-94ec81110766', ref_id)
        props = {
            'name': 'the_new_sp',
            'prefixes': ['10.0.0.0/8',
                         '10.6.0.0/16'],
        }
        props_diff = {'address_scope': None}
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name, rsrc.type(),
                                                      props)
        self.assertIsNone(rsrc.handle_update(update_snippet, {}, props_diff))
        self.assertEqual(2, self.find_resource.call_count)
        update_subnetpool.assert_called_once_with(
            'fc68ea2c-b60b-4b4f-bd82-94ec81110766',
            {'subnetpool': props_diff})
