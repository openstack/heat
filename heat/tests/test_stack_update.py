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
import mox

from heat.common import template_format
from heat.engine import environment
from heat.engine import resource
from heat.engine import scheduler
from heat.engine import stack
from heat.engine import template
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

        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)
        resource._register_class('ResWithComplexPropsAndAttrs',
                                 generic_rsrc.ResWithComplexPropsAndAttrs)

    def test_update_add(self):
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
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

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
        self.assertEqual(True, self.stack.disable_rollback)

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

        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])

        loaded_stack = stack.Stack.load(self.ctx, self.stack.id)
        stored_props = loaded_stack['AResource']._stored_properties_data
        self.assertEqual({'Foo': 'xyz'}, stored_props)

        self.m.VerifyAll()

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
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        value1 = 2
        prop_diff1 = {'an_int': value1}
        value2 = 1
        prop_diff2 = {'an_int': value2}

        self.m.StubOutWithMock(generic_rsrc.ResWithComplexPropsAndAttrs,
                               'handle_update')
        generic_rsrc.ResWithComplexPropsAndAttrs.handle_update(mox.IgnoreArg(),
                                                               mox.IgnoreArg(),
                                                               prop_diff1)
        generic_rsrc.ResWithComplexPropsAndAttrs.handle_update(mox.IgnoreArg(),
                                                               mox.IgnoreArg(),
                                                               prop_diff2)

        self.m.ReplayAll()

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
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

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
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.m.VerifyAll()

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

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps,
                               'update_template_diff')

        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 environment.Environment({'foo': 'abc'}))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl),
                                    environment.Environment({'foo': 'xyz'}))

        def check_props(*args):
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        generic_rsrc.ResourceWithProps.update_template_diff(
            {'Type': 'ResourceWithPropsType',
             'Properties': {'Foo': 'xyz'}},
            {'Type': 'ResourceWithPropsType',
             'Properties': {'Foo': 'abc'}}
        ).WithSideEffects(check_props).AndRaise(resource.UpdateReplace)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('xyz', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()

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

        # patch in a dummy handle_update
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_update')
        tmpl_diff = {'Properties': {'Foo': 'xyz'}}
        prop_diff = {'Foo': 'xyz'}
        generic_rsrc.ResourceWithProps.handle_update(
            tmpl2['Resources']['AResource'], tmpl_diff,
            prop_diff).AndRaise(Exception("Foo"))
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()
        # Unset here so destroy() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_failed_create_and_delete_1(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_failed_create_and_delete_2(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create()
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'c_res').AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is overwritten
        # by the mox.
        self.stack.resources['AResource'].resource_id_set('c_res')
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.stack.delete()
        self.assertEqual((stack.Stack.DELETE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()

    def test_update_modify_replace_create_in_progress_and_delete_1(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

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
        self.m.VerifyAll()

    def test_update_modify_replace_create_in_progress_and_delete_2(self):
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'handle_create')
        generic_rsrc.ResourceWithResourceID.handle_create()
        generic_rsrc.ResourceWithResourceID.handle_create().AndRaise(Exception)

        self.m.StubOutWithMock(generic_rsrc.ResourceWithResourceID,
                               'mox_resource_id')
        # First, attempts to delete backup_stack. The create (xyz) has been
        # failed, so it has no resource_id.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            None).AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'c_res').AndReturn(None)
        # There are dependency AResource and BResource, so we must delete
        # BResource, then delete AResource.
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'b_res').AndReturn(None)
        generic_rsrc.ResourceWithResourceID.mox_resource_id(
            'a_res').AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        # set resource_id for AResource because handle_create() is overwritten
        # by the mox.
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
        self.m.VerifyAll()

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
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = stack.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)
        self.m.VerifyAll()

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

        # patch in a dummy handle_create making BResource fail creating
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_delete')
        generic_rsrc.GenericResource.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.FAILED),
                         self.stack.state)
        self.assertIn('BResource', self.stack)

        # Reload the stack from the DB and prove that it contains the failed
        # resource (to ensure it will be deleted on stack delete)
        re_stack = stack.Stack.load(utils.dummy_context(), self.stack.id)
        self.assertIn('BResource', re_stack)
        self.m.VerifyAll()

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

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        with mock.patch.object(self.stack, 'state_set',
                               side_effect=self.stack.state_set) as mock_state:
            self.stack.update(updated_stack)
            self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                             self.stack.state)
            self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
            self.assertEqual(2, mock_state.call_count)
            self.assertEqual(('UPDATE', 'IN_PROGRESS'),
                             mock_state.call_args_list[0][0][:2])
            self.assertEqual(('ROLLBACK', 'IN_PROGRESS'),
                             mock_state.call_args_list[1][0][:2])
        self.m.VerifyAll()

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
        evt_mock = mock.MagicMock()
        evt_mock.ready.return_value = True
        evt_mock.wait.return_value = 'cancel'

        self.m.ReplayAll()

        self.stack.update(updated_stack, event=evt_mock)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_update_rollback_fail(self):
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                            'Properties': {'Foo': 'abc'}}}}

        env1 = {'parameters': {'AParam': 'abc'}}
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 disable_rollback=False,
                                 env=environment.Environment(env1))
        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)

        tmpl2 = {'HeatTemplateFormatVersion': '2012-12-12',
                 'Parameters': {'BParam': {'Type': 'String'}},
                 'Resources': {'AResource': {'Type': 'ResourceWithPropsType',
                                             'Properties': {'Foo': 'xyz'}}}}

        env2 = {'parameters': {'BParam': 'smelly'}}
        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False,
                                    env=environment.Environment(env2))

        # patch in a dummy handle_create making the replace fail when creating
        # the replacement rsrc, and again on the second call (rollback)
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.FAILED),
                         self.stack.state)
        self.m.VerifyAll()

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
        self.m.StubOutWithMock(generic_rsrc.GenericResource, 'handle_create')
        generic_rsrc.GenericResource.handle_create().AndRaise(Exception)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertNotIn('BResource', self.stack)
        self.m.VerifyAll()

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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        # replace the failed resource on rollback
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()
        self.m.ReplayAll()

        self.stack.update(updated_stack)

        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertIn('BResource', self.stack)
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

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
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        generic_rsrc.ResourceWithProps.handle_delete().AndRaise(Exception)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        generic_rsrc.ResourceWithProps.handle_delete().AndReturn(None)
        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.m.VerifyAll()
        # Unset here so delete() is not stubbed for stack.delete cleanup
        self.m.UnsetStubs()

    def test_update_replace_by_reference(self):
        '''
        assertion:
        changes in dynamic attributes, due to other resources been updated
        are not ignored and can cause dependent resources to be updated.
        '''
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
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        generic_rsrc.ResourceWithProps.FnGetRefId().AndReturn(
            'AResource')
        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'inst-007')
        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('inst-007', self.stack['BResource'].properties['Foo'])
        self.m.VerifyAll()

    def test_update_with_new_resources_with_reference(self):
        '''
        assertion:
        check, that during update with new resources which one has
        reference on second, reference will be correct resolved.
        '''
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
        self.assertEqual('abc', self.stack['CResource'].properties['Foo'])
        self.assertEqual(1, len(self.stack.resources))

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        generic_rsrc.ResourceWithProps.handle_create().MultipleTimes(
        ).AndReturn(None)

        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.assertEqual(3, len(self.stack.resources))
        self.m.VerifyAll()

    def test_update_by_reference_and_rollback_1(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the first instance
        '''
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
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'FnGetRefId')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        generic_rsrc.ResourceWithProps.FnGetRefId().MultipleTimes().AndReturn(
            'AResource')

        # mock to make the replace fail when creating the replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_by_reference_and_rollback_2(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the second instance
        '''

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
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)

        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=False)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.ROLLBACK, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_failure_recovery(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the second instance
        '''

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
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        self.m.StubOutWithMock(ResourceTypeA, 'handle_delete')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        # delete the old resource on the second update
        generic_rsrc.ResourceWithProps.handle_delete()
        ResourceTypeA.handle_delete()
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()

        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2),
                                    disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = stack.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2),
                                     disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource2',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_failure_recovery_new_param(self):
        '''
        assertion:
        check that rollback still works with dynamic metadata
        this test fails the second instance
        '''

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
                                 template.Template(tmpl), env1,
                                 disable_rollback=True)

        self.stack.store()
        self.stack.create()

        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource1',
                         self.stack['BResource'].properties['Foo'])

        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_create')
        self.m.StubOutWithMock(generic_rsrc.ResourceWithProps, 'handle_delete')
        self.m.StubOutWithMock(ResourceTypeA, 'handle_delete')

        # mock to make the replace fail when creating the second
        # replacement resource
        generic_rsrc.ResourceWithProps.handle_create().AndRaise(Exception)
        # delete the old resource on the second update
        generic_rsrc.ResourceWithProps.handle_delete()
        ResourceTypeA.handle_delete()
        generic_rsrc.ResourceWithProps.handle_create()
        generic_rsrc.ResourceWithProps.handle_delete()

        self.m.ReplayAll()

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl2), env2,
                                    disable_rollback=True)
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.FAILED),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        updated_stack2 = stack.Stack(self.ctx, 'updated_stack',
                                     template.Template(tmpl2), env2,
                                     disable_rollback=True)

        self.stack.update(updated_stack2)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)

        self.stack = stack.Stack.load(self.ctx, self.stack.id)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])
        self.assertEqual('AResource2',
                         self.stack['BResource'].properties['Foo'])

        self.m.VerifyAll()

    def test_update_replace_parameters(self):
        '''
        assertion:
        changes in static environment parameters
        are not ignored and can cause dependent resources to be updated.
        '''
        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Parameters': {'AParam': {'Type': 'String'}},
                'Resources': {
                    'AResource': {'Type': 'ResourceWithPropsType',
                                  'Properties': {'Foo': {'Ref': 'AParam'}}}}}

        env1 = {'parameters': {'AParam': 'abc'}}
        env2 = {'parameters': {'AParam': 'smelly'}}
        self.stack = stack.Stack(self.ctx, 'update_test_stack',
                                 template.Template(tmpl),
                                 environment.Environment(env1))

        self.stack.store()
        self.stack.create()
        self.assertEqual((stack.Stack.CREATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

        updated_stack = stack.Stack(self.ctx, 'updated_stack',
                                    template.Template(tmpl),
                                    environment.Environment(env2))
        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('smelly', self.stack['AResource'].properties['Foo'])

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

        class ResourceWithNoUpdate(resource.Resource):
            properties_schema = {'Foo': {'Type': 'String'}}

        resource._register_class('ResourceWithNoUpdate',
                                 ResourceWithNoUpdate)

        tmpl = {'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'AResource': {'Type': 'ResourceWithNoUpdate',
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
                        'AResource': {'Type': 'ResourceWithNoUpdate',
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
        self.assertEqual('abc', self.stack['AResource'].properties['Foo'])

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

        self.m.ReplayAll()

        self.stack.update(updated_stack)
        self.assertEqual((stack.Stack.UPDATE, stack.Stack.COMPLETE),
                         self.stack.state)
        self.assertEqual('foo', self.stack['AResource'].properties['Foo'])
        self.m.VerifyAll()
