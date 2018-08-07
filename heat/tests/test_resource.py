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

import collections
import datetime
import eventlet
import itertools
import json
import os
import sys
import uuid

import mock
from oslo_config import cfg
import six

from heat.common import exception
from heat.common.i18n import _
from heat.common import short_id
from heat.common import timeutils
from heat.db.sqlalchemy import api as db_api
from heat.db.sqlalchemy import models
from heat.engine import attributes
from heat.engine.cfn import functions as cfn_funcs
from heat.engine import clients
from heat.engine import constraints
from heat.engine import dependencies
from heat.engine import environment
from heat.engine import node_data
from heat.engine import plugin_manager
from heat.engine import properties
from heat.engine import resource
from heat.engine import resources
from heat.engine.resources.openstack.heat import none_resource
from heat.engine.resources.openstack.heat import test_resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import support
from heat.engine import template
from heat.engine import translation
from heat.objects import resource as resource_objects
from heat.objects import resource_data as resource_data_object
from heat.objects import resource_properties_data as rpd_object
from heat.tests import common
from heat.tests.engine import tools
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

import neutronclient.common.exceptions as neutron_exp


empty_template = {"HeatTemplateFormatVersion": "2012-12-12"}


class ResourceTest(common.HeatTestCase):
    def setUp(self):
        super(ResourceTest, self).setUp()

        self.env = environment.Environment()
        self.env.load({u'resource_registry':
                      {u'OS::Test::GenericResource': u'GenericResourceType',
                       u'OS::Test::ResourceWithCustomConstraint':
                       u'ResourceWithCustomConstraint'}})

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template,
                                                    env=self.env),
                                  stack_id=str(uuid.uuid4()))
        self.dummy_timeout = 10
        self.dummy_event = eventlet.event.Event()

    def test_get_class_ok(self):
        cls = resources.global_env().get_class_to_instantiate(
            'GenericResourceType')
        self.assertEqual(generic_rsrc.GenericResource, cls)

    def test_get_class_noexist(self):
        self.assertRaises(exception.StackValidationFailed,
                          resources.global_env().get_class_to_instantiate,
                          'NoExistResourceType')

    def test_resource_new_ok(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        self.assertIsInstance(res, generic_rsrc.GenericResource)
        self.assertEqual("INIT", res.action)

    def test_resource_load_with_state(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        # Store Resource
        res = resource.Resource('aresource', snippet, self.stack)
        res.current_template_id = self.stack.t.id
        res.state_set('CREATE', 'IN_PROGRESS')
        self.stack.add_resource(res)
        loaded_res, res_owning_stack, stack = resource.Resource.load(
            self.stack.context, res.id,
            self.stack.current_traversal, True, {})
        self.assertEqual(loaded_res.id, res.id)
        self.assertEqual(self.stack.t, stack.t)

    def test_resource_load_with_state_cleanup(self):
        self.old_stack = parser.Stack(
            utils.dummy_context(), 'test_old_stack',
            template.Template({
                'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'test_res': {'Type': 'ResourceWithPropsType',
                                 'Properties': {'Foo': 'abc'}}}}))
        self.old_stack.store()
        self.new_stack = parser.Stack(utils.dummy_context(), 'test_new_stack',
                                      template.Template(empty_template))
        self.new_stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        # Store Resource
        res = resource.Resource('aresource', snippet, self.old_stack)
        res.current_template_id = self.old_stack.t.id
        res.state_set('CREATE', 'IN_PROGRESS')
        self.old_stack.add_resource(res)
        loaded_res, res_owning_stack, stack = resource.Resource.load(
            self.old_stack.context, res.id,
            self.stack.current_traversal, False, {})
        self.assertEqual(loaded_res.id, res.id)
        self.assertEqual(self.old_stack.t, stack.t)
        self.assertNotEqual(self.new_stack.t, stack.t)

    def test_resource_load_with_no_resources(self):
        self.stack = parser.Stack(
            utils.dummy_context(), 'test_old_stack',
            template.Template({
                'HeatTemplateFormatVersion': '2012-12-12',
                'Resources': {
                    'test_res': {'Type': 'ResourceWithPropsType',
                                 'Properties': {'Foo': 'abc'}}}}))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        # Store Resource
        res = resource.Resource('aresource', snippet, self.stack)
        res.current_template_id = self.stack.t.id
        res.state_set('CREATE', 'IN_PROGRESS')
        self.stack.add_resource(res)
        origin_resources = self.stack.resources
        self.stack._resources = None

        loaded_res, res_owning_stack, stack = resource.Resource.load(
            self.stack.context, res.id,
            self.stack.current_traversal, False, {})
        self.assertEqual(origin_resources, stack.resources)
        self.assertEqual(loaded_res.id, res.id)
        self.assertEqual(self.stack.t, stack.t)

    def test_resource_invalid_name(self):
        snippet = rsrc_defn.ResourceDefinition('wrong/name',
                                               'GenericResourceType')
        ex = self.assertRaises(exception.StackValidationFailed,
                               resource.Resource, 'wrong/name',
                               snippet, self.stack)
        self.assertEqual('Resource name may not contain "/"',
                         six.text_type(ex))

    @mock.patch.object(translation, 'resolve_and_find')
    @mock.patch.object(parser.Stack, 'db_resource_get')
    @mock.patch.object(resource.Resource, '_load_data')
    @mock.patch.object(resource.Resource, 'translate_properties')
    def test_stack_resources(self, mock_translate, mock_load,
                             mock_db_get, mock_resolve):
        tpl = {'HeatTemplateFormatVersion': '2012-12-12',
               'Resources':
                   {'A': {'Type': 'ResourceWithPropsType',
                          'Properties': {'Foo': 'abc'}}}}

        stack = parser.Stack(utils.dummy_context(),
                             'test_stack',
                             template.Template(tpl))
        stack.store()
        mock_db_get.return_value = None
        self.assertEqual(1, len(stack.resources))
        self.assertEqual(1, mock_translate.call_count)
        self.assertEqual(0, mock_load.call_count)

        # set stack._resources = None to reload the resources
        stack._resources = None
        mock_db_get.return_value = mock.Mock()
        self.assertEqual(1, len(stack.resources))
        self.assertEqual(2, mock_translate.call_count)
        self.assertEqual(1, mock_load.call_count)
        self.assertEqual(0, mock_resolve.call_count)

    def test_resource_new_stack_not_stored(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        self.stack.id = None
        db_method = 'get_by_name_and_stack'
        with mock.patch.object(resource_objects.Resource,
                               db_method) as resource_get:
            res = resource.Resource('aresource', snippet, self.stack)
            self.assertEqual("INIT", res.action)
            self.assertIs(False, resource_get.called)

    def test_resource_new_err(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'NoExistResourceType')
        self.assertRaises(exception.StackValidationFailed,
                          resource.Resource, 'aresource', snippet, self.stack)

    def test_resource_non_type(self):
        resource_name = 'aresource'
        snippet = rsrc_defn.ResourceDefinition(resource_name, '')
        ex = self.assertRaises(exception.StackValidationFailed,
                               resource.Resource, resource_name,
                               snippet, self.stack)
        self.assertIn(_('Resource "%s" has no type') % resource_name,
                      six.text_type(ex))

    def test_state_defaults(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_def', 'Foo')
        res = generic_rsrc.GenericResource('test_res_def', tmpl, self.stack)
        self.assertEqual((res.INIT, res.COMPLETE), res.state)
        self.assertEqual('', res.status_reason)

    def test_signal_wrong_action_state(self):
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)
        actions = [res.SUSPEND, res.DELETE]
        for action in actions:
            for status in res.STATUSES:
                res.state_set(action, status)
                ev = self.patchobject(res, '_add_event')
                ex = self.assertRaises(exception.NotSupported,
                                       res.signal)
                self.assertEqual('Signal resource during %s is not '
                                 'supported.' % action, six.text_type(ex))
                ev.assert_called_with(
                    action, status,
                    'Cannot signal resource during %s' % action)

    def test_resource_str_repr_stack_id_resource_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = "123"
        res.resource_id = "456"
        expected = ('GenericResource "test_res_str_repr" [456] Stack '
                    '"test_stack" [123]')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_resource_str_repr_stack_id_no_resource_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = "123"
        res.resource_id = None
        expected = ('GenericResource "test_res_str_repr" Stack "test_stack" '
                    '[123]')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_resource_str_repr_no_stack_id(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res_str_repr', 'Foo')
        res = generic_rsrc.GenericResource('test_res_str_repr', tmpl,
                                           self.stack)
        res.stack.id = None
        expected = ('GenericResource "test_res_str_repr"')
        observed = str(res)
        self.assertEqual(expected, observed)

    def test_state_set(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.state_set(res.CREATE, res.IN_PROGRESS, 'test_state_set')
        self.assertIsNotNone(res.id)
        self.assertEqual(res.CREATE, res.action)
        self.assertEqual(res.IN_PROGRESS, res.status)
        self.assertEqual('test_state_set', res.status_reason)

        db_res = resource_objects.Resource.get_obj(res.context, res.id)
        self.assertEqual(res.CREATE, db_res.action)
        self.assertEqual(res.IN_PROGRESS, db_res.status)
        self.assertEqual('test_state_set', db_res.status_reason)

        res.state_set(res.CREATE, res.COMPLETE, 'test_update')
        self.assertEqual(res.CREATE, res.action)
        self.assertEqual(res.COMPLETE, res.status)
        self.assertEqual('test_update', res.status_reason)
        db_res.refresh()
        self.assertEqual(res.CREATE, db_res.action)
        self.assertEqual(res.COMPLETE, db_res.status)
        self.assertEqual('test_update', db_res.status_reason)

    def test_physical_resource_name_or_FnGetRefId(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        # use physical_resource_name when res.id is not None
        self.assertIsNotNone(res.id)
        expected = '%s-%s-%s' % (self.stack.name,
                                 res.name,
                                 short_id.get_id(res.uuid))
        self.assertEqual(expected, res.physical_resource_name_or_FnGetRefId())

        # otherwise use parent method
        res.id = None
        self.assertIsNone(res.resource_id)
        self.assertEqual('test_resource',
                         res.physical_resource_name_or_FnGetRefId())

    def test_prepare_abandon(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        expected = {
            'action': 'INIT',
            'metadata': {},
            'name': 'test_resource',
            'resource_data': {},
            'resource_id': None,
            'status': 'COMPLETE',
            'type': 'Foo'
        }
        actual = res.prepare_abandon()
        self.assertEqual(expected, actual)

    def test_abandon_with_resource_data(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res._data = {"test-key": "test-value"}

        expected = {
            'action': 'INIT',
            'metadata': {},
            'name': 'test_resource',
            'resource_data': {"test-key": "test-value"},
            'resource_id': None,
            'status': 'COMPLETE',
            'type': 'Foo'
        }
        actual = res.prepare_abandon()
        self.assertEqual(expected, actual)

    def test_create_from_external(self):
        tmpl = rsrc_defn.ResourceDefinition(
            'test_resource', 'GenericResourceType',
            external_id='f00d')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)
        self.assertEqual('f00d', res.resource_id)

    def test_create_from_external_not_found(self):
        external_id = 'f00d'
        tmpl = rsrc_defn.ResourceDefinition(
            'test_resource', 'GenericResourceType',
            external_id=external_id)
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res._default_client_plugin = mock.Mock()
        self.patchobject(res._default_client_plugin(), 'is_not_found',
                         return_value=True)
        self.patchobject(res, '_show_resource', side_effect=Exception())
        e = self.assertRaises(exception.StackValidationFailed,
                              res.validate_external)
        message = (("Invalid external resource: Resource %(external_id)s "
                    "(%(type)s) can not be found.") %
                   {'external_id': external_id,
                    'type': res.type()})
        self.assertEqual(message, six.text_type(e))

    def test_updated_from_external(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        utmpl = rsrc_defn.ResourceDefinition(
            'test_resource', 'GenericResourceType',
            external_id='f00d')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        expected_err_msg = ('NotSupported: resources.test_resource: Update '
                            'to property external_id of test_resource '
                            '(GenericResourceType) is not supported.')
        err = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.update, utmpl)
                                )
        self.assertEqual(expected_err_msg, six.text_type(err))

    def test_state_set_invalid(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertRaises(ValueError, res.state_set, 'foo', 'bla')
        self.assertRaises(ValueError, res.state_set, 'foo', res.COMPLETE)
        self.assertRaises(ValueError, res.state_set, res.CREATE, 'bla')

    def test_state_del_stack(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        self.stack.action = self.stack.DELETE
        self.stack.status = self.stack.IN_PROGRESS
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual(res.DELETE, res.action)
        self.assertEqual(res.COMPLETE, res.status)

    def test_type(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual('Foo', res.type())

    def test_has_interface_direct_match(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_has_interface_no_match(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertFalse(res.has_interface('LookingForAnotherType'))

    def test_has_interface_mapping(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'OS::Test::GenericResource')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertTrue(res.has_interface('GenericResourceType'))

    def test_has_interface_mapping_no_match(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'OS::Test::GenoricResort')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertFalse(res.has_interface('GenericResourceType'))

    def test_created_time(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_res_new', tmpl, self.stack)
        self.assertIsNone(res.created_time)
        res.store()
        self.assertIsNotNone(res.created_time)

    def test_updated_time(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.store()
        stored_time = res.updated_time

        utmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res.state_set(res.CREATE, res.COMPLETE)
        scheduler.TaskRunner(res.update, utmpl)()
        self.assertIsNotNone(res.updated_time)
        self.assertNotEqual(res.updated_time, stored_time)

    def _setup_resource_for_update(self, res_name):
        class TestResource(resource.Resource):
            properties_schema = {'a_string': {'Type': 'String'}}
            update_allowed_properties = ('a_string',)

        resource._register_class('TestResource', TestResource)

        tmpl = rsrc_defn.ResourceDefinition(res_name,
                                            'TestResource')
        res = TestResource('test_resource', tmpl, self.stack)

        utmpl = rsrc_defn.ResourceDefinition(res_name, 'TestResource',
                                             {'a_string': 'foo'})

        return res, utmpl

    def test_update_replace(self):
        res, utmpl = self._setup_resource_for_update(
            res_name='test_update_replace')
        self.assertEqual((res.INIT, res.COMPLETE), res.state)
        res.prepare_for_replace = mock.Mock()
        # resource replaced if in INIT_COMPLETE
        self.assertRaises(
            resource.UpdateReplace, scheduler.TaskRunner(res.update, utmpl))
        self.assertTrue(res.prepare_for_replace.called)

    def test_update_replace_in_check_failed(self):
        res, utmpl = self._setup_resource_for_update(
            res_name='test_update_replace')
        res.state_set(res.CHECK, res.FAILED)
        res.prepare_for_replace = mock.Mock()
        res.needs_replace_failed = mock.MagicMock(return_value=False)

        self.assertRaises(
            resource.UpdateReplace, scheduler.TaskRunner(res.update, utmpl))
        self.assertFalse(res.needs_replace_failed.called)
        self.assertTrue(res.prepare_for_replace.called)

    def test_no_update_or_replace_in_failed(self):
        res, utmpl = self._setup_resource_for_update(
            res_name='test_failed_res_no_update_or_replace')
        res.state_set(res.CREATE, res.FAILED)
        res.prepare_for_replace = mock.Mock()
        res.needs_replace_failed = mock.MagicMock(return_value=False)

        scheduler.TaskRunner(res.update, res.t)()
        self.assertTrue(res.needs_replace_failed.called)
        self.assertFalse(res.prepare_for_replace.called)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        status_reason = _('Update status to COMPLETE for '
                          'FAILED resource neither update '
                          'nor replace.')
        self.assertEqual(status_reason, res.status_reason)

    def test_update_replace_prepare_replace_error(self):
        # test if any error happened when prepare_for_replace,
        # whether the resource will go to FAILED
        res, utmpl = self._setup_resource_for_update(
            res_name='test_update_replace_prepare_replace_error')
        res.prepare_for_replace = mock.Mock(side_effect=Exception)

        self.assertRaises(
            exception.ResourceFailure,
            scheduler.TaskRunner(res.update, utmpl))
        self.assertTrue(res.prepare_for_replace.called)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_rsrc_in_progress_raises_exception(self):
        res, utmpl = self._setup_resource_for_update(
            res_name='test_update_rsrc_in_progress_raises_exception')

        cfg.CONF.set_override('convergence_engine', False)

        res.action = res.UPDATE
        res.status = res.IN_PROGRESS
        self.assertRaises(
            exception.ResourceFailure, scheduler.TaskRunner(res.update, utmpl))

    def test_update_replace_rollback(self):
        cfg.CONF.set_override('convergence_engine', False)
        res, utmpl = self._setup_resource_for_update(
            res_name='test_update_replace_rollback')
        res.restore_prev_rsrc = mock.Mock()
        self.stack.state_set('ROLLBACK', 'IN_PROGRESS', 'Simulate rollback')

        self.assertRaises(
            resource.UpdateReplace, scheduler.TaskRunner(res.update, utmpl))
        self.assertTrue(res.restore_prev_rsrc.called)

    def test_update_replace_rollback_restore_prev_rsrc_error(self):
        cfg.CONF.set_override('convergence_engine', False)
        res, utmpl = self._setup_resource_for_update(
            res_name='restore_prev_rsrc_error')
        res.restore_prev_rsrc = mock.Mock(side_effect=Exception)
        self.stack.state_set('ROLLBACK', 'IN_PROGRESS', 'Simulate rollback')

        self.assertRaises(
            exception.ResourceFailure, scheduler.TaskRunner(res.update, utmpl))
        self.assertTrue(res.restore_prev_rsrc.called)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_replace_in_failed_without_nested(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        m_hc = mock.Mock(side_effect=exception.ResourceFailure)
        res.handle_create = m_hc

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.create))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        # resource in failed status and hasn't nested will enter
        # UpdateReplace flow
        self.assertRaises(
            resource.UpdateReplace, scheduler.TaskRunner(res.update, utmpl))
        m_hc.assert_called_once_with()

    def test_updated_time_changes_only_when_it_changed(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.store()
        self.assertIsNone(res.updated_time)
        res.updated_time = datetime.datetime.utcnow()
        res.store()
        self.assertIsNotNone(res.updated_time)

    def test_resource_object_get_obj_fields(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        res.store()
        res_obj = resource_objects.Resource.get_obj(
            res.context, res.id, refresh=False, fields=('status', ))
        self.assertEqual(res_obj.status, res.COMPLETE)
        self.assertRaises(AttributeError, getattr, res_obj, 'action')

    def test_attributes_store(self):
        res_def = rsrc_defn.ResourceDefinition('test_resource',
                                               'ResWithStringPropAndAttr')
        res = generic_rsrc.ResWithStringPropAndAttr(
            'test_res_attr_store', res_def, self.stack)

        res.action = res.CREATE
        res.status = res.COMPLETE
        res.store()
        res.store_attributes()
        # attr was not resolved, cache was not warmed, nothing to store
        self.assertIsNone(res._attr_data_id)

        with mock.patch.object(res, '_resolve_attribute') as res_attr:
            attr_val = '0123 four'
            res_attr.return_value = attr_val
            res.attributes['string']

            # attr cache is warmed, now store_attributes persists something
            res.store_attributes()
            self.assertIsNotNone(res._attr_data_id)

            # verify the attribute rpd obj that was stored matches
            self.assertEqual({'string': attr_val},
                             rpd_object.ResourcePropertiesData.get_by_id(
                                 res.context, res._attr_data_id).data)

    def test_attributes_load_stored(self):
        res_def = rsrc_defn.ResourceDefinition('test_resource',
                                               'ResWithStringPropAndAttr')
        res = generic_rsrc.ResWithStringPropAndAttr(
            'test_res_attr_store', res_def, self.stack)

        res.action = res.UPDATE
        res.status = res.COMPLETE
        res.store()
        attr_data = {'string': 'word'}
        resource_objects.Resource.store_attributes(
            res.context, res.id, res._atomic_key, attr_data, None)
        res._load_data(resource_objects.Resource.get_obj(
            res.context, res.id))
        with mock.patch.object(res, '_resolve_attribute') as res_attr:
            self.assertEqual(attr_data, res.attributes._resolved_values)
            self.assertEqual('word', res.attributes['string'])
            self.assertEqual(0, res_attr.call_count)

    def test_store_attributes_fail(self):
        res_def = rsrc_defn.ResourceDefinition('test_resource',
                                               'ResWithStringPropAndAttr')
        res = generic_rsrc.ResWithStringPropAndAttr(
            'test_res_attr_store', res_def, self.stack)

        res.action = res.UPDATE
        res.status = res.COMPLETE
        res.store()
        attr_data = {'string': 'word'}
        # set the attr_data_id first
        resource_objects.Resource.update_by_id(res.context, res.id,
                                               {'attr_data_id': 99})
        new_attr_data_id = resource_objects.Resource.store_attributes(
            res.context, res.id, res._atomic_key, attr_data, None)
        # fail to store new attr data
        self.assertIsNone(new_attr_data_id)
        res._load_data(resource_objects.Resource.get_obj(
            res.context, res.id))
        self.assertEqual({}, res.attributes._resolved_values)

    def test_resource_object_resource_properties_data(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        data = {'p1': 'i see',
                'p2': 'good times, good times'}
        rpd_obj = rpd_object.ResourcePropertiesData().create_or_update(
            self.stack.context, data)
        rpd_db_obj = self.stack.context.session.query(
            models.ResourcePropertiesData).get(rpd_obj.id)
        res_obj1 = resource_objects.Resource().create(
            self.stack.context,
            {'stack_id': self.stack.id,
             'uuid': str(uuid.uuid4()),
             'rsrc_prop_data': rpd_db_obj})
        res_obj2 = resource_objects.Resource().create(
            self.stack.context,
            {'stack_id': self.stack.id,
             'uuid': str(uuid.uuid4()),
             'rsrc_prop_data_id': rpd_db_obj.id})
        ctx2 = utils.dummy_context()
        res_obj1 = resource_objects.Resource().get_obj(
            ctx2, res_obj1.id)
        res_obj2 = resource_objects.Resource().get_obj(
            ctx2, res_obj2.id)

        # verify the resource_properties_data association
        # can be set by id
        self.assertEqual(rpd_db_obj.id, res_obj1.rsrc_prop_data_id)
        self.assertEqual(res_obj1.rsrc_prop_data_id,
                         res_obj2.rsrc_prop_data_id)
        # properties data appears unencrypted to resource object
        self.assertEqual(data, res_obj1.properties_data)
        self.assertEqual(data, res_obj2.properties_data)

    def test_make_replacement(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_res_upd', tmpl, self.stack)
        res.store()
        new_tmpl_id = 2
        self.assertIsNotNone(res.id)
        new_requires = {1, 2, 4}
        new_id = res.make_replacement(new_tmpl_id, new_requires)
        new_res = resource_objects.Resource.get_obj(res.context, new_id)

        self.assertEqual(new_id, res.replaced_by)
        self.assertEqual(res.id, new_res.replaces)
        self.assertIsNone(new_res.physical_resource_id)
        self.assertEqual(new_tmpl_id, new_res.current_template_id)
        self.assertEqual([4, 2, 1], new_res.requires)

    def test_metadata_default(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        self.assertEqual({}, res.metadata_get())

    def test_metadata_set_when_deleted(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        res.store()
        md = {"don't": "care"}
        res.action = 'CREATE'
        res.metadata_set(md)
        self.assertFalse(hasattr(res, '_db_res_is_deleted'))

        res_obj = self.stack.context.session.query(
            models.Resource).get(res.id)
        res_obj.update({'action': 'DELETE'})

        self.assertRaises(exception.ResourceNotAvailable,
                          res.metadata_set, md)
        self.assertTrue(res._db_res_is_deleted)

    def test_equals_different_stacks(self):
        tmpl1 = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        tmpl2 = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        tmpl3 = rsrc_defn.ResourceDefinition('test_resource2', 'Bar')
        stack2 = parser.Stack(utils.dummy_context(), 'test_stack',
                              template.Template(empty_template), stack_id=-1)
        res1 = generic_rsrc.GenericResource('test_resource', tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource', tmpl2, stack2)
        res3 = generic_rsrc.GenericResource('test_resource2', tmpl3, stack2)

        self.assertEqual(res1, res2)
        self.assertNotEqual(res1, res3)

    def test_equals_names(self):
        tmpl1 = rsrc_defn.ResourceDefinition('test_resource1', 'Foo')
        tmpl2 = rsrc_defn.ResourceDefinition('test_resource2', 'Foo')
        res1 = generic_rsrc.GenericResource('test_resource1',
                                            tmpl1, self.stack)
        res2 = generic_rsrc.GenericResource('test_resource2', tmpl2,
                                            self.stack)

        self.assertNotEqual(res1, res2)

    def test_update_template_diff_changed_modified(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            metadata={'foo': 123})
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                                      metadata={'foo': 456})
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertFalse(diff.properties_changed())
        self.assertTrue(diff.metadata_changed())
        self.assertFalse(diff.update_policy_changed())

    def test_update_template_diff_changed_add(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                                      metadata={'foo': 123})
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertFalse(diff.properties_changed())
        self.assertTrue(diff.metadata_changed())
        self.assertFalse(diff.update_policy_changed())

    def test_update_template_diff_changed_remove(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            metadata={'foo': 123})
        update_snippet = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.GenericResource('test_resource', tmpl, self.stack)
        diff = res.update_template_diff(update_snippet, tmpl)
        self.assertFalse(diff.properties_changed())
        self.assertTrue(diff.metadata_changed())
        self.assertFalse(diff.update_policy_changed())

    def test_update_template_diff_properties_none(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = tmpl.properties(res.properties_schema,
                                      self.stack.context)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({}, diff)

    def test_update_template_diff_properties_added(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        update_defn = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                                   properties={'Foo': 123})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = update_defn.properties(res.properties_schema,
                                             self.stack.context)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '123'}, diff)

    def test_update_template_diff_properties_removed_no_default_value(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': '123'})
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo')

        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = new_t.properties(res.properties_schema,
                                       self.stack.context)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': None}, diff)

    def test_update_template_diff_properties_removed_with_default_value(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': '123'})
        schema = {'Foo': {'Type': 'String', 'Default': '567'}}
        self.patchobject(generic_rsrc.ResourceWithProps, 'properties_schema',
                         new=schema)
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo')

        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = new_t.properties(res.properties_schema,
                                       self.stack.context)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '567'}, diff)

    def test_update_template_diff_properties_changed(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': '123'})
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                             {'Foo': '456'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = new_t.properties(res.properties_schema,
                                       self.stack.context)
        diff = res.update_template_diff_properties(after_props, before_props)
        self.assertEqual({'Foo': '456'}, diff)

    def test_update_template_diff_properties_notallowed(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': '123'})
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                             {'Bar': '456'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Cat',)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = new_t.properties(res.properties_schema,
                                       self.stack.context)
        self.assertRaises(resource.UpdateReplace,
                          res.update_template_diff_properties,
                          after_props, before_props)

    def test_update_template_diff_properties_immutable_notsupported(self):
        before = {'Foo': 'bar', 'Parrot': 'dead',
                  'Spam': 'ham', 'Viking': 'axe'}
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            before)
        schema = {'Foo': {'Type': 'String'},
                  'Viking': {'Type': 'String', 'Immutable': True},
                  'Spam': {'Type': 'String', 'Immutable': True},
                  'Parrot': {'Type': 'String', 'Immutable': True},
                  }
        after = {'Foo': 'baz', 'Parrot': 'dead',
                 'Spam': 'eggs', 'Viking': 'sword'}
        new_t = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                             after)

        self.patchobject(generic_rsrc.ResourceWithProps,
                         'properties_schema', new=schema)
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl,
                                             self.stack)
        before_props = tmpl.properties(res.properties_schema,
                                       self.stack.context)
        after_props = new_t.properties(res.properties_schema,
                                       self.stack.context)
        ex = self.assertRaises(exception.NotSupported,
                               res.update_template_diff_properties,
                               after_props, before_props)
        self.assertIn("Update to properties Spam, Viking of",
                      six.text_type(ex))

    def test_resource(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_deprecated_prop_data_updated(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()

        res_obj = db_api.resource_get(self.stack.context, res.id)
        self.assertIsNone(res_obj.properties_data)
        self.assertIsNone(res_obj.properties_data_encrypted)
        # Now that we've established these couple of depcrated fields
        # are not populated, let's populate them.
        db_api.resource_update_and_save(self.stack.context, res_obj.id,
                                        {'properties_data': {'Foo': 'lucky'},
                                         'properties_data_encrypted': False,
                                         'rsrc_prop_data': None})
        res._rsrc_prop_data = None
        res._load_data(res_obj)
        # Legacy properties_data slurped into res._stored_properties_data
        self.assertEqual(res._stored_properties_data, {'Foo': 'lucky'})

        res._rsrc_prop_data = None
        res.state_set(res.CREATE, res.IN_PROGRESS, 'test_rpd')

        # Modernity, the data is where it belongs
        rsrc_prop_data_db_obj = db_api.resource_prop_data_get(
            self.stack.context, res._rsrc_prop_data_id)
        self.assertEqual(rsrc_prop_data_db_obj['data'], {'Foo': 'lucky'})
        # legacy locations aren't being used anymore
        self.assertFalse(hasattr(res, 'properties_data'))
        self.assertFalse(hasattr(res, 'properties_data_encrypted'))

    def test_deprecated_encrypted_prop_data_updated(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()

        res_obj = db_api.resource_get(self.stack.context, res.id)
        self.assertIsNone(res_obj.properties_data)
        self.assertIsNone(res_obj.properties_data_encrypted)
        # Now that we've established these couple of depcrated fields
        # are not populated, let's populate them.
        encrypted_data = \
            rpd_object.ResourcePropertiesData.encrypt_properties_data(
                {'Foo': 'lucky'})[1]

        db_api.resource_update_and_save(self.stack.context, res_obj.id,
                                        {'properties_data': encrypted_data,
                                         'properties_data_encrypted': True,
                                         'rsrc_prop_data': None})
        # This is where the decrypting of legacy data happens
        res_obj = resource_objects.Resource._from_db_object(
            resource_objects.Resource(), self.stack.context, res_obj)
        self.assertEqual('lucky',
                         res_obj.properties_data['Foo'])

        res._rsrc_prop_data = None
        res._load_data(res_obj)
        # Legacy properties_data slurped into res._stored_properties_data
        self.assertEqual(res._stored_properties_data, {'Foo': 'lucky'})

        res._rsrc_prop_data = None
        res.state_set(res.CREATE, res.IN_PROGRESS, 'test_store')

        # Modernity, the data is where it belongs
        # The db object data is encrypted
        rsrc_prop_data_db_obj = db_api.resource_prop_data_get(
            self.stack.context, res._rsrc_prop_data_id)
        self.assertNotEqual(rsrc_prop_data_db_obj['data'], {'Foo': 'lucky'})
        # But the objects/ rsrc_prop_data.data is always unencrypted
        rsrc_prop_data_obj = rpd_object.ResourcePropertiesData._from_db_object(
            rpd_object.ResourcePropertiesData(), self.stack.context,
            rsrc_prop_data_db_obj)
        self.assertEqual(rsrc_prop_data_obj.data, {'Foo': 'lucky'})
        # legacy locations aren't being used anymore
        self.assertFalse(hasattr(res, 'properties_data'))
        self.assertFalse(hasattr(res, 'properties_data_encrypted'))

    def test_create_fail_missing_req_prop(self):
        rname = 'test_resource'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'Foo', {})
        res = generic_rsrc.ResourceWithRequiredProps(rname, tmpl, self.stack)

        estr = ('Property error: test_resource.Properties: '
                'Property Foo not assigned')
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_prop_typo(self):
        rname = 'test_resource'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType',
                                            {'Food': 'abc'})
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        estr = ('StackValidationFailed: resources.test_resource: '
                'Property error: test_resource.Properties: '
                'Unknown Property Food')
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertIn(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_fail_metadata_parse_error(self):
        rname = 'test_resource'
        get_att = cfn_funcs.GetAtt(self.stack, 'Fn::GetAtt',
                                   ["ResourceA", "abc"])
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType',
                                            properties={},
                                            metadata={'foo': get_att})
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)

        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual((res.CREATE, res.FAILED), res.state)

    def test_create_resource_after_destroy(self):
        rname = 'test_res_id_none'
        tmpl = rsrc_defn.ResourceDefinition(rname, 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps(rname, tmpl, self.stack)
        res.id = 'test_res_id'
        (res.action, res.status) = (res.INIT, res.DELETE)
        create = scheduler.TaskRunner(res.create)
        self.assertRaises(exception.ResourceFailure, create)
        scheduler.TaskRunner(res.destroy)()
        res.state_reset()
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    @mock.patch.object(properties.Properties, 'validate')
    @mock.patch.object(timeutils, 'retry_backoff_delay')
    def test_create_validate(self, m_re, m_v):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        m_v.side_effect = [True, exception.StackValidationFailed()]
        create_excs = [
            exception.ResourceInError(resource_name='test_resource',
                                      resource_status='ERROR',
                                      resource_type='GenericResourceType',
                                      resource_action='CREATE',
                                      status_reason='just because'),
            exception.ResourceInError(resource_name='test_resource',
                                      resource_status='ERROR',
                                      resource_type='GenericResourceType',
                                      resource_action='CREATE',
                                      status_reason='just because'),
            None
        ]
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_create',
                         side_effect=create_excs)

        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_delete',
                         return_value=None)
        m_re.return_value = 0.01
        scheduler.TaskRunner(res.create)()
        self.assertEqual(2, m_re.call_count)
        self.assertEqual(1, m_v.call_count)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_create_fail_retry(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        exc = exception.ResourceInError(resource_name='test_resource',
                                        resource_status='ERROR',
                                        resource_type='GenericResourceType',
                                        resource_action='CREATE',
                                        status_reason='just because')
        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_create',
                         side_effect=[exc, None])
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_delete')

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.assertEqual(
            2, generic_rsrc.ResourceWithProps.handle_create.call_count)
        self.assertEqual(
            1, generic_rsrc.ResourceWithProps.handle_delete.call_count)
        timeutils.retry_backoff_delay.assert_called_once_with(
            1, jitter_max=2.0)

    def test_create_fail_retry_disabled(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        exc = exception.ResourceInError(resource_name='test_resource',
                                        resource_status='ERROR',
                                        resource_type='GenericResourceType',
                                        resource_action='CREATE',
                                        status_reason='just because')
        self.patchobject(timeutils, 'retry_backoff_delay')
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_create',
                         side_effect=exc)
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_delete')

        estr = ('ResourceInError: resources.test_resource: '
                'Went to status ERROR due to "just because"')
        create = scheduler.TaskRunner(res.create)
        err = self.assertRaises(exception.ResourceFailure, create)
        self.assertEqual(estr, six.text_type(err))
        self.assertEqual((res.CREATE, res.FAILED), res.state)
        self.assertEqual(
            1, generic_rsrc.ResourceWithProps.handle_create.call_count)

    def test_create_deletes_fail_retry(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        create_exc = exception.ResourceInError(
            resource_name='test_resource',
            resource_status='ERROR',
            resource_type='GenericResourceType',
            resource_action='CREATE',
            status_reason='just because')
        delete_exc = exception.ResourceInError(
            resource_name='test_resource',
            resource_status='ERROR',
            resource_type='GenericResourceType',
            resource_action='DELETE',
            status_reason='delete failed')
        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_create',
                         side_effect=[create_exc, None])
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_delete',
                         side_effect=[delete_exc, delete_exc, None])

        scheduler.TaskRunner(res.create)()

        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.assertEqual(3, timeutils.retry_backoff_delay.call_count)
        self.assertEqual(
            2, generic_rsrc.ResourceWithProps.handle_create.call_count)
        self.assertEqual(
            3, generic_rsrc.ResourceWithProps.handle_delete.call_count)

    def test_creates_fail_retry(self):
        create_exc = exception.ResourceInError(
            resource_name='test_resource',
            resource_status='ERROR',
            resource_type='GenericResourceType',
            resource_action='CREATE',
            status_reason='just because')
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)

        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)
        self.patchobject(generic_rsrc.ResourceWithProps,
                         'handle_create', side_effect=[create_exc, create_exc,
                                                       None])
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_delete',
                         return_value=None)

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        self.assertEqual(
            3, generic_rsrc.ResourceWithProps.handle_create.call_count)
        self.assertEqual(
            2, generic_rsrc.ResourceWithProps.handle_delete.call_count)

    def test_create_cancel(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.CancellableResource('test_resource', tmpl,
                                               self.stack)

        cookie = object()
        m_hc = mock.Mock(return_value=cookie)
        res.handle_create = m_hc
        m_ccc = mock.Mock(return_value=False)
        res.check_create_complete = m_ccc
        m_hcc = mock.Mock()
        res.handle_create_cancel = m_hcc

        runner = scheduler.TaskRunner(res.create)
        runner.start()
        runner.step()
        runner.cancel()
        m_hc.assert_called_once_with()
        m_ccc.assert_called_once_with(cookie)
        m_hcc.assert_called_once_with(cookie)

    def test_create_cancel_exception(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.CancellableResource('test_resource', tmpl,
                                               self.stack)
        cookie = object()

        class FakeExc(Exception):
            pass

        m_hc = mock.Mock(return_value=cookie)
        res.handle_create = m_hc
        m_ccc = mock.Mock(return_value=False)
        res.check_create_complete = m_ccc
        m_hcc = mock.Mock(side_effect=FakeExc)
        res.handle_create_cancel = m_hcc

        runner = scheduler.TaskRunner(res.create)
        runner.start()
        runner.step()
        runner.cancel()
        m_hc.assert_called_once_with()
        m_ccc.assert_called_once_with(cookie)
        m_hcc.assert_called_once_with(cookie)

    def test_preview(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        self.assertEqual(res, res.preview())

    def test_update_ok(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        prop_diff = {'Foo': 'xyz'}
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_update')

        scheduler.TaskRunner(res.update, utmpl)()
        self.assertEqual((res.UPDATE, res.COMPLETE), res.state)

        self.assertEqual({'Foo': 'xyz'}, res._stored_properties_data)
        generic_rsrc.ResourceWithProps.handle_update.assert_called_once_with(
            utmpl, mock.ANY, prop_diff)

    def test_update_replace_with_resource_name(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_update',
                         side_effect=resource.UpdateReplace(res.name))
        prop_diff = {'Foo': 'xyz'}

        # should be re-raised so parser.Stack can handle replacement
        updater = scheduler.TaskRunner(res.update, utmpl)
        ex = self.assertRaises(resource.UpdateReplace, updater)
        self.assertEqual('The Resource test_resource requires replacement.',
                         six.text_type(ex))
        generic_rsrc.ResourceWithProps.handle_update.assert_called_once_with(
            utmpl, mock.ANY, prop_diff)

    def test_update_replace_without_resource_name(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_update',
                         side_effect=resource.UpdateReplace)
        prop_diff = {'Foo': 'xyz'}
        # should be re-raised so parser.Stack can handle replacement
        updater = scheduler.TaskRunner(res.update, utmpl)
        ex = self.assertRaises(resource.UpdateReplace, updater)
        self.assertEqual('The Resource Unknown requires replacement.',
                         six.text_type(ex))
        generic_rsrc.ResourceWithProps.handle_update.assert_called_once_with(
            utmpl, mock.ANY, prop_diff)

    def test_need_update_in_init_complete_state_for_resource(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        self.assertEqual((res.INIT, res.COMPLETE), res.state)

        prop = {'Foo': 'abc'}
        self.assertRaises(resource.UpdateReplace,
                          res._needs_update, tmpl, tmpl, prop, prop, res)

    def test_need_update_in_create_failed_state_for_resource(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl,
                                             self.stack)
        res.update_allowed_properties = ('Foo',)
        res.state_set(res.CREATE, res.FAILED)
        prop = {'Foo': 'abc'}
        self.assertRaises(resource.UpdateReplace,
                          res._needs_update, tmpl, tmpl, prop, prop, res)

    def test_convg_need_update_in_delete_complete_state_for_resource(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl,
                                             self.stack)
        res.update_allowed_properties = ('Foo',)
        res.stack.convergence = True
        res.state_set(res.DELETE, res.COMPLETE)
        prop = {'Foo': 'abc'}
        self.assertRaises(resource.UpdateReplace,
                          res._needs_update, tmpl, tmpl, prop, prop, res)

    def test_update_fail_missing_req_prop(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithRequiredProps('test_resource',
                                                     tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {})

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_fail_prop_typo(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Food': 'xyz'})

        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_update_not_implemented(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'GenericResourceType',
                                             {'Foo': 'xyz'})
        prop_diff = {'Foo': 'xyz'}
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_update',
                         side_effect=NotImplementedError)
        updater = scheduler.TaskRunner(res.update, utmpl)
        self.assertRaises(exception.ResourceFailure, updater)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)
        generic_rsrc.ResourceWithProps.handle_update.assert_called_once_with(
            utmpl, mock.ANY, prop_diff)

    def test_update_cancel(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        res = generic_rsrc.CancellableResource('test_resource', tmpl,
                                               self.stack)

        cookie = object()

        m_nu = mock.Mock(return_value=True)
        res._needs_update = m_nu
        m_hu = mock.Mock(return_value=cookie)
        res.handle_update = m_hu
        m_cuc = mock.Mock(return_value=False)
        res.check_update_complete = m_cuc
        m_huc = mock.Mock()
        res.handle_update_cancel = m_huc

        scheduler.TaskRunner(res.create)()
        runner = scheduler.TaskRunner(res.update, tmpl)
        runner.start()
        runner.step()
        runner.cancel()
        m_nu.assert_called_once_with(
            mock.ANY, mock.ANY,
            mock.ANY, mock.ANY,
            None)
        m_hu.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)
        m_cuc.assert_called_once_with(cookie)
        m_huc.assert_called_once_with(cookie)

    def _mock_check_res(self, mock_check=True):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_res', tmpl, self.stack)
        res.state_set(res.CREATE, res.COMPLETE)
        if mock_check:
            res.handle_check = mock.Mock()

        return res

    def test_check_supported(self):
        res = self._mock_check_res()

        scheduler.TaskRunner(res.check)()

        self.assertTrue(res.handle_check.called)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.COMPLETE, res.status)
        self.assertNotIn('not supported', res.status_reason)

    def test_check_not_supported(self):
        res = self._mock_check_res(mock_check=False)
        scheduler.TaskRunner(res.check)()

        self.assertIn('not supported', res.status_reason)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.COMPLETE, res.status)

    def test_check_failed(self):
        res = self._mock_check_res()
        res.handle_check.side_effect = Exception('boom')

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(res.check))
        self.assertTrue(res.handle_check.called)
        self.assertEqual(res.CHECK, res.action)
        self.assertEqual(res.FAILED, res.status)
        self.assertIn('boom', res.status_reason)

    def test_verify_check_conditions(self):
        valid_foos = ['foo1', 'foo2']
        checks = [
            {'attr': 'foo1', 'expected': 'bar1', 'current': 'baz1'},
            {'attr': 'foo2', 'expected': valid_foos, 'current': 'foo2'},
            {'attr': 'foo3', 'expected': 'bar3', 'current': 'baz3'},
            {'attr': 'foo4', 'expected': 'foo4', 'current': 'foo4'},
            {'attr': 'foo5', 'expected': valid_foos, 'current': 'baz5'},
        ]
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'GenericResourceType')
        res = generic_rsrc.ResourceWithProps('test_res', tmpl, self.stack)

        exc = self.assertRaises(exception.Error,
                                res._verify_check_conditions, checks)
        exc_text = six.text_type(exc)
        self.assertNotIn("'foo2':", exc_text)
        self.assertNotIn("'foo4':", exc_text)
        self.assertIn("'foo1': expected 'bar1', got 'baz1'", exc_text)
        self.assertIn("'foo3': expected 'bar3', got 'baz3'", exc_text)
        self.assertIn("'foo5': expected '['foo1', 'foo2']', got 'baz5'",
                      exc_text)

    def test_suspend_resume_ok(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        res.update_allowed_properties = ('Foo',)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.suspend)()
        self.assertEqual((res.SUSPEND, res.COMPLETE), res.state)
        scheduler.TaskRunner(res.resume)()
        self.assertEqual((res.RESUME, res.COMPLETE), res.state)

    def test_suspend_fail_invalid_states(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        invalid_actions = (a for a in res.ACTIONS if a != res.SUSPEND)
        invalid_status = (s for s in res.STATUSES if s != res.COMPLETE)
        invalid_states = [s for s in
                          itertools.product(invalid_actions, invalid_status)]

        for state in invalid_states:
            res.state_set(*state)
            suspend = scheduler.TaskRunner(res.suspend)
            expected = 'State %s invalid for suspend' % six.text_type(state)
            exc = self.assertRaises(exception.ResourceFailure, suspend)
            self.assertIn(expected, six.text_type(exc))

    def test_resume_fail_invalid_states(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        invalid_states = [s for s in
                          itertools.product(res.ACTIONS, res.STATUSES)
                          if s not in ((res.SUSPEND, res.COMPLETE),
                                       (res.RESUME, res.FAILED),
                                       (res.RESUME, res.COMPLETE))]
        for state in invalid_states:
            res.state_set(*state)
            resume = scheduler.TaskRunner(res.resume)
            expected = 'State %s invalid for resume' % six.text_type(state)
            exc = self.assertRaises(exception.ResourceFailure, resume)
            self.assertIn(expected, six.text_type(exc))

    def test_suspend_fail_exception(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        class FakeExc(Exception):
            pass
        self.patchobject(generic_rsrc.ResourceWithProps,
                         'handle_suspend', side_effect=FakeExc)
        suspend = scheduler.TaskRunner(res.suspend)
        self.assertRaises(exception.ResourceFailure, suspend)
        self.assertEqual((res.SUSPEND, res.FAILED), res.state)

    def test_resume_fail_exception(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithProps('test_resource', tmpl, self.stack)
        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

        class FakeExc(Exception):
            pass
        self.patchobject(generic_rsrc.ResourceWithProps, 'handle_resume',
                         side_effect=FakeExc)

        res.state_set(res.SUSPEND, res.COMPLETE)

        resume = scheduler.TaskRunner(res.resume)
        self.assertRaises(exception.ResourceFailure, resume)
        self.assertEqual((res.RESUME, res.FAILED), res.state)
        self.assertEqual(
            1, generic_rsrc.ResourceWithProps.handle_resume.call_count)

    def test_resource_class_to_cfn_template(self):

        class TestResource(resource.Resource):
            list_schema = {'wont_show_up': {'Type': 'Number'}}
            map_schema = {'will_show_up': {'Type': 'Integer'}}

            properties_schema = {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean'},
                'implemented': {'Type': 'String',
                                'Implemented': True,
                                'AllowedPattern': '.*',
                                'MaxLength': 7,
                                'MinLength': 2,
                                'Required': True},
                'not_implemented': {'Type': 'String',
                                    'Implemented': False},
                'number': {'Type': 'Number',
                           'MaxValue': 77,
                           'MinValue': 41,
                           'Default': 42},
                'list': {'Type': 'List', 'Schema': {'Type': 'Map',
                         'Schema': list_schema}},
                'map': {'Type': 'Map', 'Schema': map_schema},
                'hidden': properties.Schema(
                    properties.Schema.STRING,
                    support_status=support.SupportStatus(
                        status=support.HIDDEN))
            }

            attributes_schema = {
                'output1': attributes.Schema('output1_desc'),
                'output2': attributes.Schema('output2_desc')
            }

        expected_template = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Description': 'Initial template of TestResource',
            'Parameters': {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean',
                         'AllowedValues': ['True', 'true', 'False', 'false']},
                'implemented': {
                    'Type': 'String',
                    'AllowedPattern': '.*',
                    'MaxLength': 7,
                    'MinLength': 2
                },
                'number': {'Type': 'Number',
                           'MaxValue': 77,
                           'MinValue': 41,
                           'Default': 42},
                'list': {'Type': 'CommaDelimitedList'},
                'map': {'Type': 'Json'}
            },
            'Resources': {
                'TestResource': {
                    'Type': 'Test::Resource::resource',
                    'Properties': {
                        'name': {'Ref': 'name'},
                        'bool': {'Ref': 'bool'},
                        'implemented': {'Ref': 'implemented'},
                        'number': {'Ref': 'number'},
                        'list': {'Fn::Split': [",", {'Ref': 'list'}]},
                        'map': {'Ref': 'map'}
                    }
                }
            },
            'Outputs': {
                'output1': {
                    'Description': 'output1_desc',
                    'Value': {"Fn::GetAtt": ["TestResource", "output1"]}
                },
                'output2': {
                    'Description': 'output2_desc',
                    'Value': {"Fn::GetAtt": ["TestResource", "output2"]}
                },
                'show': {
                    'Description': u'Detailed information about resource.',
                    'Value': {"Fn::GetAtt": ["TestResource", "show"]}
                },
                'OS::stack_id': {
                    'Value': {"Ref": "TestResource"}
                }
            }
        }
        self.assertEqual(expected_template,
                         TestResource.resource_to_template(
                             'Test::Resource::resource'))

    def test_resource_class_to_hot_template(self):

        class TestResource(resource.Resource):
            list_schema = {'wont_show_up': {'Type': 'Number'}}
            map_schema = {'will_show_up': {'Type': 'Integer'}}

            properties_schema = {
                'name': {'Type': 'String'},
                'bool': {'Type': 'Boolean'},
                'implemented': {'Type': 'String',
                                'Implemented': True,
                                'AllowedPattern': '.*',
                                'MaxLength': 7,
                                'MinLength': 2,
                                'Required': True},
                'not_implemented': {'Type': 'String',
                                    'Implemented': False},
                'number': {'Type': 'Number',
                           'MaxValue': 77,
                           'MinValue': 41,
                           'Default': 42},
                'list': {'Type': 'List', 'Schema': {'Type': 'Map',
                         'Schema': list_schema}},
                'map': {'Type': 'Map', 'Schema': map_schema},
                'hidden': properties.Schema(
                    properties.Schema.STRING,
                    support_status=support.SupportStatus(
                        status=support.HIDDEN))
            }

            attributes_schema = {
                'output1': attributes.Schema('output1_desc'),
                'output2': attributes.Schema('output2_desc')
            }

        expected_template = {
            'heat_template_version': '2016-10-14',
            'description': 'Initial template of TestResource',
            'parameters': {
                'name': {'type': 'string'},
                'bool': {'type': 'boolean'},
                'implemented': {
                    'type': 'string',
                    'constraints': [{'length': {'max': 7, 'min': 2}},
                                    {'allowed_pattern': '.*'}]
                },
                'number': {'type': 'number',
                           'constraints': [{'range': {'max': 77, 'min': 41}}],
                           'default': 42},
                'list': {'type': 'comma_delimited_list'},
                'map': {'type': 'json'}
            },
            'resources': {
                'TestResource': {
                    'type': 'Test::Resource::resource',
                    'properties': {
                        'name': {'get_param': 'name'},
                        'bool': {'get_param': 'bool'},
                        'implemented': {'get_param': 'implemented'},
                        'number': {'get_param': 'number'},
                        'list': {'get_param': 'list'},
                        'map': {'get_param': 'map'}
                    }
                }
            },
            'outputs': {
                'output1': {
                    'description': 'output1_desc',
                    'value': {"get_attr": ["TestResource", "output1"]}
                },
                'output2': {
                    'description': 'output2_desc',
                    'value': {"get_attr": ["TestResource", "output2"]}
                },
                'show': {
                    'description': u'Detailed information about resource.',
                    'value': {"get_attr": ["TestResource", "show"]}
                },
                'OS::stack_id': {
                    'value': {"get_resource": "TestResource"}
                }
            }
        }
        self.assertEqual(expected_template,
                         TestResource.resource_to_template(
                             'Test::Resource::resource',
                             template_type='hot'))

    def test_is_not_using_neutron_exception(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        mock_create = self.patch(
            'heat.engine.clients.os.neutron.NeutronClientPlugin._create')
        mock_create.side_effect = Exception()
        self.assertFalse(res.is_using_neutron())

    def test_is_using_neutron_endpoint_lookup(self):
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        res = resource.Resource('aresource', snippet, self.stack)
        client = mock.Mock()
        self.patchobject(client.httpclient, 'get_endpoint',
                         return_value=None)
        self.patch(
            'heat.engine.clients.os.neutron.NeutronClientPlugin._create',
            return_value=client)
        self.assertFalse(res.is_using_neutron())
        self.patchobject(client.httpclient, 'get_endpoint',
                         return_value=mock.Mock())
        self.assertTrue(res.is_using_neutron())

    def _test_skip_validation_if_custom_constraint(self, tmpl):
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        stack.store()
        path = ('heat.engine.clients.os.neutron.neutron_constraints.'
                'NetworkConstraint.validate_with_client')
        with mock.patch(path) as mock_validate:
            mock_validate.side_effect = neutron_exp.NeutronClientException
            rsrc2 = stack['bar']
            self.assertIsNone(rsrc2.validate())

    def test_ref_skip_validation_if_custom_constraint(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'OS::Test::GenericResource'},
                'bar': {
                    'Type': 'OS::Test::ResourceWithCustomConstraint',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        }, env=self.env)
        self._test_skip_validation_if_custom_constraint(tmpl)

    def test_hot_ref_skip_validation_if_custom_constraint(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithCustomConstraint',
                    'properties': {
                        'Foo': {'get_resource': 'foo'},
                    }
                }
            }
        }, env=self.env)
        self._test_skip_validation_if_custom_constraint(tmpl)

    def test_no_resource_properties_required_default(self):
        """Test that there is no required properties with default value

        Check all resources if they have properties with required flag and
        default value because it is ambiguous.
        """
        env = environment.Environment({}, user_env=False)
        resources._load_global_environment(env)

        # change loading mechanism for resources that require template files
        mod_dir = os.path.dirname(sys.modules[__name__].__file__)
        project_dir = os.path.abspath(os.path.join(mod_dir, '../../'))
        template_path = os.path.join(project_dir, 'etc', 'heat', 'templates')

        tri_db_instance = env.get_resource_info(
            'AWS::RDS::DBInstance',
            registry_type=environment.TemplateResourceInfo)
        tri_db_instance.template_name = tri_db_instance.template_name.replace(
            '/etc/heat/templates', template_path)
        tri_alarm = env.get_resource_info(
            'AWS::CloudWatch::Alarm',
            registry_type=environment.TemplateResourceInfo)
        tri_alarm.template_name = tri_alarm.template_name.replace(
            '/etc/heat/templates', template_path)

        def _validate_property_schema(prop_name, prop, res_name):
            if isinstance(prop, properties.Schema) and prop.implemented:
                ambiguous = (prop.default is not None) and prop.required
                self.assertFalse(ambiguous,
                                 "The definition of the property '{0}' "
                                 "in resource '{1}' is ambiguous: it "
                                 "has default value and required flag. "
                                 "Please delete one of these options."
                                 .format(prop_name, res_name))

            if prop.schema is not None:
                if isinstance(prop.schema, constraints.AnyIndexDict):
                    _validate_property_schema(
                        prop_name,
                        prop.schema.value,
                        res_name)
                else:
                    for nest_prop_name, nest_prop in six.iteritems(
                            prop.schema):
                        _validate_property_schema(nest_prop_name,
                                                  nest_prop,
                                                  res_name)

        resource_types = env.get_types()
        for res_type in resource_types:
            res_class = env.get_class(res_type)
            if hasattr(res_class, "properties_schema"):
                for property_schema_name, property_schema in six.iteritems(
                        res_class.properties_schema):
                    _validate_property_schema(
                        property_schema_name, property_schema,
                        res_class.__name__)

    def test_getatt_invalid_type(self):

        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'ResourceWithAttributeType'
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        res = stack['res']
        self.assertEqual('valid_sting', res.FnGetAtt('attr1'))

        res.FnGetAtt('attr2')
        self.assertIn("Attribute attr2 is not of type Map", self.LOG.output)

    def test_getatt_with_path(self):

        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'ResourceWithComplexAttributesType'
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        res = stack['res']
        self.assertEqual('abc', res.FnGetAtt('nested_dict', 'string'))

    def test_getatt_with_cache_data(self):

        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'ResourceWithAttributeType'
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl,
                             cache_data={
                                 'res': node_data.NodeData.from_dict({
                                     'attrs': {'Foo': 'Res',
                                               'foo': 'res'},
                                     'uuid': mock.ANY,
                                     'id': mock.ANY,
                                     'action': 'CREATE',
                                     'status': 'COMPLETE'})})

        res = stack.defn['res']
        self.assertEqual('Res', res.FnGetAtt('Foo'))

    def test_getatt_with_path_cache_data(self):

        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'ResourceWithComplexAttributesType'
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl,
                             cache_data={
                                 'res': node_data.NodeData.from_dict({
                                     'attrs': {('nested', 'string'): 'abc'},
                                     'uuid': mock.ANY,
                                     'id': mock.ANY,
                                     'action': 'CREATE',
                                     'status': 'COMPLETE'})})

        res = stack.defn['res']
        self.assertEqual('abc', res.FnGetAtt('nested', 'string'))

    def test_properties_data_stored_encrypted_decrypted_on_load(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', True)

        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        stored_properties_data = {'prop1': 'string',
                                  'prop2': {'a': 'dict'},
                                  'prop3': 1,
                                  'prop4': ['a', 'list'],
                                  'prop5': True}

        # The db data should be encrypted when _store() is called
        res = generic_rsrc.GenericResource('test_res_enc', tmpl, self.stack)
        res._stored_properties_data = stored_properties_data
        res._rsrc_prop_data = None
        res.store()
        db_res = db_api.resource_get(res.context, res.id)
        self.assertNotEqual('string',
                            db_res.rsrc_prop_data.data['prop1'])

        # The db data should be encrypted when state_set is called
        res = generic_rsrc.GenericResource('test_res_enc', tmpl, self.stack)
        res._stored_properties_data = stored_properties_data
        res.state_set(res.CREATE, res.IN_PROGRESS, 'test_store')
        db_res = db_api.resource_get(res.context, res.id)
        self.assertNotEqual('string',
                            db_res.rsrc_prop_data.data['prop1'])

        # The properties data should be decrypted when the object is
        # loaded using get_obj
        res_obj = resource_objects.Resource.get_obj(res.context, res.id)
        self.assertEqual('string', res_obj.properties_data['prop1'])

        # _stored_properties_data should be decrypted when the object is
        # loaded using get_all_by_stack
        res_objs = resource_objects.Resource.get_all_by_stack(res.context,
                                                              self.stack.id)
        res_obj = res_objs['test_res_enc']
        self.assertEqual('string', res_obj.properties_data['prop1'])

        # The properties data should be decrypted when the object is
        # refreshed
        res_obj = resource_objects.Resource.get_obj(res.context, res.id)
        res_obj.refresh()
        self.assertEqual('string', res_obj.properties_data['prop1'])

    def test_properties_data_no_encryption(self):
        cfg.CONF.set_override('encrypt_parameters_and_properties', False)

        tmpl = rsrc_defn.ResourceDefinition('test_resource', 'Foo')
        stored_properties_data = {'prop1': 'string',
                                  'prop2': {'a': 'dict'},
                                  'prop3': 1,
                                  'prop4': ['a', 'list'],
                                  'prop5': True}

        # The db data should not be encrypted when state_set()
        # is called
        res = generic_rsrc.GenericResource('test_res_enc', tmpl, self.stack)
        res._stored_properties_data = stored_properties_data
        res._rsrc_prop_data = None
        res.state_set(res.CREATE, res.IN_PROGRESS, 'test_store')
        db_res = db_api.resource_get(res.context, res.id)
        self.assertEqual('string', db_res.rsrc_prop_data.data['prop1'])

        # The db data should not be encrypted when _store() is called
        res = generic_rsrc.GenericResource('test_res_enc', tmpl, self.stack)
        res._stored_properties_data = stored_properties_data
        db_res = db_api.resource_get(res.context, res.id)
        self.assertEqual('string', db_res.rsrc_prop_data.data['prop1'])

        # The properties data should not be modified when the object
        # is loaded using get_obj
        prev_rsrc_prop_data_id = db_res.rsrc_prop_data.id
        res_obj = resource_objects.Resource.get_obj(res.context, res.id)
        self.assertEqual('string', res_obj.properties_data['prop1'])
        self.assertEqual(prev_rsrc_prop_data_id, res_obj.rsrc_prop_data_id)

        # The properties data should not be modified when the object
        # is loaded using get_all_by_stack
        res_objs = resource_objects.Resource.get_all_by_stack(res.context,
                                                              self.stack.id)
        res_obj = res_objs['test_res_enc']
        self.assertEqual('string', res_obj.properties_data['prop1'])
        self.assertEqual(prev_rsrc_prop_data_id, res_obj.rsrc_prop_data_id)

    def _assert_resource_lock(self, res_id, engine_id, atomic_key):
        rs = resource_objects.Resource.get_obj(self.stack.context, res_id)
        self.assertEqual(engine_id, rs.engine_id)
        self.assertEqual(atomic_key, rs.atomic_key)

    def test_create_convergence(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.action = res.CREATE
        res.store()
        self._assert_resource_lock(res.id, None, None)
        pcb = mock.Mock()

        with mock.patch.object(resource.Resource, 'create') as mock_create:
            res.create_convergence(self.stack.t.id, {1, 3}, 'engine-007',
                                   -1, pcb)
            self.assertTrue(mock_create.called)

        self.assertItemsEqual([1, 3], res.requires)
        self._assert_resource_lock(res.id, None, None)

    def test_create_convergence_throws_timeout(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.action = res.CREATE
        res.store()

        pcb = mock.Mock()
        self.assertRaises(scheduler.Timeout, res.create_convergence,
                          self.stack.t.id, {1, 3}, 'engine-007', -1, pcb)

    def test_create_convergence_sets_requires_for_failure(self):
        """Ensure that requires are computed correctly.

        Ensure that requires are computed correctly even if resource
        create fails.
        """
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.store()
        dummy_ex = exception.ResourceNotAvailable(resource_name=res.name)
        res.create = mock.Mock(side_effect=dummy_ex)
        self._assert_resource_lock(res.id, None, None)
        self.assertRaises(exception.ResourceNotAvailable,
                          res.create_convergence, self.stack.t.id, {5, 3},
                          'engine-007', self.dummy_timeout, self.dummy_event)
        self.assertItemsEqual([5, 3], res.requires)
        # The locking happens in create which we mocked out
        self._assert_resource_lock(res.id, None, None)

    @mock.patch.object(resource.Resource, 'adopt')
    def test_adopt_convergence_ok(self, mock_adopt):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.action = res.ADOPT
        res.store()
        self.stack.adopt_stack_data = {'resources': {'test_res': {
            'resource_id': 'fluffy'}}}
        self._assert_resource_lock(res.id, None, None)
        tr = scheduler.TaskRunner(res.create_convergence, self.stack.t.id,
                                  {5, 3}, 'engine-007', self.dummy_timeout,
                                  self.dummy_event)
        tr()
        mock_adopt.assert_called_once_with(
            resource_data={'resource_id': 'fluffy'})
        self.assertItemsEqual([5, 3], res.requires)
        self._assert_resource_lock(res.id, None, None)

    def test_adopt_convergence_bad_data(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.action = res.ADOPT
        res.store()
        self.stack.adopt_stack_data = {'resources': {}}
        self._assert_resource_lock(res.id, None, None)
        tr = scheduler.TaskRunner(res.create_convergence, self.stack.t.id,
                                  {5, 3}, 'engine-007', self.dummy_timeout,
                                  self.dummy_event)
        exc = self.assertRaises(exception.ResourceFailure, tr)
        self.assertIn('Resource ID was not provided', six.text_type(exc))

    @mock.patch.object(resource.Resource, 'update_template_diff_properties')
    @mock.patch.object(resource.Resource, '_needs_update')
    def test_update_convergence(self, mock_nu, mock_utd):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType'}
            }}, env=self.env)
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, convergence=True)
        stack.thread_group_mgr = tools.DummyThreadGroupManager()
        stack.converge_stack(stack.t, action=stack.CREATE)
        res = stack.resources['test_res']
        res.requires = {2}
        res.action = res.CREATE
        res.store()
        self._assert_resource_lock(res.id, None, None)

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_temp.store(stack.context)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)

        tr = scheduler.TaskRunner(res.update_convergence, new_temp.id,
                                  {4, 3}, 'engine-007', 120, new_stack)
        tr()

        self.assertItemsEqual([3, 4], res.requires)
        self.assertEqual(res.action, resource.Resource.UPDATE)
        self.assertEqual(res.status, resource.Resource.COMPLETE)
        self._assert_resource_lock(res.id, None, 2)

    def test_update_convergence_throws_timeout(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType'}
            }}, env=self.env)
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, convergence=True)
        stack.thread_group_mgr = tools.DummyThreadGroupManager()
        stack.converge_stack(stack.t, action=stack.CREATE)
        res = stack.resources['test_res']
        res.store()

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_temp.store(stack.context)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)

        tr = scheduler.TaskRunner(res.update_convergence, new_temp.id,
                                  set(), 'engine-007', -1, new_stack,
                                  self.dummy_event)
        self.assertRaises(scheduler.Timeout, tr)

    def test_update_convergence_with_substitute_class(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.store()

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_temp.store(self.stack.context)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)

        self.assertRaises(resource.UpdateReplace, res.update_convergence,
                          new_temp.id, set(), 'engine-007',
                          -1, new_stack)

    def test_update_convergence_checks_resource_class(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res',
                                            'GenericResourceType')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.store()

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        ctx = utils.dummy_context()
        new_temp.store(ctx)
        new_stack = parser.Stack(ctx, 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)

        tr = scheduler.TaskRunner(res.update_convergence, new_temp.id,
                                  set(), 'engine-007', -1, new_stack,
                                  self.dummy_event)
        self.assertRaises(resource.UpdateReplace, tr)

    @mock.patch.object(resource.Resource, '_needs_update')
    @mock.patch.object(resource.Resource, '_check_for_convergence_replace')
    def test_update_in_progress_convergence(self, mock_cfcr, mock_nu):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.requires = {1, 2}
        res.store()
        rs = resource_objects.Resource.get_obj(self.stack.context, res.id)
        rs.update_and_save({'engine_id': 'not-this'})
        self._assert_resource_lock(res.id, 'not-this', None)

        res.stack.convergence = True

        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType'}
            }}, env=self.env)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 tmpl, stack_id=self.stack.id,
                                 convergence=True)
        tr = scheduler.TaskRunner(res.update_convergence, 'template_key',
                                  {4, 3}, 'engine-007', self.dummy_timeout,
                                  new_stack)
        ex = self.assertRaises(exception.UpdateInProgress, tr)
        msg = ("The resource %s is already being updated." %
               res.name)
        self.assertEqual(msg, six.text_type(ex))
        # ensure requirements are not updated for failed resource
        rs = resource_objects.Resource.get_obj(self.stack.context, res.id)
        self.assertEqual([2, 1], rs.requires)

    @mock.patch.object(resource.Resource, 'update_template_diff_properties')
    @mock.patch.object(resource.Resource, '_needs_update')
    def test_update_resource_convergence_failed(self,
                                                mock_needs_update,
                                                mock_update_template_diff):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType'}
            }}, env=self.env)
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, convergence=True)
        stack.thread_group_mgr = tools.DummyThreadGroupManager()
        stack.converge_stack(stack.t, action=stack.CREATE)
        res = stack.resources['test_res']
        res.requires = {2}
        res.store()
        self._assert_resource_lock(res.id, None, None)

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_temp.store(stack.context)

        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)

        res.stack.convergence = True
        res._calling_engine_id = 'engine-9'

        tr = scheduler.TaskRunner(res.update_convergence, new_temp.id,
                                  {4, 3}, 'engine-007', 120, new_stack,
                                  self.dummy_event)
        self.assertRaises(exception.ResourceFailure, tr)

        self.assertEqual(new_temp.id, res.current_template_id)
        # check if requires was updated
        self.assertItemsEqual([2, 3, 4], res.requires)
        self.assertEqual(res.action, resource.Resource.UPDATE)
        self.assertEqual(res.status, resource.Resource.FAILED)
        self._assert_resource_lock(res.id, None, 2)

    def test_update_resource_convergence_update_replace(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType'}
            }}, env=self.env)
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl, convergence=True)
        stack.thread_group_mgr = tools.DummyThreadGroupManager()
        stack.converge_stack(stack.t, action=stack.CREATE)
        res = stack.resources['test_res']
        res.requires = {2}
        res.store()
        self._assert_resource_lock(res.id, None, None)

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_temp.store(stack.context)

        res.stack.convergence = True

        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id)
        tr = scheduler.TaskRunner(res.update_convergence, new_temp.id,
                                  {4, 3}, 'engine-007', 120, new_stack,
                                  self.dummy_event)
        self.assertRaises(resource.UpdateReplace, tr)

        # ensure that current_template_id was not updated
        self.assertEqual(stack.t.id, res.current_template_id)
        # ensure that requires was not updated
        self.assertItemsEqual([2], res.requires)
        self._assert_resource_lock(res.id, None, 2)

    def test_convergence_update_replace_rollback(self):
        self.stack.convergence = True
        rsrc_def = rsrc_defn.ResourceDefinition('test_res',
                                                'ResourceWithPropsType')
        res = generic_rsrc.ResourceWithProps('test_res', rsrc_def, self.stack)
        res.replaced_by = 'dummy'
        res.store()

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)
        self.stack.state_set(self.stack.ROLLBACK, self.stack.IN_PROGRESS,
                             'Simulate rollback')
        res.restore_prev_rsrc = mock.Mock()
        tr = scheduler.TaskRunner(res.update_convergence, 'new_tmpl_id', set(),
                                  'engine-007', self.dummy_timeout,
                                  new_stack, self.dummy_event)
        self.assertRaises(resource.UpdateReplace, tr)
        self.assertTrue(res.restore_prev_rsrc.called)

    def test_convergence_update_replace_rollback_restore_prev_rsrc_error(self):
        self.stack.convergence = True
        rsrc_def = rsrc_defn.ResourceDefinition('test_res',
                                                'ResourceWithPropsType')
        res = generic_rsrc.ResourceWithProps('test_res', rsrc_def, self.stack)
        res.replaced_by = 'dummy'
        res.store()

        new_temp = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'test_res': {'Type': 'ResourceWithPropsType',
                             'Properties': {'Foo': 'abc'}}
            }}, env=self.env)
        new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                 new_temp, stack_id=self.stack.id,
                                 convergence=True)
        self.stack.state_set(self.stack.ROLLBACK, self.stack.IN_PROGRESS,
                             'Simulate rollback')
        res.restore_prev_rsrc = mock.Mock(side_effect=Exception)
        tr = scheduler.TaskRunner(res.update_convergence, 'new_tmpl_id', set(),
                                  'engine-007', self.dummy_timeout, new_stack,
                                  self.dummy_event)
        self.assertRaises(exception.ResourceFailure, tr)
        self.assertTrue(res.restore_prev_rsrc.called)
        self.assertEqual((res.UPDATE, res.FAILED), res.state)

    def test_delete_convergence_ok(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.current_template_id = 1
        res.status = res.COMPLETE
        res.action = res.CREATE
        res.store()
        res.handle_delete = mock.Mock(return_value=None)
        res._update_replacement_data = mock.Mock()
        self._assert_resource_lock(res.id, None, None)
        pcb = mock.Mock()
        with mock.patch.object(resource.Resource, 'delete') as mock_delete:
            tr = scheduler.TaskRunner(res.delete_convergence, 2,
                                      'engine-007', 20, pcb)
            tr()
            self.assertTrue(mock_delete.called)
        self.assertTrue(res._update_replacement_data.called)
        self._assert_resource_lock(res.id, None, None)

    def test_delete_convergence_does_not_delete_same_template_resource(self):
        self.stack.convergence = True
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.current_template_id = 'same-template'
        res.store()
        res.delete = mock.Mock()
        tr = scheduler.TaskRunner(res.delete_convergence, 'same-template',
                                  'engine-007', self.dummy_timeout,
                                  self.dummy_event)
        tr()
        self.assertFalse(res.delete.called)

    def test_delete_convergence_fail(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.current_template_id = 1
        res.status = res.COMPLETE
        res.action = res.CREATE
        res.store()
        res_id = res.id
        res.handle_delete = mock.Mock(side_effect=ValueError('test'))
        self._assert_resource_lock(res.id, None, None)
        res.stack.convergence = True
        tr = scheduler.TaskRunner(res.delete_convergence, 2, 'engine-007',
                                  self.dummy_timeout, self.dummy_event)
        self.assertRaises(exception.ResourceFailure, tr)
        self.assertTrue(res.handle_delete.called)

        # confirm that the DB object still exists, and it's lock is released.
        rs = resource_objects.Resource.get_obj(self.stack.context, res_id)
        self.assertEqual(rs.id, res_id)
        self.assertEqual(res.FAILED, rs.status)
        self._assert_resource_lock(res.id, None, 2)

    def test_delete_in_progress_convergence(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.current_template_id = 1
        res.status = res.COMPLETE
        res.action = res.CREATE
        res.store()
        self.stack.convergence = True
        res._calling_engine_id = 'engine-9'
        rs = resource_objects.Resource.get_obj(self.stack.context, res.id)
        rs.update_and_save({'engine_id': 'not-this'})
        self._assert_resource_lock(res.id, 'not-this', None)

        tr = scheduler.TaskRunner(res.delete)
        ex = self.assertRaises(exception.UpdateInProgress, tr)
        msg = ("The resource %s is already being updated." %
               res.name)
        self.assertEqual(msg, six.text_type(ex))

    @mock.patch.object(resource_objects.Resource, 'get_obj')
    def test_update_replacement_data(self, mock_get_obj):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        r = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        r.replaced_by = 4
        r.store()
        db_res = mock.MagicMock()
        db_res.current_template_id = 'same_tmpl'
        mock_get_obj.return_value = db_res
        r._update_replacement_data('same_tmpl')
        self.assertTrue(mock_get_obj.called)
        self.assertTrue(db_res.select_and_update.called)
        args, kwargs = db_res.select_and_update.call_args
        self.assertEqual({'replaces': None}, args[0])
        self.assertIsNone(kwargs['expected_engine_id'])

    @mock.patch.object(resource_objects.Resource, 'get_obj')
    def test_update_replacement_data_ignores_rsrc_from_different_tmpl(
            self, mock_get_obj):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        r = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        r.replaced_by = 4
        db_res = mock.MagicMock()
        db_res.current_template_id = 'tmpl'
        mock_get_obj.return_value = db_res
        # db_res as tmpl id as 2, and 1 is passed
        r._update_replacement_data('diff_tmpl')
        self.assertTrue(mock_get_obj.called)
        self.assertFalse(db_res.select_and_update.called)

    def create_resource_for_attributes_tests(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'GenericResourceType'
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        return stack

    def test_resolve_attributes_stuff_base_attribute(self):
        # check path with resolving base attributes (via 'show' attribute)
        stack = self.create_resource_for_attributes_tests()
        res = stack['res']

        class MyException(Exception):
            pass

        with mock.patch.object(res, '_show_resource') as show_attr:
            # return None, if resource_id is None
            self.assertIsNone(res.FnGetAtt('show'))

            # set resource_id and recheck with re-written _show_resource
            res.resource_id = mock.Mock()
            res.default_client_name = 'foo'

            show_attr.return_value = 'my attr'
            self.assertEqual('my attr', res.FnGetAtt('show'))
            self.assertEqual(1, show_attr.call_count)

            # clean resolved_values
            res.attributes.reset_resolved_values()
            # generate error during calling _show_resource
            show_attr.side_effect = [MyException]
            self.assertRaises(MyException, res.FnGetAtt, 'show')
            self.assertEqual(2, show_attr.call_count)

    def test_resolve_attributes_stuff_custom_attribute(self):
        # check path with resolve_attribute
        stack = self.create_resource_for_attributes_tests()
        res = stack['res']
        res.default_client_name = 'foo'

        class MyException(Exception):
            pass

        with mock.patch.object(res, '_resolve_attribute') as res_attr:
            res_attr.side_effect = ['Works', MyException]
            self.assertEqual('Works', res.FnGetAtt('Foo'))
            res_attr.assert_called_once_with('Foo')

            # clean resolved_values
            res.attributes.reset_resolved_values()
            self.assertRaises(MyException, res.FnGetAtt, 'Foo')

    def test_resolve_attributes_no_default_client_name(self):
        class MyException(Exception):
            pass

        stack = self.create_resource_for_attributes_tests()
        res = stack['res']
        res.default_client_name = None

        with mock.patch.object(res, '_resolve_attribute') as res_attr:
            res_attr.side_effect = [MyException]
            # Make sure this isn't AssertionError
            self.assertRaises(MyException, res.FnGetAtt, 'Foo')

    def test_show_resource(self):
        # check default function _show_resource
        stack = self.create_resource_for_attributes_tests()
        res = stack['res']

        # check default value of entity
        self.assertIsNone(res.entity)
        self.assertIsNone(res.FnGetAtt('show'))

        # set entity and recheck
        res.resource_id = 'test_resource_id'
        res.entity = 'test'
        res.default_client_name = 'whatever'

        # mock getting resource info
        res.client = mock.Mock()
        test_obj = mock.Mock()
        test_resource = mock.Mock()
        test_resource.to_dict.return_value = {'test': 'info'}
        test_obj.get.return_value = test_resource
        res.client().test = test_obj

        self.assertEqual({'test': 'info'}, res._show_resource())

        # mock getting resource info as dict
        test_obj.get.return_value = {'test': 'info'}
        res.client().test = test_obj

        self.assertEqual({'test': 'info'}, res._show_resource())

        # check the case where resource entity isn't defined
        res.entity = None
        self.assertIsNone(res._show_resource())

        # check handling AttributeError exception
        res.entity = 'test'
        test_obj.get.side_effect = AttributeError
        self.assertIsNone(res._show_resource())

    def test_delete_convergence_deletes_resource_in_init_state(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        # action is INIT by default
        res.store()
        with mock.patch.object(resource_objects.Resource,
                               'delete') as resource_del:
            tr = scheduler.TaskRunner(res.delete_convergence, 1,
                                      'engine-007', 1, self.dummy_event)
            tr()
            resource_del.assert_called_once_with(res.context, res.id)

    def test_delete_convergence_throws_timeout(self):
        tmpl = rsrc_defn.ResourceDefinition('test_res', 'Foo')
        res = generic_rsrc.GenericResource('test_res', tmpl, self.stack)
        res.action = res.CREATE
        res.store()
        timeout = -1  # to emulate timeout
        tr = scheduler.TaskRunner(res.delete_convergence, 1, 'engine-007',
                                  timeout, self.dummy_event)
        self.assertRaises(scheduler.Timeout, tr)

    @mock.patch.object(parser.Stack, 'load')
    @mock.patch.object(resource.Resource, '_load_data')
    @mock.patch.object(template.Template, 'load')
    def test_load_loads_stack_with_cached_data(self, mock_tmpl_load,
                                               mock_load_data,
                                               mock_stack_load):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'res': {
                    'type': 'GenericResourceType'
                }
            }
        }, env=self.env)
        stack = parser.Stack(utils.dummy_context(), 'test_stack',
                             tmpl)
        stack.store()
        mock_tmpl_load.return_value = tmpl
        res = stack['res']
        res.current_template_id = stack.t.id
        res.store()
        data = {'bar': {'atrr1': 'baz', 'attr2': 'baz2'}}
        mock_stack_load.return_value = stack
        resource.Resource.load(stack.context, res.id,
                               stack.current_traversal, True, data)
        self.assertTrue(mock_stack_load.called)
        mock_stack_load.assert_called_with(stack.context,
                                           stack_id=stack.id,
                                           cache_data=data)
        self.assertTrue(mock_load_data.called)


class ResourceDeleteRetryTest(common.HeatTestCase):
    def setUp(self):
        super(ResourceDeleteRetryTest, self).setUp()

        self.env = environment.Environment()
        self.env.load({u'resource_registry':
                      {u'OS::Test::GenericResource': u'GenericResourceType'}})

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template,
                                                    env=self.env),
                                  stack_id=str(uuid.uuid4()))
        self.num_retries = 2
        cfg.CONF.set_override('action_retry_limit', self.num_retries)

    def test_delete_retry_conflict(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'GenericResourceType',
                                            {'Foo': 'xyz123'})
        res = generic_rsrc.ResourceWithProps(
            'test_resource', tmpl, self.stack)
        res.state_set(res.CREATE, res.COMPLETE, 'wobble')
        res.default_client_name = 'neutron'

        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)
        # could be any exception that is_conflict(), using the neutron
        # client one
        h_d_side_effects = [
            neutron_exp.Conflict(message='foo', request_ids=[1])] * (
                self.num_retries + 1)
        self.patchobject(
            generic_rsrc.GenericResource, 'handle_delete',
            side_effect=h_d_side_effects)

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.delete))
        exc_text = six.text_type(exc)
        self.assertIn('Conflict', exc_text)
        self.assertEqual(
            self.num_retries + 1,
            generic_rsrc.GenericResource.handle_delete.call_count)

    def test_delete_retry_phys_resource_exists(self):
        tmpl = rsrc_defn.ResourceDefinition(
            'test_resource', 'Foo', {'Foo': 'abc'})
        res = generic_rsrc.ResourceWithPropsRefPropOnDelete(
            'test_resource', tmpl, self.stack)
        res.state_set(res.CREATE, res.COMPLETE, 'wobble')

        cfg.CONF.set_override('action_retry_limit', self.num_retries)

        cdc_side_effects = [exception.PhysicalResourceExists(name="foo")
                            ] * self.num_retries
        cdc_side_effects.append(True)
        self.patchobject(timeutils, 'retry_backoff_delay', return_value=0.01)
        self.patchobject(generic_rsrc.GenericResource, 'handle_delete')
        self.patchobject(generic_rsrc.ResourceWithPropsRefPropOnDelete,
                         'check_delete_complete',
                         side_effect=cdc_side_effects)

        scheduler.TaskRunner(res.delete)()
        self.assertEqual(
            self.num_retries + 1,
            generic_rsrc.GenericResource.handle_delete.call_count)


