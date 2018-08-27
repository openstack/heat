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
from heat.common import template_format
from heat.db.sqlalchemy import api as db_api
from heat.engine import environment
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import service
from heat.engine import stack
from heat.engine import support
from heat.engine import template
from heat.objects import stack as stack_object
from heat.rpc import api as rpc_api
from heat.tests import common
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils


empty_template = template_format.parse('''{
  "HeatTemplateFormatVersion" : "2012-12-12",
}''')


class StackUpdateTest(common.HeatTestCase):
    def setUp(self):
        super(StackUpdateTest, self).setUp()

        self.tmpl = template.Template(copy.deepcopy(empty_template))
        self.ctx = utils.dummy_context()

    def test_update_add(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        raw_template_id = self.stack.t.id
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)
        self.assertNotEqual(raw_template_id, self.stack.t.id)
        self.assertNotEqual(raw_template_id, self.stack.prev_raw_template_id)
        self.assertRaises(exception.NotFound,
                          db_api.raw_template_get, self.ctx, raw_template_id)

    def test_update_remove(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'GenericResourceType'},
                    'BResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertNotIn('BResource', self.stack)

    def test_update_different_type(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('GenericResourceType',
                         self.stack['AResource'].type())

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'abc'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('ResourceWithPropsType',
                         self.stack['AResource'].type())

    def test_update_description(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'BTemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('BTemplate',
                         self.stack.t[self.stack.t.DESCRIPTION])

    def test_update_timeout(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl), timeout_mins=60)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'ATemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2), timeout_mins=30)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(30, self.stack.timeout_mins)

    def test_update_disable_rollback(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Description': 'ATemplate',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertTrue(self.stack.disable_rollback)

    def test_update_tags(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 tags=['tag1', 'tag2'])
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(['tag1', 'tag2'], self.stack.tags)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl),
                                    tags=['tag3', 'tag4'])
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(['tag3', 'tag4'], self.stack.tags)

    def test_update_tags_remove_all(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Description': 'ATemplate',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 tags=['tag1', 'tag2'])
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(['tag1', 'tag2'], self.stack.tags)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIsNone(self.stack.tags)

    def test_update_modify_ok_replace(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'xyz',
            self.stack['AResource']._stored_properties_data['Foo'])

        loaded_stack = stack.Stack.load(self.ctx, self.stack.id)
        stored_props = loaded_stack['AResource']._stored_properties_data
        self.assertEqual({'Foo': 'xyz'}, stored_props)

    def test_update_replace_resticted(self):
        env = environment.Environment()
        env_snippet = {u'resource_registry': {
            u'resources': {
                'AResource': {'restricted_actions': 'update'}
            }
        }
        }
        env.load(env_snippet)
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl1 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl1, env=env))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        env_snippet['resource_registry']['resources'][
            'AResource']['restricted_actions'] = 'replace'
        env.load(env_snippet)
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2, env=env))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)

    def test_update_modify_ok_replace_int(self):
        # create
        # ========
        tmpl = {'heat_template_version': '2013-05-23',
                'resources': {'AResource': {
                    'type': 'ResWithComplexPropsAndAttrs',
                    'properties': {'an_int': 1}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        stack_id = self.stack.id
        self.stack.create()
        self.stack._persist_state()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        value1 = 2
        prop_diff1 = {'an_int': value1}
        value2 = 1
        prop_diff2 = {'an_int': value2}

        mock_upd = self.patchobject(generic_rsrc.ResWithComplexPropsAndAttrs,
                                    'handle_update')

        # update 1
        # ==========

        self.stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        tmpl2 = {'heat_template_version': '2013-05-23',
                 'resources': {'AResource': {
                     'type': 'ResWithComplexPropsAndAttrs',
                     'properties': {'an_int': value1}}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.stack._persist_state()
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        mock_upd.assert_called_once_with(mock.ANY, mock.ANY, prop_diff1)

        # update 2
        # ==========
        # reload the previous stack
        self.stack = stack.Stack.load(self.ctx, stack_id=stack_id)
        tmpl3 = {'heat_template_version': '2013-05-23',
                 'resources': {'AResource': {
                     'type': 'ResWithComplexPropsAndAttrs',
                     'properties': {'an_int': value2}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl3))

        self.stack.update(updated_stack)
        self.stack._persist_state()
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        mock_upd.assert_called_with(mock.ANY, mock.ANY, prop_diff2)

    def test_update_modify_param_ok_replace(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'foo': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'foo'}}
                }
            }
        }

        self.stack = stack.Stack(
            self.ctx, 'update_test_stack',
            template.Template(
                tmpl, env=environment.Environment({'foo': 'abc'})))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        env2 = environment.Environment({'foo': 'xyz'})
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl, env=env2))

        def check_and_raise(*args):
            self.assertEqual(
                'abc',
                self.stack['AResource']._stored_properties_data['Foo'])
            raise resource.UpdateReplace

        mock_upd = self.patchobject(generic_rsrc.ResourceWithProps,
                                    'update_template_diff',
                                    side_effect=check_and_raise)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'xyz',
            self.stack['AResource']._stored_properties_data['Foo'])
        after = rsrc_defn.ResourceDefinition('AResource',
                                             'ResourceWithPropsType',
                                             properties={'Foo': 'xyz'})
        before = rsrc_defn.ResourceDefinition('AResource',
                                              'ResourceWithPropsType',
                                              properties={'Foo': 'abc'})
        mock_upd.assert_called_once_with(after, before)

    def test_update_replace_create_hook(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'foo': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'foo'}}
                }
            }
        }

        self.stack = stack.Stack(
            self.ctx, 'update_test_stack',
            template.Template(
                tmpl, env=environment.Environment({'foo': 'abc'})))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        env2 = environment.Environment({'foo': 'xyz'})
        # Add a create hook on the resource
        env2.registry.load(
            {'resources': {'AResource': {'hooks': 'pre-create'}}})
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl, env=env2))

        self.stack.update(updated_stack)
        # The hook is not called, and update succeeds properly
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'xyz',
            self.stack['AResource']._stored_properties_data['Foo'])

    def test_update_replace_delete_hook(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'foo': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'foo'}}
                }
            }
        }

        env = environment.Environment({'foo': 'abc'})
        env.registry.load(
            {'resources': {'AResource': {'hooks': 'pre-delete'}}})
        self.stack = stack.Stack(
            self.ctx, 'update_test_stack',
            template.Template(tmpl, env=env))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        env2 = environment.Environment({'foo': 'xyz'})
        env2.registry.load(
            {'resources': {'AResource': {'hooks': 'pre-delete'}}})
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl, env=env2))

        self.stack.update(updated_stack)
        # The hook is not called, and update succeeds properly
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'xyz',
            self.stack['AResource']._stored_properties_data['Foo'])

    def test_update_replace_post_hook(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'foo': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {
                    'Type': 'ResWithComplexPropsAndAttrs',
                    'Properties': {'an_int': {'Ref': 'foo'}}
                }
            }
        }
        self.stack = stack.Stack(
            self.ctx, 'update_test_stack',
            template.Template(tmpl, env=environment.Environment({'foo': 1})))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        env2 = environment.Environment({'foo': 2})
        env2.registry.load(
            {'resources': {'AResource': {'hooks': 'post-update'}}})
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl, env=env2))
        mock_hook = self.patchobject(self.stack['AResource'], 'trigger_hook')

        self.stack.update(updated_stack)
        mock_hook.assert_called_once_with('post-update')
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            '2',
            self.stack['AResource']._stored_properties_data['an_int'])

    def test_update_modify_update_failed(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        res = self.stack['AResource']
        res.update_allowed_properties = ('Foo',)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        mock_upd = self.patchobject(generic_rsrc.ResourceWithProps,
                                    'handle_update',
                                    side_effect=Exception("Foo"))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        mock_upd.assert_called_once_with(
            rsrc_defn.ResourceDefinition('AResource', 'ResourceWithPropsType',
                                         properties={'Foo': 'xyz'}),
            mock.ANY,
            {'Foo': 'xyz'})

    def test_update_modify_replace_failed_delete(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # make the update fail deleting the existing resource
        mock_del = self.patchobject(generic_rsrc.ResourceWithProps,
                                    'handle_delete',
                                    side_effect=Exception)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        mock_del.assert_called_once_with()

    def test_update_modify_replace_failed_create(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create',
                                       side_effect=Exception)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        mock_create.assert_called_once_with()

    def test_update_modify_replace_failed_create_and_delete_1(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'b_res'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        mock_create = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                       'handle_create', side_effect=Exception)
        mock_id = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                   'mock_resource_id',
                                   return_value=None)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

        mock_create.assert_called_once_with()

        # Three calls in list: first is an attempt to delete backup_stack
        # where create(xyz) has failed, so no resource_id passed; the 2nd
        # and the 3rd calls are invoked by resource BResource deletion
        # followed by AResource deletion.
        mock_id.assert_has_calls(
            [mock.call(None), mock.call('b_res'), mock.call('a_res')])

    def test_update_modify_replace_failed_create_and_delete_2(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'c_res'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        mock_create = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                       'handle_create',
                                       side_effect=[None, Exception])
        mock_id = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                   'mock_resource_id', return_value=None)

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is overwritten
        # by the mock.
        self.stack.resources['AResource'].resource_id_set('c_res')
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(2, mock_create.call_count)
        # Four calls in chain: 1st is an attempt to delete backup_stack where
        # the create(xyz) failed with no resource_id, the other three are
        # derived from resource dependencies.
        mock_id.assert_has_calls(
            [mock.call(None), mock.call('c_res'), mock.call('b_res'),
             mock.call('a_res')])

    def test_update_modify_replace_create_in_progress_and_delete_1(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'b_res'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        mock_create = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                       'handle_create', side_effect=Exception)
        mock_id = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                   'mock_resource_id', return_value=None)

        self.stack.update(updated_stack)
        # Override stack status and resources status for emulating
        # IN_PROGRESS situation
        self.stack.state_set(
            stack.Stack.UPDATE, stack.Stack.IN_PROGRESS, None)
        self.stack.resources['AResource'].state_set(
            resource.Resource.CREATE, resource.Resource.IN_PROGRESS, None)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

        mock_create.assert_called_once_with()
        # Three calls in chain: 1st is an attempt to delete backup_stack where
        # the create(xyz) failed with no resource_id, the other two ordered by
        # resource dependencies.
        mock_id.assert_has_calls(
            [mock.call(None), mock.call('b_res'), mock.call('a_res')])

    def test_update_modify_replace_create_in_progress_and_delete_2(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'a_res'}},
                              'BResource': {'Type':
                                            'ResourceWithResourceIDType',
                                            'Properties': {'ID': 'b_res'},
                                            'DependsOn': 'AResource'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'c_res'}},
                               'BResource': {'Type':
                                             'ResourceWithResourceIDType',
                                             'Properties': {'ID': 'xyz'},
                                             'DependsOn': 'AResource'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making the replace fail creating
        mock_create = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                       'handle_create',
                                       side_effect=[None, Exception])
        mock_id = self.patchobject(generic_rsrc.ResourceWithResourceID,
                                   'mock_resource_id', return_value=None)

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is mocked
        self.stack.resources['AResource'].resource_id_set('c_res')
        # Override stack status and resources status for emulating
        # IN_PROGRESS situation
        self.stack.state_set(
            stack.Stack.UPDATE, stack.Stack.IN_PROGRESS, None)
        self.stack.resources['BResource'].state_set(
            resource.Resource.CREATE, resource.Resource.IN_PROGRESS, None)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(2, mock_create.call_count)
        # Four calls in chain: 1st is an attempt to delete backup_stack where
        # the create(xyz) failed with no resource_id, the other three are
        # derived from resource dependencies.
        mock_id.assert_has_calls(
            [mock.call(None), mock.call('c_res'), mock.call('b_res'),
             mock.call('a_res')])

    def _update_force_cancel(self, state, disable_rollback=False,
                             cancel_message=rpc_api.THREAD_CANCEL):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}
        old_tags = ['tag1', 'tag2']
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl), tags=old_tags)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(old_tags, self.stack.tags)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'MultiStepResourceType'}}}
        new_tags = ['tag3', 'tag4']
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=disable_rollback,
                                    tags=new_tags)

        msgq_mock = mock.MagicMock()
        msgq_mock.get_nowait.return_value = cancel_message

        self.stack.update(updated_stack, msg_queue=msgq_mock)

        self.assertEqual(state, self.stack.state)
        if disable_rollback:
            self.assertEqual(new_tags, self.stack.tags)
        else:
            self.assertEqual(old_tags, self.stack.tags)
        msgq_mock.get_nowait.assert_called_once_with()

    def test_update_force_cancel_no_rollback(self):
        self._update_force_cancel(
            state=(stack.Stack.UPDATE, stack.Stack.FAILED),
            disable_rollback=True,
            cancel_message=rpc_api.THREAD_CANCEL)

    def test_update_force_cancel_rollback(self):
        self._update_force_cancel(
            state=(stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
            disable_rollback=False,
            cancel_message=rpc_api.THREAD_CANCEL)

    def test_update_force_cancel_force_rollback(self):
        self._update_force_cancel(
            state=(stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
            disable_rollback=False,
            cancel_message=rpc_api.THREAD_CANCEL_WITH_ROLLBACK)

    def test_update_add_signal(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        updater = scheduler.TaskRunner(self.stack.update_task, updated_stack)
        updater.start()
        while 'BResource' not in self.stack:
            self.assertFalse(updater.step())
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.IN_PROGRESS),
                         self.stack.state)

        # Reload the stack from the DB and prove that it contains the new
        # resource already
        re_stack = stack.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)

        updater.run_to_completion()
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

    def test_update_add_failed_create(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        # patch in a dummy handle_create making BResource fail creating
        mock_create = self.patchobject(generic_rsrc.GenericResource,
                                       'handle_create', side_effect=Exception)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = stack.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)
        mock_create.assert_called_once_with()

    def test_update_add_failed_create_rollback_failed(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'GenericResourceType'}}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch handle_create/delete making BResource fail creation/deletion
        mock_create = self.patchobject(generic_rsrc.GenericResource,
                                       'handle_create', side_effect=Exception)
        mock_delete = self.patchobject(generic_rsrc.GenericResource,
                                       'handle_delete', side_effect=Exception)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = stack.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)

        mock_create.assert_called_once_with()
        mock_delete.assert_called_once_with()

    def test_update_rollback(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.stack._persist_state()

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create', side_effect=Exception)

        with mock.patch.object(
                stack_object.Stack, 'update_by_id',
                wraps=stack_object.Stack.update_by_id) as mock_db_update:
            self.stack.update(updated_stack)
            self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                             self.stack.state)
            self.eng = service.EngineService('a-host', 'a-topic')
            events = self.eng.list_events(self.ctx, self.stack.identifier())
            self.assertEqual(11, len(events))

            self.assertEqual(
                'abc',
                self.stack['AResource']._stored_properties_data['Foo'])
            self.assertEqual(5, mock_db_update.call_count)
            self.assertEqual('UPDATE',
                             mock_db_update.call_args_list[0][0][2]['action'])
            self.assertEqual('IN_PROGRESS',
                             mock_db_update.call_args_list[0][0][2]['status'])
            self.assertEqual('ROLLBACK',
                             mock_db_update.call_args_list[1][0][2]['action'])
            self.assertEqual('IN_PROGRESS',
                             mock_db_update.call_args_list[1][0][2]['status'])

        mock_create.assert_called_once_with()

    def test_update_rollback_on_cancel_event(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}},
                               }}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)
        msgq_mock = mock.MagicMock()
        msgq_mock.get_nowait.return_value = 'cancel_with_rollback'

        self.stack.update(updated_stack, msg_queue=msgq_mock)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        msgq_mock.get_nowait.assert_called_once_with()

    def test_update_rollback_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        env1 = environment.Environment({'parameters': {'AParam': 'abc'}})
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl, env=env1),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Parameters': {'BParam': {'Type': 'String'}},
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        env2 = environment.Environment({'parameters': {'BParam': 'smelly'}})
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2, env=env2),
                                    disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and again on the second call (rollback)
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create', side_effect=Exception)
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete', side_effect=Exception)

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.FAILED),
                         self.stack.state)

        mock_create.assert_called_once_with()
        mock_delete.assert_called_once_with()

    def test_update_rollback_add(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'GenericResourceType'},
                     'BResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and succeed on the second call (rollback)
        mock_create = self.patchobject(generic_rsrc.GenericResource,
                                       'handle_create', side_effect=Exception)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertNotIn('BResource', self.stack)

        mock_create.assert_called_once_with()

    def test_update_rollback_remove(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'GenericResourceType'},
                    'BResource': {'Type': 'ResourceWithPropsType'}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'GenericResourceType'}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch in a dummy delete making the destroy fail
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create')
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete',
                                       side_effect=[Exception, None])

        self.stack.update(updated_stack)

        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        mock_create.assert_called_once_with()
        self.assertEqual(2, mock_delete.call_count)

    def test_update_rollback_replace(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'foo'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'bar'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch in a dummy delete making the destroy fail
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete',
                                       side_effect=[Exception, None, None])

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(3, mock_delete.call_count)

    def test_update_replace_by_reference(self):
        """Test case for changes in dynamic attributes.

        Changes in dynamic attributes, due to other resources been updated
        are not ignored and can cause dependent resources to be updated.
        """
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {'Foo': 'smelly'}},
                     'BResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {
                                       'Foo': {'Ref': 'AResource'}}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource',
            self.stack['BResource']._stored_properties_data['Foo'])

        mock_id = self.patchobject(generic_rsrc.ResourceWithProps,
                                   'get_reference_id',
                                   return_value='inst-007')

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'inst-007',
            self.stack['BResource']._stored_properties_data['Foo'])

        mock_id.assert_called_with()

    def test_update_with_new_resources_with_reference(self):
        """Check correct resolving of references in new resources.

        Check, that during update with new resources which one has
        reference on second, reference will be correct resolved.
        """
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'CResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'CResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {'Foo': 'abc'}},
                     'AResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {'Foo': 'smelly'}},
                     'BResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {
                                       'Foo': {'Ref': 'AResource'}}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['CResource']._stored_properties_data['Foo'])
        self.assertEqual(1, len(self.stack.resources))

        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create', return_value=None)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource',
            self.stack['BResource']._stored_properties_data['Foo'])

        self.assertEqual(3, len(self.stack.resources))

        mock_create.assert_called_with()

    def test_update_by_reference_and_rollback_1(self):
        """Check that rollback still works with dynamic metadata.

        This test fails the first instance.
        """
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {'Foo': 'smelly'}},
                     'BResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {
                                       'Foo': {'Ref': 'AResource'}}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource',
            self.stack['BResource']._stored_properties_data['Foo'])

        mock_id = self.patchobject(generic_rsrc.ResourceWithProps,
                                   'get_reference_id',
                                   return_value='AResource')

        # mock to make the replace fail when creating the replacement resource
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create', side_effect=Exception)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])

        mock_id.assert_called_with()
        mock_create.assert_called_once_with()

    def test_update_by_reference_and_rollback_2(self):
        """Check that rollback still works with dynamic metadata.

        This test fails the second instance.
        """

        class ResourceTypeA(generic_rsrc.ResourceWithProps):
            count = 0

            def handle_create(self):
                ResourceTypeA.count += 1
                self.resource_id_set('%s%d' % (self.name, self.count))

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceTypeA',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'ResourceTypeA',
                                   'Properties': {'Foo': 'smelly'}},
                     'BResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {
                                       'Foo': {'Ref': 'AResource'}}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False)

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource1',
            self.stack['BResource']._stored_properties_data['Foo'])

        # mock to make the replace fail when creating the second
        # replacement resource
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create', side_effect=Exception)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource1',
            self.stack['BResource']._stored_properties_data['Foo'])
        mock_create.assert_called_once_with()

    def test_update_failure_recovery(self):
        """Check that rollback still works with dynamic metadata.

        This test fails the second instance.
        """

        class ResourceTypeA(generic_rsrc.ResourceWithProps):
            count = 0

            def handle_create(self):
                ResourceTypeA.count += 1
                self.resource_id_set('%s%d' % (self.name, self.count))

            def handle_delete(self):
                return super(ResourceTypeA, self).handle_delete()

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceTypeA',
                                  'Properties': {'Foo': 'abc'}},
                    'BResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {
                                      'Foo': {'Ref': 'AResource'}}}}}
        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {
                     'AResource': {'Type': 'ResourceTypeA',
                                   'Properties': {'Foo': 'smelly'}},
                     'BResource': {'Type': 'ResourceWithPropsType',
                                   'Properties': {
                                       'Foo': {'Ref': 'AResource'}}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource1',
            self.stack['BResource']._stored_properties_data['Foo'])

        # mock to make the replace fail when creating the second
        # replacement resource
        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create',
                                       side_effect=[Exception, None])
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete')
        mock_delete_A = self.patchobject(ResourceTypeA, 'handle_delete')

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=True)
        self.stack.update(updated_stack)

        mock_create.assert_called_once_with()

        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = stack.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=True)

        self.stack.update(updated_stack2)

        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource2',
            self.stack['BResource']._stored_properties_data['Foo'])

        self.assertEqual(2, mock_create.call_count)
        self.assertEqual(2, mock_delete.call_count)
        mock_delete_A.assert_called_once_with()

    def test_update_failure_recovery_new_param(self):
        """Check that rollback still works with dynamic metadata.

        This test fails the second instance.
        """

        class ResourceTypeA(generic_rsrc.ResourceWithProps):
            count = 0

            def handle_create(self):
                ResourceTypeA.count += 1
                self.resource_id_set('%s%d' % (self.name, self.count))

            def handle_delete(self):
                return super(ResourceTypeA, self).handle_delete()

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'abc-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'abc-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env1 = environment.Environment({'abc-param': 'abc'})
        tmpl2 = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'smelly-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'smelly-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env2 = environment.Environment({'smelly-param': 'smelly'})

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl, env=env1),
                                 disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource1',
            self.stack['BResource']._stored_properties_data['Foo'])

        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create',
                                       side_effect=[Exception, None])
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete')
        mock_delete_A = self.patchobject(ResourceTypeA, 'handle_delete')

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2, env=env2),
                                    disable_rollback=True)
        self.stack.update(updated_stack)

        # creation was a failure
        mock_create.assert_called_once_with()
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = stack.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2, env=env2),
                                     disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        a_props = self.stack['AResource']._stored_properties_data['Foo']
        self.assertEqual('smelly', a_props)
        b_props = self.stack['BResource']._stored_properties_data['Foo']
        self.assertEqual('AResource2', b_props)

        self.assertEqual(2, mock_delete.call_count)
        mock_delete_A.assert_called_once_with()
        self.assertEqual(2, mock_create.call_count)

    def test_update_failure_recovery_new_param_stack_list(self):
        """Check that stack-list is not broken if update fails in between.

        Also ensure that next update passes.
        """

        class ResourceTypeA(generic_rsrc.ResourceWithProps):
            count = 0

            def handle_create(self):
                ResourceTypeA.count += 1
                self.resource_id_set('%s%d' % (self.name, self.count))

            def handle_delete(self):
                return super(ResourceTypeA, self).handle_delete()

        resource._register_class('ResourceTypeA', ResourceTypeA)

        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'abc-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'abc-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env1 = environment.Environment({'abc-param': 'abc'})
        tmpl2 = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'smelly-param': {'Type': 'String'}
            },
            'Resources': {
                'AResource': {'Type': 'ResourceTypeA',
                              'Properties': {'Foo': {'Ref': 'smelly-param'}}},
                'BResource': {'Type': 'ResourceWithPropsType',
                              'Properties': {'Foo': {'Ref': 'AResource'}}}
            }
        }
        env2 = environment.Environment({'smelly-param': 'smelly'})

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl, env=env1),
                                 disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])
        self.assertEqual(
            'AResource1',
            self.stack['BResource']._stored_properties_data['Foo'])

        mock_create = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_create',
                                       side_effect=[Exception, None])
        mock_delete = self.patchobject(generic_rsrc.ResourceWithProps,
                                       'handle_delete')
        mock_delete_A = self.patchobject(ResourceTypeA, 'handle_delete')

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2, env=env2),
                                    disable_rollback=True)
        self.stack.update(updated_stack)

        # Ensure UPDATE FAILED
        mock_create.assert_called_once_with()
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])

        # check if heat stack-list works, wherein it tries to fetch template
        # parameters value from env
        self.eng = service.EngineService('a-host', 'a-topic')
        self.eng.list_stacks(self.ctx)

        # Check if next update works fine
        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = stack.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2, env=env2),
                                     disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        a_props = self.stack['AResource']._stored_properties_data['Foo']
        self.assertEqual('smelly', a_props)
        b_props = self.stack['BResource']._stored_properties_data['Foo']
        self.assertEqual('AResource2', b_props)

        self.assertEqual(2, mock_delete.call_count)
        mock_delete_A.assert_called_once_with()
        self.assertEqual(2, mock_create.call_count)

    def test_update_replace_parameters(self):
        """Check that changes in static environment parameters are not ignored.

        Changes in static environment parameters are not ignored and can cause
        dependent resources to be updated.
        """
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': {'Ref': 'AParam'}}}}}

        env1 = environment.Environment({'parameters': {'AParam': 'abc'}})
        env2 = environment.Environment({'parameters': {'AParam': 'smelly'}})
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl, env=env1))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl, env=env2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'smelly',
            self.stack['AResource']._stored_properties_data['Foo'])

    def test_update_deletion_policy(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': 'Bar'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        resource_id = self.stack['AResource'].id

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                        'AResource': {'Type': 'ResourceWithPropsType',
                                      'DeletionPolicy': 'Retain',
                                      'Properties': {'Foo': 'Bar'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(resource_id, self.stack['AResource'].id)

    def test_update_deletion_policy_no_handle_update(self):

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithRequiredProps',
                                  'Properties': {'Foo': 'Bar'}}}}

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        resource_id = self.stack['AResource'].id

        new_tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                    'Resources': {
                        'AResource': {'Type': 'ResourceWithRequiredProps',
                                      'DeletionPolicy': 'Retain',
                                      'Properties': {'Foo': 'Bar'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(new_tmpl))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.assertEqual(resource_id, self.stack['AResource'].id)

    def test_update_template_format_version(self):
        tmpl = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {
                'AParam': {'Type': 'String', 'Default': 'abc'}},
            'Resources': {
                'AResource': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {'Foo': {'Ref': 'AParam'}}
                },
            }
        }

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'abc',
            self.stack['AResource']._stored_properties_data['Foo'])

        tmpl2 = {
            'heat_template_version': '2013-05-23',
            'parameters': {
                'AParam': {'type': 'string', 'default': 'foo'}},
            'resources': {
                'AResource': {
                    'type': 'ResourceWithPropsType',
                    'properties': {'Foo': {'get_param': 'AParam'}}
                }
            }
        }

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual(
            'foo',
            self.stack['AResource']._stored_properties_data['Foo'])

    def test_delete_stack_when_update_failed_twice(self):
        """Test when stack update failed twice and delete the stack.

        Test checks the following scenario:
        1. Create stack
        2. Update stack (failed)
        3. Update stack (failed)
        4. Delete stack
        The test checks the behavior of backup stack when update is failed.
        If some resources were not backed up correctly then test will fail.
        """
        tmpl_create = {
            'heat_template_version': '2013-05-23',
            'resources': {
                'Ares': {'type': 'GenericResourceType'}
            }
        }
        # create a stack
        self.stack = stack.Stack(self.ctx, 'update_fail_test_stack',
                                 template.Template(tmpl_create),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl_update = {
            'heat_template_version': '2013-05-23',
            'parameters': {'aparam': {'type': 'number', 'default': 1}},
            'resources': {
                'Ares': {'type': 'GenericResourceType'},
                'Bres': {'type': 'GenericResourceType'},
                'Cres': {
                    'type': 'ResourceWithPropsRefPropOnDelete',
                    'properties': {
                        'Foo': {'get_resource': 'Bres'},
                        'FooInt': {'get_param': 'aparam'},
                    }
                }
            }
        }

        mock_create = self.patchobject(
            generic_rsrc.ResourceWithProps,
            'handle_create',
            side_effect=[Exception, Exception])

        updated_stack_first = stack.Stack(self.ctx,
                                          'update_fail_test_stack',
                                          template.Template(tmpl_update))
        self.stack.update(updated_stack_first)
        self.stack.resources['Cres'].resource_id_set('c_res')
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)

        # try to update the stack again
        updated_stack_second = stack.Stack(self.ctx,
                                           'update_fail_test_stack',
                                           template.Template(tmpl_update))
        self.stack.update(updated_stack_second)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)

        self.assertEqual(mock_create.call_count, 2)

        # delete the failed stack
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)

    def test_backup_stack_synchronized_after_update(self):
        """Test when backup stack updated correctly during stack update.

        Test checks the following scenario:
        1. Create stack
        2. Update stack (failed - so the backup should not be deleted)
        3. Update stack (failed - so the backup from step 2 should be updated)
        The test checks that backup stack is synchronized with the main stack.
        """
        # create a stack
        tmpl_create = {
            'heat_template_version': '2013-05-23',
            'resources': {
                'Ares': {'type': 'GenericResourceType'}
            }
        }
        self.stack = stack.Stack(self.ctx, 'test_update_stack_backup',
                                 template.Template(tmpl_create),
                                 disable_rollback=True)
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        # try to update a stack with a new resource that should be backed up
        tmpl_update = {
            'heat_template_version': '2013-05-23',
            'resources': {
                'Ares': {'type': 'GenericResourceType'},
                'Bres': {
                    'type': 'ResWithComplexPropsAndAttrs',
                    'properties': {
                        'an_int': 0,
                    }
                },
                'Cres': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_resource': 'Bres'},
                    }
                }
            }
        }

        self.patchobject(generic_rsrc.ResourceWithProps,
                         'handle_create',
                         side_effect=[Exception, Exception])

        stack_with_new_resource = stack.Stack(
            self.ctx,
            'test_update_stack_backup',
            template.Template(tmpl_update))
        self.stack.update(stack_with_new_resource)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        # assert that backup stack has been updated correctly
        self.assertIn('Bres', self.stack._backup_stack())
        # set data for Bres in main stack
        self.stack['Bres'].data_set('test', '42')

        # update the stack with resource that updated in-place
        tmpl_update['resources']['Bres']['properties']['an_int'] = 1
        updated_stack_second = stack.Stack(self.ctx,
                                           'test_update_stack_backup',
                                           template.Template(tmpl_update))
        self.stack.update(updated_stack_second)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        # assert that resource in backup stack also has been updated
        backup = self.stack._backup_stack()
        self.assertEqual(1, backup['Bres'].properties['an_int'])

        # check, that updated Bres in new stack has copied data.
        # Bres in backup stack should have empty data.
        self.assertEqual({}, backup['Bres'].data())
        self.assertEqual({'test': '42'}, self.stack['Bres'].data())

    def test_update_failed_with_new_condition(self):
        create_a_res = {'equals': [{'get_param': 'create_a_res'}, 'yes']}
        create_b_res = {'equals': [{'get_param': 'create_b_res'}, 'yes']}
        tmpl = {
            'heat_template_version': '2016-10-14',
            'parameters': {
                'create_a_res': {
                    'type': 'string',
                    'default': 'yes'
                }
            },
            'conditions': {
                'create_a': create_a_res
            },
            'resources': {
                'Ares': {'type': 'GenericResourceType',
                         'condition': 'create_a'}
            }
        }

        test_stack = stack.Stack(self.ctx,
                                 'test_update_failed_with_new_condition',
                                 template.Template(tmpl))
        test_stack.store()
        test_stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         test_stack.state)
        self.assertIn('Ares', test_stack)

        update_tmpl = copy.deepcopy(tmpl)
        update_tmpl['conditions']['create_b'] = create_b_res
        update_tmpl['parameters']['create_b_res'] = {
            'type': 'string',
            'default': 'yes'
        }
        update_tmpl['resources']['Bres'] = {
            'type': 'OS::Heat::TestResource',
            'properties': {
                'value': 'res_b',
                'fail': True
            }
        }

        stack_with_new_resource = stack.Stack(
            self.ctx,
            'test_update_with_new_res_cd',
            template.Template(update_tmpl))
        test_stack.update(stack_with_new_resource)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         test_stack.state)
        self.assertIn('Bres', test_stack)
        self.assertEqual((resource.Resource.CREATE, resource.Resource.FAILED),
                         test_stack['Bres'].state)
        self.assertIn('create_b', test_stack.t.t['conditions'])
        self.assertIn('create_b_res', test_stack.t.t['parameters'])

    def test_stack_update_with_deprecated_resource(self):
        """Test with update deprecated resource to substitute.

        Test checks the following scenario:
        1. Create stack with deprecated resource.
        2. Update stack with substitute resource.
        The test checks that deprecated resource can be update to it's
        substitute resource during update Stack.
        """

        class ResourceTypeB(generic_rsrc.GenericResource):
            count_b = 0

            def update(self, after, before=None, prev_resource=None):
                ResourceTypeB.count_b += 1

        resource._register_class('ResourceTypeB', ResourceTypeB)

        class ResourceTypeA(ResourceTypeB):
            support_status = support.SupportStatus(
                status=support.DEPRECATED,
                message='deprecation_msg',
                version='2014.2',
                substitute_class=ResourceTypeB)

            count_a = 0

            def update(self, after, before=None, prev_resource=None):
                ResourceTypeA.count_a += 1

        resource._register_class('ResourceTypeA', ResourceTypeA)

        TMPL_WITH_DEPRECATED_RES = """
        heat_template_version: 2015-10-15
        resources:
          AResource:
            type: ResourceTypeA
        """
        TMPL_WITH_PEPLACE_RES = """
        heat_template_version: 2015-10-15
        resources:
          AResource:
            type: ResourceTypeB
        """
        t = template_format.parse(TMPL_WITH_DEPRECATED_RES)
        templ = template.Template(t)
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 templ)

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        t = template_format.parse(TMPL_WITH_PEPLACE_RES)
        tmpl2 = template.Template(t)
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    tmpl2)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('AResource', self.stack)
        self.assertEqual(1, ResourceTypeB.count_b)
        self.assertEqual(0, ResourceTypeA.count_a)
