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
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import resource_group
from heat.engine import scheduler
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils

template = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "dummy.resource",
                    "properties": {
                        "Foo": "Bar"
                    }
                }
            }
        }
    }
}

template2 = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "dummy": {
            "type": "dummy.resource",
            "properties": {
                "Foo": "baz"
            }
        },
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "dummy.resource",
                    "properties": {
                        "Foo": {"get_attr": ["dummy", "Foo"]}
                    }
                }
            }
        }
    }
}

template_repl = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "dummy.listresource%index%",
                    "properties": {
                        "Foo": "Bar_%index%",
                        "listprop": [
                            "%index%_0",
                            "%index%_1",
                            "%index%_2"
                        ]
                    }
                }
            }
        }
    }
}

template_attr = {
    "heat_template_version": "2014-10-16",
    "resources": {
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "dummyattr.resource",
                    "properties": {
                    }
                }
            }
        }
    },
    "outputs": {
        "nested_strings": {
            "value": {"get_attr": ["group1", "nested_dict", "string"]}
        }
    }
}


class ResourceWithPropsAndId(generic_resource.ResourceWithProps):

    def FnGetRefId(self):
        return "ID-%s" % self.name


class ResourceWithListProp(ResourceWithPropsAndId):

    def __init__(self):
        self.properties_schema.update({
            "listprop": properties.Schema(
                properties.Schema.LIST
            )
        })
        super(ResourceWithListProp, self).__init__(self)


