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

import six

from heat_integrationtests.common import exceptions
from heat_integrationtests.common import test

CFG1_SH = '''#!/bin/sh
echo "Writing to /tmp/$bar"
echo $foo > /tmp/$bar
echo -n "The file /tmp/$bar contains `cat /tmp/$bar` for server \
$deploy_server_id during $deploy_action" > $heat_outputs_path.result
echo "Written to /tmp/$bar"
echo "Output to stderr" 1>&2
'''

CFG3_PP = '''file {'barfile':
  ensure  => file,
  mode    => 0644,
  path    => "/tmp/$::bar",
  content => "$::foo",
}
file {'output_result':
  ensure  => file,
  path    => "$::heat_outputs_path.result",
  mode    => 0644,
  content => "The file /tmp/$::bar contains $::foo for server \
$::deploy_server_id during $::deploy_action",
}'''


class SoftwareConfigIntegrationTest(test.HeatIntegrationTest):

    def setUp(self):
        super(SoftwareConfigIntegrationTest, self).setUp()
        if self.conf.skip_software_config_tests:
            self.skipTest('Testing software config disabled in conf, '
                          'skipping')
        self.client = self.orchestration_client
        self.template_name = 'test_server_software_config.yaml'
        self.sub_dir = 'templates'
        self.stack_name = self._stack_rand_name()
        self.maxDiff = None

    def launch_stack(self):
        net = self._get_default_network()
        self.parameters = {
            'key_name': self.keypair_name,
            'flavor': self.conf.instance_type,
            'image': self.conf.image_ref,
            'network': net['id']
        }

        # create the stack
        self.template = self._load_template(__file__, self.template_name,
                                            self.sub_dir)
        self.stack_create(
            stack_name=self.stack_name,
            template=self.template,
            parameters=self.parameters,
            files={
                'cfg1.sh': CFG1_SH,
                'cfg3.pp': CFG3_PP
            },
            expected_status=None)

        self.stack = self.client.stacks.get(self.stack_name)
        self.stack_identifier = '%s/%s' % (self.stack_name, self.stack.id)

    def check_stack(self):
        sid = self.stack_identifier
        for res in ('cfg2a', 'cfg2b', 'cfg1', 'cfg3', 'server'):
            self._wait_for_resource_status(
                sid, res, 'CREATE_COMPLETE')

        server_resource = self.client.resources.get(sid, 'server')
        server_id = server_resource.physical_resource_id
        server = self.compute_client.servers.get(server_id)

        try:
            # wait for each deployment to contribute their
            # config to resource
            for res in ('dep2b', 'dep1', 'dep3'):
                self._wait_for_resource_status(
                    sid, res, 'CREATE_IN_PROGRESS')

            server_metadata = self.client.resources.metadata(sid, 'server')
            deployments = dict((d['name'], d) for d in
                               server_metadata['deployments'])

            for res in ('dep2a', 'dep2b', 'dep1', 'dep3'):
                self._wait_for_resource_status(
                    sid, res, 'CREATE_COMPLETE')
        except (exceptions.StackResourceBuildErrorException,
                exceptions.TimeoutException) as e:
            self._log_console_output(servers=[server])
            raise e

        self._wait_for_stack_status(sid, 'CREATE_COMPLETE')

        complete_server_metadata = self.client.resources.metadata(
            sid, 'server')
        # ensure any previously available deployments haven't changed so
        # config isn't re-triggered
        complete_deployments = dict((d['name'], d) for d in
                                    complete_server_metadata['deployments'])
        for k, v in six.iteritems(deployments):
            self.assertEqual(v, complete_deployments[k])

        stack = self.client.stacks.get(sid)

        res1 = self._stack_output(stack, 'res1')
        self.assertEqual(
            'The file %s contains %s for server %s during %s' % (
                '/tmp/baaaaa', 'fooooo', server_id, 'CREATE'),
            res1['result'])
        self.assertEqual(0, res1['status_code'])
        self.assertEqual('Output to stderr\n', res1['stderr'])
        self.assertTrue(len(res1['stdout']) > 0)

        res2 = self._stack_output(stack, 'res2')
        self.assertEqual(
            'The file %s contains %s for server %s during %s' % (
                '/tmp/cfn-init-foo', 'barrr', server_id, 'CREATE'),
            res2['result'])
        self.assertEqual(0, res2['status_code'])
        self.assertEqual('', res2['stderr'])
        self.assertEqual('', res2['stdout'])

        res3 = self._stack_output(stack, 'res3')
        self.assertEqual(
            'The file %s contains %s for server %s during %s' % (
                '/tmp/ba', 'fo', server_id, 'CREATE'),
            res3['result'])
        self.assertEqual(0, res3['status_code'])
        self.assertEqual('', res3['stderr'])
        self.assertTrue(len(res1['stdout']) > 0)

        dep1_resource = self.client.resources.get(sid, 'dep1')
        dep1_id = dep1_resource.physical_resource_id
        dep1_dep = self.client.software_deployments.get(dep1_id)
        self.assertIsNotNone(dep1_dep.updated_time)
        self.assertNotEqual(dep1_dep.updated_time, dep1_dep.creation_time)

    def test_server_software_config(self):
        self.assign_keypair()
        self.launch_stack()
        self.check_stack()
