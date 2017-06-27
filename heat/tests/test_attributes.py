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
import six

from heat.engine import attributes
from heat.engine import resources
from heat.engine import support
from heat.tests import common


class AttributeSchemaTest(common.HeatTestCase):
    def test_schema_all(self):
        d = {'description': 'A attribute'}
        s = attributes.Schema('A attribute')
        self.assertEqual(d, dict(s))

        d = {'description': 'Another attribute',
             'type': 'string'}
        s = attributes.Schema('Another attribute',
                              type=attributes.Schema.STRING)
        self.assertEqual(d, dict(s))

    def test_all_resource_schemata(self):
        for resource_type in resources.global_env().get_types():
            for schema in six.itervalues(getattr(resource_type,
                                                 'attributes_schema',
                                                 {})):
                attributes.Schema.from_attribute(schema)

    def test_from_attribute_new_schema_format(self):
        s = attributes.Schema('Test description.')
        self.assertIs(s, attributes.Schema.from_attribute(s))
        self.assertEqual('Test description.',
                         attributes.Schema.from_attribute(s).description)

        s = attributes.Schema('Test description.',
                              type=attributes.Schema.MAP)
        self.assertIs(s, attributes.Schema.from_attribute(s))
        self.assertEqual(attributes.Schema.MAP,
                         attributes.Schema.from_attribute(s).type)

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


class AttributeTest(common.HeatTestCase):
    """Test the Attribute class."""

    def test_as_output(self):
        """Test that Attribute looks right when viewed as an Output."""
        expected = {
            "Value": {"Fn::GetAtt": ["test_resource", "test1"]},
            "Description": "The first test attribute"
        }
        attr = attributes.Attribute(
            "test1", attributes.Schema("The first test attribute"))
        self.assertEqual(expected, attr.as_output("test_resource"))

    def test_as_output_hot(self):
        """Test that Attribute looks right when viewed as an Output."""
        expected = {
            "value": {"get_attr": ["test_resource", "test1"]},
            "description": "The first test attribute"
        }
        attr = attributes.Attribute(
            "test1", attributes.Schema("The first test attribute"))
        self.assertEqual(expected, attr.as_output("test_resource", "hot"))


