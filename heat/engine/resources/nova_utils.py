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
"""Utilities for Resources that use the OpenStack Nova API."""

import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
from novaclient import exceptions as nova_exceptions
import os
import pkgutil
import string

from oslo.config import cfg
import six
from six.moves.urllib import parse as urlparse
import warnings

from heat.common import exception
from heat.common.i18n import _
from heat.engine import scheduler
from heat.openstack.common import log as logging

LOG = logging.getLogger(__name__)


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


def refresh_server(server):
    '''
    Refresh server's attributes and log warnings for non-critical API errors.
    '''
    warnings.warn('nova_utils.refresh_server is deprecated. '
                  'Use self.client_plugin("nova").refresh_server')
    try:
        server.get()
    except nova_exceptions.OverLimit as exc:
        msg = _("Server %(name)s (%(id)s) received an OverLimit "
                "response during server.get(): %(exception)s")
        LOG.warning(msg % {'name': server.name,
                           'id': server.id,
                           'exception': exc})
    except nova_exceptions.ClientException as exc:
        http_status = (getattr(exc, 'http_status', None) or
                       getattr(exc, 'code', None))
        if http_status in (500, 503):
            msg = _('Server "%(name)s" (%(id)s) received the following '
                    'exception during server.get(): %(exception)s')
            LOG.warning(msg % {'name': server.name,
                               'id': server.id,
                               'exception': exc})
        else:
            raise


def get_ip(server, net_type, ip_version):
    """Return the server's IP of the given type and version."""
    warnings.warn('nova_utils.get_ip is deprecated. '
                  'Use self.client_plugin("nova").get_ip')
    if net_type in server.addresses:
        for ip in server.addresses[net_type]:
            if ip['version'] == ip_version:
                return ip['addr']


def get_flavor_id(nova_client, flavor):
    warnings.warn('nova_utils.get_flavor_id is deprecated. '
                  'Use self.client_plugin("nova").get_flavor_id')
    '''
    Get the id for the specified flavor name.
    If the specified value is flavor id, just return it.

    :param nova_client: the nova client to use
    :param flavor: the name of the flavor to find
    :returns: the id of :flavor:
    :raises: exception.FlavorMissing
    '''
    flavor_id = None
    flavor_list = nova_client.flavors.list()
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


def get_keypair(nova_client, key_name):
    warnings.warn('nova_utils.get_keypair is deprecated. '
                  'Use self.client_plugin("nova").get_keypair')
    '''
    Get the public key specified by :key_name:

    :param nova_client: the nova client to use
    :param key_name: the name of the key to look for
    :returns: the keypair (name, public_key) for :key_name:
    :raises: exception.UserKeyPairMissing
    '''
    try:
        return nova_client.keypairs.get(key_name)
    except nova_exceptions.NotFound:
        raise exception.UserKeyPairMissing(key_name=key_name)


def build_userdata(resource, userdata=None, instance_user=None,
                   user_data_format='HEAT_CFNTOOLS'):
    warnings.warn('nova_utils.build_userdata is deprecated. '
                  'Use self.client_plugin("nova").build_userdata')
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
        # FIXME(shadower): compatibility workaround for cloud-init 0.6.3. We
        # can drop this once we stop supporting 0.6.3 (which ships with Ubuntu
        # 12.04 LTS).
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

    metadata = resource.metadata_get()
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


def delete_server(server):
    '''
    A co-routine that deletes the server and waits for it to
    disappear from Nova.
    '''
    warnings.warn('nova_utils.delete_server is deprecated. '
                  'Use self.client_plugin("nova").delete_server')
    if not server:
        return
    try:
        server.delete()
    except nova_exceptions.NotFound:
        return

    while True:
        yield

        try:
            refresh_server(server)
        except nova_exceptions.NotFound:
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
def resize(server, flavor, flavor_id):
    """Resize the server and then call check_resize task to verify."""
    warnings.warn('nova_utils.resize is deprecated. '
                  'Use self.client_plugin("nova").resize')
    server.resize(flavor_id)
    yield check_resize(server, flavor, flavor_id)


def rename(server, name):
    """Update the name for a server."""
    warnings.warn('nova_utils.rename is deprecated. '
                  'Use self.client_plugin("nova").rename')
    server.update(name)


def check_resize(server, flavor, flavor_id):
    """
    Verify that a resizing server is properly resized.
    If that's the case, confirm the resize, if not raise an error.
    """
    warnings.warn('nova_utils.check_resize is deprecated. '
                  'Use self.client_plugin("nova").check_resize')
    refresh_server(server)
    while server.status == 'RESIZE':
        yield
        refresh_server(server)
    if server.status == 'VERIFY_RESIZE':
        server.confirm_resize()
    else:
        raise exception.Error(
            _("Resizing to '%(flavor)s' failed, status '%(status)s'") %
            dict(flavor=flavor, status=server.status))


@scheduler.wrappertask
def rebuild(server, image_id, preserve_ephemeral=False):
    """Rebuild the server and call check_rebuild to verify."""
    warnings.warn('nova_utils.rebuild is deprecated. '
                  'Use self.client_plugin("nova").rebuild')
    server.rebuild(image_id, preserve_ephemeral=preserve_ephemeral)
    yield check_rebuild(server, image_id)


def check_rebuild(server, image_id):
    """
    Verify that a rebuilding server is rebuilt.
    Raise error if it ends up in an ERROR state.
    """
    warnings.warn('nova_utils.check_rebuild is deprecated. '
                  'Use self.client_plugin("nova").check_rebuild')
    refresh_server(server)
    while server.status == 'REBUILD':
        yield
        refresh_server(server)
    if server.status == 'ERROR':
        raise exception.Error(
            _("Rebuilding server failed, status '%s'") % server.status)


def meta_serialize(metadata):
    """
    Serialize non-string metadata values before sending them to
    Nova.
    """
    warnings.warn('nova_utils.meta_serialize is deprecated. '
                  'Use self.client_plugin("nova").meta_serialize')
    return dict((key, (value if isinstance(value,
                                           six.string_types)
                       else json.dumps(value))
                 ) for (key, value) in metadata.items())


def meta_update(client, server, metadata):
    """Delete/Add the metadata in nova as needed."""
    warnings.warn('nova_utils.meta_update is deprecated. '
                  'Use self.client_plugin("nova").meta_update')
    metadata = meta_serialize(metadata)
    current_md = server.metadata
    to_del = [key for key in current_md.keys() if key not in metadata]
    if len(to_del) > 0:
        client.servers.delete_meta(server, to_del)

    client.servers.set_meta(server, metadata)


def server_to_ipaddress(client, server):
    '''
    Return the server's IP address, fetching it from Nova.
    '''
    warnings.warn('nova_utils.server_to_ipaddress is deprecated. '
                  'Use self.client_plugin("nova").server_to_ipaddress')
    try:
        server = client.servers.get(server)
    except nova_exceptions.NotFound as ex:
        LOG.warn(_('Instance (%(server)s) not found: %(ex)s')
                 % {'server': server, 'ex': ex})
    else:
        for n in server.networks:
            if len(server.networks[n]) > 0:
                return server.networks[n][0]


def absolute_limits(nova_client):
    """Return the absolute limits as a dictionary."""
    warnings.warn('nova_utils.absolute_limits is deprecated. '
                  'Use self.client_plugin("nova").absolute_limits')
    limits = nova_client.limits.get()
    return dict([(limit.name, limit.value) for limit in list(limits.absolute)])
