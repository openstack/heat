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

import collections
import email
from email.mime import multipart
from email.mime import text
import os
import pkgutil
import string

from neutronclient.common import exceptions as q_exceptions
from novaclient import api_versions
from novaclient import client as nc
from novaclient import exceptions
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import netutils
import six
from six.moves.urllib import parse as urlparse
import tenacity

from heat.common import exception
from heat.common.i18n import _
from heat.engine.clients import client_exception
from heat.engine.clients import client_plugin
from heat.engine.clients import microversion_mixin
from heat.engine.clients import os as os_client
from heat.engine import constraints

LOG = logging.getLogger(__name__)


CLIENT_NAME = 'nova'


class NovaClientPlugin(microversion_mixin.MicroversionMixin,
                       client_plugin.ClientPlugin):

    deferred_server_statuses = ['BUILD',
                                'HARD_REBOOT',
                                'PASSWORD',
                                'REBOOT',
                                'RESCUE',
                                'RESIZE',
                                'REVERT_RESIZE',
                                'SHUTOFF',
                                'SUSPENDED',
                                'VERIFY_RESIZE']

    exceptions_module = exceptions

    NOVA_API_VERSION = '2.1'

    max_microversion = cfg.CONF.max_nova_api_microversion

    service_types = [COMPUTE] = ['compute']

    def _get_service_name(self):
        return self.COMPUTE

    def _create(self, version=None):
        if not version:
            # TODO(prazumovsky): remove all unexpected calls from tests and
            # add default_version after that.
            version = self.NOVA_API_VERSION
        args = self._get_args(version)

        client = nc.Client(version, **args)
        return client

    def _get_args(self, version):
        endpoint_type = self._get_client_option(CLIENT_NAME, 'endpoint_type')
        extensions = nc.discover_extensions(version)

        return {
            'session': self.context.keystone_session,
            'extensions': extensions,
            'endpoint_type': endpoint_type,
            'service_type': self.COMPUTE,
            'region_name': self._get_region_name(),
            'http_log_debug': self._get_client_option(CLIENT_NAME,
                                                      'http_log_debug')
            }

    def get_max_microversion(self):
        if not self.max_microversion:
            client = self._create()
            self.max_microversion = client.versions.get_current().version
        return self.max_microversion

    def is_version_supported(self, version):
        api_ver = api_versions.get_api_version(version)
        max_api_ver = api_versions.get_api_version(
            self.get_max_microversion())
        return max_api_ver >= api_ver

    def is_not_found(self, ex):
        return isinstance(ex, (exceptions.NotFound,
                               q_exceptions.NotFound))

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.OverLimit)

    def is_bad_request(self, ex):
        return isinstance(ex, exceptions.BadRequest)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def is_unprocessable_entity(self, ex):
        http_status = (getattr(ex, 'http_status', None) or
                       getattr(ex, 'code', None))
        return (isinstance(ex, exceptions.ClientException) and
                http_status == 422)

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            max(cfg.CONF.client_retry_limit + 1, 0)),
        retry=tenacity.retry_if_exception(
            client_plugin.retry_if_connection_err),
        reraise=True)
    def get_server(self, server):
        """Return fresh server object.

        Substitutes Nova's NotFound for Heat's EntityNotFound,
        to be returned to user as HTTP error.
        """
        try:
            return self.client().servers.get(server)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Server', name=server)

    def fetch_server(self, server_id):
        """Fetch fresh server object from Nova.

        Log warnings and return None for non-critical API errors.
        Use this method in various ``check_*_complete`` resource methods,
        where intermittent errors can be tolerated.
        """
        server = None
        try:
            server = self.client().servers.get(server_id)
        except exceptions.OverLimit as exc:
            LOG.warning("Received an OverLimit response when "
                        "fetching server (%(id)s) : %(exception)s",
                        {'id': server_id,
                         'exception': exc})
        except exceptions.ClientException as exc:
            if ((getattr(exc, 'http_status', getattr(exc, 'code', None)) in
                 (500, 503))):
                LOG.warning("Received the following exception when "
                            "fetching server (%(id)s) : %(exception)s",
                            {'id': server_id,
                             'exception': exc})
            else:
                raise
        return server

    def refresh_server(self, server):
        """Refresh server's attributes.

        Also log warnings for non-critical API errors.
        """
        try:
            server.get()
        except exceptions.OverLimit as exc:
            LOG.warning("Server %(name)s (%(id)s) received an OverLimit "
                        "response during server.get(): %(exception)s",
                        {'name': server.name,
                         'id': server.id,
                         'exception': exc})
        except exceptions.ClientException as exc:
            if ((getattr(exc, 'http_status', getattr(exc, 'code', None)) in
                 (500, 503))):
                LOG.warning('Server "%(name)s" (%(id)s) received the '
                            'following exception during server.get(): '
                            '%(exception)s',
                            {'name': server.name,
                             'id': server.id,
                             'exception': exc})
            else:
                raise

    def get_ip(self, server, net_type, ip_version):
        """Return the server's IP of the given type and version."""
        if net_type in server.addresses:
            for ip in server.addresses[net_type]:
                if ip['version'] == ip_version:
                    return ip['addr']

    def get_status(self, server):
        """Return the server's status.

        :param server: server object
        :returns: status as a string
        """
        # Some clouds append extra (STATUS) strings to the status, strip it
        return server.status.split('(')[0]

    def _check_active(self, server, res_name='Server'):
        """Check server status.

        Accepts both server IDs and server objects.
        Returns True if server is ACTIVE,
        raises errors when server has an ERROR or unknown to Heat status,
        returns False otherwise.

        :param res_name: name of the resource to use in the exception message

        """
        # not checking with is_uuid_like as most tests use strings e.g. '1234'
        if isinstance(server, six.string_types):
            server = self.fetch_server(server)
            if server is None:
                return False
            else:
                status = self.get_status(server)
        else:
            status = self.get_status(server)
            if status != 'ACTIVE':
                self.refresh_server(server)
                status = self.get_status(server)

        if status in self.deferred_server_statuses:
            return False
        elif status == 'ACTIVE':
            return True
        elif status == 'ERROR':
            fault = getattr(server, 'fault', {})
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_("Message: %(message)s, Code: %(code)s") % {
                    'message': fault.get('message', _('Unknown')),
                    'code': fault.get('code', _('Unknown'))
                })
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=server.status,
                result=_('%s is not active') % res_name)

    def find_flavor_by_name_or_id(self, flavor):
        """Find the specified flavor by name or id.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        """
        return self._find_flavor_id(self.context.tenant_id,
                                    flavor)

    @os_client.MEMOIZE_FINDER
    def _find_flavor_id(self, tenant_id, flavor):
        # tenant id in the signature is used for the memoization key,
        # that would differentiate similar resource names across tenants.
        return self.get_flavor(flavor).id

    def get_flavor(self, flavor_identifier):
        """Get the flavor object for the specified flavor name or id.

        :param flavor_identifier: the name or id of the flavor to find
        :returns: a flavor object with name or id :flavor:
        """
        try:
            flavor = self.client().flavors.get(flavor_identifier)
        except exceptions.NotFound:
            flavor = self.client().flavors.find(name=flavor_identifier)

        return flavor

    def get_host(self, host_name):
        """Get the host id specified by name.

        :param host_name: the name of host to find
        :returns: the list of match hosts
        :raises exception.EntityNotFound:
        """

        host_list = self.client().hosts.list()
        for host in host_list:
            if host.host_name == host_name and host.service == self.COMPUTE:
                return host

        raise exception.EntityNotFound(entity='Host', name=host_name)

    def get_keypair(self, key_name):
        """Get the public key specified by :key_name:

        :param key_name: the name of the key to look for
        :returns: the keypair (name, public_key) for :key_name:
        :raises exception.EntityNotFound:
        """
        try:
            return self.client().keypairs.get(key_name)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Key', name=key_name)

    def build_userdata(self, metadata, userdata=None, instance_user=None,
                       user_data_format='HEAT_CFNTOOLS'):
        """Build multipart data blob for CloudInit.

        Data blob includes user-supplied Metadata, user data, and the required
        Heat in-instance configuration.

        :param resource: the resource implementation
        :type resource: heat.engine.Resource
        :param userdata: user data string
        :type userdata: str or None
        :param instance_user: the user to create on the server
        :type instance_user: string
        :param user_data_format: Format of user data to return
        :type user_data_format: string
        :returns: multipart mime as a string
        """

        if user_data_format == 'RAW':
            return userdata

        is_cfntools = user_data_format == 'HEAT_CFNTOOLS'
        is_software_config = user_data_format == 'SOFTWARE_CONFIG'

        def make_subpart(content, filename, subtype=None):
            if subtype is None:
                subtype = os.path.splitext(filename)[0]
            if content is None:
                content = ''
            try:
                content.encode('us-ascii')
                charset = 'us-ascii'
            except UnicodeEncodeError:
                charset = 'utf-8'
            msg = (text.MIMEText(content, _subtype=subtype, _charset=charset)
                   if subtype else text.MIMEText(content, _charset=charset))

            msg.add_header('Content-Disposition', 'attachment',
                           filename=filename)
            return msg

        def read_cloudinit_file(fn):
            return pkgutil.get_data(
                'heat', 'cloudinit/%s' % fn).decode('utf-8')

        if instance_user:
            config_custom_user = 'user: %s' % instance_user
            # FIXME(shadower): compatibility workaround for cloud-init 0.6.3.
            # We can drop this once we stop supporting 0.6.3 (which ships
            # with Ubuntu 12.04 LTS).
            #
            # See bug https://bugs.launchpad.net/heat/+bug/1257410
            boothook_custom_user = r"""useradd -m %s
echo -e '%s\tALL=(ALL)\tNOPASSWD: ALL' >> /etc/sudoers
""" % (instance_user, instance_user)
        else:
            config_custom_user = ''
            boothook_custom_user = ''

        cloudinit_config = string.Template(
            read_cloudinit_file('config')).safe_substitute(
                add_custom_user=config_custom_user)
        cloudinit_boothook = string.Template(
            read_cloudinit_file('boothook.sh')).safe_substitute(
                add_custom_user=boothook_custom_user)

        attachments = [(cloudinit_config, 'cloud-config'),
                       (cloudinit_boothook, 'boothook.sh', 'cloud-boothook'),
                       (read_cloudinit_file('part_handler.py'),
                        'part-handler.py')]
        if is_cfntools:
            attachments.append((userdata, 'cfn-userdata', 'x-cfninitdata'))
        elif is_software_config:
            # attempt to parse userdata as a multipart message, and if it
            # is, add each part as an attachment
            userdata_parts = None
            try:
                userdata_parts = email.message_from_string(userdata)
            except Exception:
                pass
            if userdata_parts and userdata_parts.is_multipart():
                for part in userdata_parts.get_payload():
                    attachments.append((part.get_payload(),
                                        part.get_filename(),
                                        part.get_content_subtype()))
            else:
                attachments.append((userdata, ''))

        if is_cfntools:
            attachments.append((read_cloudinit_file('loguserdata.py'),
                               'loguserdata.py', 'x-shellscript'))

        if metadata:
            attachments.append((jsonutils.dumps(metadata),
                                'cfn-init-data', 'x-cfninitdata'))

        if is_cfntools:
            heat_client_plugin = self.context.clients.client_plugin('heat')
            cfn_md_url = heat_client_plugin.get_cfn_metadata_server_url()
            attachments.append((cfn_md_url,
                                'cfn-metadata-server', 'x-cfninitdata'))

            # Create a boto config which the cfntools on the host use to know
            # where the cfn API is to be accessed
            cfn_url = urlparse.urlparse(cfn_md_url)
            is_secure = cfg.CONF.instance_connection_is_secure
            vcerts = cfg.CONF.instance_connection_https_validate_certificates
            boto_cfg = "\n".join(["[Boto]",
                                  "debug = 0",
                                  "is_secure = %s" % is_secure,
                                  "https_validate_certificates = %s" % vcerts,
                                  "cfn_region_name = heat",
                                  "cfn_region_endpoint = %s" %
                                  cfn_url.hostname])
            attachments.append((boto_cfg,
                                'cfn-boto-cfg', 'x-cfninitdata'))

        subparts = [make_subpart(*args) for args in attachments]
        mime_blob = multipart.MIMEMultipart(_subparts=subparts)

        return mime_blob.as_string()

    def check_delete_server_complete(self, server_id):
        """Wait for server to disappear from Nova."""
        try:
            server = self.fetch_server(server_id)
        except Exception as exc:
            self.ignore_not_found(exc)
            return True
        if not server:
            return False
        task_state_in_nova = getattr(server, 'OS-EXT-STS:task_state', None)
        # the status of server won't change until the delete task has done
        if task_state_in_nova == 'deleting':
            return False

        status = self.get_status(server)
        if status == 'DELETED':
            return True

        if status == 'SOFT_DELETED':
            self.client().servers.force_delete(server_id)
        elif status == 'ERROR':
            fault = getattr(server, 'fault', {})
            message = fault.get('message', 'Unknown')
            code = fault.get('code')
            errmsg = _("Server %(name)s delete failed: (%(code)s) "
                       "%(message)s") % dict(name=server.name,
                                             code=code,
                                             message=message)
            raise exception.ResourceInError(resource_status=status,
                                            status_reason=errmsg)
        return False

    def rename(self, server, name):
        """Update the name for a server."""
        server.update(name)

    def resize(self, server_id, flavor_id):
        """Resize the server."""
        server = self.fetch_server(server_id)
        if server:
            server.resize(flavor_id)
            return True
        else:
            return False

    def check_resize(self, server_id, flavor):
        """Verify that a resizing server is properly resized.

        If that's the case, confirm the resize, if not raise an error.
        """
        server = self.fetch_server(server_id)
        # resize operation is asynchronous so the server resize may not start
        # when checking server status (the server may stay ACTIVE instead
        # of RESIZE).
        if not server or server.status in ('RESIZE', 'ACTIVE'):
            return False
        if server.status == 'VERIFY_RESIZE':
            return True
        else:
            raise exception.Error(
                _("Resizing to '%(flavor)s' failed, status '%(status)s'") %
                dict(flavor=flavor, status=server.status))

    def verify_resize(self, server_id):
        server = self.fetch_server(server_id)
        if not server:
            return False
        status = self.get_status(server)
        if status == 'VERIFY_RESIZE':
            server.confirm_resize()
            return True
        else:
            msg = _("Could not confirm resize of server %s") % server_id
            raise exception.ResourceUnknownStatus(
                result=msg, resource_status=status)

    def check_verify_resize(self, server_id):
        server = self.fetch_server(server_id)
        if not server:
            return False
        status = self.get_status(server)
        if status == 'ACTIVE':
            return True
        if status == 'VERIFY_RESIZE':
            return False
        else:
            msg = _("Confirm resize for server %s failed") % server_id
            raise exception.ResourceUnknownStatus(
                result=msg, resource_status=status)

    def rebuild(self, server_id, image_id, password=None,
                preserve_ephemeral=False, meta=None, files=None):
        """Rebuild the server and call check_rebuild to verify."""
        server = self.fetch_server(server_id)
        if server:
            server.rebuild(image_id, password=password,
                           preserve_ephemeral=preserve_ephemeral,
                           meta=meta, files=files)
            return True
        else:
            return False

    def check_rebuild(self, server_id):
        """Verify that a rebuilding server is rebuilt.

        Raise error if it ends up in an ERROR state.
        """
        server = self.fetch_server(server_id)
        if server is None or server.status == 'REBUILD':
            return False
        if server.status == 'ERROR':
            raise exception.Error(
                _("Rebuilding server failed, status '%s'") % server.status)
        else:
            return True

    def meta_serialize(self, metadata):
        """Serialize non-string metadata values before sending them to Nova."""
        if not isinstance(metadata, collections.Mapping):
            raise exception.StackValidationFailed(message=_(
                "nova server metadata needs to be a Map."))

        return dict((key, (value if isinstance(value,
                                               six.string_types)
                           else jsonutils.dumps(value))
                     ) for (key, value) in metadata.items())

    def meta_update(self, server, metadata):
        """Delete/Add the metadata in nova as needed."""
        metadata = self.meta_serialize(metadata)
        current_md = server.metadata
        to_del = sorted(set(current_md) - set(metadata))
        client = self.client()
        if len(to_del) > 0:
            client.servers.delete_meta(server, to_del)

        client.servers.set_meta(server, metadata)

    def server_to_ipaddress(self, server):
        """Return the server's IP address, fetching it from Nova."""
        try:
            server = self.client().servers.get(server)
        except exceptions.NotFound as ex:
            LOG.warning('Instance (%(server)s) not found: %(ex)s',
                        {'server': server, 'ex': ex})
        else:
            for n in sorted(server.networks, reverse=True):
                if len(server.networks[n]) > 0:
                    return server.networks[n][0]

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            max(cfg.CONF.client_retry_limit + 1, 0)),
        retry=tenacity.retry_if_exception(
            client_plugin.retry_if_connection_err),
        reraise=True)
    def absolute_limits(self):
        """Return the absolute limits as a dictionary."""
        limits = self.client().limits.get()
        return dict([(limit.name, limit.value)
                    for limit in list(limits.absolute)])

    def get_console_urls(self, server):
        """Return dict-like structure of server's console urls.

        The actual console url is lazily resolved on access.
        """
        nc = self.client

        class ConsoleUrls(collections.Mapping):
            def __init__(self, server):
                self.console_method = server.get_console_url
                self.support_console_types = ['novnc', 'xvpvnc',
                                              'spice-html5', 'rdp-html5',
                                              'serial', 'webmks']

            def __getitem__(self, key):
                try:
                    if key not in self.support_console_types:
                        raise exceptions.UnsupportedConsoleType(key)
                    if key == 'webmks':
                        data = nc().servers.get_console_url(
                            server, key)
                    else:
                        data = self.console_method(key)
                    console_data = data.get(
                        'remote_console', data.get('console'))
                    url = console_data['url']
                except exceptions.UnsupportedConsoleType as ex:
                    url = ex.message
                except Exception as e:
                    url = _('Cannot get console url: %s') % six.text_type(e)

                return url

            def __len__(self):
                return len(self.support_console_types)

            def __iter__(self):
                return (key for key in self.support_console_types)

        return ConsoleUrls(server)

    def attach_volume(self, server_id, volume_id, device):
        try:
            va = self.client().volumes.create_server_volume(
                server_id=server_id,
                volume_id=volume_id,
                device=device)
        except Exception as ex:
            if self.is_client_exception(ex):
                raise exception.Error(_(
                    "Failed to attach volume %(vol)s to server %(srv)s "
                    "- %(err)s") % {'vol': volume_id,
                                    'srv': server_id,
                                    'err': ex})
            else:
                raise
        return va.id

    def detach_volume(self, server_id, attach_id):
        # detach the volume using volume_attachment
        try:
            self.client().volumes.delete_server_volume(server_id, attach_id)
        except Exception as ex:
            if not (self.is_not_found(ex)
                    or self.is_bad_request(ex)):
                raise exception.Error(
                    _("Could not detach attachment %(att)s "
                      "from server %(srv)s.") % {'srv': server_id,
                                                 'att': attach_id})

    def check_detach_volume_complete(self, server_id, attach_id):
        """Check that nova server lost attachment.

        This check is needed for immediate reattachment when updating:
        there might be some time between cinder marking volume as 'available'
        and nova removing attachment from its own objects, so we
        check that nova already knows that the volume is detached.
        """
        try:
            self.client().volumes.get_server_volume(server_id, attach_id)
        except Exception as ex:
            self.ignore_not_found(ex)
            LOG.info("Volume %(vol)s is detached from server %(srv)s",
                     {'vol': attach_id, 'srv': server_id})
            return True
        else:
            LOG.debug("Server %(srv)s still has attachment %(att)s.",
                      {'att': attach_id, 'srv': server_id})
            return False

    def associate_floatingip(self, server_id, floatingip_id):
        iface_list = self.fetch_server(server_id).interface_list()
        if len(iface_list) == 0:
            raise client_exception.InterfaceNotFound(id=server_id)
        if len(iface_list) > 1:
            LOG.warning("Multiple interfaces found for server %s, "
                        "using the first one.", server_id)

        port_id = iface_list[0].port_id
        fixed_ips = iface_list[0].fixed_ips
        fixed_address = next(ip['ip_address'] for ip in fixed_ips
                             if netutils.is_valid_ipv4(ip['ip_address']))
        request_body = {
            'floatingip': {
                'port_id': port_id,
                'fixed_ip_address': fixed_address}}

        self.clients.client('neutron').update_floatingip(floatingip_id,
                                                         request_body)

    def dissociate_floatingip(self, floatingip_id):
        request_body = {
            'floatingip': {
                'port_id': None,
                'fixed_ip_address': None}}
        self.clients.client('neutron').update_floatingip(floatingip_id,
                                                         request_body)

    def associate_floatingip_address(self, server_id, fip_address):
        fips = self.clients.client(
            'neutron').list_floatingips(
                floating_ip_address=fip_address)['floatingips']
        if len(fips) == 0:
            args = {'ip_address': fip_address}
            raise client_exception.EntityMatchNotFound(entity='floatingip',
                                                       args=args)
        self.associate_floatingip(server_id, fips[0]['id'])

    def dissociate_floatingip_address(self, fip_address):
        fips = self.clients.client(
            'neutron').list_floatingips(
                floating_ip_address=fip_address)['floatingips']
        if len(fips) == 0:
            args = {'ip_address': fip_address}
            raise client_exception.EntityMatchNotFound(entity='floatingip',
                                                       args=args)
        self.dissociate_floatingip(fips[0]['id'])

    def interface_detach(self, server_id, port_id):
        with self.ignore_not_found:
            server = self.fetch_server(server_id)
            if server:
                server.interface_detach(port_id)
                return True

    def interface_attach(self, server_id, port_id=None, net_id=None, fip=None,
                         security_groups=None):
        server = self.fetch_server(server_id)
        if server:
            attachment = server.interface_attach(port_id, net_id, fip)
            if not port_id and security_groups:
                props = {'security_groups': security_groups}
                self.clients.client('neutron').update_port(
                    attachment.port_id, {'port': props})
            return True
        else:
            return False

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            cfg.CONF.max_interface_check_attempts),
        wait=tenacity.wait_exponential(multiplier=0.5, max=12.0),
        retry=tenacity.retry_if_result(client_plugin.retry_if_result_is_false))
    def check_interface_detach(self, server_id, port_id):
        with self.ignore_not_found:
            server = self.fetch_server(server_id)
            if server:
                interfaces = server.interface_list()
                for iface in interfaces:
                    if iface.port_id == port_id:
                        return False
        return True

    @tenacity.retry(
        stop=tenacity.stop_after_attempt(
            cfg.CONF.max_interface_check_attempts),
        wait=tenacity.wait_fixed(0.5),
        retry=tenacity.retry_if_result(client_plugin.retry_if_result_is_false))
    def check_interface_attach(self, server_id, port_id):
        if not port_id:
            return True

        server = self.fetch_server(server_id)
        if server:
            interfaces = server.interface_list()
            for iface in interfaces:
                if iface.port_id == port_id:
                    return True
        return False

    @os_client.MEMOIZE_EXTENSIONS
    def _list_extensions(self):
        extensions = self.client().list_extensions.show_all()
        return set(extension.alias for extension in extensions)

    def has_extension(self, alias):
        """Check if specific extension is present."""
        return alias in self._list_extensions()


class NovaBaseConstraint(constraints.BaseCustomConstraint):

    resource_client_name = CLIENT_NAME


class ServerConstraint(NovaBaseConstraint):

    resource_getter_name = 'get_server'


class KeypairConstraint(NovaBaseConstraint):

    resource_getter_name = 'get_keypair'

    def validate_with_client(self, client, key_name):
        if not key_name:
            # Don't validate empty key, which can happen when you
            # use a KeyPair resource
            return True
        super(KeypairConstraint, self).validate_with_client(client, key_name)


class FlavorConstraint(NovaBaseConstraint):

    expected_exceptions = (exceptions.NotFound,)

    resource_getter_name = 'find_flavor_by_name_or_id'


class HostConstraint(NovaBaseConstraint):

    resource_getter_name = 'get_host'