class AttributesTest(common.HeatTestCase):
    """Test the Attributes class."""

    def setUp(self):
        super(AttributesTest, self).setUp()

        self.resolver = mock.MagicMock()
        self.attributes_schema = {
            "test1": attributes.Schema("Test attrib 1"),
            "test2": attributes.Schema("Test attrib 2"),
            "test3": attributes.Schema(
                "Test attrib 3",
                cache_mode=attributes.Schema.CACHE_NONE)
        }

    def test_get_attribute(self):
        """Test that we get the attribute values we expect."""
        self.resolver.return_value = "value1"
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        self.assertEqual("value1", attribs['test1'])
        self.resolver.assert_called_once_with('test1')

    def test_attributes_representation(self):
        """Test that attributes are displayed correct."""
        self.resolver.return_value = "value1"
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        msg = 'Attributes for test resource:\n\tvalue1\n\tvalue1\n\tvalue1'
        self.assertEqual(msg, str(attribs))
        calls = [
            mock.call('test1'),
            mock.call('test2'),
            mock.call('test3')
        ]
        self.resolver.assert_has_calls(calls, any_order=True)

    def test_get_attribute_none(self):
        """Test that we get the attribute values we expect."""
        self.resolver.return_value = None
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        self.assertIsNone(attribs['test1'])
        self.resolver.assert_called_once_with('test1')

    def test_get_attribute_nonexist(self):
        """Test that we get the attribute values we expect."""
        self.resolver.return_value = "value1"
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        self.assertRaises(KeyError, attribs.__getitem__, 'not there')
        self.assertFalse(self.resolver.called)

    def test_as_outputs(self):
        """Test that Output format works as expected."""
        expected = {
            "test1": {
                "Value": {"Fn::GetAtt": ["test_resource", "test1"]},
                "Description": "Test attrib 1"
            },
            "test2": {
                "Value": {"Fn::GetAtt": ["test_resource", "test2"]},
                "Description": "Test attrib 2"
            },
            "test3": {
                "Value": {"Fn::GetAtt": ["test_resource", "test3"]},
                "Description": "Test attrib 3"
            },
            "OS::stack_id": {
                "Value": {"Ref": "test_resource"},
            }
        }
        MyTestResourceClass = mock.MagicMock()
        MyTestResourceClass.attributes_schema = {
            "test1": attributes.Schema("Test attrib 1"),
            "test2": attributes.Schema("Test attrib 2"),
            "test3": attributes.Schema("Test attrib 3"),
            "test4": attributes.Schema(
                "Test attrib 4",
                support_status=support.SupportStatus(status=support.HIDDEN))
        }
        self.assertEqual(
            expected,
            attributes.Attributes.as_outputs("test_resource",
                                             MyTestResourceClass))

    def test_as_outputs_hot(self):
        """Test that Output format works as expected."""
        expected = {
            "test1": {
                "value": {"get_attr": ["test_resource", "test1"]},
                "description": "Test attrib 1"
            },
            "test2": {
                "value": {"get_attr": ["test_resource", "test2"]},
                "description": "Test attrib 2"
            },
            "test3": {
                "value": {"get_attr": ["test_resource", "test3"]},
                "description": "Test attrib 3"
            },
            "OS::stack_id": {
                "value": {"get_resource": "test_resource"},
            }
        }
        MyTestResourceClass = mock.MagicMock()
        MyTestResourceClass.attributes_schema = {
            "test1": attributes.Schema("Test attrib 1"),
            "test2": attributes.Schema("Test attrib 2"),
            "test3": attributes.Schema("Test attrib 3"),
            "test4": attributes.Schema(
                "Test attrib 4",
                support_status=support.SupportStatus(status=support.HIDDEN))
        }
        self.assertEqual(
            expected,
            attributes.Attributes.as_outputs("test_resource",
                                             MyTestResourceClass,
                                             "hot"))

    def test_caching_local(self):
        self.resolver.side_effect = ["value1", "value1 changed"]
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        self.assertEqual("value1", attribs['test1'])
        self.assertEqual("value1", attribs['test1'])

        attribs.reset_resolved_values()
        self.assertEqual("value1 changed", attribs['test1'])
        calls = [
            mock.call('test1'),
            mock.call('test1')
        ]
        self.resolver.assert_has_calls(calls)

    def test_caching_none(self):
        self.resolver.side_effect = ["value3", "value3 changed"]
        attribs = attributes.Attributes('test resource',
                                        self.attributes_schema,
                                        self.resolver)
        self.assertEqual("value3", attribs['test3'])
        self.assertEqual("value3 changed", attribs['test3'])
        calls = [
            mock.call('test3'),
            mock.call('test3')
        ]
        self.resolver.assert_has_calls(calls)


class AttributesTypeTest(common.HeatTestCase):
    scenarios = [
        ('string_type',
            dict(a_type=attributes.Schema.STRING,
                 value='correct value',
                 invalid_value=[])),
        ('list_type',
            dict(a_type=attributes.Schema.LIST,
                 value=[],
                 invalid_value='invalid_value')),
        ('map_type',
            dict(a_type=attributes.Schema.MAP,
                 value={},
                 invalid_value='invalid_value')),
        ('integer_type',
            dict(a_type=attributes.Schema.INTEGER,
                 value=1,
                 invalid_value='invalid_value')),
        ('boolean_type',
            dict(a_type=attributes.Schema.BOOLEAN,
                 value=True,
                 invalid_value='invalid_value')),
        ('boolean_type_string_true',
            dict(a_type=attributes.Schema.BOOLEAN,
                 value="True",
                 invalid_value='invalid_value')),
        ('boolean_type_string_false',
            dict(a_type=attributes.Schema.BOOLEAN,
                 value="false",
                 invalid_value='invalid_value'))
    ]

    def test_validate_type(self):
        resolver = mock.Mock()
        msg = 'Attribute test1 is not of type %s' % self.a_type
        attr_schema = attributes.Schema("Test attribute", type=self.a_type)
        attrs_schema = {'res1': attr_schema}
        attr = attributes.Attribute("test1", attr_schema)
        attribs = attributes.Attributes('test res1', attrs_schema, resolver)
        attribs._validate_type(attr, self.value)
        self.assertNotIn(msg, self.LOG.output)
        attribs._validate_type(attr, self.invalid_value)
        self.assertIn(msg, self.LOG.output)
