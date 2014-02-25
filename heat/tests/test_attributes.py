
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

from heat.engine import attributes
from heat.tests import common


class AttributeTest(common.HeatTestCase):
    """Test the Attribute class."""

    def test_as_output(self):
        """Test that Attribute looks right when viewed as an Output."""
        expected = {
            "Value": '{"Fn::GetAtt": ["test_resource", "test1"]}',
            "Description": "The first test attribute"
        }
        attr = attributes.Attribute("test1", "The first test attribute")
        self.assertEqual(expected, attr.as_output("test_resource"))


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
            "test1": "Test attrib 1",
            "test2": "Test attrib 2",
            "test3": "Test attrib 3"
        }
        self.m.ReplayAll()
        self.assertEqual(
            expected,
            attributes.Attributes.as_outputs("test_resource",
                                             MyTestResourceClass))
