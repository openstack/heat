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
from heat.engine.resources.openstack.heat import resource_group
from heat.engine import stack as stackm
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
        self.m.StubOutWithMock(stackm.Stack, 'validate')

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

    def test_assemble_nested_zero(self):
        templ = copy.deepcopy(template)
        templ['resources']['group1']['properties']['count'] = 0
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2013-05-23",
            "resources": {}
        }
        self.assertEqual(expect, resg._assemble_nested([]))

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
        exc = self.assertRaises(exception.ResourceTypeNotFound,
                                resg.validate)
        exp_msg = 'The Resource Type (idontexist) could not be found.'
        self.assertIn(exp_msg, six.text_type(exc))

    def test_reference_attr(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertIsNone(resgrp.validate())

    def test_invalid_removal_policies_nolist(self):
        """Test that error raised for malformed removal_policies."""
        tmp = copy.deepcopy(template)
        grp_props = tmp['resources']['group1']['properties']
        grp_props['removal_policies'] = 'notallowed'
        stack = utils.parse_stack(tmp)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        exc = self.assertRaises(exception.StackValidationFailed,
                                resg.validate)
        errstr = "removal_policies: \"'notallowed'\" is not a list"
        self.assertIn(errstr, six.text_type(exc))

    def test_invalid_removal_policies_nomap(self):
        """Test that error raised for malformed removal_policies."""
        tmp = copy.deepcopy(template)
        grp_props = tmp['resources']['group1']['properties']
        grp_props['removal_policies'] = ['notallowed']
        stack = utils.parse_stack(tmp)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        exc = self.assertRaises(exception.StackValidationFailed,
                                resg.validate)
        errstr = '"notallowed" is not a map'
        self.assertIn(errstr, six.text_type(exc))

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


class ResourceGroupBlackList(common.HeatTestCase):
    """This class tests ResourceGroup._name_blacklist()."""

    # 1) no resource_list, empty blacklist
    # 2) no resource_list, existing blacklist
    # 3) resource_list not in nested()
    # 4) resource_list (refid) not in nested()
    # 5) resource_list in nested() -> saved
    # 6) resource_list (refid) in nested() -> saved
    scenarios = [
        ('1', dict(data_in=None, rm_list=[],
                   nested_rsrcs={}, expected=[],
                   saved=False)),
        ('2', dict(data_in='0,1,2', rm_list=[],
                   nested_rsrcs={}, expected=['0', '1', '2'],
                   saved=False)),
        ('3', dict(data_in='1,3', rm_list=['6'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['1', '3'],
                   saved=False)),
        ('4', dict(data_in='0,1', rm_list=['id-7'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1'],
                   saved=False)),
        ('5', dict(data_in='0,1', rm_list=['3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1', '3'],
                   saved=True)),
        ('6', dict(data_in='0,1', rm_list=['id-3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1', '3'],
                   saved=True)),
    ]

    def test_blacklist(self):
        stack = utils.parse_stack(template)
        resg = stack['group1']

        # mock properties
        resg.properties = mock.MagicMock()
        resg.properties.__getitem__.return_value = [
            {'resource_list': self.rm_list}]

        # mock data get/set
        resg.data = mock.Mock()
        resg.data.return_value.get.return_value = self.data_in
        resg.data_set = mock.Mock()

        # mock nested access
        def stack_contains(name):
            return name in self.nested_rsrcs

        def by_refid(name):
            rid = name.replace('id-', '')
            if rid not in self.nested_rsrcs:
                return None
            res = mock.Mock()
            res.name = rid
            return res

        nested = mock.MagicMock()
        nested.__contains__.side_effect = stack_contains
        nested.resource_by_refid.side_effect = by_refid
        resg.nested = mock.Mock(return_value=nested)

        self.assertEqual(self.expected, resg._name_blacklist())
        if self.saved:
            resg.data_set.assert_called_once_with('name_blacklist',
                                                  ','.join(self.expected))


class ResourceGroupEmptyParams(common.HeatTestCase):
    """This class tests ResourceGroup._build_resource_definition()."""

    scenarios = [
        ('non_empty', dict(value='Bar', expected={'Foo': 'Bar'},
                           expected_include={'Foo': 'Bar'})),
        ('empty_None', dict(value=None, expected={},
                            expected_include={'Foo': None})),
        ('empty_boolean', dict(value=False, expected={'Foo': False},
                               expected_include={'Foo': False})),
        ('empty_string', dict(value='', expected={'Foo': ''},
                              expected_include={'Foo': ''})),
        ('empty_number', dict(value=0, expected={'Foo': 0},
                              expected_include={'Foo': 0})),
        ('empty_json', dict(value={}, expected={'Foo': {}},
                            expected_include={'Foo': {}})),
        ('empty_list', dict(value=[], expected={'Foo': []},
                            expected_include={'Foo': []}))
    ]

    def test_definition(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = self.value
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        exp1 = {
            "type": "dummy.resource",
            "properties": self.expected,
        }
        exp2 = {
            "type": "dummy.resource",
            "properties": self.expected_include,
        }
        self.assertEqual(exp1, resg._build_resource_definition())
        self.assertEqual(
            exp2, resg._build_resource_definition(include_all=True))


class ResourceGroupNameListTest(common.HeatTestCase):
    """This class tests ResourceGroup._resource_names()."""

    # 1) no blacklist, 0 count
    # 2) no blacklist, x count
    # 3) blacklist (not effecting)
    # 4) blacklist with pruning
    scenarios = [
        ('1', dict(blacklist=[], count=0,
                   expected=[])),
        ('2', dict(blacklist=[], count=4,
                   expected=['0', '1', '2', '3'])),
        ('3', dict(blacklist=['5', '6'], count=3,
                   expected=['0', '1', '2'])),
        ('4', dict(blacklist=['2', '4'], count=4,
                   expected=['0', '1', '3', '5'])),
    ]

    def test_names(self):
        stack = utils.parse_stack(template)
        resg = stack['group1']

        resg.properties = mock.MagicMock()
        resg.properties.get.return_value = self.count
        resg._name_blacklist = mock.MagicMock(return_value=self.blacklist)
        self.assertEqual(self.expected, resg._resource_names())


class ResourceGroupAttrTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceGroupAttrTest, self).setUp()
        resource._register_class("dummy.resource",
                                 ResourceWithPropsAndId)
        AttributeResource = generic_resource.ResourceWithComplexAttributes
        resource._register_class("dummyattr.resource",
                                 AttributeResource)

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
        resg = self._create_dummy_stack(template_attr,
                                        expect_attrs={'0': 2, '1': 2})
        self.assertEqual(2, resg.FnGetAtt('resource.0',
                                          'nested_dict', 'dict', 'b'))
        self.assertEqual(2, resg.FnGetAtt('resource.1',
                                          'nested_dict', 'dict', 'b'))

    def test_aggregate_deep_path_attribs(self):
        """
        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack(template_attr,
                                        expect_attrs={'0': 3, '1': 3})
        expected = [3, 3]
        self.assertEqual(expected, resg.FnGetAtt('nested_dict', 'list', 2))

    def test_aggregate_refs(self):
        """
        Test resource id aggregation
        """
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected, resg.FnGetAtt("refs"))

    def test_aggregate_refs_with_index(self):
        """
        Test resource id aggregation with index
        """
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected[0], resg.FnGetAtt("refs", 0))
        self.assertEqual(expected[1], resg.FnGetAtt("refs", 1))
        self.assertIsNone(resg.FnGetAtt("refs", 2))

    def test_aggregate_outputs(self):
        """
        Test outputs aggregation
        """
        expected = {'0': ['foo', 'bar'], '1': ['foo', 'bar']}
        resg = self._create_dummy_stack(template_attr, expect_attrs=expected)
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

    def _create_dummy_stack(self, template_data=template, expect_count=2,
                            expect_attrs=None):
        stack = utils.parse_stack(template_data)
        resg = stack['group1']
        fake_res = {}
        if expect_attrs is None:
            expect_attrs = {}
        for resc in range(expect_count):
            res = str(resc)
            fake_res[res] = mock.Mock()
            fake_res[res].FnGetRefId.return_value = 'ID-%s' % res
            if res in expect_attrs:
                fake_res[res].FnGetAtt.return_value = expect_attrs[res]
            else:
                fake_res[res].FnGetAtt.return_value = res
        resg.nested = mock.Mock(return_value=fake_res)

        names = [str(name) for name in range(expect_count)]
        resg._resource_names = mock.Mock(return_value=names)
        return resg