class ResourceAdoptTest(common.HeatTestCase):

    def test_adopt_resource_success(self):
        adopt_data = '{}'
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        res_data = {
            "status": "COMPLETE",
            "name": "foo",
            "resource_data": {},
            "metadata": {},
            "resource_id": "test-res-id",
            "action": "CREATE",
            "type": "GenericResourceType"
        }
        adopt = scheduler.TaskRunner(res.adopt, res_data)
        adopt()
        self.assertEqual({}, res.metadata_get())
        self.assertEqual((res.ADOPT, res.COMPLETE), res.state)

    def test_adopt_with_resource_data_and_metadata(self):
        adopt_data = '{}'
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        res_data = {
            "status": "COMPLETE",
            "name": "foo",
            "resource_data": {"test-key": "test-value"},
            "metadata": {"os_distro": "test-distro"},
            "resource_id": "test-res-id",
            "action": "CREATE",
            "type": "GenericResourceType"
        }
        adopt = scheduler.TaskRunner(res.adopt, res_data)
        adopt()
        self.assertEqual(
            "test-value",
            resource_data_object.ResourceData.get_val(res, "test-key"))
        self.assertEqual({"os_distro": "test-distro"}, res.metadata_get())
        self.assertEqual((res.ADOPT, res.COMPLETE), res.state)

    def test_adopt_resource_missing(self):
        adopt_data = '''{
                        "action": "CREATE",
                        "status": "COMPLETE",
                        "name": "my-test-stack-name",
                        "resources": {}
                        }'''
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  tmpl,
                                  stack_id=str(uuid.uuid4()),
                                  adopt_stack_data=json.loads(adopt_data))
        res = self.stack['foo']
        adopt = scheduler.TaskRunner(res.adopt, None)
        self.assertRaises(exception.ResourceFailure, adopt)
        expected = 'Exception: resources.foo: Resource ID was not provided.'
        self.assertEqual(expected, res.status_reason)


