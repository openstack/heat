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
from heat.engine import environment
from heat.engine import parser
from heat.engine import resource
from heat.engine import scheduler
from heat.openstack.common import log as logging
from heat.tests import common
from heat.tests import utils

from ..resources import cloud_dns  # noqa

logger = logging.getLogger(__name__)

domain_only_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "Dns instance running on Rackspace cloud",
  "Parameters" : {
    "UnittestDomain" : {
      "Description" : "Domain for unit tests",
      "Type" : "String",
      "Default" : 'dnsheatunittest.com'
    },
    "dnsttl" : {
      "Description" : "TTL for the domain",
      "Type" : "Number",
      "MinValue" : '301',
      "Default" : '301'
    },
    "name": {
      "Description" : "The cloud dns instance name",
      "Type": "String",
      "Default": "CloudDNS"
    }
  },
  "Resources" : {
    "domain" : {
      "Type": "Rackspace::Cloud::DNS",
      "Properties" : {
        "name" : "dnsheatunittest.com",
        "emailAddress" : "admin@dnsheatunittest.com",
        "ttl" : 3600,
        "comment" : "Testing Cloud DNS integration with Heat"
      }
    }
  }
}
'''


class FakeDnsInstance(object):
    def __init__(self):
        self.id = 4
        self.resource_id = 4

    def get(self):
        pass

    def delete(self):
        pass


class RackspaceDnsTest(common.HeatTestCase):

    def setUp(self):
        super(RackspaceDnsTest, self).setUp()
        utils.setup_dummy_db()
        # Test environment may not have pyrax client library installed and if
        # pyrax is not installed resource class would not be registered.
        # So register resource provider class explicitly for unit testing.
        resource._register_class("Rackspace::Cloud::DNS", cloud_dns.CloudDns)
        self.create_domain_only_args = {
            "name": 'dnsheatunittest.com',
            "emailAddress": 'admin@dnsheatunittest.com',
            "ttl": 3600,
            "comment": 'Testing Cloud DNS integration with Heat',
            "records": None
        }
        self.update_domain_only_args = {
            "emailAddress": 'updatedEmail@example.com',
            "ttl": 5555,
            "comment": 'updated comment'
        }

    def _setup_test_cloud_dns_instance(self, name, parsed_t):
        stack_name = '%s_stack' % name
        t = parsed_t
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(),
                             stack_name,
                             template,
                             environment.Environment({'name': 'test'}),
                             stack_id=str(uuid.uuid4()))

        instance = cloud_dns.CloudDns(
            '%s_name' % name,
            t['Resources']['domain'],
            stack)
        instance.t = instance.stack.resolve_runtime_data(instance.t)
        return instance

    def _stubout_create(self, instance, fake_dnsinstance, **create_args):
        mock_client = self.m.CreateMockAnything()
        self.m.StubOutWithMock(instance, 'cloud_dns')
        instance.cloud_dns().AndReturn(mock_client)
        self.m.StubOutWithMock(mock_client, "create")
        mock_client.create(**create_args).AndReturn(fake_dnsinstance)
        self.m.ReplayAll()

    def _stubout_update(
            self,
            instance,
            fake_dnsinstance,
            updateRecords=None,
            **update_args):
        mock_client = self.m.CreateMockAnything()
        self.m.StubOutWithMock(instance, 'cloud_dns')
        instance.cloud_dns().AndReturn(mock_client)
        self.m.StubOutWithMock(mock_client, "get")
        mock_domain = self.m.CreateMockAnything()
        mock_client.get(fake_dnsinstance.resource_id).AndReturn(mock_domain)
        self.m.StubOutWithMock(mock_domain, "update")
        mock_domain.update(**update_args).AndReturn(fake_dnsinstance)
        if updateRecords:
            fake_records = list()
            mock_domain.list_records().AndReturn(fake_records)
            mock_domain.add_records([{
                'type': 'A',
                'name': 'ftp.example.com',
                'data': '192.0.2.8',
                'ttl': 3600}])
        self.m.ReplayAll()

    def _get_create_args_with_comments(self, record):
        record_with_comment = [dict(record[0])]
        record_with_comment[0]["comment"] = None
        create_record_args = dict()
        create_record_args['records'] = record_with_comment
        create_args = dict(
            self.create_domain_only_args.items() + create_record_args.items())
        return create_args

    def test_create_domain_only(self):
        """
        Test domain create only without any records.
        """
        fake_dns_instance = FakeDnsInstance()
        t = template_format.parse(domain_only_template)
        instance = self._setup_test_cloud_dns_instance('dnsinstance_create', t)
        create_args = self.create_domain_only_args
        self._stubout_create(instance, fake_dns_instance, **create_args)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_create_domain_with_a_record(self):
        """
        Test domain create with an A record.  This should not have a
        priority field.
        """
        fake_dns_instance = FakeDnsInstance()
        t = template_format.parse(domain_only_template)
        a_record = [{
            "type": "A",
            "name": "ftp.example.com",
            "data": "192.0.2.8",
            "ttl": 3600
        }]
        t['Resources']['domain']['Properties']['records'] = a_record
        instance = self._setup_test_cloud_dns_instance('dnsinstance_create', t)
        create_args = self._get_create_args_with_comments(a_record)
        self._stubout_create(instance, fake_dns_instance, **create_args)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_create_domain_with_mx_record(self):
        """
        Test domain create with an MX record.  This should have a
        priority field.
        """
        fake_dns_instance = FakeDnsInstance()
        t = template_format.parse(domain_only_template)
        mx_record = [{
            "type": "MX",
            "name": "example.com",
            "data": "mail.example.com",
            "priority": 5,
            "ttl": 3600
        }]
        t['Resources']['domain']['Properties']['records'] = mx_record
        instance = self._setup_test_cloud_dns_instance('dnsinstance_create', t)
        create_args = self._get_create_args_with_comments(mx_record)
        self._stubout_create(instance, fake_dns_instance, **create_args)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_update(self, updateRecords=None):
        """
        Helper function for testing domain updates.
        """
        fake_dns_instance = FakeDnsInstance()
        t = template_format.parse(domain_only_template)
        instance = self._setup_test_cloud_dns_instance('dnsinstance_update', t)
        instance.resource_id = 4
        update_args = self.update_domain_only_args
        self._stubout_update(
            instance,
            fake_dns_instance,
            updateRecords,
            **update_args)

        ut = copy.deepcopy(instance.parsed_template())
        ut['Properties']['emailAddress'] = 'updatedEmail@example.com'
        ut['Properties']['ttl'] = 5555
        ut['Properties']['comment'] = 'updated comment'
        if updateRecords:
                ut['Properties']['records'] = updateRecords

        scheduler.TaskRunner(instance.update, ut)()
        self.assertEqual((instance.UPDATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_update_domain_only(self):
        """
        Test domain update without any records.
        """
        self.test_update()

    def test_update_domain_with_a_record(self):
        """
        Test domain update with an A record.
        """
        a_record = [{'type': 'A',
                     'name': 'ftp.example.com',
                     'data': '192.0.2.8',
                     'ttl': 3600}]
        self.test_update(updateRecords=a_record)
