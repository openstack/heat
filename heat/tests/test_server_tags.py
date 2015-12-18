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
import uuid

from heat.common import template_format
from heat.engine.clients.os import glance
from heat.engine.clients.os import nova
from heat.engine import environment
from heat.engine.resources.aws.ec2 import instance as instances
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.tests import common
from heat.tests.openstack.nova import fakes as fakes_nova
from heat.tests import utils

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


class ServerTagsTest(common.HeatTestCase):
    def setUp(self):
        super(ServerTagsTest, self).setUp()
        self.fc = fakes_nova.FakeClient()

    def _mock_get_image_id_success(self, imageId_input, imageId):
        self.m.StubOutWithMock(glance.GlanceClientPlugin,
                               'find_image_by_name_or_id')
        glance.GlanceClientPlugin.find_image_by_name_or_id(
            imageId_input).MultipleTimes().AndReturn(imageId)

    def _setup_test_instance(self, intags=None, nova_tags=None):
        stack_name = 'tag_test'
        t = template_format.parse(instance_template)
        template = tmpl.Template(t,
                                 env=environment.Environment(
                                     {'KeyName': 'test'}))
        self.stack = parser.Stack(utils.dummy_context(), stack_name, template,
                                  stack_id=str(uuid.uuid4()))

        t['Resources']['WebServer']['Properties']['Tags'] = intags
        resource_defns = template.resource_definitions(self.stack)
        instance = instances.Instance(stack_name,
                                      resource_defns['WebServer'], self.stack)

        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.fc)
        self._mock_get_image_id_success('CentOS 5.2', 1)
        # need to resolve the template functions
        metadata = instance.metadata_get()
        server_userdata = instance.client_plugin().build_userdata(
            metadata,
            instance.t['Properties']['UserData'],
            'ec2-user')
        self.m.StubOutWithMock(nova.NovaClientPlugin, 'build_userdata')
        nova.NovaClientPlugin.build_userdata(
            metadata,
            instance.t['Properties']['UserData'],
            'ec2-user').AndReturn(server_userdata)

        self.m.StubOutWithMock(self.fc.servers, 'create')
        self.fc.servers.create(
            image=1, flavor=1, key_name='test',
            name=utils.PhysName(stack_name, instance.name),
            security_groups=None,
            userdata=server_userdata, scheduler_hints=None,
            meta=nova_tags, nics=None, availability_zone=None,
            block_device_mapping=None).AndReturn(
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

    def test_instance_tags_updated(self):
        tags = [{'Key': 'Food', 'Value': 'yum'}]
        metadata = dict((tm['Key'], tm['Value']) for tm in tags)

        instance = self._setup_test_instance(intags=tags, nova_tags=metadata)
        self.m.ReplayAll()
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        # we are just using mock to verify that the tags get through to the
        # nova call.
        self.m.VerifyAll()
        self.m.UnsetStubs()

        new_tags = [{'Key': 'Food', 'Value': 'yuk'}]
        new_metadata = dict((tm['Key'], tm['Value']) for tm in new_tags)

        self.m.StubOutWithMock(self.fc.servers, 'set_meta')
        self.fc.servers.set_meta(self.fc.servers.list()[1],
                                 new_metadata).AndReturn(None)
        self.stub_ImageConstraint_validate()
        self.stub_KeypairConstraint_validate()
        self.stub_FlavorConstraint_validate()
        self.m.ReplayAll()
        update_template = copy.deepcopy(instance.t)
        update_template['Properties']['Tags'] = new_tags
        scheduler.TaskRunner(instance.update, update_template)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()
