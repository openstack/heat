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

import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import logging
import os
import pkgutil
import string

from novaclient import client as nc
from novaclient import exceptions
from novaclient import shell as novashell
from oslo.config import cfg
import six
from six.moves.urllib import parse as urlparse

from heat.common import exception
from heat.engine.clients import client_plugin
from heat.engine import scheduler

LOG = logging.getLogger(__name__)


class NovaClientPlugin(client_plugin.ClientPlugin):

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

    def _create(self):
        computeshell = novashell.OpenStackComputeShell()
        extensions = computeshell._discover_extensions("1.1")

        endpoint_type = self._get_client_option('nova', 'endpoint_type')
        args = {
            'project_id': self.context.tenant,
            'auth_url': self.context.auth_url,
            'service_type': 'compute',
            'username': None,
            'api_key': None,
            'extensions': extensions,
            'endpoint_type': endpoint_type,
            'http_log_debug': self._get_client_option('nova',
                                                      'http_log_debug'),
            'cacert': self._get_client_option('nova', 'ca_file'),
            'insecure': self._get_client_option('nova', 'insecure')
        }

        client = nc.Client(1.1, **args)

        management_url = self.url_for(service_type='compute',
                                      endpoint_type=endpoint_type)
        client.client.auth_token = self.auth_token
        client.client.management_url = management_url

        return client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

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

    def refresh_server(self, server):
        '''
        Refresh server's attributes and log warnings for non-critical
        API errors.
        '''
        try:
            server.get()
        except exceptions.OverLimit as exc:
            msg = _("Server %(name)s (%(id)s) received an OverLimit "
                    "response during server.get(): %(exception)s")
            LOG.warning(msg % {'name': server.name,
                               'id': server.id,
                               'exception': exc})
        except exceptions.ClientException as exc:
            if ((getattr(exc, 'http_status', getattr(exc, 'code', None)) in
                 (500, 503))):
                msg = _('Server "%(name)s" (%(id)s) received the following '
                        'exception during server.get(): %(exception)s')
                LOG.warning(msg % {'name': server.name,
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
        '''
        Return the server's status.
        :param server: server object
        :returns: status as a string
        '''
        # Some clouds append extra (STATUS) strings to the status, strip it
        return server.status.split('(')[0]

    def get_flavor_id(self, flavor):
        '''
        Get the id for the specified flavor name.
        If the specified value is flavor id, just return it.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        :raises: exception.FlavorMissing
        '''
        flavor_id = None
        flavor_list = self.client().flavors.list()
        for o in flavor_list:
            if o.name == flavor:
                flavor_id = o.id
                break
            if o.id == flavor:
                flavor_id = o.id
                break
        if flavor_id is None:
            raise exception.FlavorMissing(flavor_id=flavor)
        return flavor_id

    def get_keypair(self, key_name):
        '''
        Get the public key specified by :key_name:

        :param key_name: the name of the key to look for
        :returns: the keypair (name, public_key) for :key_name:
        :raises: exception.UserKeyPairMissing
        '''
        try:
            return self.client().keypairs.get(key_name)
        except exceptions.NotFound:
            raise exception.UserKeyPairMissing(key_name=key_name)

    def build_userdata(self, metadata, userdata=None, instance_user=None,
                       user_data_format='HEAT_CFNTOOLS'):
        '''
        Build multipart data blob for CloudInit which includes user-supplied
        Metadata, user data, and the required Heat in-instance configuration.

        :param resource: the resource implementation
        :type resource: heat.engine.Resource
        :param userdata: user data string
        :type userdata: str or None
        :param instance_user: the user to create on the server
        :type instance_user: string
        :param user_data_format: Format of user data to return
        :type user_data_format: string
        :returns: multipart mime as a string
        '''

        if user_data_format == 'RAW':
            return userdata

        is_cfntools = user_data_format == 'HEAT_CFNTOOLS'
        is_software_config = user_data_format == 'SOFTWARE_CONFIG'

        def make_subpart(content, filename, subtype=None):
            if subtype is None:
                subtype = os.path.splitext(filename)[0]
            msg = MIMEText(content, _subtype=subtype)
            msg.add_header('Content-Disposition', 'attachment',
                           filename=filename)
            return msg

        def read_cloudinit_file(fn):
            return pkgutil.get_data('heat', 'cloudinit/%s' % fn)

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
                attachments.append((userdata, 'userdata', 'x-shellscript'))

        if is_cfntools:
            attachments.append((read_cloudinit_file('loguserdata.py'),
                               'loguserdata.py', 'x-shellscript'))

        if metadata:
            attachments.append((json.dumps(metadata),
                                'cfn-init-data', 'x-cfninitdata'))

        attachments.append((cfg.CONF.heat_watch_server_url,
                            'cfn-watch-server', 'x-cfninitdata'))

        if is_cfntools:
            attachments.append((cfg.CONF.heat_metadata_server_url,
                                'cfn-metadata-server', 'x-cfninitdata'))

            # Create a boto config which the cfntools on the host use to know
            # where the cfn and cw API's are to be accessed
            cfn_url = urlparse.urlparse(cfg.CONF.heat_metadata_server_url)
            cw_url = urlparse.urlparse(cfg.CONF.heat_watch_server_url)
            is_secure = cfg.CONF.instance_connection_is_secure
            vcerts = cfg.CONF.instance_connection_https_validate_certificates
            boto_cfg = "\n".join(["[Boto]",
                                  "debug = 0",
                                  "is_secure = %s" % is_secure,
                                  "https_validate_certificates = %s" % vcerts,
                                  "cfn_region_name = heat",
                                  "cfn_region_endpoint = %s" %
                                  cfn_url.hostname,
                                  "cloudwatch_region_name = heat",
                                  "cloudwatch_region_endpoint = %s" %
                                  cw_url.hostname])
            attachments.append((boto_cfg,
                                'cfn-boto-cfg', 'x-cfninitdata'))

        subparts = [make_subpart(*args) for args in attachments]
        mime_blob = MIMEMultipart(_subparts=subparts)

        return mime_blob.as_string()

    def delete_server(self, server):
        '''
        Deletes a server and waits for it to disappear from Nova.
        '''
        if not server:
            return
        try:
            server.delete()
        except Exception as exc:
            self.ignore_not_found(exc)
            return

        while True:
            yield

            try:
                self.refresh_server(server)
            except Exception as exc:
                self.ignore_not_found(exc)
                break
            else:
                # Some clouds append extra (STATUS) strings to the status
                short_server_status = server.status.split('(')[0]
                if short_server_status == "DELETED":
                    break
                if short_server_status == "ERROR":
                    fault = getattr(server, 'fault', {})
                    message = fault.get('message', 'Unknown')
                    code = fault.get('code')
                    errmsg = (_("Server %(name)s delete failed: (%(code)s) "
                                "%(message)s"))
                    raise exception.Error(errmsg % {"name": server.name,
                                                    "code": code,
                                                    "message": message})

    @scheduler.wrappertask
    def resize(self, server, flavor, flavor_id):
        """Resize the server and then call check_resize task to verify."""
        server.resize(flavor_id)
        yield self.check_resize(server, flavor, flavor_id)

    def rename(self, server, name):
        """Update the name for a server."""
        server.update(name)

    def check_resize(self, server, flavor, flavor_id):
        """
        Verify that a resizing server is properly resized.
        If that's the case, confirm the resize, if not raise an error.
        """
        self.refresh_server(server)
        while server.status == 'RESIZE':
            yield
            self.refresh_server(server)
        if server.status == 'VERIFY_RESIZE':
            server.confirm_resize()
        else:
            raise exception.Error(
                _("Resizing to '%(flavor)s' failed, status '%(status)s'") %
                dict(flavor=flavor, status=server.status))

    @scheduler.wrappertask
    def rebuild(self, server, image_id, preserve_ephemeral=False):
        """Rebuild the server and call check_rebuild to verify."""
        server.rebuild(image_id, preserve_ephemeral=preserve_ephemeral)
        yield self.check_rebuild(server, image_id)

    def check_rebuild(self, server, image_id):
        """
        Verify that a rebuilding server is rebuilt.
        Raise error if it ends up in an ERROR state.
        """
        self.refresh_server(server)
        while server.status == 'REBUILD':
            yield
            self.refresh_server(server)
        if server.status == 'ERROR':
            raise exception.Error(
                _("Rebuilding server failed, status '%s'") % server.status)

    def meta_serialize(self, metadata):
        """
        Serialize non-string metadata values before sending them to
        Nova.
        """
        return dict((key, (value if isinstance(value,
                                               six.string_types)
                           else json.dumps(value))
                     ) for (key, value) in metadata.items())

    def meta_update(self, server, metadata):
        """Delete/Add the metadata in nova as needed."""
        metadata = self.meta_serialize(metadata)
        current_md = server.metadata
        to_del = [key for key in current_md.keys() if key not in metadata]
        client = self.client()
        if len(to_del) > 0:
            client.servers.delete_meta(server, to_del)

        client.servers.set_meta(server, metadata)

    def server_to_ipaddress(self, server):
        '''
        Return the server's IP address, fetching it from Nova.
        '''
        try:
            server = self.client().servers.get(server)
        except exceptions.NotFound as ex:
            LOG.warn(_('Instance (%(server)s) not found: %(ex)s')
                     % {'server': server, 'ex': ex})
        else:
            for n in server.networks:
                if len(server.networks[n]) > 0:
                    return server.networks[n][0]

    def absolute_limits(self):
        """Return the absolute limits as a dictionary."""
        limits = self.client().limits.get()
        return dict([(limit.name, limit.value)
                    for limit in list(limits.absolute)])
