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
from heat.common import grouputils
from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine import node_data
from heat.engine.resources.openstack.heat import resource_group
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils

template = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "OverwrittenFnGetRefIdType",
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
            "type": "OverwrittenFnGetRefIdType",
            "properties": {
                "Foo": "baz"
            }
        },
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "OverwrittenFnGetRefIdType",
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
                    "type": "ResourceWithListProp%index%",
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
                    "type": "ResourceWithComplexAttributesType",
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

template_server = {
    "heat_template_version": "2013-05-23",
    "resources": {
        "group1": {
            "type": "OS::Heat::ResourceGroup",
            "properties": {
                "count": 2,
                "resource_def": {
                    "type": "OS::Nova::Server",
                    "properties": {
                        "image": "image%index%",
                        "flavor": "flavor%index%"
                    }
                }
            }
        }
    }
}


class ResourceGroupTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceGroupTest, self).setUp()

        self.inspector = mock.Mock(spec=grouputils.GroupInspector)
        self.patchobject(grouputils.GroupInspector, 'from_parent_resource',
                         return_value=self.inspector)

    def test_assemble_nested(self):
        """Tests nested stack creation based on props.

        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        templ = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "2": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                        "2": {"get_resource": "2"},
                    }
                }
            }
        }

        self.assertEqual(templ, resg._assemble_nested(['0', '1', '2']).t)

    def test_assemble_nested_outputs(self):
        """Tests nested stack creation based on props.

        Tests that the nested stack that implements the group is created
        appropriately based on properties.
        """
        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        templ = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                },
                "2": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "Foo": "Bar"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                        "2": {"get_resource": "2"},
                    }
                },
                "foo": {
                    "value": [
                        {"get_attr": ["0", "foo"]},
                        {"get_attr": ["1", "foo"]},
                        {"get_attr": ["2", "foo"]},
                    ]
                }
            }
        }

        resg.referenced_attrs = mock.Mock(return_value=["foo"])
        self.assertEqual(templ, resg._assemble_nested(['0', '1', '2']).t)

    def test_assemble_nested_include(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = None
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {}
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                    }
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0']).t)
        expect['resources']["0"]['properties'] = {"Foo": None}
        self.assertEqual(
            expect, resg._assemble_nested(['0'], include_all=True).t)

    def test_assemble_nested_include_zero(self):
        templ = copy.deepcopy(template)
        templ['resources']['group1']['properties']['count'] = 0
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "outputs": {"refs_map": {"value": {}}},
        }
        self.assertEqual(expect, resg._assemble_nested([]).t)

    def test_assemble_nested_with_metadata(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        res_def['properties']['Foo'] = None
        res_def['metadata'] = {
            'priority': 'low',
            'role': 'webserver'
        }
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {},
                    "metadata": {
                        'priority': 'low',
                        'role': 'webserver'
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                    }
                }
            }
        }
        self.assertEqual(expect, resg._assemble_nested(['0']).t)

    def test_assemble_nested_rolling_update(self):
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "bar"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "baz"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                    }
                }
            }
        }
        resource_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "baz"})

        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        nested = get_fake_nested_stack(['0', '1'])
        self.inspector.template.return_value = nested.defn._template
        self.inspector.member_names.return_value = ['0', '1']
        resg.build_resource_definition = mock.Mock(return_value=resource_def)
        self.assertEqual(expect, resg._assemble_for_rolling_update(2, 1).t)

    def test_assemble_nested_rolling_update_outputs(self):
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "bar"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "baz"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                    }
                },
                "bar": {
                    "value": [
                        {"get_attr": ["0", "bar"]},
                        {"get_attr": ["1", "bar"]},
                    ]
                }
            }
        }
        resource_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "baz"})

        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        nested = get_fake_nested_stack(['0', '1'])
        self.inspector.template.return_value = nested.defn._template
        self.inspector.member_names.return_value = ['0', '1']
        resg.build_resource_definition = mock.Mock(return_value=resource_def)
        resg.referenced_attrs = mock.Mock(return_value=["bar"])
        self.assertEqual(expect, resg._assemble_for_rolling_update(2, 1).t)

    def test_assemble_nested_rolling_update_none(self):
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "bar"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "bar"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                    }
                }
            }
        }

        resource_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "baz"})

        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        nested = get_fake_nested_stack(['0', '1'])
        self.inspector.template.return_value = nested.defn._template
        self.inspector.member_names.return_value = ['0', '1']
        resg.build_resource_definition = mock.Mock(return_value=resource_def)
        self.assertEqual(expect, resg._assemble_for_rolling_update(2, 0).t)

    def test_assemble_nested_rolling_update_failed_resource(self):
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "baz"
                    }
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {
                        "foo": "bar"
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                    }
                }
            }
        }
        resource_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "baz"})

        stack = utils.parse_stack(template)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        nested = get_fake_nested_stack(['0', '1'])
        self.inspector.template.return_value = nested.defn._template
        self.inspector.member_names.return_value = ['1']
        resg.build_resource_definition = mock.Mock(return_value=resource_def)
        self.assertEqual(expect, resg._assemble_for_rolling_update(2, 1).t)

    def test_assemble_nested_missing_param(self):
        # Setup

        # Change the standard testing template to use a get_param lookup
        # within the resource definition
        templ = copy.deepcopy(template)
        res_def = templ['resources']['group1']['properties']['resource_def']
        res_def['properties']['Foo'] = {'get_param': 'bar'}

        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)

        # Test - This should not raise a ValueError about "bar" not being
        # provided
        nested_tmpl = resg._assemble_nested(['0', '1'])

        # Verify
        expected = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {}
                },
                "1": {
                    "type": "OverwrittenFnGetRefIdType",
                    "properties": {}
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                    }
                }
            }
        }
        self.assertEqual(expected, nested_tmpl.t)

    def test_index_var(self):
        stack = utils.parse_stack(template_repl)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "ResourceWithListProp%index%",
                    "properties": {
                        "Foo": "Bar_0",
                        "listprop": [
                            "0_0", "0_1", "0_2"
                        ]
                    }
                },
                "1": {
                    "type": "ResourceWithListProp%index%",
                    "properties": {
                        "Foo": "Bar_1",
                        "listprop": [
                            "1_0", "1_1", "1_2"
                        ]
                    }
                },

                "2": {
                    "type": "ResourceWithListProp%index%",
                    "properties": {
                        "Foo": "Bar_2",
                        "listprop": [
                            "2_0", "2_1", "2_2"
                        ]
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                        "1": {"get_resource": "1"},
                        "2": {"get_resource": "2"},
                    }
                }
            }
        }
        nested = resg._assemble_nested(['0', '1', '2']).t
        for res in nested['resources']:
            res_prop = nested['resources'][res]['properties']
            res_prop['listprop'] = list(res_prop['listprop'])
        self.assertEqual(expect, nested)

    def test_custom_index_var(self):
        templ = copy.deepcopy(template_repl)
        templ['resources']['group1']['properties']['index_var'] = "__foo__"
        stack = utils.parse_stack(templ)
        snip = stack.t.resource_definitions(stack)['group1']
        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "ResourceWithListProp%index%",
                    "properties": {
                        "Foo": "Bar_%index%",
                        "listprop": [
                            "%index%_0", "%index%_1", "%index%_2"
                        ]
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                    }
                }
            }
        }
        nested = resg._assemble_nested(['0']).t
        res_prop = nested['resources']['0']['properties']
        res_prop['listprop'] = list(res_prop['listprop'])
        self.assertEqual(expect, nested)

        props = copy.deepcopy(templ['resources']['group1']['properties'])
        res_def = props['resource_def']
        res_def['properties']['Foo'] = "Bar___foo__"
        res_def['properties']['listprop'] = ["__foo___0",
                                             "__foo___1",
                                             "__foo___2"]
        res_def['type'] = "ResourceWithListProp__foo__"
        snip = snip.freeze(properties=props)

        resg = resource_group.ResourceGroup('test', snip, stack)
        expect = {
            "heat_template_version": "2015-04-30",
            "resources": {
                "0": {
                    "type": "ResourceWithListProp__foo__",
                    "properties": {
                        "Foo": "Bar_0",
                        "listprop": [
                            "0_0", "0_1", "0_2"
                        ]
                    }
                }
            },
            "outputs": {
                "refs_map": {
                    "value": {
                        "0": {"get_resource": "0"},
                    }
                }
            }
        }
        nested = resg._assemble_nested(['0']).t
        res_prop = nested['resources']['0']['properties']
        res_prop['listprop'] = list(res_prop['listprop'])
        self.assertEqual(expect, nested)

    def test_assemble_no_properties(self):
        templ = copy.deepcopy(template)
        res_def = templ["resources"]["group1"]["properties"]['resource_def']
        del res_def['properties']
        stack = utils.parse_stack(templ)
        resg = stack.resources['group1']
        self.assertIsNone(resg.validate())

    def test_validate_with_blacklist(self):
        templ = copy.deepcopy(template_server)
        self.mock_flavor = mock.Mock(ram=4, disk=4)
        self.mock_active_image = mock.Mock(min_ram=1, min_disk=1,
                                           status='active')
        self.mock_inactive_image = mock.Mock(min_ram=1, min_disk=1,
                                             status='inactive')

        def get_image(image_identifier):
            if image_identifier == 'image0':
                return self.mock_inactive_image
            else:
                return self.mock_active_image

        self.patchobject(glance.GlanceClientPlugin, 'get_image',
                         side_effect=get_image)
        self.patchobject(nova.NovaClientPlugin, 'get_flavor',
                         return_value=self.mock_flavor)
        props = templ["resources"]["group1"]["properties"]
        props["removal_policies"] = [{"resource_list": ["0"]}]
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
        exp_msg = 'The Resource Type (idontexist) could not be found.'
        self.assertIn(exp_msg, six.text_type(exc))

    def test_reference_attr(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertIsNone(resgrp.validate())

    def test_validate_reference_attr_with_none_ref(self):
        stack = utils.parse_stack(template_attr)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.patchobject(resgrp, 'referenced_attrs',
                         return_value=set([('nested_dict', None)]))
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

        def check_res_names(names):
            self.assertEqual(list(names), ['0', '1'])
            return 'tmpl'

        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._assemble_nested = mock.Mock()
        resgrp._assemble_nested.side_effect = check_res_names
        resgrp.properties.data[resgrp.COUNT] = 2

        self.assertEqual('tmpl', resgrp.child_template())
        self.assertEqual(1, resgrp._assemble_nested.call_count)

    def test_child_params(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.assertEqual({}, resgrp.child_params())

    def test_handle_create(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp.create_with_template = mock.Mock(return_value=None)
        self.assertIsNone(resgrp.handle_create())
        self.assertEqual(1, resgrp.create_with_template.call_count)

    def test_handle_create_with_batching(self):
        self.inspector.member_names.return_value = []
        self.inspector.size.return_value = 0
        stack = utils.parse_stack(tmpl_with_default_updt_policy())
        defn = stack.t.resource_definitions(stack)['group1']
        props = stack.t.t['resources']['group1']['properties'].copy()
        props['count'] = 10
        update_policy = {'batch_create': {'max_batch_size': 3}}
        snip = defn.freeze(properties=props, update_policy=update_policy)
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        self.patchobject(scheduler.TaskRunner, 'start')
        checkers = resgrp.handle_create()
        self.assertEqual(4, len(checkers))

    def test_handle_create_with_batching_zero_count(self):
        self.inspector.member_names.return_value = []
        self.inspector.size.return_value = 0
        stack = utils.parse_stack(tmpl_with_default_updt_policy())
        defn = stack.t.resource_definitions(stack)['group1']
        props = stack.t.t['resources']['group1']['properties'].copy()
        props['count'] = 0
        update_policy = {'batch_create': {'max_batch_size': 1}}
        snip = defn.freeze(properties=props, update_policy=update_policy)
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp.create_with_template = mock.Mock(return_value=None)
        self.assertIsNone(resgrp.handle_create())
        self.assertEqual(1, resgrp.create_with_template.call_count)

    def test_run_to_completion(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._check_status_complete = mock.Mock(side_effect=[False, True])
        resgrp.update_with_template = mock.Mock(return_value=None)
        next(resgrp._run_to_completion(snip, 200))
        self.assertEqual(1, resgrp.update_with_template.call_count)

    def test_update_in_failed(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp.state_set('CREATE', 'FAILED')
        resgrp._assemble_nested = mock.Mock(return_value='tmpl')
        resgrp.properties.data[resgrp.COUNT] = 2
        self.patchobject(scheduler.TaskRunner, 'start')
        resgrp.handle_update(snip, mock.Mock(), {})
        self.assertTrue(resgrp._assemble_nested.called)

    def test_handle_delete(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp.delete_nested = mock.Mock(return_value=None)
        resgrp.handle_delete()
        resgrp.delete_nested.assert_called_once_with()

    def test_handle_update_size(self):
        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._assemble_nested = mock.Mock(return_value=None)
        resgrp.properties.data[resgrp.COUNT] = 5
        self.patchobject(scheduler.TaskRunner, 'start')
        resgrp.handle_update(snip, mock.Mock(), {})
        self.assertTrue(resgrp._assemble_nested.called)


class ResourceGroupBlackList(common.HeatTestCase):
    """This class tests ResourceGroup._name_blacklist()."""

    # 1) no resource_list, empty blacklist
    # 2) no resource_list, existing blacklist
    # 3) resource_list not in nested()
    # 4) resource_list (refid) not in nested()
    # 5) resource_list in nested() -> saved
    # 6) resource_list (refid) in nested() -> saved
    # 7) resource_list (refid) in nested(), update -> saved
    # 8) resource_list, update -> saved
    # 9) resource_list (refid) in nested(), grouputils fallback -> saved
    # A) resource_list (refid) in nested(), update, grouputils -> saved
    scenarios = [
        ('1', dict(data_in=None, rm_list=[],
                   nested_rsrcs=[], expected=[],
                   saved=False, fallback=False, rm_mode='append')),
        ('2', dict(data_in='0,1,2', rm_list=[],
                   nested_rsrcs=[], expected=['0', '1', '2'],
                   saved=False, fallback=False, rm_mode='append')),
        ('3', dict(data_in='1,3', rm_list=['6'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['1', '3'],
                   saved=False, fallback=False, rm_mode='append')),
        ('4', dict(data_in='0,1', rm_list=['id-7'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1'],
                   saved=False, fallback=False, rm_mode='append')),
        ('5', dict(data_in='0,1', rm_list=['3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1', '3'],
                   saved=True, fallback=False, rm_mode='append')),
        ('6', dict(data_in='0,1', rm_list=['id-3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1', '3'],
                   saved=True, fallback=False, rm_mode='append')),
        ('7', dict(data_in='0,1', rm_list=['id-3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['3'],
                   saved=True, fallback=False, rm_mode='update')),
        ('8', dict(data_in='1', rm_list=[],
                   nested_rsrcs=['0', '1', '2'],
                   expected=[],
                   saved=True, fallback=False, rm_mode='update')),
        ('9', dict(data_in='0,1', rm_list=['id-3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['0', '1', '3'],
                   saved=True, fallback=True, rm_mode='append')),
        ('A', dict(data_in='0,1', rm_list=['id-3'],
                   nested_rsrcs=['0', '1', '3'],
                   expected=['3'],
                   saved=True, fallback=True, rm_mode='update')),
    ]

    def test_blacklist(self):
        stack = utils.parse_stack(template)
        resg = stack['group1']

        if self.data_in is not None:
            resg.resource_id = 'foo'

        # mock properties
        properties = mock.MagicMock()
        p_data = {'removal_policies': [{'resource_list': self.rm_list}],
                  'removal_policies_mode': self.rm_mode}
        properties.get.side_effect = p_data.get

        # mock data get/set
        resg.data = mock.Mock()
        resg.data.return_value.get.return_value = self.data_in
        resg.data_set = mock.Mock()

        # mock nested access
        mock_inspect = mock.Mock()
        self.patchobject(grouputils.GroupInspector, 'from_parent_resource',
                         return_value=mock_inspect)
        mock_inspect.member_names.return_value = self.nested_rsrcs

        if not self.fallback:
            refs_map = {n: 'id-%s' % n for n in self.nested_rsrcs}
            resg.get_output = mock.Mock(return_value=refs_map)
        else:
            resg.get_output = mock.Mock(side_effect=exception.NotFound)

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
            nested.__iter__.side_effect = iter(self.nested_rsrcs)
            nested.resource_by_refid.side_effect = by_refid
            resg.nested = mock.Mock(return_value=nested)

        resg._update_name_blacklist(properties)
        if self.saved:
            resg.data_set.assert_called_once_with('name_blacklist',
                                                  ','.join(self.expected))
        else:
            resg.data_set.assert_not_called()
            self.assertEqual(set(self.expected), resg._name_blacklist())


class ResourceGroupEmptyParams(common.HeatTestCase):
    """This class tests ResourceGroup.build_resource_definition()."""

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
        exp1 = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            self.expected)

        exp2 = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            self.expected_include)

        rdef = resg.get_resource_def()
        self.assertEqual(exp1, resg.build_resource_definition('0', rdef))
        rdef = resg.get_resource_def(include_all=True)
        self.assertEqual(
            exp2, resg.build_resource_definition('0', rdef))


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
        self.assertEqual(self.expected, list(resg._resource_names()))


class ResourceGroupAttrTest(common.HeatTestCase):

    def test_aggregate_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        expected = ['0', '1']
        self.assertEqual(expected, resg.FnGetAtt('foo'))
        self.assertEqual(expected, resg.FnGetAtt('Foo'))

    def test_index_dotted_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        self.assertEqual('0', resg.FnGetAtt('resource.0.Foo'))
        self.assertEqual('1', resg.FnGetAtt('resource.1.Foo'))

    def test_index_path_attribs(self):
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack()
        self.assertEqual('0', resg.FnGetAtt('resource.0', 'Foo'))
        self.assertEqual('1', resg.FnGetAtt('resource.1', 'Foo'))

    def test_index_deep_path_attribs(self):
        """Test attribute aggregation.

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
        """Test attribute aggregation.

        Test attribute aggregation and that we mimic the nested resource's
        attributes.
        """
        resg = self._create_dummy_stack(template_attr,
                                        expect_attrs={'0': 3, '1': 3})
        expected = [3, 3]
        self.assertEqual(expected, resg.FnGetAtt('nested_dict', 'list', 2))

    def test_aggregate_refs(self):
        """Test resource id aggregation."""
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected, resg.FnGetAtt("refs"))

    def test_aggregate_refs_with_index(self):
        """Test resource id aggregation with index."""
        resg = self._create_dummy_stack()
        expected = ['ID-0', 'ID-1']
        self.assertEqual(expected[0], resg.FnGetAtt("refs", 0))
        self.assertEqual(expected[1], resg.FnGetAtt("refs", 1))
        self.assertIsNone(resg.FnGetAtt("refs", 2))

    def test_aggregate_refs_map(self):
        resg = self._create_dummy_stack()
        found = resg.FnGetAtt("refs_map")
        expected = {'0': 'ID-0', '1': 'ID-1'}
        self.assertEqual(expected, found)

    def test_aggregate_outputs(self):
        """Test outputs aggregation."""
        expected = {'0': ['foo', 'bar'], '1': ['foo', 'bar']}
        resg = self._create_dummy_stack(template_attr, expect_attrs=expected)
        self.assertEqual(expected, resg.FnGetAtt('attributes', 'list'))

    def test_aggregate_outputs_no_path(self):
        """Test outputs aggregation with missing path."""
        resg = self._create_dummy_stack(template_attr)
        self.assertRaises(exception.InvalidTemplateAttribute,
                          resg.FnGetAtt, 'attributes')

    def test_index_refs(self):
        """Tests getting ids of individual resources."""
        resg = self._create_dummy_stack()
        self.assertEqual("ID-0", resg.FnGetAtt('resource.0'))
        self.assertEqual("ID-1", resg.FnGetAtt('resource.1'))
        ex = self.assertRaises(exception.NotFound, resg.FnGetAtt,
                               'resource.2')
        self.assertIn("Member '2' not found in group resource 'group1'.",
                      six.text_type(ex))

    def test_get_attribute_convg(self):
        cache_data = {'group1': node_data.NodeData.from_dict({
            'uuid': mock.ANY,
            'id': mock.ANY,
            'action': 'CREATE',
            'status': 'COMPLETE',
            'attrs': {'refs': ['rsrc1', 'rsrc2']}
        })}
        stack = utils.parse_stack(template, cache_data=cache_data)
        rsrc = stack.defn['group1']
        self.assertEqual(['rsrc1', 'rsrc2'], rsrc.FnGetAtt('refs'))

    def test_get_attribute_blacklist(self):
        resg = self._create_dummy_stack()
        resg.data = mock.Mock(return_value={'name_blacklist': '3,5'})

        expected = ['3', '5']
        self.assertEqual(expected, resg.FnGetAtt(resg.REMOVED_RSRC_LIST))

    def _create_dummy_stack(self, template_data=template, expect_count=2,
                            expect_attrs=None):
        stack = utils.parse_stack(template_data)
        resg = stack['group1']
        resg.resource_id = 'test-test'
        attrs = {}
        refids = {}
        if expect_attrs is None:
            expect_attrs = {}
        for index in range(expect_count):
            res = str(index)
            attrs[index] = expect_attrs.get(res, res)
            refids[index] = 'ID-%s' % res

        names = [str(name) for name in range(expect_count)]
        resg._resource_names = mock.Mock(return_value=names)
        self._stub_get_attr(resg, refids, attrs)
        return resg

    def _stub_get_attr(self, resg, refids, attrs):
        def ref_id_fn(res_name):
            return refids[int(res_name)]

        def attr_fn(args):
            res_name = args[0]
            return attrs[int(res_name)]

        def get_output(output_name):
            outputs = resg._nested_output_defns(resg._resource_names(),
                                                attr_fn, ref_id_fn)
            op_defns = {od.name: od for od in outputs}
            self.assertIn(output_name, op_defns)
            return op_defns[output_name].get_value()

        orig_get_attr = resg.FnGetAtt

        def get_attr(attr_name, *path):
            if not path:
                attr = attr_name
            else:
                attr = (attr_name,) + path
            # Mock referenced_attrs() so that _nested_output_definitions()
            # will include the output required for this attribute
            resg.referenced_attrs = mock.Mock(return_value=[attr])

            # Pass through to actual function under test
            return orig_get_attr(attr_name, *path)

        resg.FnGetAtt = mock.Mock(side_effect=get_attr)
        resg.get_output = mock.Mock(side_effect=get_output)


