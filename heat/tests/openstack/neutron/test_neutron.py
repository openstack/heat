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
import six

from heat.common import exception
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.neutron import net
from heat.engine.resources.openstack.neutron import neutron as nr
from heat.engine import rsrc_defn
from heat.engine import stack
from heat.engine import template
from heat.tests import common
from heat.tests import utils


class NeutronTest(common.HeatTestCase):

    def test_validate_properties(self):
        vs = {'router:external': True}
        data = {'admin_state_up': False,
                'value_specs': vs}
        p = properties.Properties(net.Net.properties_schema, data)
        self.assertIsNone(nr.NeutronResource.validate_properties(p))

        vs['foo'] = '1234'
        self.assertIsNone(nr.NeutronResource.validate_properties(p))
        vs.pop('foo')

        banned_keys = {'shared': True,
                       'name': 'foo',
                       'tenant_id': '1234'}
        for key, val in six.iteritems(banned_keys):
            vs.update({key: val})
            msg = '%s not allowed in value_specs' % key
            self.assertEqual(msg, nr.NeutronResource.validate_properties(p))
            vs.pop(key)

    def test_prepare_properties(self):
        data = {'admin_state_up': False,
                'value_specs': {'router:external': True}}
        p = properties.Properties(net.Net.properties_schema, data)
        props = nr.NeutronResource.prepare_properties(p, 'resource_name')
        self.assertEqual({'name': 'resource_name',
                          'router:external': True,
                          'admin_state_up': False,
                          'shared': False}, props)

    def test_is_built(self):
        self.assertTrue(nr.NeutronResource.is_built({'status': 'ACTIVE'}))
        self.assertTrue(nr.NeutronResource.is_built({'status': 'DOWN'}))
        self.assertFalse(nr.NeutronResource.is_built({'status': 'BUILD'}))
        e = self.assertRaises(
            exception.ResourceInError,
            nr.NeutronResource.is_built, {'status': 'ERROR'})
        self.assertEqual(
            'Went to status ERROR due to "Unknown"',
            six.text_type(e))
        e = self.assertRaises(
            exception.ResourceUnknownStatus,
            nr.NeutronResource.is_built, {'status': 'FROBULATING'})
        self.assertEqual('Resource is not built - Unknown status '
                         'FROBULATING due to "Unknown"',
                         six.text_type(e))

    def _get_some_neutron_resource(self):
        class SomeNeutronResource(nr.NeutronResource):
            properties_schema = {}

            @classmethod
            def is_service_available(cls, context):
                return (True, None)

        empty_tmpl = {'heat_template_version': 'ocata'}
        tmpl = template.Template(empty_tmpl)
        stack_name = 'dummystack'
        self.dummy_stack = stack.Stack(utils.dummy_context(), stack_name, tmpl)
        self.dummy_stack.store()

        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        return SomeNeutronResource('aresource', tmpl, self.dummy_stack)

    def test_resolve_attribute(self):
        res = self._get_some_neutron_resource()
        res.attributes_schema.update(
            {'attr2': attributes.Schema(type=attributes.Schema.STRING)})
        res.attributes = attributes.Attributes(res.name,
                                               res.attributes_schema,
                                               res._resolve_any_attribute)
        side_effect = [{'attr1': 'val1', 'attr2': 'val2'},
                       {'attr1': 'val1', 'attr2': 'val2'},
                       {'attr1': 'val1', 'attr2': 'val2'},
                       qe.NotFound]
        self.patchobject(res, '_show_resource', side_effect=side_effect)
        res.resource_id = 'resource_id'
        self.assertEqual({'attr1': 'val1', 'attr2': 'val2'},
                         res.FnGetAtt('show'))
        self.assertEqual('val2', res.attributes['attr2'])
        self.assertRaises(KeyError, res._resolve_any_attribute, 'attr3')
        self.assertIsNone(res._resolve_any_attribute('attr1'))

        res.resource_id = None
        # use local cached object for non-show attribute
        self.assertEqual('val2',
                         res.FnGetAtt('attr2'))
        # but the 'show' attribute is never cached
        self.assertIsNone(res.FnGetAtt('show'))

        # remove 'attr2' from res.attributes cache
        res.attributes.reset_resolved_values()
        # _resolve_attribute (in NeutronResource class) returns None
        # due to no resource_id
        self.assertIsNone(res.FnGetAtt('attr2'))

    def test_needs_replace_failed(self):
        res = self._get_some_neutron_resource()
        res.state_set(res.CREATE, res.FAILED)
        side_effect = [
            {'attr1': 'val1', 'status': 'ACTIVE'},
            {'attr1': 'val1', 'status': 'ERROR'},
            {'attr1': 'val1', 'attr2': 'val2'},
            qe.NotFound]
        mock_show_resource = self.patchobject(res, '_show_resource',
                                              side_effect=side_effect)
        # needs replace because res not created yet
        res.resource_id = None
        self.assertTrue(res.needs_replace_failed())
        self.assertEqual(0, mock_show_resource.call_count)

        # no need to replace because res is ACTIVE underlying
        res.resource_id = 'I am a resource'
        self.assertFalse(res.needs_replace_failed())
        self.assertEqual(1, mock_show_resource.call_count)

        # needs replace because res is ERROR underlying
        self.assertTrue(res.needs_replace_failed())
        self.assertEqual(2, mock_show_resource.call_count)

        # no need to replace because res exists and no status
        # to check
        self.assertFalse(res.needs_replace_failed())
        self.assertEqual(3, mock_show_resource.call_count)

        # needs replace because res can not be found
        self.assertTrue(res.needs_replace_failed())
        self.assertEqual(4, mock_show_resource.call_count)
