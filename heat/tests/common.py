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

import os
import sys

import fixtures
from oslo_config import cfg
from oslo_log import log as logging
import testscenarios
import testtools

from heat.common import context
from heat.common import messaging
from heat.common import policy
from heat.engine.clients.os import barbican
from heat.engine.clients.os import cinder
from heat.engine.clients.os import glance
from heat.engine.clients.os import keystone
from heat.engine.clients.os.keystone import fake_keystoneclient as fake_ks
from heat.engine.clients.os.keystone import keystone_constraints as ks_constr
from heat.engine.clients.os.neutron import neutron_constraints as neutron
from heat.engine.clients.os import nova
from heat.engine.clients.os import sahara
from heat.engine.clients.os import trove
from heat.engine import environment
from heat.engine import resource
from heat.engine import resources
from heat.engine import scheduler
from heat.tests import fakes
from heat.tests import generic_resource as generic_rsrc
from heat.tests import utils

TEST_DEFAULT_LOGLEVELS = {'migrate': logging.WARN,
                          'sqlalchemy': logging.WARN,
                          'heat.engine.environment': logging.ERROR}
_LOG_FORMAT = "%(levelname)8s [%(name)s] %(message)s"
_TRUE_VALUES = ('True', 'true', '1', 'yes')


class FakeLogMixin(object):
    def setup_logging(self, quieten=True):
        # Assign default logs to self.LOG so we can still
        # assert on heat logs.
        default_level = logging.INFO
        if os.environ.get('OS_DEBUG') in _TRUE_VALUES:
            default_level = logging.DEBUG

        self.LOG = self.useFixture(
            fixtures.FakeLogger(level=default_level, format=_LOG_FORMAT))
        base_list = set([nlog.split('.')[0]
                         for nlog in logging.logging.Logger.manager.loggerDict]
                        )
        for base in base_list:
            if base in TEST_DEFAULT_LOGLEVELS:
                self.useFixture(fixtures.FakeLogger(
                    level=TEST_DEFAULT_LOGLEVELS[base],
                    name=base, format=_LOG_FORMAT))
            elif base != 'heat':
                self.useFixture(fixtures.FakeLogger(
                    name=base, format=_LOG_FORMAT))
        if quieten:
            for ll in TEST_DEFAULT_LOGLEVELS:
                if ll.startswith('heat.'):
                    self.useFixture(fixtures.FakeLogger(
                        level=TEST_DEFAULT_LOGLEVELS[ll],
                        name=ll, format=_LOG_FORMAT))


