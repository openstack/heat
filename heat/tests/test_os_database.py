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

from troveclient.openstack.common.apiclient import exceptions as troveexc
import uuid

import six

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import nova
from heat.engine.clients.os import trove
from heat.engine import parser
from heat.engine.resources import os_database
from heat.engine import scheduler
from heat.tests.common import HeatTestCase
from heat.tests import utils


db_template = '''
{
  "AWSTemplateFormatVersion" : "2010-09-09",
  "Description" : "MySQL instance running on openstack DBaaS cloud",
  "Resources" : {
    "MySqlCloudDB": {
      "Type": "OS::Trove::Instance",
      "Properties" : {
        "name" : "test",
        "flavor" : "1GB",
        "size" : 30,
        "users" : [{"name": "testuser", "password": "pass", "databases":
        ["validdb"]}],
        "databases" : [{"name": "validdb"}],
        "datastore_type": "SomeDStype",
        "datastore_version": "MariaDB-5.5"
      }
    }
  }

}
'''

db_template_with_nics = '''
heat_template_version: 2013-05-23
description: MySQL instance running on openstack DBaaS cloud
resources:
  MySqlCloudDB:
    type: OS::Trove::Instance
    properties:
      name: test
      flavor: 1GB
      size: 30
      networks:
        - port: someportname
          fixed_ip: 1.2.3.4
'''


class FakeDBInstance(object):
    def __init__(self):
        self.id = 12345
        self.hostname = "testhost"
        self.links = [
            {"href": "https://adga23dd432a.rackspacecloud.com/132345245",
             "rel": "self"}]
        self.resource_id = 12345
        self.status = 'ACTIVE'

    def get(self):
        pass

    def delete(self):
        pass


class FakeFlavor(object):
    def __init__(self, id, name):
        self.id = id
        self.name = name


class FakeVersion(object):
    def __init__(self, name="MariaDB-5.5"):
        self.name = name


