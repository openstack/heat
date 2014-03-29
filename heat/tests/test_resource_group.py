
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


class ResourceWithPropsAndId(generic_resource.ResourceWithProps):

    def FnGetRefId(self):
        return "ID-%s" % self.name


class ResourceGroupTest(common.HeatTestCase):

    def setUp(self):
        common.HeatTestCase.setUp(self)
        resource._register_class("dummy.resource",
                                 ResourceWithPropsAndId)
        utils.setup_dummy_db()

    def test_assemble_nested(self):
        """
        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(template)
        snip = stack.t['Resources']['group1']
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

        self.assertEqual(templ, resg._assemble_nested(3))

    def test_assemble_nested_include(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = None
        stack = utils.parse_stack(templ)
        snip = stack.t['Resources']['group1']
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
        self.assertEqual(expect, resg._assemble_nested(1))
        expect['resources']["0"]['properties'] = {"Foo": None}
        self.assertEqual(expect, resg._assemble_nested(1, include_all=True))

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
        snip = stack.t['Resources']['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        exc = self.assertRaises(exception.StackValidationFailed,
                                resg.validate)
        self.assertIn('Unknown resource Type', str(exc))

    def test_reference_attr(self):
        stack = utils.parse_stack(template2)
        snip = stack.t['Resources']['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertIsNone(resgrp.validate())

    @utils.stack_delete_after
    def test_delete(self):
        """Test basic delete."""
        resg = self._create_dummy_stack()
        self.assertIsNotNone(resg.nested())
        scheduler.TaskRunner(resg.delete)()
        self.assertEqual((resg.DELETE, resg.COMPLETE), resg.nested().state)
        self.assertEqual((resg.DELETE, resg.COMPLETE), resg.state)

    @utils.stack_delete_after
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

    @utils.stack_delete_after
    def test_aggregate_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        expected = ['0', '1']
        self.assertEqual(expected, resg.FnGetAtt('foo'))
        self.assertEqual(expected, resg.FnGetAtt('Foo'))

    @utils.stack_delete_after
    def test_aggregate_refs(self):
        """
        Test resource id aggregation
        """
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected, resg.FnGetAtt("refs"))

    @utils.stack_delete_after
    def test_index_refs(self):
        """Tests getting ids of individual resources."""
        resg = self._create_dummy_stack()
        self.assertEqual("ID-0", resg.FnGetAtt('resource.0'))
        self.assertEqual("ID-1", resg.FnGetAtt('resource.1'))
        self.assertRaises(exception.InvalidTemplateAttribute, resg.FnGetAtt,
                          'resource.2')

    def _create_dummy_stack(self):
        stack = utils.parse_stack(template)
        snip = stack.t['Resources']['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        scheduler.TaskRunner(resg.create)()
        self.stack = resg.nested()
        self.assertEqual(2, len(resg.nested()))
        self.assertEqual((resg.CREATE, resg.COMPLETE), resg.state)
        return resg

    def test_child_template(self):
        stack = utils.parse_stack(template2)
        snip = stack.t['Resources']['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._assemble_nested = mock.Mock(return_value='tmpl')
        resgrp.properties.data[resgrp.COUNT] = 2

        self.assertEqual('tmpl', resgrp.child_template())
        resgrp._assemble_nested.assert_called_once_with(2)

    def test_child_params(self):
        stack = utils.parse_stack(template2)
        snip = stack.t['Resources']['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertEqual({}, resgrp.child_params())