class ResourceGroupTest(common.HeatTestCase):

    def setUp(self):
        common.HeatTestCase.setUp(self)
        resource._register_class("dummy.resource",
                                 ResourceWithPropsAndId)
        resource._register_class('dummy.listresource',
                                 ResourceWithListProp)
        AttributeResource = generic_resource.ResourceWithComplexAttributes
        resource._register_class("dummyattr.resource",
                                 AttributeResource)

    def test_build_resource_definition(self):
        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "type": "dummy.resource",
            "properties": {
                "Foo": "Bar"
            },
        }
        self.assertEqual(
            expect, resg._build_resource_definition())
        self.assertEqual(
            expect, resg._build_resource_definition(include_all=True))

    def test_build_resource_definition_include(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = None
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "type": "dummy.resource",
            "properties": {}
        }
        self.assertEqual(
            expect, resg._build_resource_definition())
        expect = {
            "type": "dummy.resource",
            "properties": {"Foo": None}
        }
        self.assertEqual(
            expect, resg._build_resource_definition(include_all=True))

    def test_assemble_nested(self):
        """
        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        templ = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "0": {
                    "type": "dummy.resource",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "1": {
                    "type": "dummy.resource",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "2": {
                    "type": "dummy.resource",
                    "properties": {
                        "Foo": "Bar"
                    }
                }
            }
        }

        self.assertEqual(templ, resg._assemble_nested(['0', '1', '2']))

    def test_assemble_nested_include(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = None
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "0": {
                    "type": "dummy.resource",
                    "properties": {}
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0']))
        expect['resources']["0"]['properties'] = {"Foo": None}
        self.assertEqual(
            expect, resg._assemble_nested(['0'], include_all=True))

    def test_index_var(self):
        stack = utils.parse_stack(template_repl)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "0": {
                    "type": "dummy.listresource%index%",
                    "properties": {
                        "Foo": "Bar_0",
                        "listprop": [
                            "0_0", "0_1", "0_2"
                        ]
                    }
                },
                "1": {
                    "type": "dummy.listresource%index%",
                    "properties": {
                        "Foo": "Bar_1",
                        "listprop": [
                            "1_0", "1_1", "1_2"
                        ]
                    }
                },
                "2": {
                    "type": "dummy.listresource%index%",
                    "properties": {
                        "Foo": "Bar_2",
                        "listprop": [
                            "2_0", "2_1", "2_2"
                        ]
                    }
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0', '1', '2']))

    def test_custom_index_var(self):
        templ = copy.deepcopy(template_repl)
        templ['resources']['group1']['properties']['index_var'] = "__foo__"
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "0": {
                    "type": "dummy.listresource%index%",
                    "properties": {
                        "Foo": "Bar_%index%",
                        "listprop": [
                            "%index%_0", "%index%_1", "%index%_2"
                        ]
                    }
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0']))

        res_def = snip['Properties']['resource_def']
        res_def['properties']['Foo'] = "Bar___foo__"
        res_def['properties']['listprop'] = ["__foo___0", "__foo___1",
                                             "__foo___2"]
        res_def['type'] = "dummy.listresource__foo__"
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2013-05-23",
            "resources": {
                "0": {
                    "type": "dummy.listresource__foo__",
                    "properties": {
                        "Foo": "Bar_0",
                        "listprop": [
                            "0_0", "0_1", "0_2"
                        ]
                    }
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0']))

    def test_assemble_no_properties(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        del res_def['properties']
        stack = utils.parse_stack(templ)
        resg = stack.resources['group1']
        self.assertIsNone(resg.validate())

    def test_invalid_res_type(self):
        """Test that error raised for unknown resource type."""
        tmp = copy.deepcopy(template)
        grp_props = tmp['resources']['group1']['properties']
        grp_props['resource_def']['type'] = "idontexist"
        stack = utils.parse_stack(tmp)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        exc = self.assertRaises(exception.StackValidationFailed,
                                resg.validate)
        self.assertIn('Unknown resource Type', six.text_type(exc))

    def test_reference_attr(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertIsNone(resgrp.validate())

    def test_zero_resources(self):
        noresources = copy.deepcopy(template)
        noresources['resources']['group1']['properties']['count'] = 0
        resg = self._create_dummy_stack(noresources, expect_count=0)
        self.assertEqual((resg.CREATE, resg.COMPLETE), resg.state)

    def test_delete(self):
        """Test basic delete."""
        resg = self._create_dummy_stack()
        self.assertIsNotNone(resg.nested())
        scheduler.TaskRunner(resg.delete)()
        self.assertEqual((resg.DELETE, resg.COMPLETE), resg.nested().state)
        self.assertEqual((resg.DELETE, resg.COMPLETE), resg.state)

    def test_update(self):
        """Test basic update."""
        resg = self._create_dummy_stack()
        new_snip = copy.deepcopy(resg.t)
        new_snip['Properties']['count'] = 3
        scheduler.TaskRunner(resg.update, new_snip)()
        self.stack = resg.nested()
        self.assertEqual((resg.UPDATE, resg.COMPLETE), resg.state)
        self.assertEqual((resg.UPDATE, resg.COMPLETE), resg.nested().state)
        self.assertEqual(3, len(resg.nested()))

    def test_aggregate_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        expected = ['0', '1']
        self.assertEqual(expected, resg.FnGetAtt('foo'))
        self.assertEqual(expected, resg.FnGetAtt('Foo'))

    def test_index_dotted_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        self.assertEqual('0', resg.FnGetAtt('resource.0.Foo'))
        self.assertEqual('1', resg.FnGetAtt('resource.1.Foo'))

    def test_index_path_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        self.assertEqual('0', resg.FnGetAtt('resource.0', 'Foo'))
        self.assertEqual('1', resg.FnGetAtt('resource.1', 'Foo'))

    def test_index_deep_path_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack(template_attr)
        self.assertEqual(2, resg.FnGetAtt('resource.0',
                                          'nested_dict', 'dict', 'b'))
        self.assertEqual(2, resg.FnGetAtt('resource.1',
                                          'nested_dict', 'dict', 'b'))

    def test_aggregate_deep_path_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack(template_attr)
        expected = [3, 3]
        self.assertEqual(expected, resg.FnGetAtt('nested_dict', 'list', 2))

    def test_get_attr_path(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack(template_attr)
        expected = ['abc', 'abc']
        self.assertEqual(expected, resg.stack.output('nested_strings'))

    def test_aggregate_refs(self):
        """
        Test resource id aggregation
        """
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected, resg.FnGetAtt("refs"))

    def test_aggregate_outputs(self):
        """
        Test outputs aggregation
        """
        resg = self._create_dummy_stack(template_attr)
        expected = {'0': ['foo', 'bar'], '1': ['foo', 'bar']}
        self.assertEqual(expected, resg.FnGetAtt('attributes', 'list'))

    def test_aggregate_outputs_no_path(self):
        """
        Test outputs aggregation with missing path
        """
        resg = self._create_dummy_stack(template_attr)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          resg.FnGetAtt, 'attributes')

    def test_index_refs(self):
        """Tests getting ids of individual resources."""
        resg = self._create_dummy_stack()
        self.assertEqual("ID-0", resg.FnGetAtt('resource.0'))
        self.assertEqual("ID-1", resg.FnGetAtt('resource.1'))
        self.assertRaises(exception.InvalidTemplateAttribute, resg.FnGetAtt,
                          'resource.2')

    def _create_dummy_stack(self, template_data=template, expect_count=2):
        stack = utils.parse_stack(template_data)
        resg = stack['group1']
        scheduler.TaskRunner(resg.create)()
        self.stack = resg.nested()
        if expect_count > 0:
            self.assertEqual(expect_count, len(resg.nested()))
        else:
            self.assertIsNone(resg.nested())
        self.assertEqual((resg.CREATE, resg.COMPLETE), resg.state)
        return resg

    def test_child_template(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._assemble_nested = mock.Mock(return_value='tmpl')
        resgrp.properties.data[resgrp.COUNT] = 2

        self.assertEqual('tmpl', resgrp.child_template())
        resgrp._assemble_nested.assert_called_once_with(['0', '1'])

    def test_child_params(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertEqual({}, resgrp.child_params())
