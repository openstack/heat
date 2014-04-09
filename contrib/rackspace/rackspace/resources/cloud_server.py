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

import copy
import socket
import tempfile

from Crypto.PublicKey import RSA
import paramiko

from heat.common import exception
from heat.db.sqlalchemy import api as db_api
from heat.engine.resources import nova_utils
from heat.engine.resources import server
from heat.openstack.common.gettextutils import _
from heat.openstack.common import log as logging

try:
    import pyrax  # noqa
    PYRAX_INSTALLED = True
except ImportError:
    PYRAX_INSTALLED = False

logger = logging.getLogger(__name__)


class CloudServer(server.Server):
    """Resource for Rackspace Cloud Servers."""

    SCRIPT_INSTALL_REQUIREMENTS = {
        'ubuntu': """
apt-get update
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -o Dpkg::Options::="--force-confdef" -o \
  Dpkg::Options::="--force-confold" python-boto python-pip gcc python-dev
pip install heat-cfntools
cfn-create-aws-symlinks --source /usr/local/bin
""",
        'fedora': """
yum install -y python-boto python-pip gcc python-devel
pip-python install heat-cfntools
cfn-create-aws-symlinks
""",
        'centos': """
if ! (yum repolist 2> /dev/null | egrep -q "^[\!\*]?epel ");
then
 rpm -ivh http://mirror.rackspace.com/epel/6/i386/epel-release-6-8.noarch.rpm
fi
yum install -y python-boto python-pip gcc python-devel python-argparse
pip-python install heat-cfntools
""",
        'rhel': """
if ! (yum repolist 2> /dev/null | egrep -q "^[\!\*]?epel ");
then
 rpm -ivh http://mirror.rackspace.com/epel/6/i386/epel-release-6-8.noarch.rpm
fi
# The RPM DB stays locked for a few secs
while fuser /var/lib/rpm/*; do sleep 1; done
yum install -y python-boto python-pip gcc python-devel python-argparse
pip-python install heat-cfntools
cfn-create-aws-symlinks
""",
        'debian': """
echo "deb http://mirror.rackspace.com/debian wheezy-backports main" >> \
  /etc/apt/sources.list
apt-get update
apt-get -t wheezy-backports install -y cloud-init
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -o Dpkg::Options::="--force-confdef" -o \
  Dpkg::Options::="--force-confold" python-pip gcc python-dev
pip install heat-cfntools
"""}

    SCRIPT_CREATE_DATA_SOURCE = """
sed -i 's/ConfigDrive/NoCloud/' /etc/cloud/cloud.cfg.d/*
rm -rf /var/lib/cloud
mkdir -p /var/lib/cloud/seed/nocloud-net
mv /tmp/userdata /var/lib/cloud/seed/nocloud-net/user-data
touch /var/lib/cloud/seed/nocloud-net/meta-data
chmod 600 /var/lib/cloud/seed/nocloud-net/*
"""

    SCRIPT_RUN_CLOUD_INIT = """
cloud-init start || cloud-init init
"""

    SCRIPT_RUN_CFN_USERDATA = """
bash -x /var/lib/cloud/data/cfn-userdata > /root/cfn-userdata.log 2>&1 ||
  exit 42
"""

    SCRIPT_ERROR_MSG = _("The %(path)s script exited with a non-zero exit "
                         "status.  To see the error message, log into the "
                         "server at %(ip)s and view %(log)s")

    # Managed Cloud automation statuses
    MC_STATUS_IN_PROGRESS = 'In Progress'
    MC_STATUS_COMPLETE = 'Complete'
    MC_STATUS_BUILD_ERROR = 'Build Error'

    # RackConnect automation statuses
    RC_STATUS_DEPLOYING = 'DEPLOYING'
    RC_STATUS_DEPLOYED = 'DEPLOYED'
    RC_STATUS_FAILED = 'FAILED'
    RC_STATUS_UNPROCESSABLE = 'UNPROCESSABLE'

    attributes_schema = copy.deepcopy(server.Server.attributes_schema)
    attributes_schema.update(
        {
            'distro': _('The Linux distribution on the server.'),
            'privateIPv4': _('The private IPv4 address of the server.'),
        }
    )

    def __init__(self, name, json_snippet, stack):
        super(CloudServer, self).__init__(name, json_snippet, stack)
        self.stack = stack
        self._private_key = None
        self._server = None
        self._distro = None
        self._image = None
        self._retry_iterations = 0
        self._managed_cloud_started_event_sent = False
        self._rack_connect_started_event_sent = False

    @property
    def server(self):
        """Return the Cloud Server object."""
        if self._server is None:
            self._server = self.nova().servers.get(self.resource_id)
        return self._server

    @property
    def distro(self):
        """Return the Linux distribution for this server."""
        image = self.properties.get(self.IMAGE)
        if self._distro is None and image:
            image_data = self.nova().images.get(self.image)
            self._distro = image_data.metadata['os_distro']
        return self._distro

    @property
    def script(self):
        """
        Return the config script for the Cloud Server image.

        The config script performs the following steps:
        1) Install cloud-init
        2) Create cloud-init data source
        3) Run cloud-init
        4) If user_data_format is 'HEAT_CFNTOOLS', run cfn-userdata script
        """
        base_script = (self.SCRIPT_INSTALL_REQUIREMENTS[self.distro] +
                       self.SCRIPT_CREATE_DATA_SOURCE +
                       self.SCRIPT_RUN_CLOUD_INIT)
        userdata_format = self.properties.get(self.USER_DATA_FORMAT)
        if userdata_format == 'HEAT_CFNTOOLS':
            return base_script + self.SCRIPT_RUN_CFN_USERDATA
        elif userdata_format == 'RAW':
            return base_script

    @property
    def image(self):
        """Return the server's image ID."""
        image = self.properties.get(self.IMAGE)
        if image and self._image is None:
            self._image = nova_utils.get_image_id(self.nova(), image)
        return self._image

    @property
    def private_key(self):
        """Return the private SSH key for the resource."""
        if self._private_key is not None:
            return self._private_key
        if self.id is not None:
            self._private_key = db_api.resource_data_get(self, 'private_key')
            return self._private_key

    @private_key.setter
    def private_key(self, private_key):
        """Save the resource's private SSH key to the database."""
        self._private_key = private_key
        if self.id is not None:
            db_api.resource_data_set(self, 'private_key', private_key, True)

    @property
    def has_userdata(self):
        """Return True if the server has user_data, False otherwise."""
        user_data = self.properties.get(self.USER_DATA)
        if user_data or self.metadata != {}:
            return True
        else:
            return False

    def validate(self):
        """Validate user parameters."""
        image = self.properties.get(self.IMAGE)

        # It's okay if there's no script, as long as user_data and
        # metadata are both empty
        if image and self.script is None and self.has_userdata:
            msg = _("user_data is not supported for image %s.") % image
            raise exception.StackValidationFailed(message=msg)

        # Validate that the personality does not contain a reserved
        # key and that the number of personalities does not exceed the
        # Rackspace limit.
        personality = self.properties.get(self.PERSONALITY)
        if personality:
            limits = nova_utils.absolute_limits(self.nova())

            # One personality will be used for an SSH key
            personality_limit = limits['maxPersonality'] - 1

            if "/root/.ssh/authorized_keys" in personality:
                msg = _('The personality property may not contain a key '
                        'of "/root/.ssh/authorized_keys"')
                raise exception.StackValidationFailed(message=msg)

            elif len(personality) > personality_limit:
                msg = _("The personality property may not contain greater "
                        "than %s entries.") % personality_limit
                raise exception.StackValidationFailed(message=msg)

        super(CloudServer, self).validate()

        # Validate that user_data is passed for servers with bootable
        # volumes AFTER validating that the server has either an image
        # or a bootable volume in Server.validate()
        if not image and self.has_userdata:
            msg = _("user_data scripts are not supported with bootable "
                    "volumes.")
            raise exception.StackValidationFailed(message=msg)

    def _run_ssh_command(self, command):
        """Run a shell command on the Cloud Server via SSH."""
        with tempfile.NamedTemporaryFile() as private_key_file:
            private_key_file.write(self.private_key)
            private_key_file.seek(0)
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.MissingHostKeyPolicy())
            ssh.connect(self.server.accessIPv4,
                        username="root",
                        key_filename=private_key_file.name)
            chan = ssh.get_transport().open_session()
            chan.settimeout(self.stack.timeout_secs())
            chan.exec_command(command)
            try:
                # The channel timeout only works for read/write operations
                chan.recv(1024)
            except socket.timeout:
                raise exception.Error(
                    _("SSH command timed out after %s seconds") %
                    self.stack.timeout_secs())
            else:
                return chan.recv_exit_status()
            finally:
                ssh.close()
                chan.close()

    def _sftp_files(self, files):
        """Transfer files to the Cloud Server via SFTP."""

        if self._retry_iterations > 30:
            raise exception.Error(_("Failed to establish SSH connection after "
                                    "30 tries"))
        self._retry_iterations += 1

        try:
            transport = paramiko.Transport((self.server.accessIPv4, 22))
        except paramiko.SSHException:
            logger.debug("Failed to get SSH transport, will retry")
            return False
        with tempfile.NamedTemporaryFile() as private_key_file:
            private_key_file.write(self.private_key)
            private_key_file.seek(0)
            pkey = paramiko.RSAKey.from_private_key_file(private_key_file.name)
            try:
                transport.connect(hostkey=None, username="root", pkey=pkey)
            except EOFError:
                logger.debug("Failed to connect to SSH transport, will retry")
                return False
            sftp = paramiko.SFTPClient.from_transport(transport)
            try:
                for remote_file in files:
                    sftp_file = sftp.open(remote_file['path'], 'w')
                    sftp_file.write(remote_file['data'])
                    sftp_file.close()
            except:
                raise
            finally:
                sftp.close()
                transport.close()

    def _personality(self):
        # Generate SSH public/private keypair for the engine to use
        if self._private_key is not None:
            rsa = RSA.importKey(self._private_key)
        else:
            rsa = RSA.generate(1024)
        self.private_key = rsa.exportKey()
        public_keys = [rsa.publickey().exportKey('OpenSSH')]

        # Add the user-provided key_name to the authorized_keys file
        key_name = self.properties.get(self.KEY_NAME)
        if key_name:
            user_keypair = nova_utils.get_keypair(self.nova(), key_name)
            public_keys.append(user_keypair.public_key)
        personality = {"/root/.ssh/authorized_keys": '\n'.join(public_keys)}

        # Add any user-provided personality files
        user_personality = self.properties.get(self.PERSONALITY)
        if user_personality:
            personality.update(user_personality)

        return personality

    def _key_name(self):
        return None

    def _check_managed_cloud_complete(self, server):
        if not self._managed_cloud_started_event_sent:
            msg = _("Waiting for Managed Cloud automation to complete")
            self._add_event(self.action, self.status, msg)
            self._managed_cloud_started_event_sent = True

        if 'rax_service_level_automation' not in server.metadata:
            logger.debug(_("Managed Cloud server does not have the "
                           "rax_service_level_automation metadata tag yet"))
            return False

        mc_status = server.metadata['rax_service_level_automation']
        logger.debug(_("Managed Cloud automation status: %s") % mc_status)

        if mc_status == self.MC_STATUS_IN_PROGRESS:
            return False

        elif mc_status == self.MC_STATUS_COMPLETE:
            msg = _("Managed Cloud automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif mc_status == self.MC_STATUS_BUILD_ERROR:
            raise exception.Error(_("Managed Cloud automation failed"))

        else:
            raise exception.Error(_("Unknown Managed Cloud automation "
                                    "status: %s") % mc_status)

    def _check_rack_connect_complete(self, server):
        if not self._rack_connect_started_event_sent:
            msg = _("Waiting for RackConnect automation to complete")
            self._add_event(self.action, self.status, msg)
            self._rack_connect_started_event_sent = True

        if 'rackconnect_automation_status' not in server.metadata:
            logger.debug(_("RackConnect server does not have the "
                           "rackconnect_automation_status metadata tag yet"))
            return False

        rc_status = server.metadata['rackconnect_automation_status']
        logger.debug(_("RackConnect automation status: %s") % rc_status)

        if rc_status == self.RC_STATUS_DEPLOYING:
            return False

        elif rc_status == self.RC_STATUS_DEPLOYED:
            self._server = None  # The public IP changed, forget old one
            return True

        elif rc_status == self.RC_STATUS_UNPROCESSABLE:
            # UNPROCESSABLE means the RackConnect automation was not
            # attempted (eg. Cloud Server in a different DC than
            # dedicated gear, so RackConnect does not apply).  It is
            # okay if we do not raise an exception.
            reason = server.metadata.get('rackconnect_unprocessable_reason',
                                         None)
            if reason is not None:
                logger.warning(_("RackConnect unprocessable reason: %s") %
                               reason)

            msg = _("RackConnect automation has completed")
            self._add_event(self.action, self.status, msg)
            return True

        elif rc_status == self.RC_STATUS_FAILED:
            raise exception.Error(_("RackConnect automation FAILED"))

        else:
            msg = _("Unknown RackConnect automation status: %s") % rc_status
            raise exception.Error(msg)

    def _run_userdata(self):
        msg = _("Running user_data")
        self._add_event(self.action, self.status, msg)

        # Create heat-script and userdata files on server
        raw_userdata = self.properties[self.USER_DATA]
        userdata = nova_utils.build_userdata(self, raw_userdata)

        files = [{'path': "/tmp/userdata", 'data': userdata},
                 {'path': "/root/heat-script.sh", 'data': self.script}]
        if self._sftp_files(files) is False:
            return False

        # Connect via SSH and run script
        cmd = "bash -ex /root/heat-script.sh > /root/heat-script.log 2>&1"
        exit_code = self._run_ssh_command(cmd)
        if exit_code == 42:
            raise exception.Error(self.SCRIPT_ERROR_MSG %
                                  {'path': "cfn-userdata",
                                   'ip': self.server.accessIPv4,
                                   'log': "/root/cfn-userdata.log"})
        elif exit_code != 0:
            raise exception.Error(self.SCRIPT_ERROR_MSG %
                                  {'path': "heat-script.sh",
                                   'ip': self.server.accessIPv4,
                                   'log': "/root/heat-script.log"})

        msg = _("Successfully ran user_data")
        self._add_event(self.action, self.status, msg)

    def check_create_complete(self, server):
        """Check if server creation is complete and handle server configs."""
        if not self._check_active(server):
            return False

        nova_utils.refresh_server(server)

        if 'rack_connect' in self.context.roles and not \
           self._check_rack_connect_complete(server):
            return False

        if 'rax_managed' in self.context.roles and not \
           self._check_managed_cloud_complete(server):
            return False

        if self.has_userdata:
            if self._run_userdata() is False:
                return False

        return True

    def _resolve_attribute(self, name):
        if name == 'distro':
            return self.distro
        if name == 'privateIPv4':
            return nova_utils.get_ip(self.server, 'private', 4)
        return super(CloudServer, self)._resolve_attribute(name)


def resource_mapping():
    return {'Rackspace::Cloud::Server': CloudServer}


def available_resource_mapping():
    if PYRAX_INSTALLED:
        return resource_mapping()
    return {}
