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
import itertools

from oslo.config import cfg

from heat.common import exception
from heat.common import grouputils
from heat.common import short_id
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack_resource
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils


class AutoScalingGroupTest(common.HeatTestCase):

    as_template = '''
        heat_template_version: 2013-05-23
        description: AutoScaling Test
        resources:
          my-group:
            properties:
              max_size: 5
              min_size: 1
              resource:
                type: ResourceWithPropsAndAttrs
                properties:
                    Foo: hello
            type: OS::Heat::AutoScalingGroup
    '''

    def setUp(self):
        super(AutoScalingGroupTest, self).setUp()
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_resource.ResourceWithPropsAndAttrs)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        self.parsed = template_format.parse(self.as_template)

    def create_stack(self, t):
        stack = utils.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_scaling_delete_empty(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 0
        properties['max_size'] = 0
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(0, grouputils.get_size(rsrc))
        rsrc.delete()

    def test_scaling_adjust_down_empty(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 1
        rsrc = self.create_stack(self.parsed)['my-group']
        resources = grouputils.get_members(rsrc)
        self.assertEqual(1, len(resources))

        # Reduce the min size to 0, should complete without adjusting
        props = copy.copy(rsrc.properties.data)
        props['min_size'] = 0
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, grouputils.get_members(rsrc))

        # trigger adjustment to reduce to 0, there should be no more instances
        rsrc.adjust(-1)
        self.assertEqual(0, grouputils.get_size(rsrc))

    def test_scaling_group_suspend(self):
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, grouputils.get_size(rsrc))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        scheduler.TaskRunner(rsrc.suspend)()
        self.assertEqual((rsrc.SUSPEND, rsrc.COMPLETE), rsrc.state)

    def test_scaling_group_resume(self):
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, grouputils.get_size(rsrc))
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        rsrc.state_set(rsrc.SUSPEND, rsrc.COMPLETE)
        for i in rsrc.nested().values():
            i.state_set(rsrc.SUSPEND, rsrc.COMPLETE)

        scheduler.TaskRunner(rsrc.resume)()
        self.assertEqual((rsrc.RESUME, rsrc.COMPLETE), rsrc.state)

    def test_scaling_group_create_error(self):
        mock_create = self.patchobject(generic_resource.ResourceWithProps,
                                       'handle_create')
        mock_create.side_effect = Exception("Creation failed!")

        rsrc = utils.parse_stack(self.parsed)['my-group']

        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(rsrc.create))
        self.assertEqual((rsrc.CREATE, rsrc.FAILED), rsrc.state)

        self.assertEqual(0, grouputils.get_size(rsrc))

    def test_scaling_group_update_ok_maxsize(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3

        rsrc = self.create_stack(self.parsed)['my-group']
        resources = grouputils.get_members(rsrc)
        self.assertEqual(1, len(resources))

        # Reduce the max size to 2, should complete without adjusting
        props = copy.copy(rsrc.properties.data)
        props['max_size'] = 2
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, grouputils.get_members(rsrc))
        self.assertEqual(2, rsrc.properties['max_size'])

    def test_scaling_group_update_ok_minsize(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3

        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, grouputils.get_size(rsrc))

        props = copy.copy(rsrc.properties.data)
        props['min_size'] = 2
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, grouputils.get_size(rsrc))
        self.assertEqual(2, rsrc.properties['min_size'])

    def test_scaling_group_update_ok_desired(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['min_size'] = 1
        properties['max_size'] = 3
        rsrc = self.create_stack(self.parsed)['my-group']
        self.assertEqual(1, grouputils.get_size(rsrc))

        props = copy.copy(rsrc.properties.data)
        props['desired_capacity'] = 2
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(2, grouputils.get_size(rsrc))
        self.assertEqual(2, rsrc.properties['desired_capacity'])

    def test_scaling_group_update_ok_desired_remove(self):
        properties = self.parsed['resources']['my-group']['properties']
        properties['desired_capacity'] = 2
        rsrc = self.create_stack(self.parsed)['my-group']
        resources = grouputils.get_members(rsrc)
        self.assertEqual(2, len(resources))

        props = copy.copy(rsrc.properties.data)
        props.pop('desired_capacity')
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()
        self.assertEqual(resources, grouputils.get_members(rsrc))
        self.assertIsNone(rsrc.properties['desired_capacity'])

    def test_scaling_group_scale_up_failure(self):
        stack = self.create_stack(self.parsed)
        mock_create = self.patchobject(generic_resource.ResourceWithProps,
                                       'handle_create')
        rsrc = stack['my-group']
        self.assertEqual(1, grouputils.get_size(rsrc))

        mock_create.side_effect = exception.Error('Bang')
        self.assertRaises(exception.Error, rsrc.adjust, 1)
        self.assertEqual(1, grouputils.get_size(rsrc))


class RollingUpdatesTest(common.HeatTestCase):

    as_template = '''
        heat_template_version: 2013-05-23
        description: AutoScaling Test
        resources:
          my-group:
            properties:
              max_size: 5
              min_size: 4
              rolling_updates:
                min_in_service: 2
                max_batch_size: 2
                pause_time: 0
              resource:
                type: ResourceWithProps
                properties:
                    Foo: hello
            type: OS::Heat::AutoScalingGroup
    '''

    def setUp(self):
        super(RollingUpdatesTest, self).setUp()
        utils.setup_dummy_db()
        resource._register_class('ResourceWithProps',
                                 generic_resource.ResourceWithProps)
        cfg.CONF.set_default('heat_waitcondition_server_url',
                             'http://server.test:8000/v1/waitcondition')
        self.stub_keystoneclient()
        self.parsed = template_format.parse(self.as_template)
        generate_id = self.patchobject(short_id, 'generate_id')
        generate_id.side_effect = ('id-%d' % (i,)
                                   for i in itertools.count()).next

    def create_stack(self, t):
        stack = utils.parse_stack(t)
        stack.create()
        self.assertEqual((stack.CREATE, stack.COMPLETE), stack.state)
        return stack

    def test_rolling_update(self):
        stack = self.create_stack(self.parsed)
        rsrc = stack['my-group']
        created_order = sorted(
            rsrc.nested().resources,
            key=lambda name: rsrc.nested().resources[name].created_time)
        batches = []

        def update_with_template(tmpl, env):
            # keep track of the new updates to resources _in creation order_.
            definitions = tmpl.resource_definitions(stack)
            templates = [definitions[name] for name in created_order]
            batches.append(templates)

        self.patchobject(
            stack_resource.StackResource, 'update_with_template',
            side_effect=update_with_template, wraps=rsrc.update_with_template)

        props = copy.deepcopy(rsrc.properties.data)
        props['resource']['properties']['Foo'] = 'Hi'
        update_snippet = rsrc_defn.ResourceDefinition(rsrc.name,
                                                      rsrc.type(),
                                                      props)
        scheduler.TaskRunner(rsrc.update, update_snippet)()

        props_schema = generic_resource.ResourceWithProps.properties_schema

        def get_foos(defns):
            return [d.properties(props_schema)['Foo'] for d in defns]

        # first batch has 2 new resources
        self.assertEqual(['Hi', 'Hi', 'hello', 'hello'],
                         get_foos(batches[0]))
        # second batch has all new resources.
        self.assertEqual(['Hi', 'Hi', 'Hi', 'Hi'],
                         get_foos(batches[1]))
