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
from saharaclient.api import base as sahara_base
import six

from heat.common import exception
from heat.engine.clients.os import sahara
from heat.tests import common
from heat.tests import utils


class SaharaUtilsTest(common.HeatTestCase):
    """Basic tests :module:'heat.engine.resources.clients.os.sahara'."""

    def setUp(self):
        super(SaharaUtilsTest, self).setUp()
        self.sahara_client = mock.MagicMock()
        con = utils.dummy_context()
        c = con.clients
        self.sahara_plugin = c.client_plugin('sahara')
        self.sahara_plugin.client = lambda: self.sahara_client
        self.my_image = mock.MagicMock()
        self.my_plugin = mock.MagicMock()
        self.my_jobtype = mock.MagicMock()

    def test_get_image_id(self):
        """Tests the get_image_id function."""
        img_id = str(uuid.uuid4())
        img_name = 'myfakeimage'
        self.my_image.id = img_id
        self.my_image.name = img_name
        self.sahara_client.images.get.side_effect = [
            self.my_image,
            sahara_base.APIException(404),
            sahara_base.APIException(404)
        ]
        self.sahara_client.images.find.side_effect = [[self.my_image], []]

        self.assertEqual(img_id, self.sahara_plugin.get_image_id(img_id))
        self.assertEqual(img_id, self.sahara_plugin.get_image_id(img_name))
        self.assertRaises(exception.EntityNotFound,
                          self.sahara_plugin.get_image_id, 'noimage')

        calls = [mock.call(name=img_name),
                 mock.call(name='noimage')]
        self.sahara_client.images.find.assert_has_calls(calls)

    def test_get_image_id_by_name_in_uuid(self):
        """Tests the get_image_id function by name in uuid."""
        img_id = str(uuid.uuid4())
        img_name = str(uuid.uuid4())
        self.my_image.id = img_id
        self.my_image.name = img_name
        self.sahara_client.images.get.side_effect = [
            sahara_base.APIException(error_code=400,
                                     error_name='IMAGE_NOT_REGISTERED')]

        self.sahara_client.images.find.return_value = [self.my_image]
        self.assertEqual(img_id, self.sahara_plugin.get_image_id(img_name))

        self.sahara_client.images.get.assert_called_once_with(img_name)
        self.sahara_client.images.find.assert_called_once_with(name=img_name)

    def test_get_image_id_sahara_exception(self):
        """Test get_image_id when sahara raises an exception."""
        # Simulate HTTP exception
        img_name = str(uuid.uuid4())
        self.sahara_client.images.find.side_effect = [
            sahara_base.APIException(error_message="Error", error_code=404)]

        expected_error = "Error retrieving images list from sahara: Error"
        e = self.assertRaises(exception.Error,
                              self.sahara_plugin.find_resource_by_name,
                              'images', img_name)
        self.assertEqual(expected_error, six.text_type(e))

        self.sahara_client.images.find.assert_called_once_with(name=img_name)

    def test_get_image_id_not_found(self):
        """Tests the get_image_id function while image is not found."""
        img_name = str(uuid.uuid4())
        self.my_image.name = img_name
        self.sahara_client.images.get.side_effect = [
            sahara_base.APIException(error_code=400,
                                     error_name='IMAGE_NOT_REGISTERED')]
        self.sahara_client.images.find.return_value = []

        self.assertRaises(exception.EntityNotFound,
                          self.sahara_plugin.get_image_id, img_name)

        self.sahara_client.images.get.assert_called_once_with(img_name)
        self.sahara_client.images.find.assert_called_once_with(name=img_name)

    def test_get_image_id_name_ambiguity(self):
        """Tests the get_image_id function while name ambiguity ."""
        img_name = 'ambiguity_name'
        self.my_image.name = img_name

        self.sahara_client.images.get.side_effect = sahara_base.APIException()
        self.sahara_client.images.find.return_value = [self.my_image,
                                                       self.my_image]
        self.assertRaises(exception.PhysicalResourceNameAmbiguity,
                          self.sahara_plugin.get_image_id, img_name)
        self.sahara_client.images.find.assert_called_once_with(name=img_name)

    def test_get_plugin_id(self):
        """Tests the get_plugin_id function."""
        plugin_name = 'myfakeplugin'
        self.my_plugin.name = plugin_name

        def side_effect(name):
            if name == plugin_name:
                return self.my_plugin
            else:
                raise sahara_base.APIException(error_code=404,
                                               error_name='NOT_FOUND')

        self.sahara_client.plugins.get.side_effect = side_effect
        self.assertIsNone(self.sahara_plugin.get_plugin_id(plugin_name))
        self.assertRaises(exception.EntityNotFound,
                          self.sahara_plugin.get_plugin_id, 'noplugin')

        calls = [mock.call(plugin_name), mock.call('noplugin')]
        self.sahara_client.plugins.get.assert_has_calls(calls)

    def test_validate_hadoop_version(self):
        """Tests the validate_hadoop_version function."""
        versions = ['1.2.1', '2.6.0', '2.7.1']
        plugin_name = 'vanilla'
        self.my_plugin.name = plugin_name
        self.my_plugin.versions = versions

        self.sahara_client.plugins.get.return_value = self.my_plugin
        self.assertIsNone(self.sahara_plugin.validate_hadoop_version(
            plugin_name, '2.6.0'))
        ex = self.assertRaises(exception.StackValidationFailed,
                               self.sahara_plugin.validate_hadoop_version,
                               plugin_name, '1.2.3')
        self.assertEqual("Requested plugin 'vanilla' doesn't support version "
                         "'1.2.3'. Allowed versions are 1.2.1, 2.6.0, 2.7.1",
                         six.text_type(ex))
        calls = [mock.call(plugin_name), mock.call(plugin_name)]
        self.sahara_client.plugins.get.assert_has_calls(calls)

    def test_get_job_type(self):
        """Tests the get_job_type function."""
        job_type = 'myfakejobtype'
        self.my_jobtype = job_type

        def side_effect(name):
            if name == job_type:
                return self.my_jobtype
            else:
                raise sahara_base.APIException(error_code=404,
                                               error_name='NOT_FOUND')

        self.sahara_client.job_types.find_unique.side_effect = side_effect
        self.assertEqual(self.sahara_plugin.get_job_type(job_type), job_type)
        self.assertRaises(exception.EntityNotFound,
                          self.sahara_plugin.get_job_type, 'nojobtype')
        calls = [mock.call(name=job_type), mock.call(name='nojobtype')]
        self.sahara_client.job_types.find_unique.assert_has_calls(calls)


