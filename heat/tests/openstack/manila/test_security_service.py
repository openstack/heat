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

import mock
import six

from heat.common import exception
from heat.common import template_format
from heat.engine import resource
from heat.engine.resources.openstack.manila import security_service
from heat.engine import scheduler
from heat.engine import template
from heat.tests import common
from heat.tests import utils

stack_template = '''
heat_template_version: 2013-05-23

resources:
  security_service:
    type: OS::Manila::SecurityService
    properties:
      name: my_security_service
      domain: test-domain
      dns_ip: 1.1.1.1
      type: ldap
      server: test-server
      user: test-user
      password: test-password
'''

stack_template_update = '''
heat_template_version: 2013-05-23

resources:
  security_service:
    type: OS::Manila::SecurityService
    properties:
      name: fake_security_service
      domain: fake-domain
      dns_ip: 1.1.1.1
      type: ldap
      server: fake-server
'''

stack_template_update_replace = '''
heat_template_version: 2013-05-23

resources:
  security_service:
    type: OS::Manila::SecurityService
    properties:
      name: my_security_service
      domain: test-domain
      dns_ip: 1.1.1.1
      type: kerberos
      server: test-server
      user: test-user
      password: test-password
'''


class ManilaSecurityServiceTest(common.HeatTestCase):

    def setUp(self):
        super(ManilaSecurityServiceTest, self).setUp()

        t = template_format.parse(stack_template)
        self.stack = utils.parse_stack(t)
        resource_defns = self.stack.t.resource_definitions(self.stack)
        self.rsrc_defn = resource_defns['security_service']

        self.client = mock.Mock()
        self.patchobject(security_service.SecurityService, 'client',
                         return_value=self.client)

    def _create_resource(self, name, snippet, stack):
        ss = security_service.SecurityService(name, snippet, stack)
        value = mock.MagicMock(id='12345')
        self.client.security_services.create.return_value = value
        self.client.security_services.get.return_value = value
        scheduler.TaskRunner(ss.create)()
        args = self.client.security_services.create.call_args[1]
        self.assertEqual(self.rsrc_defn._properties, args)
        self.assertEqual('12345', ss.resource_id)
        return ss

    def test_create(self):
        ct = self._create_resource('security_service', self.rsrc_defn,
                                   self.stack)
        expected_state = (ct.CREATE, ct.COMPLETE)
        self.assertEqual(expected_state, ct.state)
        self.assertEqual('security_services', ct.entity)

    def test_create_failed(self):
        ss = security_service.SecurityService('security_service',
                                              self.rsrc_defn, self.stack)
        self.client.security_services.create.side_effect = Exception('error')

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(ss.create))
        expected_state = (ss.CREATE, ss.FAILED)
        self.assertEqual(expected_state, ss.state)
        self.assertIn('Exception: resources.security_service: error',
                      six.text_type(exc))

    def test_update(self):
        ss = self._create_resource('security_service', self.rsrc_defn,
                                   self.stack)
        t = template_format.parse(stack_template_update)
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_ss = rsrc_defns['security_service']
        scheduler.TaskRunner(ss.update, new_ss)()
        args = {
            'domain': 'fake-domain',
            'password': None,
            'user': None,
            'server': 'fake-server',
            'name': 'fake_security_service'
        }
        self.client.security_services.update.assert_called_once_with(
            '12345', **args)
        self.assertEqual((ss.UPDATE, ss.COMPLETE), ss.state)

    def test_update_replace(self):
        ss = self._create_resource('security_service', self.rsrc_defn,
                                   self.stack)
        t = template_format.parse(stack_template_update_replace)
        rsrc_defns = template.Template(t).resource_definitions(self.stack)
        new_ss = rsrc_defns['security_service']
        self.assertEqual(0, self.client.security_services.update.call_count)
        err = self.assertRaises(resource.UpdateReplace,
                                scheduler.TaskRunner(ss.update, new_ss))
        msg = 'The Resource security_service requires replacement.'
        self.assertEqual(msg, six.text_type(err))
