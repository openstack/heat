#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from heat.common import template_format
from heat.engine.clients.os import sahara
from heat.engine.resources.openstack.sahara import job
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


job_template = """
heat_template_version: newton
resources:
  job:
    type: OS::Sahara::Job
    properties:
      name: test_name_job
      type: MapReduce
      libs: [ fake-lib-id ]
      description: test_description
      is_public: True
      default_execution_data:
        cluster: fake-cluster-id
        input: fake-input-id
        output: fake-output-id
        is_public: True
        configs:
          mapred.map.class: org.apache.oozie.example.SampleMapper
          mapred.reduce.class: org.apache.oozie.example.SampleReducer
          mapreduce.framework.name: yarn
"""


class SaharaJobTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaJobTest, self).setUp()
        t = template_format.parse(job_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['job']
        self.client = mock.Mock()
        self.patchobject(job.SaharaJob, 'client', return_value=self.client)
        fake_execution = mock.Mock()
        fake_execution.job_id = 'fake-resource-id'
        fake_execution.id = 'fake-execution-id'
        fake_execution.to_dict.return_value = {'job_id': 'fake-resource-id',
                                               'id': 'fake-execution-id'}
        self.client.job_executions.find.return_value = [fake_execution]

    def _create_resource(self, name, snippet, stack, without_name=False):
        jb = job.SaharaJob(name, snippet, stack)
        if without_name:
            self.client.jobs.create = mock.Mock(return_value='fake_rsrc_id')
            jb.physical_resource_name = mock.Mock(
                return_value='fake_phys_name')
        value = mock.MagicMock(id='fake-resource-id')
        self.client.jobs.create.return_value = value
        mock_get_res = mock.Mock(return_value='some res id')
        mock_get_type = mock.Mock(return_value='MapReduce')
        jb.client_plugin().find_resource_by_name_or_id = mock_get_res
        jb.client_plugin().get_job_type = mock_get_type
        scheduler.TaskRunner(jb.create)()
        return jb

    def test_create(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        args = self.client.jobs.create.call_args[1]
        expected_args = {
            'name': 'test_name_job',
            'type': 'MapReduce',
            'libs': ['some res id'],
            'description': 'test_description',
            'is_public': True,
            'is_protected': False,
            'mains': []
        }
        self.assertEqual(expected_args, args)
        self.assertEqual('fake-resource-id', jb.resource_id)
        expected_state = (jb.CREATE, jb.COMPLETE)
        self.assertEqual(expected_state, jb.state)

    def test_create_without_name_passed(self):
        props = self.stack.t.t['resources']['job']['properties']
        del props['name']
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        jb = self._create_resource('job', self.rsrc_defn, self.stack, True)
        args = self.client.jobs.create.call_args[1]
        expected_args = {
            'name': 'fake_phys_name',
            'type': 'MapReduce',
            'libs': ['some res id'],
            'description': 'test_description',
            'is_public': True,
            'is_protected': False,
            'mains': []
        }
        self.assertEqual(expected_args, args)
        self.assertEqual('fake-resource-id', jb.resource_id)
        expected_state = (jb.CREATE, jb.COMPLETE)
        self.assertEqual(expected_state, jb.state)

    def test_delete(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(jb.delete)()
        self.assertEqual((jb.DELETE, jb.COMPLETE), jb.state)
        self.client.jobs.delete.assert_called_once_with(jb.resource_id)
        self.client.job_executions.delete.assert_called_once_with(
            'fake-execution-id')

    def test_delete_not_found(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        self.client.jobs.delete.side_effect = (
            sahara.sahara_base.APIException(error_code=404))
        scheduler.TaskRunner(jb.delete)()
        self.assertEqual((jb.DELETE, jb.COMPLETE), jb.state)
        self.client.jobs.delete.assert_called_once_with(jb.resource_id)
        self.client.job_executions.delete.assert_called_once_with(
            'fake-execution-id')

    def test_delete_job_executions_raises_error(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        self.client.job_executions.find.side_effect = [
            sahara.sahara_base.APIException(400)]
        self.assertRaises(sahara.sahara_base.APIException, jb.handle_delete)

    def test_update(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        props = self.stack.t.t['resources']['job']['properties'].copy()
        props['name'] = 'test_name_job_new'
        props['description'] = 'test_description_new'
        props['is_public'] = False
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(jb.update, self.rsrc_defn)()
        self.client.jobs.update.assert_called_once_with(
            'fake-resource-id', name='test_name_job_new',
            description='test_description_new', is_public=False)
        self.assertEqual((jb.UPDATE, jb.COMPLETE), jb.state)

    def test_handle_signal(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(jb.handle_signal, None)()
        expected_args = {
            'job_id': 'fake-resource-id',
            'cluster_id': 'some res id',
            'input_id': 'some res id',
            'output_id': 'some res id',
            'is_public': True,
            'is_protected': False,
            'interface': {},
            'configs': {
                'configs': {
                    'mapred.reduce.class':
                        'org.apache.oozie.example.SampleReducer',
                    'mapred.map.class':
                        'org.apache.oozie.example.SampleMapper',
                    'mapreduce.framework.name': 'yarn'},
                'args': [],
                'params': {}
            }
        }
        self.client.job_executions.create.assert_called_once_with(
            **expected_args)

    def test_attributes(self):
        jb = self._create_resource('job', self.rsrc_defn, self.stack)
        jb._get_ec2_signed_url = mock.Mock(return_value='fake-url')
        self.assertEqual('fake-execution-id',
                         jb.FnGetAtt('executions')[0]['id'])
        self.assertEqual('fake-url', jb.FnGetAtt('default_execution_url'))