class OSDBInstanceTest(HeatTestCase):
    def setUp(self):
        super(OSDBInstanceTest, self).setUp()
        self.stub_keystoneclient()
        self.fc = self.m.CreateMockAnything()
        self.nova = self.m.CreateMockAnything()
        self.m.StubOutWithMock(trove.TroveClientPlugin, '_create')

    def _setup_test_clouddbinstance(self, name, t):
        stack_name = '%s_stack' % name
        template = parser.Template(t)
        stack = parser.Stack(utils.dummy_context(),
                             stack_name,
                             template,
                             stack_id=str(uuid.uuid4()))

        instance = os_database.OSDBInstance(
            '%s_name' % name,
            template.resource_definitions(stack)['MySqlCloudDB'],
            stack)
        return instance

    def _stubout_common_create(self):
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'flavors')
        self.m.StubOutWithMock(trove.TroveClientPlugin, 'get_flavor_id')
        trove.TroveClientPlugin.get_flavor_id('1GB').AndReturn(1)
        self.m.StubOutWithMock(self.fc, 'instances')
        self.m.StubOutWithMock(self.fc.instances, 'create')

    def _stubout_create(self, instance, fake_dbinstance):
        self._stubout_common_create()
        users = [{"name": "testuser", "password": "pass", "host": "%",
                  "databases": [{"name": "validdb"}]}]
        databases = [{"collate": "utf8_general_ci",
                      "character_set": "utf8",
                      "name": "validdb"}]
        self.fc.instances.create('test', 1, volume={'size': 30},
                                 databases=databases,
                                 users=users,
                                 restorePoint=None,
                                 availability_zone=None,
                                 datastore="SomeDStype",
                                 datastore_version="MariaDB-5.5",
                                 nics=[]
                                 ).AndReturn(fake_dbinstance)
        self.m.ReplayAll()

    def _stubout_validate(self, instance, neutron=None):
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'datastore_versions')
        self.m.StubOutWithMock(self.fc.datastore_versions, 'list')
        self.fc.datastore_versions.list(instance.properties['datastore_type']
                                        ).AndReturn([FakeVersion()])
        if neutron is not None:
            self.m.StubOutWithMock(instance, 'is_using_neutron')
            instance.is_using_neutron().AndReturn(bool(neutron))
        self.m.ReplayAll()

    def test_osdatabase_create(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_create', t)
        self._stubout_create(instance, fake_dbinstance)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_osdatabase_restore_point(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['restore_point'] = "1234"
        instance = self._setup_test_clouddbinstance('dbinstance_create', t)

        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'flavors')
        self.m.StubOutWithMock(self.fc.flavors, "list")
        self.fc.flavors.list().AndReturn([FakeFlavor(1, '1GB'),
                                          FakeFlavor(2, '2GB')])
        self.m.StubOutWithMock(self.fc, 'instances')
        self.m.StubOutWithMock(self.fc.instances, 'create')
        users = [{"name": "testuser", "password": "pass", "host": "%",
                  "databases": [{"name": "validdb"}]}]
        databases = [{"collate": "utf8_general_ci",
                      "character_set": "utf8",
                      "name": "validdb"}]
        self.fc.instances.create('test', 1, volume={'size': 30},
                                 databases=databases,
                                 users=users,
                                 restorePoint={"backupRef": "1234"},
                                 availability_zone=None,
                                 datastore="SomeDStype",
                                 datastore_version="MariaDB-5.5",
                                 nics=[]
                                 ).AndReturn(fake_dbinstance)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_osdatabase_create_overlimit(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_create', t)

        self._stubout_create(instance, fake_dbinstance)

        # Simulate an OverLimit exception
        self.m.StubOutWithMock(fake_dbinstance, 'get')
        fake_dbinstance.get().AndRaise(
            troveexc.RequestEntityTooLarge)

        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_osdatabase_create_fails(self):
        fake_dbinstance = FakeDBInstance()
        fake_dbinstance.status = 'ERROR'
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_create', t)
        self._stubout_create(instance, fake_dbinstance)
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(instance.create))
        self.m.VerifyAll()

    def test_osdatabase_delete(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_del', t)
        self._stubout_create(instance, fake_dbinstance)
        scheduler.TaskRunner(instance.create)()
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndReturn(fake_dbinstance)
        self.m.StubOutWithMock(fake_dbinstance, 'delete')
        fake_dbinstance.delete().AndReturn(None)
        self.m.StubOutWithMock(fake_dbinstance, 'get')
        fake_dbinstance.get().AndReturn(None)
        fake_dbinstance.get().AndRaise(troveexc.NotFound(404))

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.delete)()
        self.m.VerifyAll()

    def test_osdatabase_delete_overlimit(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_del', t)
        self._stubout_create(instance, fake_dbinstance)
        scheduler.TaskRunner(instance.create)()
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndReturn(fake_dbinstance)
        self.m.StubOutWithMock(fake_dbinstance, 'delete')
        fake_dbinstance.delete().AndReturn(None)

        # Simulate an OverLimit exception
        self.m.StubOutWithMock(fake_dbinstance, 'get')
        fake_dbinstance.get().AndRaise(
            troveexc.RequestEntityTooLarge)
        fake_dbinstance.get().AndReturn(None)
        fake_dbinstance.get().AndRaise(troveexc.NotFound(404))

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.delete)()
        self.m.VerifyAll()

    def test_osdatabase_delete_resource_none(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_del', t)
        self._stubout_create(instance, fake_dbinstance)
        scheduler.TaskRunner(instance.create)()
        instance.resource_id = None

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.delete)()
        self.assertIsNone(instance.resource_id)
        self.m.VerifyAll()

    def test_osdatabase_resource_not_found(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_del', t)
        self._stubout_create(instance, fake_dbinstance)
        scheduler.TaskRunner(instance.create)()
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndRaise(
            troveexc.NotFound(404))

        self.m.ReplayAll()
        scheduler.TaskRunner(instance.delete)()
        self.m.VerifyAll()

    def test_osdatabase_invalid_attribute(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance("db_invalid_attrib", t)
        attrib = instance._resolve_attribute("invalid_attrib")
        self.assertIsNone(attrib)
        self.m.VerifyAll()

    def test_osdatabase_get_hostname(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        instance.resource_id = 12345
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'instances')
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndReturn(fake_dbinstance)
        self.m.ReplayAll()
        attrib = instance._resolve_attribute('hostname')
        self.assertEqual(fake_dbinstance.hostname, attrib)
        self.m.VerifyAll()

    def test_osdatabase_get_href(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        instance.resource_id = 12345
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'instances')
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndReturn(fake_dbinstance)
        self.m.ReplayAll()
        attrib = instance._resolve_attribute('href')
        self.assertEqual(fake_dbinstance.links[0]['href'], attrib)
        self.m.VerifyAll()

    def test_osdatabase_get_href_links_none(self):
        fake_dbinstance = FakeDBInstance()
        fake_dbinstance.links = None
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        instance.resource_id = 12345
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'instances')
        self.m.StubOutWithMock(self.fc.instances, 'get')
        self.fc.instances.get(12345).AndReturn(fake_dbinstance)
        self.m.ReplayAll()
        attrib = instance._resolve_attribute('href')
        self.assertIsNone(attrib)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_success(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)
        ret = instance.validate()
        self.assertIsNone(ret)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_invaliddb(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = [
            {"name": "onedb"}]
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser",
             "password": "pass",
             "databases": ["invaliddb"]}]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertRaises(exception.StackValidationFailed, instance.validate)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_users_none(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['users'] = []
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)
        ret = instance.validate()
        self.assertIsNone(ret)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_databases_none(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = []
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser",
             "password": "pass",
             "databases": ["invaliddb"]}]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertRaises(exception.StackValidationFailed, instance.validate)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_user_no_db(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = [
            {"name": "validdb"}]
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser", "password": "pass", "databases": []}]

        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self.assertRaises(exception.StackValidationFailed, instance.validate)
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_no_datastore_yes_version(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_type')
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        exp_msg = "Not allowed - datastore_version without datastore_type."
        self.assertEqual(exp_msg, six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_no_dsversion(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_version')
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)

        self.assertIsNone(instance.validate())
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_wrong_dsversion(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_version'] = 'SomeVersion'
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance)

        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        expected_msg = ("Datastore version SomeVersion for datastore type "
                        "mysql is not valid. "
                        "Allowed versions are MariaDB-5.5.")
        self.assertEqual(expected_msg, six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_implicit_version_fail(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_version')
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        trove.TroveClientPlugin._create().AndReturn(self.fc)
        self.m.StubOutWithMock(self.fc, 'datastore_versions')
        self.m.StubOutWithMock(self.fc.datastore_versions, 'list')
        self.fc.datastore_versions.list(
            instance.properties['datastore_type']
        ).AndReturn([FakeVersion(), FakeVersion('MariaDB-5.0')])
        self.m.ReplayAll()

        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        expected_msg = ("Multiple active datastore versions exist for "
                        "datastore type mysql. "
                        "Explicit datastore version must be provided. "
                        "Allowed versions are MariaDB-5.5, MariaDB-5.0.")
        self.assertEqual(expected_msg, six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_net_with_port_fail(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "port": "someportuuid",
                "network": "somenetuuid"
            }]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=True)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Either network or port must be provided.',
                         six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_no_net_no_port_fail(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "fixed_ip": "1.2.3.4"
            }]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=True)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Either network or port must be provided.',
                         six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_prop_validation_nic_port_on_novanet_fails(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "port": "someportuuid",
            }]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=False)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Can not use port property on Nova-network.',
                         six.text_type(ex))
        self.m.VerifyAll()

    def test_osdatabase_create_with_port(self):
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template_with_nics)
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_common_create()
        self.m.StubOutWithMock(neutron.NeutronClientPlugin,
                               'find_neutron_resource')
        neutron.NeutronClientPlugin.find_neutron_resource(
            instance.properties, 'port', 'port').AndReturn('someportid')

        self.fc.instances.create('test', 1, volume={'size': 30},
                                 databases=[],
                                 users=[],
                                 restorePoint=None,
                                 availability_zone=None,
                                 datastore=None,
                                 datastore_version=None,
                                 nics=[{'port-id': 'someportid',
                                        'v4-fixed-ip': '1.2.3.4'}]
                                 ).AndReturn(fake_dbinstance)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_osdatabase_create_with_net_id(self):
        net_id = '034aa4d5-0f36-4127-8481-5caa5bfc9403'
        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template_with_nics)
        t['resources']['MySqlCloudDB']['properties']['networks'] = [
            {'network': net_id}]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_common_create()
        self.fc.instances.create('test', 1, volume={'size': 30},
                                 databases=[],
                                 users=[],
                                 restorePoint=None,
                                 availability_zone=None,
                                 datastore=None,
                                 datastore_version=None,
                                 nics=[{'net-id': net_id}]
                                 ).AndReturn(fake_dbinstance)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()

    def test_osdatabase_create_with_net_name(self):

        class FakeNet(object):
            id = 'somenetid'

        fake_dbinstance = FakeDBInstance()
        t = template_format.parse(db_template_with_nics)
        t['resources']['MySqlCloudDB']['properties']['networks'] = [
            {'network': 'somenetname'}]
        instance = self._setup_test_clouddbinstance('dbinstance_test', t)
        self._stubout_common_create()
        self.m.StubOutWithMock(nova.NovaClientPlugin, '_create')
        nova.NovaClientPlugin._create().AndReturn(self.nova)
        self.m.StubOutWithMock(self.nova, 'networks')
        self.m.StubOutWithMock(self.nova.networks, 'find')
        self.nova.networks.find(label='somenetname').AndReturn(FakeNet())

        self.fc.instances.create('test', 1, volume={'size': 30},
                                 databases=[],
                                 users=[],
                                 restorePoint=None,
                                 availability_zone=None,
                                 datastore=None,
                                 datastore_version=None,
                                 nics=[{'net-id': 'somenetid'}]
                                 ).AndReturn(fake_dbinstance)
        self.m.ReplayAll()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.m.VerifyAll()