class ResourceDependenciesTest(common.HeatTestCase):
    def setUp(self):
        super(ResourceDependenciesTest, self).setUp()

        self.deps = dependencies.Dependencies()

    def test_no_deps(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['foo']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)

    def test_hot_add_dep_error_create(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {'type': 'ResourceWithPropsType'}
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        res = stack['bar']

        class TestException(Exception):
            pass

        self.patchobject(res, 'add_dependencies',
                         side_effect=TestException)

        def get_dependencies():
            return stack.dependencies

        self.assertRaises(TestException, get_dependencies)

    def test_hot_add_dep_error_load(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {'type': 'ResourceWithPropsType'}
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test_hot_add_dep_err',
                             tmpl)
        stack.store()
        res = stack['bar']
        self.patchobject(res, 'add_dependencies',
                         side_effect=ValueError)
        graph = stack.dependencies.graph()
        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph)

    def test_ref(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'foo'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref(self):
        '''Test that HOT get_resource creates dependencies.'''
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_resource': 'foo'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_dict(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Base64': {'Ref': 'foo'}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref_nested_dict(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Base64': {'get_resource': 'foo'}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Ref': 'foo'},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_ref_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_resource': 'foo'},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_ref_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Ref': 'baz'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        self.assertRaises(exception.StackValidationFailed,
                          stack.validate)

    def test_hot_ref_fail(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_resource': 'baz'},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               stack.validate)
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_validate_value_fail(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'FooInt': 'notanint',
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.StackValidationFailed,
                               stack.validate)
        self.assertIn("Property error: resources.bar.properties.FooInt: "
                      "Value 'notanint' is not an integer",
                      six.text_type(ex))

        # You can turn off value validation via strict_validate
        stack_novalidate = parser.Stack(utils.dummy_context(), 'test', tmpl,
                                        strict_validate=False)
        self.assertIsNone(stack_novalidate.validate())

    def test_getatt(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::GetAtt': ['foo', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_attr': ['foo', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_dict(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Base64': {'Fn::GetAtt': ['foo', 'bar']}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt_nested_dict(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Base64': {'get_attr': ['foo', 'bar']}},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Fn::GetAtt': ['foo',
                                                                   'bar']},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_hot_getatt_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_attr': ['foo',
                                                                 'bar']},
                                                   "wibble"]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_getatt_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::GetAtt': ['baz', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_hot_getatt_fail(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'get_attr': ['baz', 'bar']},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo)', six.text_type(ex))

    def test_getatt_fail_nested_deep(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'ResourceWithPropsType',
                    'Properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'Fn::GetAtt': ['foo',
                                                                   'bar']},
                                                   "wibble",
                                                   {'Fn::GetAtt': ['baz',
                                                                   'bar']}]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])',
                      six.text_type(ex))

    def test_hot_getatt_fail_nested_deep(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'ResourceWithPropsType',
                    'properties': {
                        'Foo': {'Fn::Join': [",", ["blarg",
                                                   {'get_attr': ['foo',
                                                                 'bar']},
                                                   "wibble",
                                                   {'get_attr': ['baz',
                                                                 'bar']}]]},
                    }
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"baz" (in bar.Properties.Foo.Fn::Join[1][3])',
                      six.text_type(ex))

    def test_dependson(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {'Type': 'GenericResourceType'},
                'bar': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'foo',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_dependson_hot(self):
        tmpl = template.Template({
            'heat_template_version': '2013-05-23',
            'resources': {
                'foo': {'type': 'GenericResourceType'},
                'bar': {
                    'type': 'GenericResourceType',
                    'depends_on': 'foo',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)

        res = stack['bar']
        res.add_explicit_dependencies(self.deps)
        graph = self.deps.graph()

        self.assertIn(res, graph)
        self.assertIn(stack['foo'], graph[res])

    def test_dependson_fail(self):
        tmpl = template.Template({
            'HeatTemplateFormatVersion': '2012-12-12',
            'Resources': {
                'foo': {
                    'Type': 'GenericResourceType',
                    'DependsOn': 'wibble',
                }
            }
        })
        stack = parser.Stack(utils.dummy_context(), 'test', tmpl)
        ex = self.assertRaises(exception.InvalidTemplateReference,
                               getattr, stack, 'dependencies')
        self.assertIn('"wibble" (in foo)', six.text_type(ex))


class MetadataTest(common.HeatTestCase):
    def setUp(self):
        super(MetadataTest, self).setUp()
        self.stack = parser.Stack(utils.dummy_context(),
                                  'test_stack',
                                  template.Template(empty_template))
        self.stack.store()

        metadata = {'Test': 'Initial metadata'}
        tmpl = rsrc_defn.ResourceDefinition('metadata_resource', 'Foo',
                                            metadata=metadata)
        self.res = generic_rsrc.GenericResource('metadata_resource',
                                                tmpl, self.stack)

        scheduler.TaskRunner(self.res.create)()
        self.addCleanup(self.stack.delete)

    def test_read_initial(self):
        self.assertEqual({'Test': 'Initial metadata'}, self.res.metadata_get())

    def test_write(self):
        test_data = {'Test': 'Newly-written data'}
        self.res.metadata_set(test_data)
        self.assertEqual(test_data, self.res.metadata_get())


class ReducePhysicalResourceNameTest(common.HeatTestCase):
    scenarios = [
        ('one', dict(
            limit=10,
            original='one',
            reduced='one')),
        ('limit_plus_one', dict(
            will_reduce=True,
            limit=10,
            original='onetwothree',
            reduced='on-wothree')),
        ('limit_exact', dict(
            limit=11,
            original='onetwothree',
            reduced='onetwothree')),
        ('limit_minus_one', dict(
            limit=12,
            original='onetwothree',
            reduced='onetwothree')),
        ('limit_four', dict(
            will_reduce=True,
            limit=4,
            original='onetwothree',
            reduced='on-e')),
        ('limit_three', dict(
            will_raise=ValueError,
            limit=3,
            original='onetwothree')),
        ('three_nested_stacks', dict(
            will_reduce=True,
            limit=63,
            original=('ElasticSearch-MasterCluster-ccicxsm25ug6-MasterSvr1'
                      '-men65r4t53hh-MasterServer-gxpc3wqxy4el'),
            reduced=('El-icxsm25ug6-MasterSvr1-men65r4t53hh-'
                     'MasterServer-gxpc3wqxy4el'))),
        ('big_names', dict(
            will_reduce=True,
            limit=63,
            original=('MyReallyQuiteVeryLongStackName-'
                      'MyExtraordinarilyLongResourceName-ccicxsm25ug6'),
            reduced=('My-LongStackName-'
                     'MyExtraordinarilyLongResourceName-ccicxsm25ug6'))),
    ]

    will_raise = None

    will_reduce = False

    def test_reduce(self):
        if self.will_raise:
            self.assertRaises(
                self.will_raise,
                resource.Resource.reduce_physical_resource_name,
                self.original,
                self.limit)
        else:
            reduced = resource.Resource.reduce_physical_resource_name(
                self.original, self.limit)
            self.assertEqual(self.reduced, reduced)
            if self.will_reduce:
                # check it has been truncated to exactly the limit
                self.assertEqual(self.limit, len(reduced))
            else:
                # check that nothing has changed
                self.assertEqual(self.original, reduced)


class ResourceHookTest(common.HeatTestCase):

    def setUp(self):
        super(ResourceHookTest, self).setUp()

        self.env = environment.Environment()

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template,
                                                    env=self.env),
                                  stack_id=str(uuid.uuid4()))

    def test_hook(self):
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)

        res.data = mock.Mock(return_value={})
        self.assertFalse(res.has_hook('pre-create'))
        self.assertFalse(res.has_hook('pre-update'))

        res.data = mock.Mock(return_value={'pre-create': 'True'})
        self.assertTrue(res.has_hook('pre-create'))
        self.assertFalse(res.has_hook('pre-update'))

        res.data = mock.Mock(return_value={'pre-create': 'False'})
        self.assertFalse(res.has_hook('pre-create'))
        self.assertFalse(res.has_hook('pre-update'))

        res.data = mock.Mock(return_value={'pre-update': 'True'})
        self.assertFalse(res.has_hook('pre-create'))
        self.assertTrue(res.has_hook('pre-update'))

        res.data = mock.Mock(return_value={'pre-delete': 'True'})
        self.assertFalse(res.has_hook('pre-create'))
        self.assertFalse(res.has_hook('pre-update'))
        self.assertTrue(res.has_hook('pre-delete'))

        res.data = mock.Mock(return_value={'post-create': 'True'})
        self.assertFalse(res.has_hook('post-delete'))
        self.assertFalse(res.has_hook('post-update'))
        self.assertTrue(res.has_hook('post-create'))

        res.data = mock.Mock(return_value={'post-update': 'True'})
        self.assertFalse(res.has_hook('post-create'))
        self.assertFalse(res.has_hook('post-delete'))
        self.assertTrue(res.has_hook('post-update'))

        res.data = mock.Mock(return_value={'post-delete': 'True'})
        self.assertFalse(res.has_hook('post-create'))
        self.assertFalse(res.has_hook('post-update'))
        self.assertTrue(res.has_hook('post-delete'))

    def test_set_hook(self):
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)

        res.data_set = mock.Mock()
        res.data_delete = mock.Mock()

        res.trigger_hook('pre-create')
        res.data_set.assert_called_with('pre-create', 'True')

        res.trigger_hook('pre-update')
        res.data_set.assert_called_with('pre-update', 'True')

        res.clear_hook('pre-create')
        res.data_delete.assert_called_with('pre-create')

    def test_signal_clear_hook(self):
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)

        res.clear_hook = mock.Mock()
        res.has_hook = mock.Mock(return_value=True)
        self.assertRaises(exception.ResourceActionNotSupported,
                          res.signal, None)
        self.assertFalse(res.clear_hook.called)

        self.assertRaises(exception.ResourceActionNotSupported,
                          res.signal, {'other_hook': 'alarm'})
        self.assertFalse(res.clear_hook.called)

        self.assertRaises(exception.InvalidBreakPointHook,
                          res.signal, {'unset_hook': 'unknown_hook'})
        self.assertFalse(res.clear_hook.called)

        result = res.signal({'unset_hook': 'pre-create'})
        res.clear_hook.assert_called_with('pre-create')
        self.assertFalse(result)

        result = res.signal({'unset_hook': 'pre-update'})
        res.clear_hook.assert_called_with('pre-update')
        self.assertFalse(result)

        res.has_hook = mock.Mock(return_value=False)
        self.assertRaises(exception.InvalidBreakPointHook,
                          res.signal, {'unset_hook': 'pre-create'})

    def test_pre_create_hook_call(self):
        self.stack.env.registry.load(
            {'resources': {'res': {'hooks': 'pre-create'}}})
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)
        res.id = '1234'
        res.uuid = uuid.uuid4()
        res.store = mock.Mock()
        task = scheduler.TaskRunner(res.create)
        task.start()
        task.step()
        self.assertTrue(res.has_hook('pre-create'))
        res.signal(details={'unset_hook': 'pre-create'})
        task.run_to_completion()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_pre_delete_hook_call(self):
        self.stack.env.registry.load(
            {'resources': {'res': {'hooks': 'pre-delete'}}})
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)
        res.id = '1234'
        res.action = 'CREATE'
        res.uuid = uuid.uuid4()
        res.store = mock.Mock()
        self.stack.action = 'DELETE'
        task = scheduler.TaskRunner(res.delete)
        task.start()
        task.step()
        self.assertTrue(res.has_hook('pre-delete'))
        res.signal(details={'unset_hook': 'pre-delete'})
        task.run_to_completion()
        self.assertEqual((res.DELETE, res.COMPLETE), res.state)

    def test_post_create_hook_call(self):
        self.stack.env.registry.load(
            {'resources': {'res': {'hooks': 'post-create'}}})
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)
        res.id = '1234'
        res.uuid = uuid.uuid4()
        res.store = mock.Mock()
        task = scheduler.TaskRunner(res.create)
        task.start()
        task.step()
        self.assertTrue(res.has_hook('post-create'))
        res.signal(details={'unset_hook': 'post-create'})
        task.run_to_completion()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)

    def test_post_delete_hook_call(self):
        self.stack.env.registry.load(
            {'resources': {'res': {'hooks': 'post-delete'}}})
        snippet = rsrc_defn.ResourceDefinition('res',
                                               'GenericResourceType')
        res = resource.Resource('res', snippet, self.stack)
        res.id = '1234'
        res.uuid = uuid.uuid4()
        res.action = 'CREATE'
        self.stack.action = 'DELETE'
        res.store = mock.Mock()
        task = scheduler.TaskRunner(res.delete)
        task.start()
        task.step()
        self.assertTrue(res.has_hook('post-delete'))
        res.signal(details={'unset_hook': 'post-delete'})
        task.run_to_completion()
        self.assertEqual((res.DELETE, res.COMPLETE), res.state)


