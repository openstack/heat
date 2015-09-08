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

from keystoneclient.contrib.ec2 import utils as ec2_utils
from oslo_config import cfg
from oslo_log import log as logging
from six.moves.urllib import parse as urlparse

from heat.common.i18n import _LW
from heat.engine.resources import stack_user

LOG = logging.getLogger(__name__)

SIGNAL_TYPES = (
    WAITCONDITION, SIGNAL
) = (
    '/waitcondition', '/signal'
)
SIGNAL_VERB = {WAITCONDITION: 'PUT',
               SIGNAL: 'POST'}


class SignalResponder(stack_user.StackUser):

    # Anything which subclasses this may trigger authenticated
    # API operations as a consequence of handling a signal
    requires_deferred_auth = True

    def handle_delete(self):
        self._delete_signals()
        return super(SignalResponder, self).handle_delete()

    def _delete_signals(self):
        self._delete_ec2_signed_url()
        self._delete_heat_signal_url()
        self._delete_swift_signal_url()
        self._delete_zaqar_signal_queue()

    @property
    def password(self):
        return self.data().get('password')

    @password.setter
    def password(self, password):
        if password is None:
            self.data_delete('password')
        else:
            self.data_set('password', password, True)

    def _get_heat_signal_credentials(self):
        """Return OpenStack credentials that can be used to send a signal.

        These credentials are for the user associated with this resource in
        the heat stack user domain.
        """
        if self._get_user_id() is None:
            if self.password is None:
                self.password = uuid.uuid4().hex
            self._create_user()
        return {'auth_url': self.keystone().v3_endpoint,
                'username': self.physical_resource_name(),
                'user_id': self._get_user_id(),
                'password': self.password,
                'project_id': self.stack.stack_user_project_id}

    def _get_ec2_signed_url(self, signal_type=SIGNAL):
        """Create properly formatted and pre-signed URL.

        This uses the created user for the credentials.

        See boto/auth.py::QuerySignatureV2AuthHandler

        :param signal_type: either WAITCONDITION or SIGNAL.
        """
        stored = self.data().get('ec2_signed_url')
        if stored is not None:
            return stored

        access_key = self.data().get('access_key')
        secret_key = self.data().get('secret_key')

        if not access_key or not secret_key:
            if self.id is None:
                # it is too early
                return
            if self._get_user_id() is None:
                self._create_user()
            self._create_keypair()
            access_key = self.data().get('access_key')
            secret_key = self.data().get('secret_key')

            if not access_key or not secret_key:
                LOG.warn(_LW('Cannot generate signed url, '
                             'unable to create keypair'))
                return

        config_url = cfg.CONF.heat_waitcondition_server_url
        if config_url:
            signal_url = config_url.replace('/waitcondition', signal_type)
        else:
            heat_client_plugin = self.stack.clients.client_plugin('heat')
            endpoint = heat_client_plugin.get_heat_cfn_url()
            signal_url = ''.join([endpoint, signal_type])

        host_url = urlparse.urlparse(signal_url)

        path = self.identifier().arn_url_path()

        # Note the WSGI spec apparently means that the webob request we end up
        # processing in the CFN API (ec2token.py) has an unquoted path, so we
        # need to calculate the signature with the path component unquoted, but
        # ensure the actual URL contains the quoted version...
        unquoted_path = urlparse.unquote(host_url.path + path)
        request = {'host': host_url.netloc.lower(),
                   'verb': SIGNAL_VERB[signal_type],
                   'path': unquoted_path,
                   'params': {'SignatureMethod': 'HmacSHA256',
                              'SignatureVersion': '2',
                              'AWSAccessKeyId': access_key,
                              'Timestamp':
                              self.created_time.strftime("%Y-%m-%dT%H:%M:%SZ")
                              }}
        # Sign the request
        signer = ec2_utils.Ec2Signer(secret_key)
        request['params']['Signature'] = signer.generate(request)

        qs = urlparse.urlencode(request['params'])
        url = "%s%s?%s" % (signal_url.lower(),
                           path, qs)

        self.data_set('ec2_signed_url', url)
        return url

    def _delete_ec2_signed_url(self):
        self.data_delete('ec2_signed_url')
        self._delete_keypair()

    def _get_heat_signal_url(self):
        """Return a heat-api signal URL for this resource.

        This URL is not pre-signed, valid user credentials are required.
        """
        stored = self.data().get('heat_signal_url')
        if stored is not None:
            return stored

        if self.id is None:
            # it is too early
            return

        url = self.client_plugin('heat').get_heat_url()
        host_url = urlparse.urlparse(url)
        path = self.identifier().url_path()

        url = urlparse.urlunsplit(
            (host_url.scheme, host_url.netloc, 'v1/%s/signal' % path, '', ''))

        self.data_set('heat_signal_url', url)
        return url

    def _delete_heat_signal_url(self):
        self.data_delete('heat_signal_url')

    def _get_swift_signal_url(self):
        """Create properly formatted and pre-signed Swift signal URL.

        This uses a Swift pre-signed temp_url.
        """
        put_url = self.data().get('swift_signal_url')
        if put_url:
            return put_url

        if self.id is None:
            # it is too early
            return

        container = self.stack.id
        object_name = self.physical_resource_name()

        self.client('swift').put_container(container)

        put_url = self.client_plugin('swift').get_temp_url(
            container, object_name)
        self.data_set('swift_signal_url', put_url)
        self.data_set('swift_signal_object_name', object_name)

        self.client('swift').put_object(
            container, object_name, '')
        return put_url

    def _delete_swift_signal_url(self):
        object_name = self.data().get('swift_signal_object_name')
        if not object_name:
            return
        try:
            container = self.physical_resource_name()
            swift = self.client('swift')
            swift.delete_object(container, object_name)
            headers = swift.head_container(container)
            if int(headers['x-container-object-count']) == 0:
                swift.delete_container(container)
        except Exception as ex:
            self.client_plugin('swift').ignore_not_found(ex)
        self.data_delete('swift_signal_object_name')
        self.data_delete('swift_signal_url')

    def _get_zaqar_signal_queue_id(self):
        """Return a zaqar queue_id for signaling this resource.

        This uses the created user for the credentials.
        """
        queue_id = self.data().get('zaqar_signal_queue_id')
        if queue_id:
            return queue_id

        if self.id is None:
            # it is too early
            return

        if self._get_user_id() is None:
            if self.password is None:
                self.password = uuid.uuid4().hex
            self._create_user()

        queue_id = self.physical_resource_name()
        zaqar = self.client('zaqar')
        zaqar.queue(queue_id).ensure_exists()
        self.data_set('zaqar_signal_queue_id', queue_id)
        return queue_id

    def _delete_zaqar_signal_queue(self):
        queue_id = self.data().get('zaqar_signal_queue_id')
        if not queue_id:
            return
        zaqar = self.client('zaqar')
        try:
            zaqar.queue(queue_id).delete()
        except Exception as ex:
            self.client_plugin('zaqar').ignore_not_found(ex)
        self.data_delete('zaqar_signal_queue_id')