class HeatTestCase(testscenarios.WithScenarios,
                   testtools.TestCase, FakeLogMixin):

    def setUp(self, mock_keystone=True, mock_resource_policy=True,
              quieten_logging=True):
        super(HeatTestCase, self).setUp()
        self.setup_logging(quieten=quieten_logging)
        self.warnings = self.useFixture(fixtures.WarningsCapture())
        scheduler.ENABLE_SLEEP = False
        self.useFixture(fixtures.MonkeyPatch(
            'heat.common.exception._FATAL_EXCEPTION_FORMAT_ERRORS',
            True))

        def enable_sleep():
            scheduler.ENABLE_SLEEP = True

        self.addCleanup(enable_sleep)

        mod_dir = os.path.dirname(sys.modules[__name__].__file__)
        project_dir = os.path.abspath(os.path.join(mod_dir, '../../'))
        env_dir = os.path.join(project_dir, 'etc', 'heat',
                               'environment.d')
        template_dir = os.path.join(project_dir, 'etc', 'heat',
                                    'templates')

        cfg.CONF.set_default('environment_dir', env_dir)
        cfg.CONF.set_override('error_wait_time', None)
        cfg.CONF.set_default('template_dir', template_dir)
        self.addCleanup(cfg.CONF.reset)

        messaging.setup("fake://", optional=True)
        self.addCleanup(messaging.cleanup)

        tri_names = ['AWS::RDS::DBInstance', 'AWS::CloudWatch::Alarm']
        tris = []
        for name in tri_names:
            tris.append(resources.global_env().get_resource_info(
                name,
                registry_type=environment.TemplateResourceInfo))
        for tri in tris:
            if tri is not None:
                cur_path = tri.template_name
                templ_path = os.path.join(project_dir, 'etc',
                                          'heat', 'templates')
                if templ_path not in cur_path:
                    tri.template_name = cur_path.replace(
                        '/etc/heat/templates',
                        templ_path)

        if mock_keystone:
            self.stub_keystoneclient()
        if mock_resource_policy:
            self.mock_resource_policy = self.patchobject(
                policy.ResourceEnforcer, 'enforce')
        utils.setup_dummy_db()
        self.register_test_resources()
        self.addCleanup(utils.reset_dummy_db)

    def register_test_resources(self):
        resource._register_class('GenericResourceType',
                                 generic_rsrc.GenericResource)
        resource._register_class('MultiStepResourceType',
                                 generic_rsrc.MultiStepResource)
        resource._register_class('ResWithShowAttrType',
                                 generic_rsrc.ResWithShowAttr)
        resource._register_class('SignalResourceType',
                                 generic_rsrc.SignalResource)
        resource._register_class('ResourceWithPropsType',
                                 generic_rsrc.ResourceWithProps)
        resource._register_class('ResourceWithPropsRefPropOnDelete',
                                 generic_rsrc.ResourceWithPropsRefPropOnDelete)
        resource._register_class(
            'ResourceWithPropsRefPropOnValidate',
            generic_rsrc.ResourceWithPropsRefPropOnValidate)
        resource._register_class('StackUserResourceType',
                                 generic_rsrc.StackUserResource)
        resource._register_class('ResourceWithResourceIDType',
                                 generic_rsrc.ResourceWithResourceID)
        resource._register_class('ResourceWithAttributeType',
                                 generic_rsrc.ResourceWithAttributeType)
        resource._register_class('ResourceWithRequiredProps',
                                 generic_rsrc.ResourceWithRequiredProps)
        resource._register_class(
            'ResourceWithMultipleRequiredProps',
            generic_rsrc.ResourceWithMultipleRequiredProps)
        resource._register_class(
            'ResourceWithRequiredPropsAndEmptyAttrs',
            generic_rsrc.ResourceWithRequiredPropsAndEmptyAttrs)
        resource._register_class('ResourceWithPropsAndAttrs',
                                 generic_rsrc.ResourceWithPropsAndAttrs)
        resource._register_class('ResWithStringPropAndAttr',
                                 generic_rsrc.ResWithStringPropAndAttr),
        resource._register_class('ResWithComplexPropsAndAttrs',
                                 generic_rsrc.ResWithComplexPropsAndAttrs)
        resource._register_class('ResourceWithCustomConstraint',
                                 generic_rsrc.ResourceWithCustomConstraint)
        resource._register_class('ResourceWithComplexAttributesType',
                                 generic_rsrc.ResourceWithComplexAttributes)
        resource._register_class('ResourceWithDefaultClientName',
                                 generic_rsrc.ResourceWithDefaultClientName)
        resource._register_class('OverwrittenFnGetAttType',
                                 generic_rsrc.ResourceWithFnGetAttType)
        resource._register_class('OverwrittenFnGetRefIdType',
                                 generic_rsrc.ResourceWithFnGetRefIdType)
        resource._register_class('ResourceWithListProp',
                                 generic_rsrc.ResourceWithListProp)
        resource._register_class('StackResourceType',
                                 generic_rsrc.StackResourceType)
        resource._register_class('ResourceWithRestoreType',
                                 generic_rsrc.ResourceWithRestoreType)
        resource._register_class('ResourceTypeUnSupportedLiberty',
                                 generic_rsrc.ResourceTypeUnSupportedLiberty)
        resource._register_class('ResourceTypeSupportedKilo',
                                 generic_rsrc.ResourceTypeSupportedKilo)
        resource._register_class('ResourceTypeHidden',
                                 generic_rsrc.ResourceTypeHidden)
        resource._register_class(
            'ResourceWithHiddenPropertyAndAttribute',
            generic_rsrc.ResourceWithHiddenPropertyAndAttribute)

    def patchobject(self, obj, attr, **kwargs):
        mockfixture = self.useFixture(fixtures.MockPatchObject(obj, attr,
                                                               **kwargs))
        return mockfixture.mock

    # NOTE(pshchelo): this overrides the testtools.TestCase.patch method
    # that does simple monkey-patching in favor of mock's patching
    def patch(self, target, **kwargs):
        mockfixture = self.useFixture(fixtures.MockPatch(target,
                                                         **kwargs))
        return mockfixture.mock

    def stub_auth(self, ctx=None, **kwargs):
        auth = self.patchobject(ctx or context.RequestContext,
                                "_create_auth_plugin")
        fake_auth = fakes.FakeAuth(**kwargs)
        auth.return_value = fake_auth
        return auth

    def stub_keystoneclient(self, fake_client=None, **kwargs):
        client = self.patchobject(keystone.KeystoneClientPlugin, "_create")
        fkc = fake_client or fake_ks.FakeKeystoneClient(**kwargs)
        client.return_value = fkc
        return fkc

    def stub_KeypairConstraint_validate(self):
        validate = self.patchobject(nova.KeypairConstraint, 'validate')
        validate.return_value = True

    def stub_ImageConstraint_validate(self, num=None):
        validate = self.patchobject(glance.ImageConstraint, 'validate')
        if num is None:
            validate.return_value = True
        else:
            validate.side_effect = [True for x in range(num)]

    def stub_FlavorConstraint_validate(self):
        validate = self.patchobject(nova.FlavorConstraint, 'validate')
        validate.return_value = True

    def stub_VolumeConstraint_validate(self):
        validate = self.patchobject(cinder.VolumeConstraint, 'validate')
        validate.return_value = True

    def stub_QoSSpecsConstraint_validate(self):
        validate = self.patchobject(cinder.QoSSpecsConstraint, 'validate')
        validate.return_value = True

    def stub_SnapshotConstraint_validate(self):
        validate = self.patchobject(
            cinder.VolumeSnapshotConstraint, 'validate')
        validate.return_value = True

    def stub_VolumeTypeConstraint_validate(self):
        validate = self.patchobject(cinder.VolumeTypeConstraint, 'validate')
        validate.return_value = True

    def stub_VolumeBackupConstraint_validate(self):
        validate = self.patchobject(cinder.VolumeBackupConstraint, 'validate')
        validate.return_value = True

    def stub_ServerConstraint_validate(self):
        validate = self.patchobject(nova.ServerConstraint, 'validate')
        validate.return_value = True

    def stub_NetworkConstraint_validate(self):
        validate = self.patchobject(neutron.NetworkConstraint, 'validate')
        validate.return_value = True

    def stub_PortConstraint_validate(self):
        validate = self.patchobject(neutron.PortConstraint, 'validate')
        validate.return_value = True

    def stub_TroveFlavorConstraint_validate(self):
        validate = self.patchobject(trove.FlavorConstraint, 'validate')
        validate.return_value = True

    def stub_SubnetConstraint_validate(self):
        validate = self.patchobject(neutron.SubnetConstraint, 'validate')
        validate.return_value = True

    def stub_AddressScopeConstraint_validate(self):
        validate = self.patchobject(neutron.AddressScopeConstraint, 'validate')
        validate.return_value = True

    def stub_SubnetPoolConstraint_validate(self):
        validate = self.patchobject(neutron.SubnetPoolConstraint, 'validate')
        validate.return_value = True

    def stub_RouterConstraint_validate(self):
        validate = self.patchobject(neutron.RouterConstraint, 'validate')
        validate.return_value = True

    def stub_QoSPolicyConstraint_validate(self):
        validate = self.patchobject(neutron.QoSPolicyConstraint, 'validate')
        validate.return_value = True

    def stub_KeystoneProjectConstraint(self):
        validate = self.patchobject(ks_constr.KeystoneProjectConstraint,
                                    'validate')
        validate.return_value = True

    def stub_SaharaPluginConstraint(self):
        validate = self.patchobject(sahara.PluginConstraint, 'validate')
        validate.return_value = True

    def stub_ProviderConstraint_validate(self):
        validate = self.patchobject(neutron.ProviderConstraint, 'validate')
        validate.return_value = True

    def stub_SecretConstraint_validate(self):
        validate = self.patchobject(barbican.SecretConstraint, 'validate')
        validate.return_value = True