class ResourceAvailabilityTest(common.HeatTestCase):
    def _mock_client_plugin(self, service_types=None, is_available=True):
        service_types = service_types or []
        mock_client_plugin = mock.Mock()
        mock_service_types = mock.PropertyMock(return_value=service_types)
        type(mock_client_plugin).service_types = mock_service_types
        mock_client_plugin.does_endpoint_exist = mock.Mock(
            return_value=is_available)
        return mock_service_types, mock_client_plugin

    def test_default_true_with_default_client_name_none(self):
        """Test availability of resource when default_client_name is None.

        When default_client_name is None, resource is considered as available.
        """
        with mock.patch(('heat.tests.generic_resource'
                        '.ResourceWithDefaultClientName.default_client_name'),
                        new_callable=mock.PropertyMock) as mock_client_name:
            mock_client_name.return_value = None
            self.assertTrue((generic_rsrc.ResourceWithDefaultClientName.
                            is_service_available(context=mock.Mock())[0]))

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_default_true_empty_service_types(
            self,
            mock_client_plugin_method):
        """Test availability of resource when service_types is empty list.

        When service_types is empty list, resource is considered as available.
        """

        mock_service_types, mock_client_plugin = self._mock_client_plugin()
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertTrue(
            generic_rsrc.ResourceWithDefaultClientName.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_deployed(
            self,
            mock_client_plugin_method):
        """Test availability of resource when the service is deployed.

        When the service is deployed, resource is considered as available.
        """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type']
        )
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertTrue(
            generic_rsrc.ResourceWithDefaultClientName.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name)
        )

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_not_deployed(
            self,
            mock_client_plugin_method):
        """Test availability of resource when the service is not deployed.

        When the service is not deployed, resource is considered as
        unavailable.
        """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type_un_deployed'],
            False
        )
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertFalse(
            generic_rsrc.ResourceWithDefaultClientName.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type_un_deployed',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name)
        )

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_deployed_required_extension_true(
            self,
            mock_client_plugin_method):
        """Test availability of resource with a required extension. """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type']
        )
        mock_client_plugin.has_extension = mock.Mock(
            return_value=True)
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertTrue(
            generic_rsrc.ResourceWithDefaultClientNameExt.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name))
        mock_client_plugin.has_extension.assert_called_once_with('foo')

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_deployed_required_extension_false(
            self,
            mock_client_plugin_method):
        """Test availability of resource with a required extension. """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type']
        )
        mock_client_plugin.has_extension = mock.Mock(
            return_value=False)
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertFalse(
            generic_rsrc.ResourceWithDefaultClientNameExt.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name))
        mock_client_plugin.has_extension.assert_called_once_with('foo')

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_deployed_required_extension_exception(
            self,
            mock_client_plugin_method):
        """Test availability of resource with a required extension. """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type']
        )
        mock_client_plugin.has_extension = mock.Mock(
            side_effect=exception.AuthorizationFailure())
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertRaises(
            exception.AuthorizationFailure,
            generic_rsrc.ResourceWithDefaultClientNameExt.is_service_available,
            context=mock.Mock())
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name))
        mock_client_plugin.has_extension.assert_called_once_with('foo')

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_not_deployed_required_extension(
            self,
            mock_client_plugin_method):
        """Test availability of resource when the service is not deployed.

        When the service is not deployed, resource is considered as
        unavailable.
        """

        mock_service_types, mock_client_plugin = self._mock_client_plugin(
            ['test_type_un_deployed'],
            False
        )
        mock_client_plugin_method.return_value = mock_client_plugin

        self.assertFalse(
            generic_rsrc.ResourceWithDefaultClientNameExt.is_service_available(
                context=mock.Mock())[0])
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)
        mock_service_types.assert_called_once_with()
        mock_client_plugin.does_endpoint_exist.assert_called_once_with(
            service_type='test_type_un_deployed',
            service_name=(generic_rsrc.ResourceWithDefaultClientName
                          .default_client_name))

    @mock.patch.object(clients.OpenStackClients, 'client_plugin')
    def test_service_not_installed_required_extension(
            self,
            mock_client_plugin_method):
        """Test availability of resource when the client is not installed.

        When the client is not installed, we can't create the resource properly
        so raise a proper exception for information.
        """
        mock_client_plugin_method.return_value = None

        self.assertRaises(
            exception.ClientNotAvailable,
            generic_rsrc.ResourceWithDefaultClientNameExt.is_service_available,
            context=mock.Mock())
        mock_client_plugin_method.assert_called_once_with(
            generic_rsrc.ResourceWithDefaultClientName.default_client_name)

    def test_service_not_available_returns_false(self):
        """Test when the service is not in service catalog.

        When the service is not deployed, make sure resource is throwing
        ResourceTypeUnavailable exception.
        """
        with mock.patch.object(
                generic_rsrc.ResourceWithDefaultClientName,
                'is_service_available') as mock_method:
            mock_method.return_value = (
                False, 'Service endpoint not in service catalog.')

            definition = rsrc_defn.ResourceDefinition(
                name='Test Resource',
                resource_type='UnavailableResourceType')

            mock_stack = mock.MagicMock()
            mock_stack.in_convergence_check = False
            mock_stack.db_resource_get.return_value = None
            rsrc = generic_rsrc.ResourceWithDefaultClientName('test_res',
                                                              definition,
                                                              mock_stack)

            ex = self.assertRaises(
                exception.ResourceTypeUnavailable,
                rsrc.validate_template)

            msg = ('HEAT-E99001 Service sample is not available for resource '
                   'type UnavailableResourceType, reason: '
                   'Service endpoint not in service catalog.')
            self.assertEqual(msg,
                             six.text_type(ex),
                             'invalid exception message')

            # Make sure is_service_available is called on the right class
            mock_method.assert_called_once_with(mock_stack.context)

    def test_service_not_available_throws_exception(self):
        """Test for other exceptions when checking for service availability

        Ex. when client throws an error, make sure resource is throwing
        ResourceTypeUnavailable that contains the original exception message.
        """
        with mock.patch.object(
                generic_rsrc.ResourceWithDefaultClientName,
                'is_service_available') as mock_method:
            mock_method.side_effect = exception.AuthorizationFailure()

            definition = rsrc_defn.ResourceDefinition(
                name='Test Resource',
                resource_type='UnavailableResourceType')

            mock_stack = mock.MagicMock()
            mock_stack.in_convergence_check = False
            mock_stack.db_resource_get.return_value = None
            rsrc = generic_rsrc.ResourceWithDefaultClientName('test_res',
                                                              definition,
                                                              mock_stack)

            ex = self.assertRaises(
                exception.ResourceTypeUnavailable,
                rsrc.validate_template)

            msg = ('HEAT-E99001 Service sample is not available for resource '
                   'type UnavailableResourceType, reason: '
                   'Authorization failed.')
            self.assertEqual(msg,
                             six.text_type(ex),
                             'invalid exception message')

            # Make sure is_service_available is called on the right class
            mock_method.assert_called_once_with(mock_stack.context)

    def test_handle_delete_successful(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)

        FakeClient = collections.namedtuple('Client',
                                            ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        res.client().entity.delete = delete
        res.entity = 'entity'
        res.default_client_name = 'something'
        res.resource_id = '12345'

        self.assertEqual('12345', res.handle_delete())
        delete.assert_called_once_with('12345')

    def test_handle_delete_not_found(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)
        res.entity = 'entity'
        res.default_client_name = 'foo'
        res.resource_id = '12345'

        FakeClient = collections.namedtuple('Client', ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        client_plugin = res._default_client_plugin()

        def is_not_found(ex):
            return isinstance(ex, exception.NotFound)

        client_plugin.is_not_found = mock.Mock(side_effect=is_not_found)
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        delete.side_effect = [exception.NotFound()]
        res.client().entity.delete = delete

        with mock.patch.object(res, '_default_client_plugin',
                               return_value=client_plugin):
            self.assertIsNone(res.handle_delete())
        delete.assert_called_once_with('12345')

    def test_handle_delete_raise_error(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)
        res.entity = 'entity'
        res.default_client_name = 'something'
        res.resource_id = '12345'

        FakeClient = collections.namedtuple('Client', ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        client_plugin = res._default_client_plugin()

        def is_not_found(ex):
            return isinstance(ex, exception.NotFound)

        client_plugin.is_not_found = mock.Mock(side_effect=is_not_found)
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        delete.side_effect = [exception.Error('boom!')]
        res.client().entity.delete = delete

        with mock.patch.object(res, '_default_client_plugin',
                               return_value=client_plugin):
            ex = self.assertRaises(exception.Error, res.handle_delete)
        self.assertEqual('boom!', six.text_type(ex))
        delete.assert_called_once_with('12345')

    def test_handle_delete_no_entity(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)

        FakeClient = collections.namedtuple('Client',
                                            ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        res.client().entity.delete = delete
        res.resource_id = '12345'

        self.assertIsNone(res.handle_delete())
        self.assertEqual(0, delete.call_count)

    def test_handle_delete_no_resource_id(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)

        FakeClient = collections.namedtuple('Client',
                                            ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        res.client().entity.delete = delete
        res.entity = 'entity'
        res.default_client_name = 'something'
        res.resource_id = None

        self.assertIsNone(res.handle_delete())
        self.assertEqual(0, delete.call_count)

    def test_handle_delete_no_default_client_name(self):
        class MyException(Exception):
            pass

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'OS::Heat::None')
        res = resource.Resource('aresource', snippet, self.stack)

        FakeClient = collections.namedtuple('Client',
                                            ['entity'])
        client = FakeClient(collections.namedtuple('entity', ['delete']))
        self.patchobject(resource.Resource, 'client', return_value=client)
        delete = mock.Mock()
        delete.side_effect = [MyException]
        res.client().entity.delete = delete
        res.entity = 'entity'
        res.resource_id = '1234'
        res.default_client_name = None

        self.assertRaises(MyException, res.handle_delete)


class TestLiveStateUpdate(common.HeatTestCase):

    scenarios = [
        ('update_all_args', dict(
            live_state={'Foo': 'abb', 'FooInt': 2},
            updated_props={'Foo': 'bca', 'FooInt': 3},
            expected_error=False,
            resource_id='1234',
            expected={'Foo': 'bca', 'FooInt': 3}
        )),
        ('update_some_args', dict(
            live_state={'Foo': 'bca'},
            updated_props={'Foo': 'bca', 'FooInt': 3},
            expected_error=False,
            resource_id='1234',
            expected={'Foo': 'bca', 'FooInt': 3}
        )),
        ('live_state_some_error', dict(
            live_state={'Foo': 'bca'},
            updated_props={'Foo': 'bca', 'FooInt': 3},
            expected_error=False,
            resource_id='1234',
            expected={'Foo': 'bca', 'FooInt': 3}
        )),
        ('entity_not_found', dict(
            live_state=exception.EntityNotFound(entity='resource',
                                                name='test'),
            updated_props={'Foo': 'bca'},
            expected_error=True,
            resource_id='1234',
            expected=resource.UpdateReplace
        )),
        ('live_state_not_found_id', dict(
            live_state=exception.EntityNotFound(entity='resource',
                                                name='test'),
            updated_props={'Foo': 'bca'},
            expected_error=True,
            resource_id=None,
            expected=resource.UpdateReplace
        ))
    ]

    def setUp(self):
        super(TestLiveStateUpdate, self).setUp()
        self.env = environment.Environment()
        self.env.load({u'resource_registry':
                      {u'OS::Test::GenericResource': u'GenericResourceType',
                       u'OS::Test::ResourceWithCustomConstraint':
                       u'ResourceWithCustomConstraint'}})

        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template,
                                                    env=self.env),
                                  stack_id=str(uuid.uuid4()))

    def _prepare_resource_live_state(self):
        tmpl = rsrc_defn.ResourceDefinition('test_resource',
                                            'ResourceWithPropsType',
                                            {'Foo': 'abc',
                                             'FooInt': 2})
        res = generic_rsrc.ResourceWithProps('test_resource',
                                             tmpl, self.stack)
        for prop in six.itervalues(res.properties.props):
            prop.schema.update_allowed = True
        res.update_allowed_properties = ('Foo', 'FooInt',)

        scheduler.TaskRunner(res.create)()
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        return res

    def _clean_tests_after_resource_live_state(self, res):
        """Revert changes for correct work of other tests.

        Need to revert changes of resource properties schema for correct work
        of other tests.
        """
        res.update_allowed_properties = []
        res.update_allowed_set = []
        for prop in six.itervalues(res.properties.props):
            prop.schema.update_allowed = False

    def test_update_resource_live_state(self):
        res = self._prepare_resource_live_state()
        res.resource_id = self.resource_id

        cfg.CONF.set_override('observe_on_update', True)

        utmpl = rsrc_defn.ResourceDefinition('test_resource',
                                             'ResourceWithPropsType',
                                             self.updated_props)

        if not self.expected_error:
            self.patchobject(res, 'get_live_state',
                             return_value=self.live_state)
            scheduler.TaskRunner(res.update, utmpl)()
            self.assertEqual((res.UPDATE, res.COMPLETE), res.state)
            self.assertEqual(self.expected, res.properties.data)
        else:
            self.patchobject(res, 'get_live_state',
                             side_effect=[self.live_state])
            self.assertRaises(self.expected,
                              scheduler.TaskRunner(res.update, utmpl))
        self._clean_tests_after_resource_live_state(res)

    def test_get_live_resource_data_success(self):
        res = self._prepare_resource_live_state()
        res.resource_id = self.resource_id
        res._show_resource = mock.MagicMock(return_value={'a': 'b'})
        self.assertEqual({'a': 'b'}, res.get_live_resource_data())
        self._clean_tests_after_resource_live_state(res)

    def test_get_live_resource_data_not_found(self):
        res = self._prepare_resource_live_state()
        res.default_client_name = 'foo'
        res.resource_id = self.resource_id
        res._show_resource = mock.MagicMock(
            side_effect=[exception.NotFound()])
        res.client_plugin = mock.MagicMock()
        res.client_plugin().is_not_found = mock.MagicMock(return_value=True)
        ex = self.assertRaises(exception.EntityNotFound,
                               res.get_live_resource_data)
        self.assertEqual('The Resource (test_resource) could not be found.',
                         six.text_type(ex))
        self._clean_tests_after_resource_live_state(res)

    def test_parse_live_resource_data(self):
        res = self._prepare_resource_live_state()

        res.update_allowed_props = mock.Mock(return_value=['Foo', 'Bar'])
        resource_data = {
            'Foo': 'brave new data',
            'Something not so good': 'for all of us'
        }
        res._update_allowed_properties = ['Foo', 'Bar']
        result = res.parse_live_resource_data(res.properties, resource_data)
        self.assertEqual({'Foo': 'brave new data'}, result)
        self._clean_tests_after_resource_live_state(res)

    def test_get_live_resource_data_not_found_no_default_client_name(self):
        class MyException(Exception):
            pass

        res = self._prepare_resource_live_state()
        res.default_client_name = None
        res.resource_id = self.resource_id
        res._show_resource = mock.MagicMock(
            side_effect=[MyException])
        res.client_plugin = mock.MagicMock()
        res.client_plugin().is_not_found = mock.MagicMock(return_value=True)
        self.assertRaises(MyException, res.get_live_resource_data)
        self._clean_tests_after_resource_live_state(res)

    def test_get_live_resource_data_other_error(self):
        res = self._prepare_resource_live_state()
        res.resource_id = self.resource_id
        res._show_resource = mock.MagicMock(
            side_effect=[exception.Forbidden()])
        res.client_plugin = mock.MagicMock()
        res.client_plugin().is_not_found = mock.MagicMock(return_value=False)
        self.assertRaises(exception.Forbidden, res.get_live_resource_data)
        self._clean_tests_after_resource_live_state(res)


class ResourceUpdateRestrictionTest(common.HeatTestCase):
    def setUp(self):
        super(ResourceUpdateRestrictionTest, self).setUp()
        resource._register_class('TestResourceType',
                                 test_resource.TestResource)
        resource._register_class('NoneResourceType',
                                 none_resource.NoneResource)
        self.tmpl = {
            'heat_template_version': '2013-05-23',
            'resources': {
                'bar': {
                    'type': 'TestResourceType',
                    'properties': {
                        'value': '1234',
                        'update_replace': False
                    }
                }
            }
        }
        self.dummy_timeout = 10
        self.dummy_event = eventlet.event.Event()

    def create_resource(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(self.tmpl, env=self.env),
                                  stack_id=str(uuid.uuid4()))
        res = self.stack['bar']
        scheduler.TaskRunner(res.create)()
        return res

    def create_convergence_resource(self):
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(self.tmpl, env=self.env),
                                  stack_id=str(uuid.uuid4()))
        res = self.stack['bar']
        pcb = mock.Mock()
        self.patchobject(res, 'lock')
        res.create_convergence(self.stack.t.id, set(), 'engine-007',
                               self.dummy_timeout, pcb)
        return res

    def test_update_restricted(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'update'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_resource()
        ev = self.patchobject(res, '_add_event')
        props = self.tmpl['resources']['bar']['properties']
        props['value'] = '4567'
        snippet = rsrc_defn.ResourceDefinition('bar',
                                               'TestResourceType',
                                               props)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(res.update, snippet))

        self.assertEqual('ResourceActionRestricted: resources.bar: '
                         'update is restricted for resource.',
                         six.text_type(error))
        self.assertEqual('UPDATE', error.action)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        ev.assert_called_with(res.UPDATE, res.FAILED,
                              'update is restricted for resource.')

    def test_replace_restricted(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'replace'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_resource()
        ev = self.patchobject(res, '_add_event')
        props = self.tmpl['resources']['bar']['properties']
        props['value'] = '4567'
        props['update_replace'] = True
        snippet = rsrc_defn.ResourceDefinition('bar',
                                               'TestResourceType',
                                               props)
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(res.update, snippet))
        self.assertEqual('ResourceActionRestricted: resources.bar: '
                         'replace is restricted for resource.',
                         six.text_type(error))
        self.assertEqual('UPDATE', error.action)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        ev.assert_called_with(res.UPDATE, res.FAILED,
                              'replace is restricted for resource.')

    def test_update_with_replace_restricted(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'replace'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_resource()
        ev = self.patchobject(res, '_add_event')
        props = self.tmpl['resources']['bar']['properties']
        props['value'] = '4567'
        snippet = rsrc_defn.ResourceDefinition('bar',
                                               'TestResourceType',
                                               props)
        self.assertIsNone(scheduler.TaskRunner(res.update, snippet)())
        self.assertEqual((res.UPDATE, res.COMPLETE), res.state)
        ev.assert_called_with(res.UPDATE, res.COMPLETE,
                              'state changed')

    def test_replace_with_update_restricted(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'update'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_resource()
        ev = self.patchobject(res, '_add_event')
        prep_replace = self.patchobject(res, 'prepare_for_replace')
        props = self.tmpl['resources']['bar']['properties']
        props['value'] = '4567'
        props['update_replace'] = True
        snippet = rsrc_defn.ResourceDefinition('bar',
                                               'TestResourceType',
                                               props)
        error = self.assertRaises(resource.UpdateReplace,
                                  scheduler.TaskRunner(res.update, snippet))
        self.assertIn('requires replacement', six.text_type(error))
        self.assertEqual(1, prep_replace.call_count)
        ev.assert_not_called()

    def test_replace_restricted_type_change_with_convergence(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'replace'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_convergence_resource()
        ev = self.patchobject(res, '_add_event')
        bar = self.tmpl['resources']['bar']
        bar['type'] = 'OS::Heat::None'
        self.new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                      template.Template(self.tmpl,
                                                        env=self.env))
        error = self.assertRaises(exception.ResourceFailure,
                                  scheduler.TaskRunner(res.update_convergence,
                                                       self.stack.t.id,
                                                       set(),
                                                       'engine-007',
                                                       self.dummy_timeout,
                                                       self.new_stack,
                                                       eventlet.event.Event()))
        self.assertEqual('ResourceActionRestricted: resources.bar: '
                         'replace is restricted for resource.',
                         six.text_type(error))
        self.assertEqual('UPDATE', error.action)
        self.assertEqual((res.CREATE, res.COMPLETE), res.state)
        ev.assert_called_with(res.UPDATE, res.FAILED,
                              'replace is restricted for resource.')

    def test_update_restricted_type_change_with_convergence(self):
        self.env_snippet = {u'resource_registry': {
            u'resources': {
                'bar': {'restricted_actions': 'update'}
            }
        }
        }
        self.env = environment.Environment()
        self.env.load(self.env_snippet)
        res = self.create_convergence_resource()
        ev = self.patchobject(res, '_add_event')
        bar = self.tmpl['resources']['bar']
        bar['type'] = 'OS::Heat::None'
        self.new_stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                      template.Template(self.tmpl,
                                                        env=self.env))
        error = self.assertRaises(resource.UpdateReplace,
                                  scheduler.TaskRunner(res.update_convergence,
                                                       self.stack.t.id,
                                                       set(),
                                                       'engine-007',
                                                       self.dummy_timeout,
                                                       self.new_stack,
                                                       eventlet.event.Event()))
        self.assertIn('requires replacement', six.text_type(error))
        ev.assert_not_called()


class TestResourceMapping(common.HeatTestCase):

    def _check_mapping_func(self, func, module):
        self.assertTrue(callable(func))
        res = func()
        self.assertIsInstance(res, collections.Mapping)
        for r_type, r_class in six.iteritems(res):
            self.assertIsInstance(r_type, six.string_types)
            type_elements = r_type.split('::')
            # type has fixed format
            # Platform type::Service/Type::Optional Sub-sections::Name
            self.assertGreaterEqual(len(type_elements), 3)
            # type should be OS or AWS
            self.assertIn(type_elements[0], ('AWS', 'OS'))
            # check that value is a class object
            self.assertIsInstance(r_class, six.class_types)
            # check that class is subclass of Resource base class
            self.assertTrue(issubclass(r_class, resource.Resource))
            # check that mentioned class is presented in the same module
            self.assertTrue(hasattr(module, six.text_type(r_class.__name__)))
        return len(res)

    def test_resource_mappings(self):
        # use plugin manager for loading all resources
        # use the same approach like and in heat.engine.resources.__init__
        manager = plugin_manager.PluginManager('heat.engine.resources')
        num_of_types = 0
        for module in manager.modules:
            # check for both potential mappings
            for name in ('resource_mapping', 'available_resource_mapping'):
                mapping_func = getattr(module, name, None)
                if mapping_func:
                    num_of_types += self._check_mapping_func(
                        mapping_func, module)

        # check number of registred resource types to make sure,
        # that there is no regressions
        # It's soft check and should not be a cause of the merge conflict
        # Feel free to update it in some separate patch
        self.assertGreaterEqual(num_of_types, 137)


class TestResourcePropDataUpdate(common.HeatTestCase):

    scenarios = [
        ('s1', dict(
            old_rpd={1: 2}, new_rpd={3: 4}, replaced=True)),
        ('s2', dict(
            old_rpd={'1': '2'}, new_rpd={'3': '4'}, replaced=True)),
        ('s3', dict(
            old_rpd={'1': '2'}, new_rpd={'1': '4'}, replaced=True)),
        ('s4', dict(
            old_rpd={'1': '2'}, new_rpd={'1': '2'}, replaced=False)),
        ('s5', dict(
            old_rpd={'1': '2', 4: 3}, new_rpd={'1': '2'}, replaced=True)),
        ('s6', dict(
            old_rpd={'1': '2', 4: 3}, new_rpd={'1': '2', 4: 3},
            replaced=False)),
        ('s7', dict(
            old_rpd={'1': '2'}, new_rpd={'1': '2', 4: 3}, replaced=True)),
        ('s8', dict(
            old_rpd={'1': '2'}, new_rpd={}, replaced=True)),
        ('s9', dict(
            old_rpd={}, new_rpd={1: 2}, replaced=True)),
        ('s10', dict(
            old_rpd={}, new_rpd={}, replaced=False)),
        ('s11', dict(
            old_rpd=None, new_rpd={}, replaced=False)),
        ('s11', dict(
            old_rpd={}, new_rpd=None, replaced=False)),
        ('s12', dict(
            old_rpd={3: 4}, new_rpd=None, replaced=True)),
    ]

    def setUp(self):
        super(TestResourcePropDataUpdate, self).setUp()
        self.stack = parser.Stack(utils.dummy_context(), 'test_stack',
                                  template.Template(empty_template))
        self.stack.store()
        snippet = rsrc_defn.ResourceDefinition('aresource',
                                               'GenericResourceType')
        self.res = resource.Resource('aresource', snippet, self.stack)

    def test_create_or_replace_rsrc_prop_data(self):
        res = self.res
        res._stored_properties_data = self.old_rpd
        res.store()
        old_rpd_id = res._rsrc_prop_data_id
        with mock.patch("heat.engine.function.resolve") as mock_fr:
            mock_fr.return_value = self.new_rpd
            res._update_stored_properties()
        res.store()
        new_rpd_id = res._rsrc_prop_data_id
        self.assertEqual(self.replaced, old_rpd_id != new_rpd_id)
