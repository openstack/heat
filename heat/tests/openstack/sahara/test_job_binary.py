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
import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import sahara
from heat.engine.resources.openstack.sahara import job_binary
from heat.engine import scheduler
from heat.tests import common
from heat.tests import utils


job_binary_template = """
heat_template_version: 2015-10-15
resources:
  job-binary:
    type: OS::Sahara::JobBinary
    properties:
      name: my-jb
      url: swift://container/jar-example.jar
      credentials: {'user': 'admin','password': 'swordfish'}
"""


class SaharaJobBinaryTest(common.HeatTestCase):
    def setUp(self):
        super(SaharaJobBinaryTest, self).setUp()
        t = template_format.parse(job_binary_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['job-binary']
        self.client = mock.Mock()
        self.patchobject(job_binary.JobBinary, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        jb = job_binary.JobBinary(name, snippet, stack)
        value = mock.MagicMock(id='12345')
        self.client.job_binaries.create.return_value = value
        scheduler.TaskRunner(jb.create)()
        return jb

    def test_create(self):
        jb = self._create_resource('job-binary', self.rsrc_defn, self.stack)
        args = self.client.job_binaries.create.call_args[1]
        expected_args = {
            'name': 'my-jb',
            'description': '',
            'url': 'swift://container/jar-example.jar',
            'extra': {
                'user': 'admin',
                'password': 'swordfish'
            }
        }
        self.assertEqual(expected_args, args)
        self.assertEqual('12345', jb.resource_id)
        expected_state = (jb.CREATE, jb.COMPLETE)
        self.assertEqual(expected_state, jb.state)

    def test_update(self):
        jb = self._create_resource('job-binary', self.rsrc_defn,
                                   self.stack)
        props = self.stack.t.t['resources']['job-binary']['properties'].copy()
        props['url'] = 'internal-db://94b8821d-1ce7-4131-8364-a6c6d85ad57b'
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        scheduler.TaskRunner(jb.update, self.rsrc_defn)()
        data = {
            'name': 'my-jb',
            'description': '',
            'url': 'internal-db://94b8821d-1ce7-4131-8364-a6c6d85ad57b',
            'extra': {
                'user': 'admin',
                'password': 'swordfish'
            }
        }
        self.client.job_binaries.update.assert_called_once_with(
            '12345', data)
        self.assertEqual((jb.UPDATE, jb.COMPLETE), jb.state)

    def test_delete(self):
        jb = self._create_resource('job-binary', self.rsrc_defn, self.stack)
        scheduler.TaskRunner(jb.delete)()
        self.assertEqual((jb.DELETE, jb.COMPLETE), jb.state)
        self.client.job_binaries.delete.assert_called_once_with(
            jb.resource_id)

    def test_delete_not_found(self):
        jb = self._create_resource('job-binary', self.rsrc_defn, self.stack)
        self.client.job_binaries.delete.side_effect = (
            sahara.sahara_base.APIException(error_code=404))
        scheduler.TaskRunner(jb.delete)()
        self.assertEqual((jb.DELETE, jb.COMPLETE), jb.state)
        self.client.job_binaries.delete.assert_called_once_with(
            jb.resource_id)

    def test_show_attribute(self):
        jb = self._create_resource('job-binary', self.rsrc_defn, self.stack)
        value = mock.MagicMock()
        value.to_dict.return_value = {'jb': 'info'}
        self.client.job_binaries.get.return_value = value
        self.assertEqual({'jb': 'info'}, jb.FnGetAtt('show'))

    def test_validate_invalid_url(self):
        props = self.stack.t.t['resources']['job-binary']['properties'].copy()
        props['url'] = 'internal-db://38273f82'
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        jb = job_binary.JobBinary('job-binary', self.rsrc_defn, self.stack)
        ex = self.assertRaises(exception.StackValidationFailed, jb.validate)
        error_msg = ('resources.job-binary.properties: internal-db://38273f82 '
                     'is not a valid job location.')
        self.assertEqual(error_msg, six.text_type(ex))

    def test_validate_password_without_user(self):
        props = self.stack.t.t['resources']['job-binary']['properties'].copy()
        props['credentials'].pop('user')
        self.rsrc_defn = self.rsrc_defn.freeze(properties=props)
        jb = job_binary.JobBinary('job-binary', self.rsrc_defn, self.stack)
        ex = self.assertRaises(exception.StackValidationFailed, jb.validate)
        error_msg = ('Property error: resources.job-binary.properties.'
                     'credentials: Property user not assigned')
        self.assertEqual(error_msg, six.text_type(ex))
