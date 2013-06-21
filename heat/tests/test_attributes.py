# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import mox

from heat.engine import attributes
from heat.tests import common

test_attribute_schema = {
    "attribute1": "A description for attribute 1",
    "attribute2": "A description for attribute 2",
    "another attribute": "The last attribute"
}


class AttributeTest(common.HeatTestCase):
    """Test the Attribute class."""

    def setUp(self):
        common.HeatTestCase.setUp(self)
        self.test_resolver = self.m.CreateMockAnything()

    def test_resolve_attribute(self):
        """Test that an Attribute returns a good value based on resolver."""
        test_val = "test value"
        # resolved with a good value first
        self.test_resolver('test').AndReturn('test value')
        # second call resolves to None
        self.test_resolver(mox.IgnoreArg()).AndReturn(None)
        self.m.ReplayAll()
        test_attr = attributes.Attribute("test", "A test attribute",
                                         self.test_resolver)
        self.assertEqual(test_val, test_attr.value,
                         "Unexpected attribute value")
        self.assertIsNone(test_attr.value,
                          "Second attrib value should be None")
        self.m.VerifyAll()

    def test_as_output(self):
        """Test that Attribute looks right when viewed as an Output."""
        expected = {
            "test1": {
                "Value": '{"Fn::GetAtt": ["test_resource", "test1"]}',
                "Description": "The first test attribute"
            }
        }
        self.assertEqual(expected,
                         attributes.Attribute.as_output(
                         "test_resource",
                         "test1",
                         "The first test attribute"),
                         'Attribute as Output mismatch')


class AttributesTest(common.HeatTestCase):
    """Test the Attributes class."""

    attributes_schema = {
        "test1": "Test attrib 1",
        "test2": "Test attrib 2",
        "test3": "Test attrib 3"
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
            "test1": "Test attrib 1",
            "test2": "Test attrib 2",
            "test3": "Test attrib 3"
        }
        self.m.ReplayAll()
        self.assertEqual(
            expected,
            attributes.Attributes.as_outputs("test_resource",
                                             MyTestResourceClass))