class ResourceGroupAttrFallbackTest(ResourceGroupAttrTest):
    def _stub_get_attr(self, resg, refids, attrs):
        # Raise NotFound when getting output, to force fallback to old-school
        # grouputils functions
        resg.get_output = mock.Mock(side_effect=exception.NotFound)

        def make_fake_res(idx):
            fr = mock.Mock()
            fr.stack = resg.stack
            fr.FnGetRefId.return_value = refids[idx]
            fr.FnGetAtt.return_value = attrs[idx]
            return fr

        fake_res = {str(i): make_fake_res(i) for i in refids}
        resg.nested = mock.Mock(return_value=fake_res)

    @mock.patch.object(grouputils, 'get_rsrc_id')
    def test_get_attribute(self, mock_get_rsrc_id):
        stack = utils.parse_stack(template)
        mock_get_rsrc_id.side_effect = ['0', '1']
        rsrc = stack['group1']
        rsrc.get_output = mock.Mock(side_effect=exception.NotFound)
        self.assertEqual(['0', '1'], rsrc.FnGetAtt(rsrc.REFS))


class ReplaceTest(common.HeatTestCase):
    # 1. no min_in_service
    # 2. min_in_service > count and existing with no blacklist
    # 3. min_in_service > count and existing with blacklist
    # 4. existing > count and min_in_service with blacklist
    # 5. existing > count and min_in_service with no blacklist
    # 6. all existing blacklisted
    # 7. count > existing and min_in_service with no blacklist
    # 8. count > existing and min_in_service with blacklist
    # 9. count < existing - blacklisted
    # 10. pause_sec > 0

    scenarios = [
        ('1', dict(min_in_service=0, count=2,
                   existing=['0', '1'], black_listed=['0'],
                   batch_size=1, pause_sec=0, tasks=2)),
        ('2', dict(min_in_service=3, count=2,
                   existing=['0', '1'], black_listed=[],
                   batch_size=2, pause_sec=0, tasks=3)),
        ('3', dict(min_in_service=3, count=2,
                   existing=['0', '1'], black_listed=['0'],
                   batch_size=2, pause_sec=0, tasks=3)),
        ('4', dict(min_in_service=3, count=2,
                   existing=['0', '1', '2', '3'], black_listed=['2', '3'],
                   batch_size=1, pause_sec=0, tasks=4)),
        ('5', dict(min_in_service=2, count=2,
                   existing=['0', '1', '2', '3'], black_listed=[],
                   batch_size=2, pause_sec=0, tasks=2)),
        ('6', dict(min_in_service=2, count=3,
                   existing=['0', '1'], black_listed=['0', '1'],
                   batch_size=2, pause_sec=0, tasks=2)),
        ('7', dict(min_in_service=0, count=5,
                   existing=['0', '1'], black_listed=[],
                   batch_size=1, pause_sec=0, tasks=5)),
        ('8', dict(min_in_service=0, count=5,
                   existing=['0', '1'], black_listed=['0'],
                   batch_size=1, pause_sec=0, tasks=5)),
        ('9', dict(min_in_service=0, count=3,
                   existing=['0', '1', '2', '3', '4', '5'],
                   black_listed=['0'],
                   batch_size=2, pause_sec=0, tasks=2)),
        ('10', dict(min_in_service=0, count=3,
                    existing=['0', '1', '2', '3', '4', '5'],
                    black_listed=['0'],
                    batch_size=2, pause_sec=10, tasks=3))]

    def setUp(self):
        super(ReplaceTest, self).setUp()
        templ = copy.deepcopy(template)
        self.stack = utils.parse_stack(templ)
        snip = self.stack.t.resource_definitions(self.stack)['group1']
        self.group = resource_group.ResourceGroup('test', snip, self.stack)
        self.group.update_with_template = mock.Mock()
        self.group.check_update_complete = mock.Mock()

        inspector = mock.Mock(spec=grouputils.GroupInspector)
        self.patchobject(grouputils.GroupInspector, 'from_parent_resource',
                         return_value=inspector)
        inspector.member_names.return_value = self.existing
        inspector.size.return_value = len(self.existing)

    def test_rolling_updates(self):
        self.group._nested = get_fake_nested_stack(self.existing)
        self.group.get_size = mock.Mock(return_value=self.count)
        self.group._name_blacklist = mock.Mock(
            return_value=set(self.black_listed))
        tasks = self.group._replace(self.min_in_service, self.batch_size,
                                    self.pause_sec)
        self.assertEqual(self.tasks, len(tasks))


