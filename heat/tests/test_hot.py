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
from heat.common import template_format
from heat.common import exception
from heat.engine import parser
from heat.engine import hot
from heat.engine import template

from heat.tests.common import HeatTestCase
from heat.tests import test_parser
from heat.tests.utils import stack_delete_after


hot_tpl_empty = template_format.parse('''
heat_template_version: 2013-05-23
''')


class HOTemplateTest(HeatTestCase):
    """Test processing of HOT templates."""

    def test_defaults(self):
        """Test default content behavior of HOT template."""

        tmpl = parser.Template(hot_tpl_empty)
        # check if we get the right class
        self.assertTrue(isinstance(tmpl, hot.HOTemplate))
        try:
            # test getting an invalid section
            tmpl['foobar']
        except KeyError:
            pass
        else:
            self.fail('Expected KeyError for invalid section')

        # test defaults for valid sections
        self.assertEquals(tmpl[hot.VERSION], '2013-05-23')
        self.assertEquals(tmpl[hot.DESCRIPTION], 'No description')
        self.assertEquals(tmpl[hot.PARAMETERS], {})
        self.assertEquals(tmpl[hot.RESOURCES], {})
        self.assertEquals(tmpl[hot.OUTPUTS], {})

    def test_translate_parameters(self):
        """Test translation of parameters into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
          param1:
            description: foo
            type: string
        ''')

        expected = {'param1': {'Description': 'foo', 'Type': 'String'}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(tmpl[hot.PARAMETERS], expected)

    def test_translate_parameters_unsupported_type(self):
        """Test translation of parameters into internal engine format

        This tests if parameters with a type not yet supported by engine
        are also parsed.
        """

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        parameters:
          param1:
            description: foo
            type: unsupported_type
        ''')

        expected = {'param1': {'Description': 'foo',
                               'Type': 'unsupported_type'}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(tmpl[hot.PARAMETERS], expected)

    def test_translate_resources(self):
        """Test translation of resources into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: AWS::EC2::Instance
            properties:
              property1: value1
        ''')

        expected = {'resource1': {'Type': 'AWS::EC2::Instance',
                                  'Properties': {'property1': 'value1'}}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(tmpl[hot.RESOURCES], expected)

    def test_translate_outputs(self):
        """Test translation of outputs into internal engine format."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        outputs:
          output1:
            description: output1
            value: value1
        ''')

        expected = {'output1': {'Description': 'output1', 'Value': 'value1'}}

        tmpl = parser.Template(hot_tpl)
        self.assertEqual(tmpl[hot.OUTPUTS], expected)

    def test_param_refs(self):
        """Test if parameter references work."""
        params = {'foo': 'bar', 'blarg': 'wibble'}
        snippet = {'properties': {'key1': {'get_param': 'foo'},
                                  'key2': {'get_param': 'blarg'}}}
        snippet_resolved = {'properties': {'key1': 'bar',
                                           'key2': 'wibble'}}
        tmpl = parser.Template(hot_tpl_empty)
        self.assertEqual(tmpl.resolve_param_refs(snippet, params),
                         snippet_resolved)


class StackTest(test_parser.StackTest):
    """Test stack function when stack was created from HOT template."""

    @stack_delete_after
    def test_get_attr(self):
        """Test resolution of get_attr occurrences in HOT template."""

        hot_tpl = template_format.parse('''
        heat_template_version: 2013-05-23
        resources:
          resource1:
            type: GenericResourceType
        ''')

        self.stack = parser.Stack(self.ctx, 'test_get_attr',
                                  template.Template(hot_tpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual(self.stack.state,
                         (parser.Stack.CREATE, parser.Stack.COMPLETE))

        snippet = {'Value': {'get_attr': ['resource1', 'foo']}}
        resolved = hot.HOTemplate.resolve_attributes(snippet, self.stack)
        # GenericResourceType has an attribute 'foo' which yields the resource
        # name.
        self.assertEqual(resolved, {'Value': 'resource1'})
        # test invalid reference
        self.assertRaises(exception.InvalidTemplateAttribute,
                          hot.HOTemplate.resolve_attributes,
                          {'Value': {'get_attr': ['resource1', 'NotThere']}},
                          self.stack)
