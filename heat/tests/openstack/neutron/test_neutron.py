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
from neutronclient.common import exceptions as qe
import six

from heat.common import exception
from heat.engine.clients.os import neutron
from heat.engine import properties
from heat.engine.resources.openstack.neutron import net
from heat.engine.resources.openstack.neutron import neutron as nr
from heat.engine import rsrc_defn
from heat.tests import common


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

    def test_resolve_attribute(self):
        class SomeNeutronResource(nr.NeutronResource):
            properties_schema = {}

            @classmethod
            def is_service_available(cls, context):
                return True

        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        stack = mock.MagicMock()
        stack.has_cache_data = mock.Mock(return_value=False)
        res = SomeNeutronResource('aresource', tmpl, stack)

        mock_show_resource = mock.MagicMock()
        mock_show_resource.side_effect = [{'attr1': 'val1', 'attr2': 'val2'},
                                          {'attr1': 'val1', 'attr2': 'val2'},
                                          {'attr1': 'val1', 'attr2': 'val2'},
                                          qe.NotFound]
        res._show_resource = mock_show_resource
        nclientplugin = neutron.NeutronClientPlugin(mock.MagicMock())
        res.client_plugin = mock.Mock(return_value=nclientplugin)

        self.assertEqual({'attr1': 'val1', 'attr2': 'val2'},
                         res.FnGetAtt('show'))
        self.assertEqual('val2', res._resolve_all_attributes('attr2'))
        self.assertRaises(KeyError, res._resolve_all_attributes, 'attr3')
        self.assertIsNone(res._resolve_all_attributes('attr2'))

        res.resource_id = None
        # use local cached object
        self.assertEqual({'attr1': 'val1', 'attr2': 'val2'},
                         res.FnGetAtt('show'))
        # reset cache, so resolver should be used again
        # and return None due to resource_id is None
        res.attributes.reset_resolved_values()
        self.assertIsNone(res.FnGetAtt('show'))