def tmpl_with_bad_updt_policy():
    t = copy.deepcopy(template)
    rg = t['resources']['group1']
    rg["update_policy"] = {"foo": {}}
    return t


def tmpl_with_default_updt_policy():
    t = copy.deepcopy(template)
    rg = t['resources']['group1']
    rg["update_policy"] = {"rolling_update": {}}
    return t


def tmpl_with_updt_policy():
    t = copy.deepcopy(template)
    rg = t['resources']['group1']
    rg["update_policy"] = {"rolling_update": {
        "min_in_service": "1",
        "max_batch_size": "2",
        "pause_time": "1"
    }}
    return t


def get_fake_nested_stack(names):
    nested_t = '''
    heat_template_version: 2015-04-30
    description: Resource Group
    resources:
    '''
    resource_snip = '''
      '%s':
        type: OverwrittenFnGetRefIdType
        properties:
          foo: bar
    '''
    resources = [nested_t]
    for res_name in names:
        resources.extend([resource_snip % res_name])

    nested_t = ''.join(resources)
    return utils.parse_stack(template_format.parse(nested_t))


class RollingUpdatePolicyTest(common.HeatTestCase):

    def test_parse_without_update_policy(self):
        stack = utils.parse_stack(template)
        stack.validate()
        grp = stack['group1']
        self.assertFalse(grp.update_policy['rolling_update'])

    def test_parse_with_update_policy(self):
        tmpl = tmpl_with_updt_policy()
        stack = utils.parse_stack(tmpl)
        stack.validate()
        tmpl_grp = tmpl['resources']['group1']
        tmpl_policy = tmpl_grp['update_policy']['rolling_update']
        tmpl_batch_sz = int(tmpl_policy['max_batch_size'])
        grp = stack['group1']
        self.assertTrue(grp.update_policy)
        self.assertEqual(2, len(grp.update_policy))
        self.assertIn('rolling_update', grp.update_policy)
        policy = grp.update_policy['rolling_update']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(1, int(policy['min_in_service']))
        self.assertEqual(tmpl_batch_sz, int(policy['max_batch_size']))
        self.assertEqual(1, policy['pause_time'])

    def test_parse_with_default_update_policy(self):
        tmpl = tmpl_with_default_updt_policy()
        stack = utils.parse_stack(tmpl)
        stack.validate()
        grp = stack['group1']
        self.assertTrue(grp.update_policy)
        self.assertEqual(2, len(grp.update_policy))
        self.assertIn('rolling_update', grp.update_policy)
        policy = grp.update_policy['rolling_update']
        self.assertIsNotNone(policy)
        self.assertGreater(len(policy), 0)
        self.assertEqual(0, int(policy['min_in_service']))
        self.assertEqual(1, int(policy['max_batch_size']))
        self.assertEqual(0, policy['pause_time'])

    def test_parse_with_bad_update_policy(self):
        tmpl = tmpl_with_bad_updt_policy()
        stack = utils.parse_stack(tmpl)
        error = self.assertRaises(
            exception.StackValidationFailed, stack.validate)
        self.assertIn("foo", six.text_type(error))


