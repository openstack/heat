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

from oslo_log import log as logging
import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import stack_user

LOG = logging.getLogger(__name__)

#
# We are ignoring Groups as keystone does not support them.
# For now support users and accesskeys,
# We also now support a limited heat-native Policy implementation, and
# the native access policy resource is located at:
# heat/engine/resources/openstack/access_policy.py
#


class User(stack_user.StackUser):
    PROPERTIES = (
        PATH, GROUPS, LOGIN_PROFILE, POLICIES,
    ) = (
        'Path', 'Groups', 'LoginProfile', 'Policies',
    )

    _LOGIN_PROFILE_KEYS = (
        LOGIN_PROFILE_PASSWORD,
    ) = (
        'Password',
    )

    properties_schema = {
        PATH: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.')
        ),
        GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Not Implemented.')
        ),
        LOGIN_PROFILE: properties.Schema(
            properties.Schema.MAP,
            _('A login profile for the user.'),
            schema={
                LOGIN_PROFILE_PASSWORD: properties.Schema(
                    properties.Schema.STRING
                ),
            }
        ),
        POLICIES: properties.Schema(
            properties.Schema.LIST,
            _('Access policies to apply to the user.')
        ),
    }

    def _validate_policies(self, policies):
        for policy in (policies or []):
            # When we support AWS IAM style policies, we will have to accept
            # either a ref to an AWS::IAM::Policy defined in the stack, or
            # and embedded dict describing the policy directly, but for now
            # we only expect this list to contain strings, which must map
            # to an OS::Heat::AccessPolicy in this stack
            # If a non-string (e.g embedded IAM dict policy) is passed, we
            # ignore the policy (don't reject it because we previously ignored
            # and we don't want to break templates which previously worked
            if not isinstance(policy, six.string_types):
                LOG.debug("Ignoring policy %s, must be string "
                          "resource name", policy)
                continue

            try:
                policy_rsrc = self.stack[policy]
            except KeyError:
                LOG.debug("Policy %(policy)s does not exist in stack "
                          "%(stack)s",
                          {'policy': policy, 'stack': self.stack.name})
                return False

            if not callable(getattr(policy_rsrc, 'access_allowed', None)):
                LOG.debug("Policy %s is not an AccessPolicy resource", policy)
                return False

        return True

    def handle_create(self):
        profile = self.properties[self.LOGIN_PROFILE]
        if profile and self.LOGIN_PROFILE_PASSWORD in profile:
            self.password = profile[self.LOGIN_PROFILE_PASSWORD]

        if self.properties[self.POLICIES]:
            if not self._validate_policies(self.properties[self.POLICIES]):
                raise exception.InvalidTemplateAttribute(resource=self.name,
                                                         key=self.POLICIES)

        super(User, self).handle_create()
        self.resource_id_set(self._get_user_id())

    def get_reference_id(self):
        return self.physical_resource_name_or_FnGetRefId()

    def access_allowed(self, resource_name):
        policies = (self.properties[self.POLICIES] or [])
        for policy in policies:
            if not isinstance(policy, six.string_types):
                LOG.debug("Ignoring policy %s, must be string "
                          "resource name", policy)
                continue
            policy_rsrc = self.stack[policy]
            if not policy_rsrc.access_allowed(resource_name):
                return False
        return True


class AccessKey(resource.Resource):
    PROPERTIES = (
        SERIAL, USER_NAME, STATUS,
    ) = (
        'Serial', 'UserName', 'Status',
    )

    ATTRIBUTES = (
        USER_NAME, SECRET_ACCESS_KEY,
    ) = (
        'UserName', 'SecretAccessKey',
    )

    properties_schema = {
        SERIAL: properties.Schema(
            properties.Schema.INTEGER,
            _('Not Implemented.'),
            implemented=False
        ),
        USER_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The name of the user that the new key will belong to.'),
            required=True
        ),
        STATUS: properties.Schema(
            properties.Schema.STRING,
            _('Not Implemented.'),
            constraints=[
                constraints.AllowedValues(['Active', 'Inactive']),
            ],
            implemented=False
        ),
    }

    attributes_schema = {
        USER_NAME: attributes.Schema(
            _('Username associated with the AccessKey.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        SECRET_ACCESS_KEY: attributes.Schema(
            _('Keypair secret key.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    def __init__(self, name, json_snippet, stack):
        super(AccessKey, self).__init__(name, json_snippet, stack)
        self._secret = None
        if self.resource_id:
            self._register_access_key()

    def _get_user(self):
        """Derive the keystone userid, stored in the User resource_id.

        Helper function to derive the keystone userid, which is stored in the
        resource_id of the User associated with this key. We want to avoid
        looking the name up via listing keystone users, as this requires admin
        rights in keystone, so FnGetAtt which calls _secret_accesskey won't
        work for normal non-admin users.
        """
        # Lookup User resource by intrinsic reference (which is what is passed
        # into the UserName parameter.  Would be cleaner to just make the User
        # resource return resource_id for FnGetRefId but the AWS definition of
        # user does say it returns a user name not ID
        return self.stack.resource_by_refid(self.properties[self.USER_NAME])

    def handle_create(self):
        user = self._get_user()
        if user is None:
            raise exception.NotFound(_('could not find user %s') %
                                     self.properties[self.USER_NAME])
        # The keypair is actually created and owned by the User resource
        kp = user._create_keypair()
        self.resource_id_set(kp.access)
        self._secret = kp.secret
        self._register_access_key()

        # Store the secret key, encrypted, in the DB so we don't have lookup
        # the user every time someone requests the SecretAccessKey attribute
        self.data_set('secret_key', kp.secret, redact=True)
        self.data_set('credential_id', kp.id, redact=True)

    def handle_delete(self):
        self._secret = None
        if self.resource_id is None:
            return

        user = self._get_user()
        if user is None:
            LOG.debug('Error deleting %s - user not found', str(self))
            return
        user._delete_keypair()

    def _secret_accesskey(self):
        """Return the user's access key.

        Fetching it from keystone if necessary.
        """
        if self._secret is None:
            if not self.resource_id:
                LOG.info('could not get secret for %(username)s '
                         'Error:%(msg)s',
                         {'username': self.properties[self.USER_NAME],
                          'msg': "resource_id not yet set"})
            else:
                # First try to retrieve the secret from resource_data, but
                # for backwards compatibility, fall back to requesting from
                # keystone
                self._secret = self.data().get('secret_key')
                if self._secret is None:
                    try:
                        user_id = self._get_user().resource_id
                        kp = self.keystone().get_ec2_keypair(
                            user_id=user_id, access=self.resource_id)
                        self._secret = kp.secret
                        # Store the key in resource_data
                        self.data_set('secret_key', kp.secret, redact=True)
                        # And the ID of the v3 credential
                        self.data_set('credential_id', kp.id, redact=True)
                    except Exception as ex:
                        LOG.info('could not get secret for %(username)s '
                                 'Error:%(msg)s',
                                 {'username': self.properties[self.USER_NAME],
                                  'msg': ex})

        return self._secret or '000-000-000'

    def _resolve_attribute(self, name):
        if name == self.USER_NAME:
            return self.properties[self.USER_NAME]
        elif name == self.SECRET_ACCESS_KEY:
            return self._secret_accesskey()

    def _register_access_key(self):

        def access_allowed(resource_name):
            return self._get_user().access_allowed(resource_name)
        self.stack.register_access_allowed_handler(
            self.resource_id, access_allowed)


def resource_mapping():
    return {
        'AWS::IAM::User': User,
        'AWS::IAM::AccessKey': AccessKey,
    }
