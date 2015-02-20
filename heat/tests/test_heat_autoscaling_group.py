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

from oslo_config import cfg

from heat.common import short_id
from heat.common import template_format
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack_resource
from heat.tests import common
from heat.tests import generic_resource
from heat.tests import utils


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

        def update_with_template(tmpl):
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
