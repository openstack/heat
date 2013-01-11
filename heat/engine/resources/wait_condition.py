# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import eventlet
import time
import urllib
import urlparse

from heat.common import exception
from heat.common import identifier
from heat.engine import resource

from heat.openstack.common import log as logging

from heat.openstack.common import cfg

# FIXME : we should remove the common.ec2signer fallback implementation
# when the versions of keystoneclient we support all have the Ec2Signer
# utility class
# Ref https://review.openstack.org/#/c/16964/
# https://blueprints.launchpad.net/keystone/+spec/ec2signer-to-keystoneclient
try:
    from keystoneclient.contrib.ec2.utils import Ec2Signer
except ImportError:
    from heat.common.ec2signer import Ec2Signer

logger = logging.getLogger(__name__)


class WaitConditionHandle(resource.Resource):
    '''
    the main point of this class is to :
    have no dependancies (so the instance can reference it)
    generate a unique url (to be returned in the refernce)
    then the cfn-signal will use this url to post to and
    WaitCondition will poll it to see if has been written to.
    '''
    properties_schema = {}

    def __init__(self, name, json_snippet, stack):
        super(WaitConditionHandle, self).__init__(name, json_snippet, stack)

    def _sign_url(self, credentials, path):
        """
        Create properly formatted and pre-signed URL using supplied credentials
        See http://docs.amazonwebservices.com/AWSECommerceService/latest/DG/
            rest-signature.html
        Also see boto/auth.py::QuerySignatureV2AuthHandler
        """
        host_url = urlparse.urlparse(cfg.CONF.heat_waitcondition_server_url)
        # Note the WSGI spec apparently means that the webob request we end up
        # prcessing in the CFN API (ec2token.py) has an unquoted path, so we
        # need to calculate the signature with the path component unquoted, but
        # ensure the actual URL contains the quoted version...
        unquoted_path = urllib.unquote(host_url.path + path)
        request = {'host': host_url.netloc.lower(),
                   'verb': 'PUT',
                   'path': unquoted_path,
                   'params': {'SignatureMethod': 'HmacSHA256',
                              'SignatureVersion': '2',
                              'AWSAccessKeyId': credentials.access,
                              'Timestamp': time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                         time.gmtime())}}
        # Sign the request
        signer = Ec2Signer(credentials.secret)
        request['params']['Signature'] = signer.generate(request)

        qs = urllib.urlencode(request['params'])
        url = "%s%s?%s" % (cfg.CONF.heat_waitcondition_server_url.lower(),
                           path, qs)
        return url

    def handle_create(self):
        # Create a keystone user so we can create a signed URL via FnGetRefId
        user_id = self.keystone().create_stack_user(
            self.physical_resource_name())
        kp = self.keystone().get_ec2_keypair(user_id)
        if not kp:
            raise exception.Error("Error creating ec2 keypair for user %s" %
                                  user_id)
        else:
            self.resource_id_set(user_id)

    def handle_delete(self):
        if self.resource_id is None:
            return
        self.keystone().delete_stack_user(self.resource_id)

    def handle_update(self):
        return self.UPDATE_REPLACE

    def FnGetRefId(self):
        '''
        Override the default resource FnGetRefId so we return the signed URL
        '''
        if self.resource_id:
            urlpath = self.identifier().arn_url_path()
            ec2_creds = self.keystone().get_ec2_keypair(self.resource_id)
            signed_url = self._sign_url(ec2_creds, urlpath)
            return unicode(signed_url)
        else:
            return unicode(self.name)

    def metadata_update(self, metadata):
        '''
        Update the resource metadata
        '''
        self.metadata = metadata


WAIT_STATUSES = (
    WAITING,
    TIMEDOUT,
    SUCCESS,
) = (
    'WAITING',
    'TIMEDOUT',
    'SUCCESS',
)


class WaitCondition(resource.Resource):
    properties_schema = {'Handle': {'Type': 'String',
                                    'Required': True},
                         'Timeout': {'Type': 'Number',
                                     'Required': True,
                                     'MinValue': '1'},
                         'Count': {'Type': 'Number',
                                   'MinValue': '1'}}

    # Sleep time between polling for wait completion
    # is calculated as a fraction of timeout time
    # bounded by MIN_SLEEP and MAX_SLEEP
    MIN_SLEEP = 1  # seconds
    MAX_SLEEP = 10
    SLEEP_DIV = 100  # 1/100'th of timeout

    def __init__(self, name, json_snippet, stack):
        super(WaitCondition, self).__init__(name, json_snippet, stack)

        self.timeout = int(self.t['Properties']['Timeout'])
        self.count = int(self.t['Properties'].get('Count', '1'))
        self.sleep_time = max(min(self.MAX_SLEEP,
                              self.timeout / self.SLEEP_DIV),
                              self.MIN_SLEEP)

    def _get_handle_resource_name(self):
        handle_url = self.properties['Handle']
        handle_id = identifier.ResourceIdentifier.from_arn_url(handle_url)
        return handle_id.resource_name

    def _get_status_reason(self, handle):
        return (handle.metadata.get('Status', WAITING),
                handle.metadata.get('Reason', 'Reason not provided'))

    def _create_timeout(self):
        return eventlet.Timeout(self.timeout)

    def handle_create(self):
        tmo = None
        try:
            # keep polling our Metadata to see if the cfn-signal has written
            # it yet. The execution here is limited by timeout.
            with self._create_timeout() as tmo:
                handle_res_name = self._get_handle_resource_name()
                handle = self.stack[handle_res_name]
                self.resource_id_set(handle_res_name)

                (status, reason) = (WAITING, '')

                while status == WAITING:
                    (status, reason) = self._get_status_reason(handle)
                    if status == WAITING:
                        logger.debug('Polling for WaitCondition completion,' +
                                     ' sleeping for %s seconds, timeout %s' %
                                     (self.sleep_time, self.timeout))
                        eventlet.sleep(self.sleep_time)

        except eventlet.Timeout as t:
            if t is not tmo:
                # not my timeout
                raise
            else:
                (status, reason) = (TIMEDOUT, 'Timed out waiting for instance')

        if status != SUCCESS:
            raise exception.Error(reason)

    def handle_update(self):
        return self.UPDATE_REPLACE

    def handle_delete(self):
        if self.resource_id is None:
            return

        handle = self.stack[self.resource_id]
        handle.metadata = {}

    def FnGetAtt(self, key):
        res = None
        if key == 'Data':
            try:
                meta = self.metadata
                if meta and 'Data' in meta:
                    res = meta['Data']
            except Exception as ex:
                pass

        else:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        logger.debug('%s.GetAtt(%s) == %s' % (self.name, key, res))
        return unicode(res)


def resource_mapping():
    return {
        'AWS::CloudFormation::WaitCondition': WaitCondition,
        'AWS::CloudFormation::WaitConditionHandle': WaitConditionHandle,
    }
