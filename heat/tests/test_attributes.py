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
import testtools

from heat.engine import attributes
from heat.engine import resources
from heat.engine import support
from heat.tests import common


class AttributeSchemaTest(testtools.TestCase):
    def test_schema_all(self):
        d = {'description': 'A attribute'}
        s = attributes.Schema('A attribute')
        self.assertEqual(d, dict(s))

    def test_all_resource_schemata(self):
        for resource_type in resources.global_env().get_types():
            for schema in getattr(resource_type,
                                  'attributes_schema',
                                  {}).itervalues():
                attributes.Schema.from_attribute(schema)

    def test_from_attribute_new_schema_format(self):
        s = attributes.Schema('Test description.')
        self.assertIs(s, attributes.Schema.from_attribute(s))
        self.assertEqual('Test description.',
                         attributes.Schema.from_attribute(s).description)

    def test_schema_support_status(self):
        schema = {
            'foo_sup': attributes.Schema(
                'Description1'
            ),
            'bar_dep': attributes.Schema(
                'Description2',
                support_status=support.SupportStatus(
                    support.DEPRECATED,
                    'Do not use this ever')
            )
        }
        attrs = attributes.Attributes('test_rsrc', schema, lambda d: d)
        self.assertEqual(support.SUPPORTED,
                         attrs._attributes['foo_sup'].support_status().status)
        self.assertEqual(support.DEPRECATED,
                         attrs._attributes['bar_dep'].support_status().status)
        self.assertEqual('Do not use this ever',
                         attrs._attributes['bar_dep'].support_status().message)

    def test_old_attribute_schema_format(self):
        with mock.patch('heat.engine.attributes.warnings'):
            s = 'Test description.'
            self.assertIsInstance(attributes.Schema.from_attribute(s),
                                  attributes.Schema)
            self.assertEqual('Test description.',
                             attributes.Schema.from_attribute(s).description)


class AttributeTest(common.HeatTestCase):
    """Test the Attribute class."""

    def test_as_output(self):
        """Test that Attribute looks right when viewed as an Output."""
        expected = {
            "Value": '{"Fn::GetAtt": ["test_resource", "test1"]}',
            "Description": "The first test attribute"
        }
        attr = attributes.Attribute(
            "test1", attributes.Schema("The first test attribute"))
        self.assertEqual(expected, attr.as_output("test_resource"))


class AttributesTest(common.HeatTestCase):
    """Test the Attributes class."""

    attributes_schema = {
        "test1": attributes.Schema("Test attrib 1"),
        "test2": attributes.Schema("Test attrib 2"),
        "test3": attributes.Schema(
            "Test attrib 3",
            cache_mode=attributes.Schema.CACHE_NONE)
    }

    def setUp(self):
        super(AttributesTest, self).setUp()
        self.addCleanup(self.m.VerifyAll)

    def test_get_attribute(self):
        """Test that we get the attribute values we expect."""
        test_resolver = lambda x: "value1"
        self.m.ReplayAll()
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        test_resolver)
        self.assertEqual("value1", attribs['test1'])

    def test_get_attribute_none(self):
        """Test that we get the attribute values we expect."""
        test_resolver = lambda x: None
        self.m.ReplayAll()
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        test_resolver)
        self.assertIsNone(attribs['test1'])

    def test_get_attribute_nonexist(self):
        """Test that we get the attribute values we expect."""
        test_resolver = lambda x: "value1"
        self.m.ReplayAll()
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        test_resolver)
        self.assertRaises(KeyError, attribs.__getitem__, 'not there')

    def test_as_outputs(self):
        """Test that Output format works as expected."""
        expected = {
            "test1": {
                "Value": '{"Fn::GetAtt": ["test_resource", "test1"]}',
                "Description": "Test attrib 1"
            },
            "test2": {
                "Value": '{"Fn::GetAtt": ["test_resource", "test2"]}',
                "Description": "Test attrib 2"
            },
            "test3": {
                "Value": '{"Fn::GetAtt": ["test_resource", "test3"]}',
                "Description": "Test attrib 3"
            }
        }
        MyTestResourceClass = self.m.CreateMockAnything()
        MyTestResourceClass.attributes_schema = {
            "test1": attributes.Schema("Test attrib 1"),
            "test2": attributes.Schema("Test attrib 2"),
            "test3": attributes.Schema("Test attrib 3"),
        }
        self.m.ReplayAll()
        self.assertEqual(
            expected,
            attributes.Attributes.as_outputs("test_resource",
                                             MyTestResourceClass))

    def test_caching_local(self):
        value = 'value1'
        test_resolver = lambda x: value
        self.m.ReplayAll()
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        test_resolver)
        self.assertEqual("value1", attribs['test1'])
        value = 'value1 changed'
        self.assertEqual("value1", attribs['test1'])

        attribs.reset_resolved_values()
        self.assertEqual("value1 changed", attribs['test1'])

    def test_caching_none(self):
        value = 'value3'
        test_resolver = lambda x: value
        self.m.ReplayAll()
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        test_resolver)
        self.assertEqual("value3", attribs['test3'])
        value = 'value3 changed'
        self.assertEqual("value3 changed", attribs['test3'])
