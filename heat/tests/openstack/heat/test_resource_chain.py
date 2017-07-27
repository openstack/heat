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

import copy
import mock

from heat.common import exception
from heat.common import grouputils
from heat.engine import node_data
from heat.engine.resources.openstack.heat import resource_chain
from heat.engine import rsrc_defn
from heat.tests import common
from heat.tests import utils

RESOURCE_PROPERTIES = {
    'group': 'test-group',
}

TEMPLATE = {
    'heat_template_version': '2016-04-08',
    'resources': {
        'test-chain': {
            'type': 'OS::Heat::ResourceChain',
            'properties': {
                'resources': ['OS::Heat::SoftwareConfig',
                              'OS::Heat::StructuredConfig'],
                'concurrent': False,
                'resource_properties': RESOURCE_PROPERTIES,
            }
        }
    }
}


class ResourceChainTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceChainTest, self).setUp()

        self.stack = None  # hold on to stack to prevent weakref cleanup

    def test_child_template_without_concurrency(self):
        # Test
        chain = self._create_chain(TEMPLATE)
        child_template = chain.child_template()

        # Verify
        tmpl = child_template.t
        self.assertEqual('2015-04-30', tmpl['heat_template_version'])
        self.assertEqual(2, len(child_template.t['resources']))

        resource = tmpl['resources']['0']
        self.assertEqual('OS::Heat::SoftwareConfig', resource['type'])
        self.assertEqual(RESOURCE_PROPERTIES, resource['properties'])
        self.assertNotIn('depends_on', resource)

        resource = tmpl['resources']['1']
        self.assertEqual('OS::Heat::StructuredConfig', resource['type'])
        self.assertEqual(RESOURCE_PROPERTIES, resource['properties'])
        self.assertEqual(['0'], resource['depends_on'])

    def test_child_template_with_concurrent(self):

        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_def['resources']['test-chain']['properties']['concurrent'] = True
        chain = self._create_chain(tmpl_def)

        # Test
        child_template = chain.child_template()

        # Verify
        # Trimmed down version of above that just checks the depends_on
        # isn't present
        tmpl = child_template.t
        resource = tmpl['resources']['0']
        self.assertNotIn('depends_on', resource)

        resource = tmpl['resources']['1']
        self.assertNotIn('depends_on', resource)

    def test_child_template_default_concurrent(self):
        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_def['resources']['test-chain']['properties'].pop('concurrent')
        chain = self._create_chain(tmpl_def)

        # Test
        child_template = chain.child_template()

        # Verify
        # Trimmed down version of above that just checks the depends_on
        # isn't present
        tmpl = child_template.t
        resource = tmpl['resources']['0']
        self.assertNotIn('depends_on', resource)

        resource = tmpl['resources']['1']
        self.assertEqual(['0'], resource['depends_on'])

    def test_child_template_empty_resource_list(self):
        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_def['resources']['test-chain']['properties']['resources'] = []
        chain = self._create_chain(tmpl_def)

        # Test
        child_template = chain.child_template()

        # Verify
        tmpl = child_template.t
        # No error, but no resources to create
        self.assertNotIn('resources', tmpl)
        # Sanity check that it's actually a template
        self.assertIn('heat_template_version', tmpl)

    def test_validate_nested_stack(self):
        # Test - should not raise exception
        chain = self._create_chain(TEMPLATE)
        chain.validate_nested_stack()

    def test_validate_incompatible_properties(self):
        # Tests a resource in the chain that does not support the properties
        # specified to each resource.

        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_res_prop = tmpl_def['resources']['test-chain']['properties']
        res_list = tmpl_res_prop['resources']
        res_list.append('OS::Heat::RandomString')

        # Test
        chain = self._create_chain(tmpl_def)

        try:
            chain.validate_nested_stack()
            self.fail('Exception expected')
        except exception.StackValidationFailed as e:
            self.assertEqual('property error: '
                             'resources.test<nested_stack>.resources[2].'
                             'properties: unknown property group',
                             e.message.lower())

    def test_validate_fake_resource_type(self):
        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_res_prop = tmpl_def['resources']['test-chain']['properties']
        res_list = tmpl_res_prop['resources']
        res_list.append('foo')

        # Test
        chain = self._create_chain(tmpl_def)

        try:
            chain.validate_nested_stack()
            self.fail('Exception expected')
        except exception.StackValidationFailed as e:
            self.assertIn('could not be found', e.message.lower())
            self.assertIn('foo', e.message)

    @mock.patch.object(resource_chain.ResourceChain, 'create_with_template')
    def test_handle_create(self, mock_create):
        # Tests the handle create is propagated upwards with the
        # child template.

        # Setup
        chain = self._create_chain(TEMPLATE)

        # Test
        chain.handle_create()

        # Verify
        expected_tmpl = chain.child_template()
        mock_create.assert_called_once_with(expected_tmpl)

    @mock.patch.object(resource_chain.ResourceChain, 'update_with_template')
    def test_handle_update(self, mock_update):
        # Test the handle update is propagated upwards with the child
        # template.

        # Setup
        chain = self._create_chain(TEMPLATE)

        # Test
        json_snippet = rsrc_defn.ResourceDefinition(
            'test-chain', 'OS::Heat::ResourceChain',
            TEMPLATE['resources']['test-chain']['properties'])

        chain.handle_update(json_snippet, None, None)

        # Verify
        expected_tmpl = chain.child_template()
        mock_update.assert_called_once_with(expected_tmpl)

    def test_child_params(self):
        chain = self._create_chain(TEMPLATE)
        self.assertEqual({}, chain.child_params())

    def _create_chain(self, t):
        self.stack = utils.parse_stack(t)
        snip = self.stack.t.resource_definitions(self.stack)['test-chain']
        chain = resource_chain.ResourceChain('test', snip, self.stack)
        return chain

    @mock.patch.object(grouputils, 'get_rsrc_id')
    def test_get_attribute(self, mock_get_rsrc_id):
        stack = utils.parse_stack(TEMPLATE)
        mock_get_rsrc_id.side_effect = ['0', '1']
        rsrc = stack['test-chain']
        self.assertEqual(['0', '1'], rsrc.FnGetAtt(rsrc.REFS))

    def test_get_attribute_convg(self):
        cache_data = {'test-chain': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'attrs': {'refs': ['rsrc1', 'rsrc2']}
        })}
        stack = utils.parse_stack(TEMPLATE, cache_data=cache_data)
        rsrc = stack.defn['test-chain']
        self.assertEqual(['rsrc1', 'rsrc2'], rsrc.FnGetAtt('refs'))
