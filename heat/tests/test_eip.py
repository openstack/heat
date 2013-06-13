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


from heat.common import exception
from heat.common import template_format
from heat.engine.resources import eip
from heat.engine import resource
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests.v1_1 import fakes
from heat.tests.utils import setup_dummy_db
from heat.tests.utils import parse_stack


eip_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "IPAddress" : {
      "Type" : "AWS::EC2::EIP",
      "Properties" : {
        "InstanceId" : { "Ref" : "WebServer" }
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
    }
  }
}
'''

eip_template_ipassoc = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "EIP Test",
  "Parameters" : {},
  "Resources" : {
    "IPAddress" : {
      "Type" : "AWS::EC2::EIP"
    },
    "IPAssoc" : {
      "Type" : "AWS::EC2::EIPAssociation",
      "Properties" : {
        "InstanceId" : { "Ref" : "WebServer" },
        "EIP" : { "Ref" : "IPAddress" }
      }
    },
    "WebServer": {
      "Type": "AWS::EC2::Instance",
    }
  }
}
'''


class EIPTest(HeatTestCase):
    def setUp(self):
        super(EIPTest, self).setUp()
        self.fc = fakes.FakeClient()
        self.m.StubOutWithMock(eip.ElasticIp, 'nova')
        self.m.StubOutWithMock(eip.ElasticIpAssociation, 'nova')
        self.m.StubOutWithMock(self.fc.servers, 'get')
        setup_dummy_db()

    def create_eip(self, t, stack, resource_name):
        rsrc = eip.ElasticIp(resource_name,
                             t['Resources'][resource_name],
                             stack)
        self.assertEqual(None, rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def create_association(self, t, stack, resource_name):
        rsrc = eip.ElasticIpAssociation(resource_name,
                                        t['Resources'][resource_name],
                                        stack)
        self.assertEqual(None, rsrc.validate())
        scheduler.TaskRunner(rsrc.create)()
        self.assertEqual((rsrc.CREATE, rsrc.COMPLETE), rsrc.state)
        return rsrc

    def test_eip(self):

        eip.ElasticIp.nova().MultipleTimes().AndReturn(self.fc)
        self.fc.servers.get('WebServer').AndReturn(self.fc.servers.list()[0])
        self.fc.servers.get('WebServer')

        self.m.ReplayAll()

        t = template_format.parse(eip_template)
        stack = parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')

        try:
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())
            rsrc.ipaddress = None
            self.assertEqual('11.0.0.1', rsrc.FnGetRefId())

            self.assertEqual('1', rsrc.FnGetAtt('AllocationId'))

            self.assertRaises(resource.UpdateReplace,
                              rsrc.handle_update, {}, {}, {})

            self.assertRaises(exception.InvalidTemplateAttribute,
                              rsrc.FnGetAtt, 'Foo')

        finally:
            rsrc.destroy()

        self.m.VerifyAll()

    def test_association(self):
        eip.ElasticIp.nova().AndReturn(self.fc)
        eip.ElasticIpAssociation.nova().AndReturn(self.fc)
        self.fc.servers.get('WebServer').AndReturn(self.fc.servers.list()[0])
        eip.ElasticIpAssociation.nova().AndReturn(self.fc)
        self.fc.servers.get('WebServer').AndReturn(self.fc.servers.list()[0])
        eip.ElasticIp.nova().AndReturn(self.fc)

        self.m.ReplayAll()

        t = template_format.parse(eip_template_ipassoc)
        stack = parse_stack(t)

        rsrc = self.create_eip(t, stack, 'IPAddress')
        association = self.create_association(t, stack, 'IPAssoc')

        # TODO(sbaker), figure out why this is an empty string
        #self.assertEqual('', association.FnGetRefId())

        association.delete()
        rsrc.delete()

        self.m.VerifyAll()