class RollingUpdatePolicyDiffTest(common.HeatTestCase):

    def validate_update_policy_diff(self, current, updated):
        # load current stack
        current_stack = utils.parse_stack(current)
        current_grp = current_stack['group1']
        current_grp_json = current_grp.frozen_definition()

        updated_stack = utils.parse_stack(updated)
        updated_grp = updated_stack['group1']
        updated_grp_json = updated_grp.t.freeze()

        # identify the template difference
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)
        self.assertTrue(tmpl_diff.update_policy_changed())
        prop_diff = current_grp.update_template_diff_properties(
            updated_grp.properties,
            current_grp.properties)

        # test application of the new update policy in handle_update
        current_grp._try_rolling_update = mock.Mock()
        current_grp._assemble_nested_for_size = mock.Mock()
        self.patchobject(scheduler.TaskRunner, 'start')
        current_grp.handle_update(updated_grp_json, tmpl_diff, prop_diff)
        self.assertEqual(updated_grp_json._update_policy or {},
                         current_grp.update_policy.data)

    def test_update_policy_added(self):
        self.validate_update_policy_diff(template,
                                         tmpl_with_updt_policy())

    def test_update_policy_updated(self):
        updt_template = tmpl_with_updt_policy()
        grp = updt_template['resources']['group1']
        policy = grp['update_policy']['rolling_update']
        policy['min_in_service'] = '2'
        policy['max_batch_size'] = '4'
        policy['pause_time'] = '90'
        self.validate_update_policy_diff(tmpl_with_updt_policy(),
                                         updt_template)

    def test_update_policy_removed(self):
        self.validate_update_policy_diff(tmpl_with_updt_policy(),
                                         template)


