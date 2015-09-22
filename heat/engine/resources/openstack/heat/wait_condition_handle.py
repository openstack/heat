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

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine.resources.aws.cfn import wait_condition_handle as aws_wch
from heat.engine.resources import wait_condition as wc_base
from heat.engine import support


class HeatWaitConditionHandle(wc_base.BaseWaitConditionHandle):

    support_status = support.SupportStatus(version='2014.2')

    METADATA_KEYS = (
        DATA, REASON, STATUS, UNIQUE_ID
    ) = (
        'data', 'reason', 'status', 'id'
    )

    ATTRIBUTES = (
        TOKEN,
        ENDPOINT,
        CURL_CLI,
    ) = (
        'token',
        'endpoint',
        'curl_cli',
    )

    attributes_schema = {
        TOKEN: attributes.Schema(
            _('Token for stack-user which can be used for signalling handle'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        ENDPOINT: attributes.Schema(
            _('Endpoint/url which can be used for signalling handle'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        CURL_CLI: attributes.Schema(
            _('Convenience attribute, provides curl CLI command '
              'prefix, which can be used for signalling handle completion or '
              'failure.  You can signal success by adding '
              '--data-binary \'{"status": "SUCCESS"}\' '
              ', or signal failure by adding '
              '--data-binary \'{"status": "FAILURE"}\''),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
    }

    def handle_create(self):
        self.password = uuid.uuid4().hex
        super(HeatWaitConditionHandle, self).handle_create()
        # FIXME(shardy): The assumption here is that token expiry > timeout
        # but we probably need a check here to fail fast if that's not true
        # Also need to implement an update property, such that the handle
        # can be replaced on update which will replace the token
        token = self._user_token()
        self.data_set('token', token, True)
        self.data_set('endpoint', '%s/signal' % self._get_resource_endpoint())

    def _get_resource_endpoint(self):
        # Get the endpoint from stack.clients then replace the context
        # project_id with the path to the resource (which includes the
        # context project_id), then replace the context project with
        # the one needed for signalling from the stack_user_project
        heat_client_plugin = self.stack.clients.client_plugin('heat')
        endpoint = heat_client_plugin.get_heat_url()
        rsrc_ep = endpoint.replace(self.context.tenant_id,
                                   self.identifier().url_path())
        return rsrc_ep.replace(self.context.tenant_id,
                               self.stack.stack_user_project_id)

    def _resolve_attribute(self, key):
        if self.resource_id:
            if key == self.TOKEN:
                return self.data().get('token')
            elif key == self.ENDPOINT:
                return self.data().get('endpoint')
            elif key == self.CURL_CLI:
                # Construct curl command for template-author convenience
                return ("curl -i -X POST "
                        "-H 'X-Auth-Token: %(token)s' "
                        "-H 'Content-Type: application/json' "
                        "-H 'Accept: application/json' "
                        "%(endpoint)s" %
                        dict(token=self.data().get('token'),
                             endpoint=self.data().get('endpoint')))

    def handle_signal(self, details=None):
        """Validate and update the resource metadata.

        Metadata is not mandatory, but if passed it must use the following
        format:
        {
            "status" : "Status (must be SUCCESS or FAILURE)",
            "data" : "Arbitrary data",
            "reason" : "Reason string"
        }
        Optionally "id" may also be specified, but if missing the index
        of the signal received will be used.
        """
        rsrc_metadata = self.metadata_get(refresh=True)
        signal_num = len(rsrc_metadata) + 1
        reason = 'Signal %s received' % signal_num
        # Tolerate missing values, default to success
        metadata = details or {}
        metadata.setdefault(self.REASON, reason)
        metadata.setdefault(self.DATA, None)
        metadata.setdefault(self.UNIQUE_ID, signal_num)
        metadata.setdefault(self.STATUS, self.STATUS_SUCCESS)
        return super(HeatWaitConditionHandle, self).handle_signal(metadata)


class UpdateWaitConditionHandle(aws_wch.WaitConditionHandle):
    """WaitConditionHandle that clears signals and changes handle on update.

    This works identically to a regular WaitConditionHandle, except that
    on update it clears all signals received and changes the handle. Using
    this handle means that you must setup the signal senders to send their
    signals again any time the update handle changes. This allows us to roll
    out new configurations and be confident that they are rolled out once
    UPDATE COMPLETE is reached.
    """

    support_status = support.SupportStatus(version='2014.1')

    def update(self, after, before=None, prev_resource=None):
        raise exception.UpdateReplace(self.name)


def resource_mapping():
    return {
        'OS::Heat::WaitConditionHandle': HeatWaitConditionHandle,
        'OS::Heat::UpdateWaitConditionHandle': UpdateWaitConditionHandle,
    }
