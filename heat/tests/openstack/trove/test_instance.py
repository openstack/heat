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

import uuid

import mock
from oslo_config import cfg
import six
from troveclient import exceptions as troveexc
from troveclient.v1 import users

from heat.common import exception
from heat.common import template_format
from heat.engine.clients.os import neutron
from heat.engine.clients.os import trove
from heat.engine import resource
from heat.engine.resources.openstack.trove import instance as dbinstance
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import stack as parser
from heat.engine import template as tmpl
from heat.tests import common
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

db_template_with_replication = '''
heat_template_version: 2013-05-23
description: MySQL instance running on openstack DBaaS cloud
resources:
  MySqlCloudDB:
    type: OS::Trove::Instance
    properties:
      name: test
      flavor: 1GB
      size: 30
      replica_of: 0e642916-dd64-43b3-933f-ff34fff69a7f
      replica_count: 2
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

    def delete(self):
        pass

    def to_dict(self):
        pass


class FakeFlavor(object):
    def __init__(self, id, name):
        self.id = id
        self.name = name


class FakeVersion(object):
    def __init__(self, name="MariaDB-5.5"):
        self.name = name


class InstanceTest(common.HeatTestCase):

    def setUp(self):
        super(InstanceTest, self).setUp()
        self.fc = mock.MagicMock()
        self.nova = mock.Mock()
        self.client = mock.Mock()
        self.patchobject(trove.TroveClientPlugin, '_create',
                         return_value=self.client)
        self.stub_TroveFlavorConstraint_validate()
        self.patchobject(resource.Resource, 'is_using_neutron',
                         return_value=True)
        self.flavor_resolve = self.patchobject(trove.TroveClientPlugin,
                                               'find_flavor_by_name_or_id',
                                               return_value='1')
        self.fake_instance = FakeDBInstance()
        self.client.instances.create.return_value = self.fake_instance
        self.client.instances.get.return_value = self.fake_instance

    def _setup_test_instance(self, name, t, rsrc_name='MySqlCloudDB'):
        stack_name = '%s_stack' % name
        template = tmpl.Template(t)
        self.stack = parser.Stack(utils.dummy_context(),
                                  stack_name,
                                  template,
                                  stack_id=str(uuid.uuid4()))
        rsrc = self.stack[rsrc_name]
        rsrc.resource_id = '12345'
        return rsrc

    def _stubout_validate(self, instance, neutron=None,
                          mock_net_constraint=False,
                          with_port=True):
        if mock_net_constraint:
            self.stub_NetworkConstraint_validate()

        self.client.datastore_versions.list.return_value = [FakeVersion()]

        if neutron is not None:
            instance.is_using_neutron = mock.Mock(return_value=bool(neutron))
            if with_port:
                self.stub_PortConstraint_validate()

    def test_instance_create(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_create', t)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.assertEqual('instances', instance.entity)

    def test_create_failed(self):
        t = template_format.parse(db_template)
        osdb_res = self._setup_test_instance('dbinstance_create', t)

        trove_mock = mock.Mock()
        self.patchobject(osdb_res, 'client', return_value=trove_mock)

        # test for bad statuses
        mock_input = mock.Mock()
        mock_input.status = 'ERROR'
        trove_mock.instances.get.return_value = mock_input
        error_string = ('Went to status ERROR due to "The last operation for '
                        'the database instance failed due to an error."')
        exc = self.assertRaises(exception.ResourceInError,
                                osdb_res.check_create_complete,
                                mock_input)
        self.assertIn(error_string, six.text_type(exc))

        mock_input = mock.Mock()
        mock_input.status = 'FAILED'
        trove_mock.instances.get.return_value = mock_input
        error_string = ('Went to status FAILED due to "The database instance '
                        'was created, but heat failed to set up the '
                        'datastore. If a database instance is in the FAILED '
                        'state, it should be deleted and a new one should '
                        'be created."')
        exc = self.assertRaises(exception.ResourceInError,
                                osdb_res.check_create_complete,
                                mock_input)
        self.assertIn(error_string, six.text_type(exc))

        # test if error string is not defined

        osdb_res.TROVE_STATUS_REASON = {}
        mock_input = mock.Mock()
        mock_input.status = 'ERROR'
        error_string = ('Went to status ERROR due to "Unknown"')
        trove_mock.instances.get.return_value = mock_input
        exc = self.assertRaises(exception.ResourceInError,
                                osdb_res.check_create_complete,
                                mock_input)
        self.assertIn(error_string, six.text_type(exc))

    def _create_failed_bad_status(self, status, error_message):
        t = template_format.parse(db_template)
        bad_instance = mock.Mock()
        bad_instance.status = status
        self.client.instances.get.return_value = bad_instance
        instance = self._setup_test_instance('test_bad_statuses', t)
        ex = self.assertRaises(exception.ResourceInError,
                               instance.check_create_complete,
                               self.fake_instance.id)
        self.assertIn(error_message, six.text_type(ex))

    def test_create_failed_status_error(self):
        self._create_failed_bad_status(
            'ERROR', 'Went to status ERROR due to "The last operation for '
                     'the database instance failed due to an error."')

    def test_create_failed_status_failed(self):
        self._create_failed_bad_status(
            'FAILED', 'Went to status FAILED due to "The database instance '
                      'was created, but heat failed to set up the datastore. '
                      'If a database instance is in the FAILED state, it '
                      'should be deleted and a new one should be created."')

    def test_instance_restore_point(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['restore_point'] = "1234"
        instance = self._setup_test_instance('dbinstance_create', t)

        self.client.flavors.get.side_effect = [troveexc.NotFound()]
        self.client.flavors.find.return_value = FakeFlavor(1, '1GB')

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)

        users = [{"name": "testuser", "password": "pass", "host": "%",
                  "databases": [{"name": "validdb"}]}]
        databases = [{"collate": "utf8_general_ci",
                      "character_set": "utf8",
                      "name": "validdb"}]
        self.client.instances.create.assert_called_once_with(
            'test', '1', volume={'size': 30}, databases=databases, users=users,
            restorePoint={"backupRef": "1234"}, availability_zone=None,
            datastore="SomeDStype", datastore_version="MariaDB-5.5", nics=[],
            replica_of=None, replica_count=None)

    def test_instance_create_overlimit(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_create', t)

        # Simulate an OverLimit exception
        self.client.instances.get.side_effect = [
            troveexc.RequestEntityTooLarge(), self.fake_instance]

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)

    def test_instance_create_fails(self):
        cfg.CONF.set_override('action_retry_limit', 0)
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_create', t)
        self.fake_instance.status = 'ERROR'
        self.assertRaises(exception.ResourceFailure,
                          scheduler.TaskRunner(instance.create))
        # return previous status
        self.fake_instance.status = 'ACTIVE'

    def _get_db_instance(self):
        t = template_format.parse(db_template)
        res = self._setup_test_instance('trove_check', t)
        res.state_set(res.CREATE, res.COMPLETE)
        res.flavor = 'Foo Flavor'
        res.volume = 'Foo Volume'
        res.datastore_type = 'Foo Type'
        res.datastore_version = 'Foo Version'
        return res

    def test_instance_check(self):
        res = self._get_db_instance()
        scheduler.TaskRunner(res.check)()
        self.assertEqual((res.CHECK, res.COMPLETE), res.state)

    def test_instance_check_not_active(self):
        res = self._get_db_instance()
        self.fake_instance.status = 'FOOBAR'

        exc = self.assertRaises(exception.ResourceFailure,
                                scheduler.TaskRunner(res.check))
        self.assertIn('FOOBAR', six.text_type(exc))
        self.assertEqual((res.CHECK, res.FAILED), res.state)
        # return previous status
        self.fake_instance.status = 'ACTIVE'

    def test_instance_delete(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_del', t)
        self.client.instances.get.side_effect = [self.fake_instance,
                                                 troveexc.NotFound(404)]

        scheduler.TaskRunner(instance.create)()
        scheduler.TaskRunner(instance.delete)()

    def test_instance_delete_overlimit(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_del', t)

        # Simulate an OverLimit exception
        self.client.instances.get.side_effect = [
            troveexc.RequestEntityTooLarge(), self.fake_instance,
            troveexc.NotFound(404)]

        scheduler.TaskRunner(instance.create)()
        scheduler.TaskRunner(instance.delete)()

    def test_instance_delete_resource_none(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_del', t)
        scheduler.TaskRunner(instance.create)()
        instance.resource_id = None
        scheduler.TaskRunner(instance.delete)()
        self.assertIsNone(instance.resource_id)

    def test_instance_resource_not_found(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_del', t)
        self.client.instances.get.side_effect = [self.fake_instance,
                                                 troveexc.NotFound(404)]
        scheduler.TaskRunner(instance.create)()
        scheduler.TaskRunner(instance.delete)()

    def test_instance_attributes(self):
        fake_instance = FakeDBInstance()
        self.client.instances.create.return_value = fake_instance
        self.client.instances.get.return_value = fake_instance
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('attr_test', t)
        self.assertEqual("testhost", instance.FnGetAtt('hostname'))
        self.assertEqual("https://adga23dd432a.rackspacecloud.com/132345245",
                         instance.FnGetAtt('href'))

    def test_instance_validation_success(self):
        t = template_format.parse(db_template)
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertIsNone(instance.validate())

    def test_instance_validation_invalid_db(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = [
            {"name": "onedb"}]
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser",
             "password": "pass",
             "databases": ["invaliddb"]}]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        self.assertEqual("Database ['invaliddb'] specified for user does not "
                         "exist in databases for resource MySqlCloudDB.",
                         six.text_type(ex))

    def test_instance_validation_db_name_hyphens(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = [
            {"name": "-foo-bar-"}]
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser",
             "password": "pass",
             "databases": ["-foo-bar-"]}]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertIsNone(instance.validate())

    def test_instance_validation_users_none(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['users'] = []
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertIsNone(instance.validate())

    def test_instance_validation_databases_none(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = []
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser",
             "password": "pass",
             "databases": ["invaliddb"]}]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        self.assertEqual('Databases property is required if users property '
                         'is provided for resource MySqlCloudDB.',
                         six.text_type(ex))

    def test_instance_validation_user_no_db(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['databases'] = [
            {"name": "validdb"}]
        t['Resources']['MySqlCloudDB']['Properties']['users'] = [
            {"name": "testuser", "password": "pass", "databases": []}]

        instance = self._setup_test_instance('dbinstance_test', t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        self.assertEqual('Property error: '
                         'Resources.MySqlCloudDB.Properties.'
                         'users[0].databases: length (0) is out of range '
                         '(min: 1, max: None)', six.text_type(ex))

    def test_instance_validation_no_datastore_yes_version(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_type')
        instance = self._setup_test_instance('dbinstance_test', t)
        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        exp_msg = "Not allowed - datastore_version without datastore_type."
        self.assertEqual(exp_msg, six.text_type(ex))

    def test_instance_validation_no_ds_version(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_version')
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)
        self.assertIsNone(instance.validate())

    def test_instance_validation_wrong_dsversion(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_version'] = 'SomeVersion'
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance)

        ex = self.assertRaises(exception.StackValidationFailed,
                               instance.validate)
        expected_msg = ("Datastore version SomeVersion for datastore type "
                        "mysql is not valid. "
                        "Allowed versions are MariaDB-5.5.")
        self.assertEqual(expected_msg, six.text_type(ex))

    def test_instance_validation_implicit_version(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties'][
            'datastore_type'] = 'mysql'
        t['Resources']['MySqlCloudDB']['Properties'].pop('datastore_version')
        instance = self._setup_test_instance('dbinstance_test', t)
        self.client.datastore_versions.list.return_value = [
            FakeVersion(), FakeVersion('MariaDB-5.0')]
        self.assertIsNone(instance.validate())

    def test_instance_validation_net_with_port_fail(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "port": "someportuuid",
                "network": "somenetuuid"
            }]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=True,
                               mock_net_constraint=True)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Either network or port must be provided.',
                         six.text_type(ex))

    def test_instance_validation_no_net_no_port_fail(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "fixed_ip": "1.2.3.4"
            }]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=True, with_port=False)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Either network or port must be provided.',
                         six.text_type(ex))

    def test_instance_validation_nic_port_on_novanet_fails(self):
        t = template_format.parse(db_template)
        t['Resources']['MySqlCloudDB']['Properties']['networks'] = [
            {
                "port": "someportuuid",
            }]
        instance = self._setup_test_instance('dbinstance_test', t)
        self._stubout_validate(instance, neutron=False)

        ex = self.assertRaises(
            exception.StackValidationFailed, instance.validate)
        self.assertEqual('Can not use port property on Nova-network.',
                         six.text_type(ex))

    def test_instance_create_with_port(self):
        t = template_format.parse(db_template_with_nics)
        instance = self._setup_test_instance('dbinstance_test', t)
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value='someportid')
        self.stub_PortConstraint_validate()

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.client.instances.create.assert_called_once_with(
            'test', '1', volume={'size': 30}, databases=[], users=[],
            restorePoint=None, availability_zone=None, datastore=None,
            datastore_version=None, nics=[{'port-id': 'someportid',
                                           'v4-fixed-ip': '1.2.3.4'}],
            replica_of=None, replica_count=None)

    def test_instance_create_with_net_id(self):
        net_id = '034aa4d5-0f36-4127-8481-5caa5bfc9403'
        t = template_format.parse(db_template_with_nics)
        t['resources']['MySqlCloudDB']['properties']['networks'] = [
            {'network': net_id}]
        instance = self._setup_test_instance('dbinstance_test', t)
        self.stub_NetworkConstraint_validate()
        self.patchobject(neutron.NeutronClientPlugin,
                         'find_resourceid_by_name_or_id',
                         return_value=net_id)
        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.client.instances.create.assert_called_once_with(
            'test', '1', volume={'size': 30}, databases=[], users=[],
            restorePoint=None, availability_zone=None, datastore=None,
            datastore_version=None, nics=[{'net-id': net_id}], replica_of=None,
            replica_count=None)

    def test_instance_create_with_replication(self):
        t = template_format.parse(db_template_with_replication)
        instance = self._setup_test_instance('dbinstance_test', t)

        scheduler.TaskRunner(instance.create)()
        self.assertEqual((instance.CREATE, instance.COMPLETE), instance.state)
        self.client.instances.create.assert_called_once_with(
            'test', '1', volume={'size': 30}, databases=[], users=[],
            restorePoint=None, availability_zone=None, datastore=None,
            datastore_version=None, nics=[],
            replica_of="0e642916-dd64-43b3-933f-ff34fff69a7f", replica_count=2)

    def test_instance_get_live_state(self):
        self.fake_instance.to_dict = mock.Mock(return_value={
            'name': 'test_instance',
            'flavor': {'id': '1'},
            'volume': {'size': 30}
        })

        fake_db1 = mock.Mock()
        fake_db1.name = 'validdb'
        fake_db2 = mock.Mock()
        fake_db2.name = 'secondvaliddb'
        self.client.databases.list.return_value = [fake_db1, fake_db2]

        expected = {
            'flavor': '1',
            'name': 'test_instance',
            'size': 30,
            'databases': [{'name': 'validdb',
                           'character_set': 'utf8',
                           'collate': 'utf8_general_ci'},
                          {'name': 'secondvaliddb'}]
        }

        t = template_format.parse(db_template)
        instance = self._setup_test_instance('get_live_state_test', t)
        reality = instance.get_live_state(instance.properties)

        self.assertEqual(expected, reality)


@mock.patch.object(resource.Resource, "client_plugin")
@mock.patch.object(resource.Resource, "client")
class InstanceUpdateTests(common.HeatTestCase):

    def setUp(self):
        super(InstanceUpdateTests, self).setUp()
        self._stack = utils.parse_stack(template_format.parse(db_template))
        testprops = {
            "name": "testinstance",
            "flavor": "foo",
            "datastore_type": "database",
            "datastore_version": "1",
            "size": 10,
            "databases": [
                {"name": "bar"},
                {"name": "biff"}
            ],
            "users": [
                {
                    "name": "baz",
                    "password": "password",
                    "databases": ["bar"]
                },
                {
                    "name": "deleted",
                    "password": "password",
                    "databases": ["biff"]
                }
            ]
        }
        self._rdef = rsrc_defn.ResourceDefinition('test',
                                                  dbinstance.Instance,
                                                  properties=testprops)

    def test_handle_no_update(self, mock_client, mock_plugin):
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertEqual({}, trove.handle_update(None, None, {}))

    def test_handle_update_name(self, mock_client, mock_plugin):
        prop_diff = {
            "name": "changed"
        }
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertEqual(prop_diff, trove.handle_update(None, None, prop_diff))

    def test_handle_update_databases(self, mock_client, mock_plugin):
        prop_diff = {
            "databases": [
                {"name": "bar",
                 "character_set": "ascii"},
                {'name': "baz"}
            ]
        }
        mget = mock_client().databases.list
        mbar = mock.Mock(name='bar')
        mbar.name = 'bar'
        mbiff = mock.Mock(name='biff')
        mbiff.name = 'biff'
        mget.return_value = [mbar, mbiff]
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        expected = {
            'databases': [
                {'character_set': 'ascii', 'name': 'bar'},
                {'ACTION': 'CREATE', 'name': 'baz'},
                {'ACTION': 'DELETE', 'name': 'biff'}
            ]}
        self.assertEqual(expected, trove.handle_update(None, None, prop_diff))

    def test_handle_update_users(self, mock_client, mock_plugin):
        prop_diff = {
            "users": [
                {"name": "baz",
                 "password": "changed",
                 "databases": ["bar", "biff"]},
                {'name': "user2",
                 "password": "password",
                 "databases": ["biff", "bar"]}
            ]
        }
        uget = mock_client().users
        mbaz = mock.Mock(name='baz')
        mbaz.name = 'baz'
        mdel = mock.Mock(name='deleted')
        mdel.name = 'deleted'
        uget.list.return_value = [mbaz, mdel]
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        expected = {
            'users': [{
                'databases': ['bar', 'biff'],
                'name': 'baz',
                'password': 'changed'
            }, {
                'ACTION': 'CREATE',
                'databases': ['biff', 'bar'],
                'name': 'user2',
                'password': 'password'
            }, {
                'ACTION': 'DELETE',
                'name': 'deleted'
            }]}
        self.assertEqual(expected, trove.handle_update(None, None, prop_diff))

    def test_handle_update_flavor(self, mock_client, mock_plugin):
        # Translation mechanism already resolved flavor name to id.
        prop_diff = {
            "flavor": 1234
        }
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        expected = {
            "flavor": 1234
        }
        self.assertEqual(expected, trove.handle_update(None, None, prop_diff))

    def test_handle_update_size(self, mock_client, mock_plugin):
        prop_diff = {
            "size": 42
        }
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        expected = {
            "size": 42
        }
        self.assertEqual(expected, trove.handle_update(None, None, prop_diff))

    def test_check_complete_none(self, mock_client, mock_plugin):
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertTrue(trove.check_update_complete({}))

    def test_check_complete_error(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ERROR")
        mock_client().instances.get.return_value = mock_instance
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        exc = self.assertRaises(exception.ResourceInError,
                                trove.check_update_complete,
                                {"foo": "bar"})
        msg = "The last operation for the database instance failed"
        self.assertIn(msg, six.text_type(exc))

    def test_check_client_exceptions(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE")
        mock_client().instances.get.return_value = mock_instance
        mock_plugin().is_client_exception.return_value = True
        mock_plugin().is_over_limit.side_effect = [True, False]
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        with mock.patch.object(trove, "_update_flavor") as mupdate:
            mupdate.side_effect = [Exception("test"),
                                   Exception("No change was requested "
                                             "because I'm testing")]
            self.assertFalse(trove.check_update_complete({"foo": "bar"}))
            self.assertFalse(trove.check_update_complete({"foo": "bar"}))
            self.assertEqual(2, mupdate.call_count)
            self.assertEqual(2, mock_plugin().is_client_exception.call_count)

    def test_check_complete_status(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="RESIZING")
        mock_client().instances.get.return_value = mock_instance
        updates = {"foo": "bar"}
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertFalse(trove.check_update_complete(updates))

    def test_check_complete_name(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE", name="mock_instance")
        mock_client().instances.get.return_value = mock_instance
        updates = {"name": "changed"}
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertFalse(trove.check_update_complete(updates))
        mock_instance.name = "changed"
        self.assertTrue(trove.check_update_complete(updates))
        mock_client().instances.edit.assert_called_once_with(mock_instance,
                                                             name="changed")

    def test_check_complete_databases(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE", name="mock_instance")
        mock_client().instances.get.return_value = mock_instance
        updates = {
            'databases': [
                {'name': 'bar', "character_set": "ascii"},
                {'ACTION': 'CREATE', 'name': 'baz'},
                {'ACTION': 'DELETE', 'name': 'biff'}
            ]}
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertTrue(trove.check_update_complete(updates))
        mcreate = mock_client().databases.create
        mdelete = mock_client().databases.delete
        mcreate.assert_called_once_with(mock_instance, [{'name': 'baz'}])
        mdelete.assert_called_once_with(mock_instance, 'biff')

    def test_check_complete_users(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE", name="mock_instance")
        mock_client().instances.get.return_value = mock_instance
        mock_plugin().is_client_exception.return_value = False
        mock_client().users.get.return_value = users.User(None, {
            "databases": [{
                "name": "bar"
            }, {
                "name": "buzz"
            }],
            "name": "baz"
            }, loaded=True)
        updates = {
            'users': [{
                'databases': ['bar', 'biff'],
                'name': 'baz',
                'password': 'changed'
            }, {
                'ACTION': 'CREATE',
                'databases': ['biff', 'bar'],
                'name': 'user2',
                'password': 'password'
            }, {
                'ACTION': 'DELETE',
                'name': 'deleted'
            }]}
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertTrue(trove.check_update_complete(updates))
        create_calls = [
            mock.call(mock_instance, [{'password': 'password',
                                       'databases': [{'name': 'biff'},
                                                     {'name': 'bar'}],
                                       'name': 'user2'}])
        ]
        delete_calls = [
            mock.call(mock_instance, 'deleted')
        ]
        mock_client().users.create.assert_has_calls(create_calls)
        mock_client().users.delete.assert_has_calls(delete_calls)
        self.assertEqual(1, mock_client().users.create.call_count)
        self.assertEqual(1, mock_client().users.delete.call_count)
        updateattr = mock_client().users.update_attributes
        updateattr.assert_called_once_with(
            mock_instance, 'baz', newuserattr={'password': 'changed'},
            hostname=mock.ANY)
        mock_client().users.grant.assert_called_once_with(
            mock_instance, 'baz', ['biff'])
        mock_client().users.revoke.assert_called_once_with(
            mock_instance, 'baz', ['buzz'])

    def test_check_complete_flavor(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE", flavor={'id': 4567},
                                  name="mock_instance")
        mock_client().instances.get.return_value = mock_instance
        updates = {
            "flavor": 1234
        }
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertFalse(trove.check_update_complete(updates))
        mock_instance.status = "RESIZING"
        self.assertFalse(trove.check_update_complete(updates))
        mock_instance.status = "ACTIVE"
        mock_instance.flavor = {'id': 1234}
        self.assertTrue(trove.check_update_complete(updates))

    def test_check_complete_size(self, mock_client, mock_plugin):
        mock_instance = mock.Mock(status="ACTIVE", volume={'size': 24},
                                  name="mock_instance")
        mock_client().instances.get.return_value = mock_instance
        updates = {
            "size": 42
        }
        trove = dbinstance.Instance('test', self._rdef, self._stack)
        self.assertFalse(trove.check_update_complete(updates))
        mock_instance.status = "RESIZING"
        self.assertFalse(trove.check_update_complete(updates))
        mock_instance.status = "ACTIVE"
        mock_instance.volume = {'size': 42}
        self.assertTrue(trove.check_update_complete(updates))
