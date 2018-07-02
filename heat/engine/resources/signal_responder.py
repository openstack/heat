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

from keystoneclient.contrib.ec2 import utils as ec2_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.common.i18n import _
from heat.common import password_gen
from heat.engine.clients.os import swift
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

    PROPERTIES = (
        SIGNAL_TRANSPORT,
    ) = (
        'signal_transport',
    )

    ATTRIBUTES = (
        SIGNAL_ATTR,
    ) = (
        'signal',
    )

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

    def _signal_transport_cfn(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.CFN_SIGNAL

    def _signal_transport_heat(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.HEAT_SIGNAL

    def _signal_transport_none(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.NO_SIGNAL

    def _signal_transport_temp_url(self):
        return self.properties[
            self.SIGNAL_TRANSPORT] == self.TEMP_URL_SIGNAL

    def _signal_transport_zaqar(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.ZAQAR_SIGNAL

    def _get_heat_signal_credentials(self):
        """Return OpenStack credentials that can be used to send a signal.

        These credentials are for the user associated with this resource in
        the heat stack user domain.
        """
        if self._get_user_id() is None:
            if self.password is None:
                self.password = password_gen.generate_openstack_password()
            self._create_user()
        return {'auth_url': self.keystone().v3_endpoint,
                'username': self.physical_resource_name(),
                'user_id': self._get_user_id(),
                'password': self.password,
                'project_id': self.stack.stack_user_project_id,
                'domain_id': self.keystone().stack_domain_id,
                'region_name': (self.context.region_name or
                                cfg.CONF.region_name_for_services)}

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
                LOG.warning('Cannot generate signed url, '
                            'unable to create keypair')
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

    def _get_heat_signal_url(self, project_id=None):
        """Return a heat-api signal URL for this resource.

        This URL is not pre-signed, valid user credentials are required.
        If a project_id is provided, it is used in place of the original
        project_id. This is useful to generate a signal URL that uses
        the heat stack user project instead of the user's.
        """
        stored = self.data().get('heat_signal_url')
        if stored is not None:
            return stored

        if self.id is None:
            # it is too early
            return

        url = self.client_plugin('heat').get_heat_url()
        path = self.identifier().url_path()
        if project_id is not None:
            path = project_id + path[path.find('/'):]

        url = urlparse.urljoin(url, '%s/signal' % path)

        self.data_set('heat_signal_url', url)
        return url

    def _delete_heat_signal_url(self):
        self.data_delete('heat_signal_url')

    def _get_swift_signal_url(self, multiple_signals=False):
        """Create properly formatted and pre-signed Swift signal URL.

        This uses a Swift pre-signed temp_url. If multiple_signals is
        requested, the Swift object referenced by the returned URL will have
        versioning enabled.
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

        if multiple_signals:
            put_url = self.client_plugin('swift').get_signal_url(container,
                                                                 object_name)
        else:
            put_url = self.client_plugin('swift').get_temp_url(container,
                                                               object_name)
            self.client('swift').put_object(container, object_name, '')
        self.data_set('swift_signal_url', put_url)
        self.data_set('swift_signal_object_name', object_name)

        return put_url

    def _delete_swift_signal_url(self):
        object_name = self.data().get('swift_signal_object_name')
        if not object_name:
            return
        with self.client_plugin('swift').ignore_not_found:
            container_name = self.stack.id
            swift = self.client('swift')

            # delete all versions of the object, in case there are some
            # signals that are waiting to be handled
            container = swift.get_container(container_name)
            filtered = [obj for obj in container[1]
                        if object_name in obj['name']]
            for obj in filtered:
                # we delete the main object every time, swift takes
                # care of restoring the previous version after each delete
                swift.delete_object(container_name, object_name)

            headers = swift.head_container(container_name)
            if int(headers['x-container-object-count']) == 0:
                swift.delete_container(container_name)
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
                self.password = password_gen.generate_openstack_password()
            self._create_user()

        queue_id = self.physical_resource_name()
        zaqar_plugin = self.client_plugin('zaqar')
        zaqar = zaqar_plugin.create_for_tenant(
            self.stack.stack_user_project_id, self._user_token())
        queue = zaqar.queue(queue_id)
        signed_url_data = queue.signed_url(
            ['messages'], methods=['GET', 'DELETE'])
        self.data_set('zaqar_queue_signed_url_data',
                      jsonutils.dumps(signed_url_data))
        self.data_set('zaqar_signal_queue_id', queue_id)
        return queue_id

    def _delete_zaqar_signal_queue(self):
        queue_id = self.data().get('zaqar_signal_queue_id')
        if not queue_id:
            return
        zaqar_plugin = self.client_plugin('zaqar')
        zaqar = zaqar_plugin.create_for_tenant(
            self.stack.stack_user_project_id, self._user_token())
        with zaqar_plugin.ignore_not_found:
            zaqar.queue(queue_id).delete()
        self.data_delete('zaqar_signal_queue_id')

    def _get_signal(self, signal_type=SIGNAL, multiple_signals=False):
        """Return a dictionary with signal details.

        Subclasses can invoke this method to retrieve information of the
        resource signal for the specified transport.
        """
        signal = None
        if self._signal_transport_cfn():
            signal = {'alarm_url': self._get_ec2_signed_url(
                signal_type=signal_type)}
        elif self._signal_transport_heat():
            signal = self._get_heat_signal_credentials()
            signal['alarm_url'] = self._get_heat_signal_url(
                project_id=self.stack.stack_user_project_id)
        elif self._signal_transport_temp_url():
            signal = {'alarm_url': self._get_swift_signal_url(
                multiple_signals=multiple_signals)}
        elif self._signal_transport_zaqar():
            signal = self._get_heat_signal_credentials()
            signal['queue_id'] = self._get_zaqar_signal_queue_id()
        elif self._signal_transport_none():
            signal = {}
        return signal

    def _service_swift_signal(self):
        swift_client = self.client('swift')
        try:
            container = swift_client.get_container(self.stack.id)
        except Exception as exc:
            self.client_plugin('swift').ignore_not_found(exc)
            LOG.debug("Swift container %s was not found", self.stack.id)
            return

        index = container[1]
        if not index:  # Swift objects were deleted by user
            LOG.debug("Swift objects in container %s were not found",
                      self.stack.id)
            return

        # Remove objects that are for other resources, given that
        # multiple swift signals in the same stack share a container
        object_name = self.physical_resource_name()
        filtered = [obj for obj in index if object_name in obj['name']]

        # Fetch objects from Swift and filter results
        signal_names = []
        for obj in filtered:
            try:
                signal = swift_client.get_object(self.stack.id, obj['name'])
            except Exception as exc:
                self.client_plugin('swift').ignore_not_found(exc)
                continue

            body = signal[1]
            if body == swift.IN_PROGRESS:  # Ignore the initial object
                continue
            signal_names.append(obj['name'])

            if body == "":
                self.signal(details={})
                continue
            try:
                self.signal(details=jsonutils.loads(body))
            except ValueError:
                raise exception.Error(_("Failed to parse JSON data: %s") %
                                      body)

        # remove the signals that were consumed
        for signal_name in signal_names:
            if signal_name != object_name:
                swift_client.delete_object(self.stack.id, signal_name)
        if object_name in signal_names:
            swift_client.delete_object(self.stack.id, object_name)

    def _service_zaqar_signal(self):
        zaqar_plugin = self.client_plugin('zaqar')
        zaqar = zaqar_plugin.create_for_tenant(
            self.stack.stack_user_project_id, self._user_token())
        try:
            queue = zaqar.queue(self._get_zaqar_signal_queue_id())
        except Exception as ex:
            self.client_plugin('zaqar').ignore_not_found(ex)
            return
        messages = list(queue.pop())
        for message in messages:
            self.signal(details=message.body)

    def _service_signal(self):
        """Service the signal, when necessary.

        This method must be called repeatedly by subclasses to update the
        state of the signals that require polling, which are the ones based on
        Swift temp URLs and Zaqar queues. The "NO_SIGNAL" case is also handled
        here by triggering the signal once per call.
        """
        if self._signal_transport_temp_url():
            self._service_swift_signal()
        elif self._signal_transport_zaqar():
            self._service_zaqar_signal()
        elif self._signal_transport_none():
            self.signal(details={})
