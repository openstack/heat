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

from heat.tests.common import HeatTestCase

from heat.common import exception
from heat.engine.cfn import functions as cfn_funcs
from heat.engine.hot import functions as hot_funcs
from heat.engine import properties
from heat.engine import rsrc_defn


class ResourceDefinitionTest(HeatTestCase):

    def make_me_one_with_everything(self):
        return rsrc_defn.ResourceDefinition(
            'rsrc', 'SomeType',
            properties={'Foo': cfn_funcs.Join(None,
                                              'Fn::Join',
                                              ['a', ['b', 'r']]),
                        'Blarg': 'wibble'},
            metadata={'Baz': cfn_funcs.Join(None,
                                            'Fn::Join',
                                            ['u', ['q', '', 'x']])},
            depends=['other_resource'],
            deletion_policy='Retain',
            update_policy={'SomePolicy': {}})

    def test_properties_default(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        self.assertEqual({}, rd.properties({}))

    def test_properties(self):
        rd = self.make_me_one_with_everything()

        schema = {
            'Foo': properties.Schema(properties.Schema.STRING),
            'Blarg': properties.Schema(properties.Schema.STRING, default=''),
            'Baz': properties.Schema(properties.Schema.STRING, default='quux'),
        }

        props = rd.properties(schema)
        self.assertEqual('bar', props['Foo'])
        self.assertEqual('wibble', props['Blarg'])
        self.assertEqual('quux', props['Baz'])

    def test_metadata_default(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        self.assertEqual({}, rd.metadata())

    def test_metadata(self):
        rd = self.make_me_one_with_everything()
        metadata = rd.metadata()
        self.assertEqual({'Baz': 'quux'}, metadata)
        self.assertIsInstance(metadata['Baz'], basestring)

    def test_dependencies_default(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        stack = {'foo': 'FOO', 'bar': 'BAR'}
        self.assertEqual([], list(rd.dependencies(stack)))

    def test_dependencies_explicit(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType', depends=['foo'])
        stack = {'foo': 'FOO', 'bar': 'BAR'}
        self.assertEqual(['FOO'], list(rd.dependencies(stack)))

    def test_dependencies_explicit_invalid(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType', depends=['baz'])
        stack = {'foo': 'FOO', 'bar': 'BAR'}
        self.assertRaises(exception.InvalidTemplateReference,
                          lambda: list(rd.dependencies(stack)))

    def test_deletion_policy_default(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        self.assertEqual(rsrc_defn.ResourceDefinition.DELETE,
                         rd.deletion_policy())

    def test_deletion_policy(self):
        for policy in rsrc_defn.ResourceDefinition.DELETION_POLICIES:
            rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType',
                                              deletion_policy=policy)
            self.assertEqual(policy, rd.deletion_policy())

    def test_deletion_policy_invalid(self):
        self.assertRaises(AssertionError,
                          rsrc_defn.ResourceDefinition,
                          'rsrc', 'SomeType', deletion_policy='foo')

    def test_update_policy_default(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        self.assertEqual({}, rd.update_policy({}))

    def test_update_policy(self):
        rd = self.make_me_one_with_everything()

        policy_schema = {'Foo': properties.Schema(properties.Schema.STRING,
                                                  default='bar')}
        schema = {
            'SomePolicy': properties.Schema(properties.Schema.MAP,
                                            schema=policy_schema),
        }

        up = rd.update_policy(schema)
        self.assertEqual('bar', up['SomePolicy']['Foo'])

    def test_freeze(self):
        rd = self.make_me_one_with_everything()

        frozen = rd.freeze()
        self.assertEqual('bar', frozen._properties['Foo'])
        self.assertEqual('quux', frozen._metadata['Baz'])

    def test_freeze_override(self):
        rd = self.make_me_one_with_everything()

        frozen = rd.freeze(metadata={'Baz': 'wibble'})
        self.assertEqual('bar', frozen._properties['Foo'])
        self.assertEqual('wibble', frozen._metadata['Baz'])

    def test_render_hot(self):
        rd = self.make_me_one_with_everything()

        expected_hot = {
            'type': 'SomeType',
            'properties': {'Foo': {'Fn::Join': ['a', ['b', 'r']]},
                           'Blarg': 'wibble'},
            'metadata': {'Baz': {'Fn::Join': ['u', ['q', '', 'x']]}},
            'depends_on': ['other_resource'],
            'deletion_policy': 'Retain',
            'update_policy': {'SomePolicy': {}},
        }

        self.assertEqual(expected_hot, rd.render_hot())

    def test_template_equality(self):
        class FakeStack(object):
            def __init__(self, params):
                self.parameters = params

        def get_param_defn(value):
            stack = FakeStack({'Foo': value})
            param_func = hot_funcs.GetParam(stack, 'get_param', 'Foo')

            return rsrc_defn.ResourceDefinition('rsrc', 'SomeType',
                                                {'Foo': param_func})

        self.assertEqual(get_param_defn('bar'), get_param_defn('baz'))

    def test_hash_equal(self):
        rd1 = self.make_me_one_with_everything()
        rd2 = self.make_me_one_with_everything()
        self.assertEqual(rd1, rd2)
        self.assertEqual(hash(rd1), hash(rd2))

    def test_hash_names(self):
        rd1 = rsrc_defn.ResourceDefinition('rsrc1', 'SomeType')
        rd2 = rsrc_defn.ResourceDefinition('rsrc2', 'SomeType')
        self.assertEqual(rd1, rd2)
        self.assertEqual(hash(rd1), hash(rd2))

    def test_hash_types(self):
        rd1 = rsrc_defn.ResourceDefinition('rsrc', 'SomeType1')
        rd2 = rsrc_defn.ResourceDefinition('rsrc', 'SomeType2')
        self.assertNotEqual(rd1, rd2)
        self.assertNotEqual(hash(rd1), hash(rd2))


class ResourceDefinitionSnippetTest(HeatTestCase):
    def test_type(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType')
        self.assertEqual({'Type': 'SomeType'}, rd)

    def test_properties(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType',
                                          properties={'Foo': 'bar'})
        self.assertEqual({'Type': 'SomeType',
                          'Properties': {'Foo': 'bar'}}, rd)

    def test_metadata(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType',
                                          metadata={'Foo': 'bar'})
        self.assertEqual({'Type': 'SomeType',
                          'Metadata': {'Foo': 'bar'}}, rd)

    def test_deletion_policy(self):
        rd = rsrc_defn.ResourceDefinition(
            'rsrc', 'SomeType',
            deletion_policy=rsrc_defn.ResourceDefinition.RETAIN)
        self.assertEqual({'Type': 'SomeType',
                          'DeletionPolicy': 'Retain'}, rd)

    def test_update_policy(self):
        rd = rsrc_defn.ResourceDefinition('rsrc', 'SomeType',
                                          update_policy={'Foo': 'bar'})
        self.assertEqual({'Type': 'SomeType',
                          'UpdatePolicy': {'Foo': 'bar'}}, rd)
