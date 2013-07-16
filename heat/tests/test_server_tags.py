# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from heat.engine import environment
from heat.tests.v1_1 import fakes
from heat.engine.resources import instance as instances
from heat.common import template_format
from heat.engine import parser
from heat.engine import scheduler
from heat.openstack.common import uuidutils
from heat.tests.common import HeatTestCase
from heat.tests import utils
from heat.tests.utils import setup_dummy_db


instance_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "WordPress",
  "Parameters" : {
    "KeyName" : {
      "Description" : "KeyName",
      "Type" : "String",
      "Default" : "test"
    }
  },
  "Resources" : {
    "WebServer": {
      "Type": "AWS::EC2::Instance",
      "Properties": {
        "ImageId"      : "CentOS 5.2",
        "InstanceType" : "256 MB Server",
        "KeyName"      : "test",
        "UserData"     : "wordpress"
      }
    }
  }
}
'''


class ServerTagsTest(HeatTestCase):
    def setUp(self):
        super(ServerTagsTest, self).setUp()
        self.fc = fakes.FakeClient()
        setup_dummy_db()

    def _setup_test_instance(self, intags=None, nova_tags=None):
        stack_name = 'tag_test'
        t = template_format.parse(instance_template)
        template = parser.Template(t)
        stack = parser.Stack(None, stack_name, template,
                             environment.Environment({'KeyName': 'test'}),
                             stack_id=uuidutils.generate_uuid())

        t['Resources']['WebServer']['Properties']['Tags'] = intags
        instance = instances.Instance(stack_name,
                                      t['Resources']['WebServer'], stack)

        self.m.StubOutWithMock(instance, 'nova')
        instance.nova().MultipleTimes().AndReturn(self.fc)

        instance.t = instance.stack.resolve_runtime_data(instance.t)

        # need to resolve the template functions
        server_userdata = instance._build_userdata(
            instance.t['Properties']['UserData'])
        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=nova_tags, nics=None, availability_zone=None).AndReturn(
                self.fc.servers.list()[1])

        return instance

    def test_instance_tags(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)

        instance = self._setup_test_instance(intags=tags, nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()
