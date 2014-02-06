
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

from heat.common import template_format
from heat.engine import clients
from heat.engine.resources import instance as instances
from heat.engine.resources import nova_utils
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.v1_1 import fakes


nokey_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "NoKey Test",
  "Parameters" : {},
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId" : "foo",
        "InstanceType"   : "m1.large",
        "UserData"       : "some data"
      }
    }
  }
}
'''


class nokeyTest(HeatTestCase):
    def setUp(self):
        super(nokeyTest, self).setUp()
        self.fc = fakes.FakeClient()
        utils.setup_dummy_db()

    def test_nokey_create(self):

        stack_name = 's_nokey'
        t = template_format.parse(nokey_template)
        stack = utils.parse_stack(t, stack_name=stack_name)

        t['Resources']['WebServer']['Properties']['ImageId'] = 'CentOS 5.2'
        t['Resources']['WebServer']['Properties']['InstanceType'] = \
            '256 MB Server'
        instance = instances.Instance('create_instance_name',
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)
        self.m.StubOutWithMock(clients.OpenStackClients, 'nova')
        clients.OpenStackClients.nova().MultipleTimes().AndReturn(self.fc)

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user')
        self.m.StubOutWithMock(nova_utils, 'build_userdata')
        nova_utils.build_userdata(
            instance,
            instance.t['Properties']['UserData'],
            'ec2-user').AndReturn(server_userdata)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name=None,
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=None, nics=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