class RollingUpdateTest(common.HeatTestCase):

    def check_with_update(self, with_policy=False, with_diff=False):
        current = copy.deepcopy(template)
        self.current_stack = utils.parse_stack(current)
        self.current_grp = self.current_stack['group1']
        current_grp_json = self.current_grp.frozen_definition()
        prop_diff, tmpl_diff = None, None
        updated = tmpl_with_updt_policy() if (
            with_policy) else copy.deepcopy(template)
        if with_diff:
            res_def = updated['resources']['group1'][
                'properties']['resource_def']
            res_def['properties']['Foo'] = 'baz'
            prop_diff = dict(
                {'count': 2,
                 'resource_def': {'properties': {'Foo': 'baz'},
                                  'type': 'OverwrittenFnGetRefIdType'}})
        updated_stack = utils.parse_stack(updated)
        updated_grp = updated_stack['group1']
        updated_grp_json = updated_grp.t.freeze()
        tmpl_diff = updated_grp.update_template_diff(
            updated_grp_json, current_grp_json)

        self.current_grp._replace = mock.Mock(return_value=[])
        self.current_grp._assemble_nested = mock.Mock()
        self.patchobject(scheduler.TaskRunner, 'start')
        self.current_grp.handle_update(updated_grp_json, tmpl_diff, prop_diff)

    def test_update_without_policy_prop_diff(self):
        self.check_with_update(with_diff=True)
        self.assertTrue(self.current_grp._assemble_nested.called)

    def test_update_with_policy_prop_diff(self):
        self.check_with_update(with_policy=True, with_diff=True)
        self.current_grp._replace.assert_called_once_with(1, 2, 1)
        self.assertTrue(self.current_grp._assemble_nested.called)

    def test_update_time_not_sufficient(self):
        current = copy.deepcopy(template)
        self.stack = utils.parse_stack(current)
        self.current_grp = self.stack['group1']
        self.stack.timeout_secs = mock.Mock(return_value=200)
        err = self.assertRaises(ValueError, self.current_grp._update_timeout,
                                3, 100)
        self.assertIn('The current update policy will result in stack update '
                      'timeout.', six.text_type(err))

    def test_update_time_sufficient(self):
        current = copy.deepcopy(template)
        self.stack = utils.parse_stack(current)
        self.current_grp = self.stack['group1']
        self.stack.timeout_secs = mock.Mock(return_value=400)
        self.assertEqual(200, self.current_grp._update_timeout(3, 100))