class SaharaConstraintsTest(common.HeatTestCase):
    scenarios = [
        ('JobType', dict(
            constraint=sahara.JobTypeConstraint(),
            resource_name=None
        )),
        ('ClusterTemplate', dict(
            constraint=sahara.ClusterTemplateConstraint(),
            resource_name='cluster_templates'
        )),
        ('DataSource', dict(
            constraint=sahara.DataSourceConstraint(),
            resource_name='data_sources'
        )),
        ('Cluster', dict(
            constraint=sahara.ClusterConstraint(),
            resource_name='clusters'
        )),
        ('JobBinary', dict(
            constraint=sahara.JobBinaryConstraint(),
            resource_name='job_binaries'
        )),
        ('Plugin', dict(
            constraint=sahara.PluginConstraint(),
            resource_name=None
        )),
        ('Image', dict(
            constraint=sahara.ImageConstraint(),
            resource_name='images'
        )),
    ]

    def setUp(self):
        super(SaharaConstraintsTest, self).setUp()
        self.ctx = utils.dummy_context()
        self.mock_get = mock.Mock()
        cl_plgn = self.ctx.clients.client_plugin('sahara')
        cl_plgn.find_resource_by_name_or_id = self.mock_get
        cl_plgn.get_image_id = self.mock_get
        cl_plgn.get_plugin_id = self.mock_get
        cl_plgn.get_job_type = self.mock_get

    def test_validation(self):
        self.mock_get.return_value = "fake_val"
        self.assertTrue(self.constraint.validate("foo", self.ctx))
        if self.resource_name is None:
            self.mock_get.assert_called_once_with("foo")
        else:
            self.mock_get.assert_called_once_with(self.resource_name, "foo")

    def test_validation_error(self):
        self.mock_get.side_effect = exception.EntityNotFound(
            entity='Fake entity', name='bar')
        self.assertFalse(self.constraint.validate("bar", self.ctx))
        if self.resource_name is None:
            self.mock_get.assert_called_once_with("bar")
        else:
            self.mock_get.assert_called_once_with(self.resource_name, "bar")
