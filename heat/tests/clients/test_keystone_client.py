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

from keystoneauth1 import exceptions as keystone_exceptions
import mock
import six

from heat.common import exception
from heat.engine.clients.os import keystone
from heat.engine.clients.os.keystone import keystone_constraints as ks_constr
from heat.tests import common


class KeystoneRoleConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneRoleConstraint.expected_exceptions,
            "KeystoneRoleConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneRoleConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_role_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'role_1'))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_role_id.assert_called_once_with('role_1')


class KeystoneProjectConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneProjectConstraint.expected_exceptions,
            "KeystoneProjectConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneProjectConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_project_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'project_1'))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_project_id.assert_called_once_with('project_1')


class KeystoneGroupConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneGroupConstraint.expected_exceptions,
            "KeystoneGroupConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneGroupConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_group_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'group_1'))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_group_id.assert_called_once_with('group_1')


class KeystoneDomainConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneDomainConstraint.expected_exceptions,
            "KeystoneDomainConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneDomainConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_domain_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'domain_1'))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_domain_id.assert_called_once_with('domain_1')


class KeystoneServiceConstraintTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound, exception.KeystoneServiceNameConflict,),
            ks_constr.KeystoneServiceConstraint.expected_exceptions,
            "KeystoneServiceConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneServiceConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_service_id.return_value = self.sample_uuid
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          self.sample_uuid))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_service_id.assert_called_once_with(
            self.sample_uuid)


class KeystoneUserConstraintTest(common.HeatTestCase):

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneUserConstraint.expected_exceptions,
            "KeystoneUserConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneUserConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_user_id.return_value = None
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          'admin'))
        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_user_id.assert_called_once_with('admin')


class KeystoneRegionConstraintTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd151'

    def test_expected_exceptions(self):
        self.assertEqual(
            (exception.EntityNotFound,),
            ks_constr.KeystoneRegionConstraint.expected_exceptions,
            "KeystoneRegionConstraint expected exceptions error")

    def test_constraint(self):
        constraint = ks_constr.KeystoneRegionConstraint()
        client_mock = mock.MagicMock()
        client_plugin_mock = mock.MagicMock()
        client_plugin_mock.get_region_id.return_value = self.sample_uuid
        client_mock.client_plugin.return_value = client_plugin_mock

        self.assertIsNone(constraint.validate_with_client(client_mock,
                                                          self.sample_uuid))

        self.assertRaises(exception.EntityNotFound,
                          constraint.validate_with_client, client_mock, '')

        client_plugin_mock.get_region_id.assert_called_once_with(
            self.sample_uuid)


class KeystoneClientPluginServiceTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_service'

    def _get_mock_service(self):
        srv = mock.MagicMock()
        srv.id = self.sample_uuid
        srv.name = self.sample_name
        return srv

    def setUp(self):
        super(KeystoneClientPluginServiceTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_service_id(self, client_keystone):

        self._client.client.services.get.return_value = (self
                                                         ._get_mock_service())

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_service_id(self.sample_uuid))
        self._client.client.services.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_service_id_with_name(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
            self._get_mock_service()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_service_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.services.get,
                          self.sample_name)
        self._client.client.services.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_service_id_with_name_conflict(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
            self._get_mock_service(),
            self._get_mock_service()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.KeystoneServiceNameConflict,
                               client_plugin.get_service_id,
                               self.sample_name)
        msg = ("Keystone has more than one service with same name "
               "%s. Please use service id instead of name" %
               self.sample_name)
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.services.get,
                          self.sample_name)
        self._client.client.services.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_service_id_not_found(self, client_keystone):
        self._client.client.services.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.services.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_service_id,
                               self.sample_name)
        msg = ("The KeystoneService (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.services.get,
                          self.sample_name)
        self._client.client.services.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginRoleTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_role'

    def _get_mock_role(self):
        role = mock.MagicMock()
        role.id = self.sample_uuid
        role.name = self.sample_name
        return role

    def setUp(self):
        super(KeystoneClientPluginRoleTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_role_id(self, client_keystone):
        self._client.client.roles.get.return_value = (self
                                                      ._get_mock_role())

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_role_id(self.sample_uuid))
        self._client.client.roles.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_role_id_with_name(self, client_keystone):
        self._client.client.roles.get.side_effect = (keystone_exceptions
                                                     .NotFound)
        self._client.client.roles.list.return_value = [
            self._get_mock_role()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_role_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.roles.get,
                          self.sample_name)
        self._client.client.roles.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_role_id_not_found(self, client_keystone):
        self._client.client.roles.get.side_effect = (keystone_exceptions
                                                     .NotFound)
        self._client.client.roles.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_role_id,
                               self.sample_name)
        msg = ("The KeystoneRole (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.roles.get,
                          self.sample_name)
        self._client.client.roles.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginProjectTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_project'

    def _get_mock_project(self):
        project = mock.MagicMock()
        project.id = self.sample_uuid
        project.name = self.sample_name
        return project

    def setUp(self):
        super(KeystoneClientPluginProjectTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_project_id(self, client_keystone):
        self._client.client.projects.get.return_value = (self
                                                         ._get_mock_project())

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_project_id(self.sample_uuid))
        self._client.client.projects.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_project_id_with_name(self, client_keystone):
        self._client.client.projects.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.projects.list.return_value = [
            self._get_mock_project()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_project_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.projects.get,
                          self.sample_name)
        self._client.client.projects.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_project_id_not_found(self, client_keystone):
        self._client.client.projects.get.side_effect = (keystone_exceptions
                                                        .NotFound)
        self._client.client.projects.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_project_id,
                               self.sample_name)
        msg = ("The KeystoneProject (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.projects.get,
                          self.sample_name)
        self._client.client.projects.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginDomainTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_domain'

    def _get_mock_domain(self):
        domain = mock.MagicMock()
        domain.id = self.sample_uuid
        domain.name = self.sample_name
        return domain

    def setUp(self):
        super(KeystoneClientPluginDomainTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_domain_id(self, client_keystone):
        self._client.client.domains.get.return_value = (self
                                                        ._get_mock_domain())

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_domain_id(self.sample_uuid))
        self._client.client.domains.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_domain_id_with_name(self, client_keystone):
        self._client.client.domains.get.side_effect = (keystone_exceptions
                                                       .NotFound)
        self._client.client.domains.list.return_value = [
            self._get_mock_domain()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_domain_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.domains.get,
                          self.sample_name)
        self._client.client.domains.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_domain_id_not_found(self, client_keystone):
        self._client.client.domains.get.side_effect = (keystone_exceptions
                                                       .NotFound)
        self._client.client.domains.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_domain_id,
                               self.sample_name)
        msg = ("The KeystoneDomain (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.domains.get,
                          self.sample_name)
        self._client.client.domains.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginGroupTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_group'

    def _get_mock_group(self):
        group = mock.MagicMock()
        group.id = self.sample_uuid
        group.name = self.sample_name
        return group

    def setUp(self):
        super(KeystoneClientPluginGroupTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_group_id(self, client_keystone):
        self._client.client.groups.get.return_value = (self
                                                       ._get_mock_group())

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_group_id(self.sample_uuid))
        self._client.client.groups.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_group_id_with_name(self, client_keystone):
        self._client.client.groups.get.side_effect = (keystone_exceptions
                                                      .NotFound)
        self._client.client.groups.list.return_value = [
            self._get_mock_group()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_group_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.groups.get,
                          self.sample_name)
        self._client.client.groups.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_group_id_not_found(self, client_keystone):
        self._client.client.groups.get.side_effect = (keystone_exceptions
                                                      .NotFound)
        self._client.client.groups.list.return_value = [
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_group_id,
                               self.sample_name)
        msg = ("The KeystoneGroup (%(name)s) could not be found." %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.groups.get,
                          self.sample_name)
        self._client.client.groups.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginUserTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_user'

    def _get_mock_user(self):
        user = mock.MagicMock()
        user.id = self.sample_uuid
        user.name = self.sample_name
        return user

    def setUp(self):
        super(KeystoneClientPluginUserTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_user_id(self, client_keystone):
        self._client.client.users.get.return_value = self._get_mock_user()

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_user_id(self.sample_uuid))
        self._client.client.users.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_user_id_with_name(self, client_keystone):
        self._client.client.users.get.side_effect = (keystone_exceptions
                                                     .NotFound)
        self._client.client.users.list.return_value = [
            self._get_mock_user()
        ]

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_user_id(self.sample_name))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.users.get,
                          self.sample_name)
        self._client.client.users.list.assert_called_once_with(
            name=self.sample_name)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_user_id_not_found(self, client_keystone):
        self._client.client.users.get.side_effect = (keystone_exceptions
                                                     .NotFound)
        self._client.client.users.list.return_value = []

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_user_id,
                               self.sample_name)
        msg = ('The KeystoneUser (%(name)s) could not be found.' %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
        self.assertRaises(keystone_exceptions.NotFound,
                          self._client.client.users.get,
                          self.sample_name)
        self._client.client.users.list.assert_called_once_with(
            name=self.sample_name)


class KeystoneClientPluginRegionTest(common.HeatTestCase):

    sample_uuid = '477e8273-60a7-4c41-b683-fdb0bc7cd152'
    sample_name = 'sample_region'

    def _get_mock_region(self):
        region = mock.MagicMock()
        region.id = self.sample_uuid
        region.name = self.sample_name
        return region

    def setUp(self):
        super(KeystoneClientPluginRegionTest, self).setUp()
        self._client = mock.MagicMock()

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_region_id(self, client_keystone):
        self._client.client.regions.get.return_value = self._get_mock_region()

        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        self.assertEqual(self.sample_uuid,
                         client_plugin.get_region_id(self.sample_uuid))
        self._client.client.regions.get.assert_called_once_with(
            self.sample_uuid)

    @mock.patch.object(keystone.KeystoneClientPlugin, 'client')
    def test_get_region_id_not_found(self, client_keystone):
        self._client.client.regions.get.side_effect = (keystone_exceptions
                                                       .NotFound)
        client_keystone.return_value = self._client
        client_plugin = keystone.KeystoneClientPlugin(
            context=mock.MagicMock()
        )

        ex = self.assertRaises(exception.EntityNotFound,
                               client_plugin.get_region_id,
                               self.sample_name)
        msg = ('The KeystoneRegion (%(name)s) could not be found.' %
               {'name': self.sample_name})
        self.assertEqual(msg, six.text_type(ex))