class TestUtils(common.HeatTestCase):
    # 1. No existing no blacklist
    # 2. Existing with no blacklist
    # 3. Existing with blacklist
    scenarios = [
        ('1', dict(existing=[], black_listed=[], count=0)),
        ('2', dict(existing=['0', '1'], black_listed=[], count=0)),
        ('3', dict(existing=['0', '1'], black_listed=['0'], count=1)),
        ('4', dict(existing=['0', '1'], black_listed=['1', '2'], count=1))

    ]

    def test_count_black_listed(self):
        inspector = mock.Mock(spec=grouputils.GroupInspector)
        self.patchobject(grouputils.GroupInspector, 'from_parent_resource',
                         return_value=inspector)
        inspector.member_names.return_value = self.existing

        stack = utils.parse_stack(template2)
        snip = stack.t.resource_definitions(stack)['group1']
        resgrp = resource_group.ResourceGroup('test', snip, stack)
        resgrp._name_blacklist = mock.Mock(return_value=set(self.black_listed))
        rcount = resgrp._count_black_listed(self.existing)
        self.assertEqual(self.count, rcount)


class TestGetBatches(common.HeatTestCase):

    scenarios = [
        ('4_4_1_0', dict(targ_cap=4, init_cap=4, bat_size=1, min_serv=0,
                         batches=[
                             (4, 1, ['4']),
                             (4, 1, ['3']),
                             (4, 1, ['2']),
                             (4, 1, ['1']),
                         ])),
        ('4_4_1_4', dict(targ_cap=4, init_cap=4, bat_size=1, min_serv=4,
                         batches=[
                             (5, 1, ['5']),
                             (5, 1, ['4']),
                             (5, 1, ['3']),
                             (5, 1, ['2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),
        ('4_4_1_5', dict(targ_cap=4, init_cap=4, bat_size=1, min_serv=5,
                         batches=[
                             (5, 1, ['5']),
                             (5, 1, ['4']),
                             (5, 1, ['3']),
                             (5, 1, ['2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),
        ('4_4_2_0', dict(targ_cap=4, init_cap=4, bat_size=2, min_serv=0,
                         batches=[
                             (4, 2, ['4', '3']),
                             (4, 2, ['2', '1']),
                         ])),
        ('4_4_2_4', dict(targ_cap=4, init_cap=4, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['6', '5']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                             (4, 0, []),
                         ])),
        ('5_5_2_0', dict(targ_cap=5, init_cap=5, bat_size=2, min_serv=0,
                         batches=[
                             (5, 2, ['5', '4']),
                             (5, 2, ['3', '2']),
                             (5, 1, ['1']),
                         ])),
        ('5_5_2_4', dict(targ_cap=5, init_cap=5, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['6', '5']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                             (5, 0, []),
                         ])),
        ('3_3_2_0', dict(targ_cap=3, init_cap=3, bat_size=2, min_serv=0,
                         batches=[
                             (3, 2, ['3', '2']),
                             (3, 1, ['1']),
                         ])),
        ('3_3_2_4', dict(targ_cap=3, init_cap=3, bat_size=2, min_serv=4,
                         batches=[
                             (5, 2, ['5', '4']),
                             (5, 2, ['3', '2']),
                             (4, 1, ['1']),
                             (3, 0, []),
                         ])),
        ('4_4_4_0', dict(targ_cap=4, init_cap=4, bat_size=4, min_serv=0,
                         batches=[
                             (4, 4, ['4', '3', '2', '1']),
                         ])),
        ('4_4_5_0', dict(targ_cap=4, init_cap=4, bat_size=5, min_serv=0,
                         batches=[
                             (4, 4, ['4', '3', '2', '1']),
                         ])),
        ('4_4_4_1', dict(targ_cap=4, init_cap=4, bat_size=4, min_serv=1,
                         batches=[
                             (5, 4, ['5', '4', '3', '2']),
                             (4, 1, ['1']),
                         ])),
        ('4_4_6_1', dict(targ_cap=4, init_cap=4, bat_size=6, min_serv=1,
                         batches=[
                             (5, 4, ['5', '4', '3', '2']),
                             (4, 1, ['1']),
                         ])),
        ('4_4_4_2', dict(targ_cap=4, init_cap=4, bat_size=4, min_serv=2,
                         batches=[
                             (6, 4, ['6', '5', '4', '3']),
                             (4, 2, ['2', '1']),
                         ])),
        ('4_4_4_4', dict(targ_cap=4, init_cap=4, bat_size=4, min_serv=4,
                         batches=[
                             (8, 4, ['8', '7', '6', '5']),
                             (8, 4, ['4', '3', '2', '1']),
                             (4, 0, []),
                         ])),
        ('4_4_5_6', dict(targ_cap=4, init_cap=4, bat_size=5, min_serv=6,
                         batches=[
                             (8, 4, ['8', '7', '6', '5']),
                             (8, 4, ['4', '3', '2', '1']),
                             (4, 0, []),
                         ])),

        ('4_7_1_0', dict(targ_cap=4, init_cap=7, bat_size=1, min_serv=0,
                         batches=[
                             (4, 1, ['4']),
                             (4, 1, ['3']),
                             (4, 1, ['2']),
                             (4, 1, ['1']),
                         ])),
        ('4_7_1_4', dict(targ_cap=4, init_cap=7, bat_size=1, min_serv=4,
                         batches=[
                             (5, 1, ['4']),
                             (5, 1, ['3']),
                             (5, 1, ['2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),
        ('4_7_1_5', dict(targ_cap=4, init_cap=7, bat_size=1, min_serv=5,
                         batches=[
                             (5, 1, ['4']),
                             (5, 1, ['3']),
                             (5, 1, ['2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),
        ('4_7_2_0', dict(targ_cap=4, init_cap=7, bat_size=2, min_serv=0,
                         batches=[
                             (4, 2, ['4', '3']),
                             (4, 2, ['2', '1']),
                         ])),
        ('4_7_2_4', dict(targ_cap=4, init_cap=7, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                             (4, 0, []),
                         ])),
        ('5_7_2_0', dict(targ_cap=5, init_cap=7, bat_size=2, min_serv=0,
                         batches=[
                             (5, 2, ['5', '4']),
                             (5, 2, ['3', '2']),
                             (5, 1, ['1']),
                         ])),
        ('5_7_2_4', dict(targ_cap=5, init_cap=7, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['5', '4']),
                             (6, 2, ['3', '2']),
                             (5, 1, ['1']),
                         ])),
        ('4_7_4_4', dict(targ_cap=4, init_cap=7, bat_size=4, min_serv=4,
                         batches=[
                             (8, 4, ['8', '4', '3', '2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),
        ('4_7_5_6', dict(targ_cap=4, init_cap=7, bat_size=5, min_serv=6,
                         batches=[
                             (8, 4, ['8', '4', '3', '2']),
                             (5, 1, ['1']),
                             (4, 0, []),
                         ])),

        ('6_4_1_0', dict(targ_cap=6, init_cap=4, bat_size=1, min_serv=0,
                         batches=[
                             (5, 1, ['5']),
                             (6, 1, ['6']),
                             (6, 1, ['4']),
                             (6, 1, ['3']),
                             (6, 1, ['2']),
                             (6, 1, ['1']),
                         ])),
        ('6_4_1_4', dict(targ_cap=6, init_cap=4, bat_size=1, min_serv=4,
                         batches=[
                             (5, 1, ['5']),
                             (6, 1, ['6']),
                             (6, 1, ['4']),
                             (6, 1, ['3']),
                             (6, 1, ['2']),
                             (6, 1, ['1']),
                         ])),
        ('6_4_1_5', dict(targ_cap=6, init_cap=4, bat_size=1, min_serv=5,
                         batches=[
                             (5, 1, ['5']),
                             (6, 1, ['6']),
                             (6, 1, ['4']),
                             (6, 1, ['3']),
                             (6, 1, ['2']),
                             (6, 1, ['1']),
                         ])),
        ('6_4_2_0', dict(targ_cap=6, init_cap=4, bat_size=2, min_serv=0,
                         batches=[
                             (6, 2, ['5', '6']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_4_2_4', dict(targ_cap=6, init_cap=4, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['5', '6']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_5_2_0', dict(targ_cap=6, init_cap=5, bat_size=2, min_serv=0,
                         batches=[
                             (6, 2, ['6', '5']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_5_2_4', dict(targ_cap=6, init_cap=5, bat_size=2, min_serv=4,
                         batches=[
                             (6, 2, ['6', '5']),
                             (6, 2, ['4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_3_2_0', dict(targ_cap=6, init_cap=3, bat_size=2, min_serv=0,
                         batches=[
                             (5, 2, ['4', '5']),
                             (6, 2, ['6', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_3_2_4', dict(targ_cap=6, init_cap=3, bat_size=2, min_serv=4,
                         batches=[
                             (5, 2, ['4', '5']),
                             (6, 2, ['6', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_4_4_0', dict(targ_cap=6, init_cap=4, bat_size=4, min_serv=0,
                         batches=[
                             (6, 4, ['5', '6', '4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_4_5_0', dict(targ_cap=6, init_cap=4, bat_size=5, min_serv=0,
                         batches=[
                             (6, 5, ['5', '6', '4', '3', '2']),
                             (6, 1, ['1']),
                         ])),
        ('6_4_4_1', dict(targ_cap=6, init_cap=4, bat_size=4, min_serv=1,
                         batches=[
                             (6, 4, ['5', '6', '4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_4_6_1', dict(targ_cap=6, init_cap=4, bat_size=6, min_serv=1,
                         batches=[
                             (7, 6, ['5', '6', '7', '4', '3', '2']),
                             (6, 1, ['1']),
                         ])),
        ('6_4_4_2', dict(targ_cap=6, init_cap=4, bat_size=4, min_serv=2,
                         batches=[
                             (6, 4, ['5', '6', '4', '3']),
                             (6, 2, ['2', '1']),
                         ])),
        ('6_4_4_4', dict(targ_cap=6, init_cap=4, bat_size=4, min_serv=4,
                         batches=[
                             (8, 4, ['8', '7', '6', '5']),
                             (8, 4, ['4', '3', '2', '1']),
                             (6, 0, []),
                         ])),
        ('6_4_5_6', dict(targ_cap=6, init_cap=4, bat_size=5, min_serv=6,
                         batches=[
                             (9, 5, ['9', '8', '7', '6', '5']),
                             (10, 4, ['10', '4', '3', '2']),
                             (7, 1, ['1']),
                             (6, 0, []),
                         ])),
    ]

    def setUp(self):
        super(TestGetBatches, self).setUp()

        self.stack = utils.parse_stack(template)
        self.grp = self.stack['group1']
        self.grp._name_blacklist = mock.Mock(return_value={'0'})

    def test_get_batches(self):
        batches = list(self.grp._get_batches(self.targ_cap,
                                             self.init_cap,
                                             self.bat_size,
                                             self.min_serv))
        self.assertEqual([(s, u) for s, u, n in self.batches], batches)

    def test_assemble(self):
        old_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "baz"})

        new_def = rsrc_defn.ResourceDefinition(
            None,
            "OverwrittenFnGetRefIdType",
            {"foo": "bar"})

        resources = [(str(i), old_def) for i in range(self.init_cap + 1)]
        self.grp.get_size = mock.Mock(return_value=self.targ_cap)
        self.patchobject(grouputils, 'get_member_definitions',
                         return_value=resources)
        self.grp.build_resource_definition = mock.Mock(return_value=new_def)
        all_updated_names = set()

        for size, max_upd, names in self.batches:

            template = self.grp._assemble_for_rolling_update(size,
                                                             max_upd,
                                                             names)
            res_dict = template.resource_definitions(self.stack)

            expected_names = set(map(str, range(1, size + 1)))
            self.assertEqual(expected_names, set(res_dict))

            all_updated_names &= expected_names
            all_updated_names |= set(names)
            updated = set(n for n, v in res_dict.items() if v != old_def)
            self.assertEqual(all_updated_names, updated)

            resources[:] = sorted(res_dict.items(), key=lambda i: int(i[0]))
