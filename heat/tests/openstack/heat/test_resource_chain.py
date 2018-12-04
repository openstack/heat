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
import six

from heat.common import exception
from heat.engine import node_data
from heat.engine.resources.openstack.heat import resource_chain
from heat.engine import rsrc_defn
from heat.objects import service as service_objects
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

    @mock.patch.object(service_objects.Service, 'active_service_count')
    def test_child_template_with_concurrent(self, mock_count):

        # Setup
        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_def['resources']['test-chain']['properties']['concurrent'] = True
        chain = self._create_chain(tmpl_def)
        mock_count.return_value = 5

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

    @mock.patch.object(service_objects.Service, 'active_service_count')
    def test_child_template_with_concurrent_limit(self, mock_count):

        tmpl_def = copy.deepcopy(TEMPLATE)
        tmpl_def['resources']['test-chain']['properties']['concurrent'] = True
        tmpl_def['resources']['test-chain']['properties']['resources'] = [
            'OS::Heat::SoftwareConfig', 'OS::Heat::StructuredConfig',
            'OS::Heat::SoftwareConfig', 'OS::Heat::StructuredConfig']
        chain = self._create_chain(tmpl_def)
        mock_count.return_value = 2

        child_template = chain.child_template()

        tmpl = child_template.t
        resource = tmpl['resources']['0']
        self.assertNotIn('depends_on', resource)

        resource = tmpl['resources']['1']
        self.assertNotIn('depends_on', resource)

        resource = tmpl['resources']['2']
        self.assertEqual(['0'], resource['depends_on'])

        resource = tmpl['resources']['3']
        self.assertEqual(['1'], resource['depends_on'])

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

    def test_validate_reference_attr_with_none_ref(self):
        chain = self._create_chain(TEMPLATE)
        self.patchobject(chain, 'referenced_attrs',
                         return_value=set([('config', None)]))
        self.assertIsNone(chain.validate())

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


class ResourceChainAttrTest(common.HeatTestCase):
    def test_aggregate_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        chain = self._create_dummy_stack()
        expected = ['0', '1']
        self.assertEqual(expected, chain.FnGetAtt('foo'))
        self.assertEqual(expected, chain.FnGetAtt('Foo'))

    def test_index_dotted_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        chain = self._create_dummy_stack()
        self.assertEqual('0', chain.FnGetAtt('resource.0.Foo'))
        self.assertEqual('1', chain.FnGetAtt('resource.1.Foo'))

    def test_index_path_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        chain = self._create_dummy_stack()
        self.assertEqual('0', chain.FnGetAtt('resource.0', 'Foo'))
        self.assertEqual('1', chain.FnGetAtt('resource.1', 'Foo'))

    def test_index_deep_path_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        chain = self._create_dummy_stack(expect_attrs={'0': 2, '1': 3})
        self.assertEqual(2, chain.FnGetAtt('resource.0',
                                           'nested_dict', 'dict', 'b'))
        self.assertEqual(3, chain.FnGetAtt('resource.1',
                                           'nested_dict', 'dict', 'b'))

    def test_aggregate_deep_path_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        chain = self._create_dummy_stack(expect_attrs={'0': 3, '1': 3})
        expected = [3, 3]
        self.assertEqual(expected, chain.FnGetAtt('nested_dict', 'list', 2))

    def test_aggregate_refs(self):
        """Test resource id aggregation."""
        chain = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected, chain.FnGetAtt("refs"))

    def test_aggregate_refs_with_index(self):
        """Test resource id aggregation with index."""
        chain = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected[0], chain.FnGetAtt("refs", 0))
        self.assertEqual(expected[1], chain.FnGetAtt("refs", 1))
        self.assertIsNone(chain.FnGetAtt("refs", 2))

    def test_aggregate_outputs(self):
        """Test outputs aggregation."""
        expected = {'0': ['foo', 'bar'], '1': ['foo', 'bar']}
        chain = self._create_dummy_stack(expect_attrs=expected)
        self.assertEqual(expected, chain.FnGetAtt('attributes', 'list'))

    def test_aggregate_outputs_no_path(self):
        """Test outputs aggregation with missing path."""
        chain = self._create_dummy_stack()
        self.assertRaises(exception.InvalidTemplateAttribute,
                          chain.FnGetAtt, 'attributes')

    def test_index_refs(self):
        """Tests getting ids of individual resources."""
        chain = self._create_dummy_stack()
        self.assertEqual("ID-0", chain.FnGetAtt('resource.0'))
        self.assertEqual("ID-1", chain.FnGetAtt('resource.1'))
        ex = self.assertRaises(exception.NotFound, chain.FnGetAtt,
                               'resource.2')
        self.assertIn("Member '2' not found in group resource 'test'",
                      six.text_type(ex))

    def _create_dummy_stack(self, expect_count=2, expect_attrs=None):
        self.stack = utils.parse_stack(TEMPLATE)
        snip = self.stack.t.resource_definitions(self.stack)['test-chain']
        chain = resource_chain.ResourceChain('test', snip, self.stack)
        attrs = {}
        refids = {}
        if expect_attrs is None:
            expect_attrs = {}
        for index in range(expect_count):
            res = str(index)
            attrs[index] = expect_attrs.get(res, res)
            refids[index] = 'ID-%s' % res

        names = [str(name) for name in range(expect_count)]
        chain._resource_names = mock.Mock(return_value=names)
        self._stub_get_attr(chain, refids, attrs)
        return chain

    def _stub_get_attr(self, chain, refids, attrs):
        def ref_id_fn(res_name):
            return refids[int(res_name)]

        def attr_fn(args):
            res_name = args[0]
            return attrs[int(res_name)]

        def get_output(output_name):
            outputs = chain._nested_output_defns(chain._resource_names(),
                                                 attr_fn, ref_id_fn)
            op_defns = {od.name: od for od in outputs}
            if output_name not in op_defns:
                raise exception.NotFound('Specified output key %s not found.' %
                                         output_name)
            return op_defns[output_name].get_value()

        orig_get_attr = chain.FnGetAtt

        def get_attr(attr_name, *path):
            if not path:
                attr = attr_name
            else:
                attr = (attr_name,) + path
            # Mock referenced_attrs() so that _nested_output_definitions()
            # will include the output required for this attribute
            chain.referenced_attrs = mock.Mock(return_value=[attr])

            # Pass through to actual function under test
            return orig_get_attr(attr_name, *path)

        chain.FnGetAtt = mock.Mock(side_effect=get_attr)
        chain.get_output = mock.Mock(side_effect=get_output)


class ResourceChainAttrFallbackTest(ResourceChainAttrTest):
    def _stub_get_attr(self, chain, refids, attrs):
        # Raise NotFound when getting output, to force fallback to old-school
        # grouputils functions
        chain.get_output = mock.Mock(side_effect=exception.NotFound)

        def make_fake_res(idx):
            fr = mock.Mock()
            fr.stack = chain.stack
            fr.FnGetRefId.return_value = refids[idx]
            fr.FnGetAtt.return_value = attrs[idx]
            return fr

        fake_res = {str(i): make_fake_res(i) for i in refids}
        chain.nested = mock.Mock(return_value=fake_res)
