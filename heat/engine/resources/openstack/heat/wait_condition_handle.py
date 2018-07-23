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

from oslo_serialization import jsonutils

from heat.common.i18n import _
from heat.common import password_gen
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources.aws.cfn import wait_condition_handle as aws_wch
from heat.engine.resources import signal_responder
from heat.engine.resources import wait_condition as wc_base
from heat.engine import support


class HeatWaitConditionHandle(wc_base.BaseWaitConditionHandle):
    """Resource for managing instance signals.

    The main points of this resource are:
      - have no dependencies (so the instance can reference it).
      - create credentials to allow for signalling from the instance.
      - handle signals from the instance, validate and store result.
    """

    support_status = support.SupportStatus(version='2014.2')

    PROPERTIES = (
        SIGNAL_TRANSPORT,
    ) = (
        'signal_transport',
    )

    SIGNAL_TRANSPORTS = (
        CFN_SIGNAL, TEMP_URL_SIGNAL, HEAT_SIGNAL, NO_SIGNAL,
        ZAQAR_SIGNAL, TOKEN_SIGNAL
    ) = (
        'CFN_SIGNAL', 'TEMP_URL_SIGNAL', 'HEAT_SIGNAL', 'NO_SIGNAL',
        'ZAQAR_SIGNAL', 'TOKEN_SIGNAL'
    )

    properties_schema = {
        SIGNAL_TRANSPORT: properties.Schema(
            properties.Schema.STRING,
            _('How the client will signal the wait condition. CFN_SIGNAL '
              'will allow an HTTP POST to a CFN keypair signed URL. '
              'TEMP_URL_SIGNAL will create a Swift TempURL to be '
              'signalled via HTTP PUT. HEAT_SIGNAL will allow calls to the '
              'Heat API resource-signal using the provided keystone '
              'credentials. ZAQAR_SIGNAL will create a dedicated zaqar queue '
              'to be signalled using the provided keystone credentials. '
              'TOKEN_SIGNAL will allow and HTTP POST to a Heat API endpoint '
              'with the provided keystone token. NO_SIGNAL will result in '
              'the resource going to a signalled state without waiting for '
              'any signal.'),
            default='TOKEN_SIGNAL',
            constraints=[
                constraints.AllowedValues(SIGNAL_TRANSPORTS),
            ],
            support_status=support.SupportStatus(version='6.0.0'),
        ),
    }

    ATTRIBUTES = (
        TOKEN,
        ENDPOINT,
        CURL_CLI,
        SIGNAL,
    ) = (
        'token',
        'endpoint',
        'curl_cli',
        'signal',
    )

    attributes_schema = {
        TOKEN: attributes.Schema(
            _('Token for stack-user which can be used for signalling handle '
              'when signal_transport is set to TOKEN_SIGNAL. None for all '
              'other signal transports.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        ENDPOINT: attributes.Schema(
            _('Endpoint/url which can be used for signalling handle when '
              'signal_transport is set to TOKEN_SIGNAL. None for all '
              'other signal transports.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        CURL_CLI: attributes.Schema(
            _('Convenience attribute, provides curl CLI command '
              'prefix, which can be used for signalling handle completion or '
              'failure when signal_transport is set to TOKEN_SIGNAL. You '
              'can signal success by adding '
              '--data-binary \'{"status": "SUCCESS"}\' '
              ', or signal failure by adding '
              '--data-binary \'{"status": "FAILURE"}\'. '
              'This attribute is set to None for all other signal '
              'transports.'),

            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        ),
        SIGNAL: attributes.Schema(
            _('JSON serialized map that includes the endpoint, token and/or '
              'other attributes the client must use for signalling this '
              'handle. The contents of this map depend on the type of signal '
              'selected in the signal_transport property.'),
            cache_mode=attributes.Schema.CACHE_NONE,
            type=attributes.Schema.STRING
        )
    }

    METADATA_KEYS = (
        DATA, REASON, STATUS, UNIQUE_ID
    ) = (
        'data', 'reason', 'status', 'id'
    )

    def _signal_transport_token(self):
        return self.properties.get(
            self.SIGNAL_TRANSPORT) == self.TOKEN_SIGNAL

    def handle_create(self):
        self.password = password_gen.generate_openstack_password()
        super(HeatWaitConditionHandle, self).handle_create()
        if self._signal_transport_token():
            # FIXME(shardy): The assumption here is that token expiry > timeout
            # but we probably need a check here to fail fast if that's not true
            # Also need to implement an update property, such that the handle
            # can be replaced on update which will replace the token
            token = self._user_token()
            self.data_set('token', token, True)
            self.data_set('endpoint',
                          '%s/signal' % self._get_resource_endpoint())

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
            if key == self.SIGNAL:
                return jsonutils.dumps(self._get_signal(
                    signal_type=signal_responder.WAITCONDITION,
                    multiple_signals=True))
            elif key == self.TOKEN:
                return self.data().get('token')
            elif key == self.ENDPOINT:
                return self.data().get('endpoint')
            elif key == self.CURL_CLI:
                # Construct curl command for template-author convenience
                endpoint = self.data().get('endpoint')
                token = self.data().get('token')
                if endpoint is None or token is None:
                    return None
                heat_client_plugin = self.stack.clients.client_plugin('heat')
                insecure_option = heat_client_plugin.get_insecure_option()
                return ("curl %(insecure)s-i -X POST "
                        "-H 'X-Auth-Token: %(token)s' "
                        "-H 'Content-Type: application/json' "
                        "-H 'Accept: application/json' "
                        "%(endpoint)s" %
                        dict(insecure="--insecure " if insecure_option else "",
                             token=token, endpoint=endpoint))

    def get_status(self):
        # before we check status, we have to update the signal transports
        # that require constant polling
        self._service_signal()

        return super(HeatWaitConditionHandle, self).get_status()

    def handle_signal(self, details=None):
        """Validate and update the resource metadata.

        Metadata is not mandatory, but if passed it must use the following
        format::

            {
                "status" : "Status (must be SUCCESS or FAILURE)",
                "data" : "Arbitrary data",
                "reason" : "Reason string"
            }

        Optionally "id" may also be specified, but if missing the index
        of the signal received will be used.
        """
        return super(HeatWaitConditionHandle, self).handle_signal(details)

    def normalise_signal_data(self, signal_data, latest_metadata):
        signal_num = len(latest_metadata) + 1
        reason = 'Signal %s received' % signal_num
        # Tolerate missing values, default to success
        metadata = signal_data.copy() if signal_data else {}
        metadata.setdefault(self.REASON, reason)
        metadata.setdefault(self.DATA, None)
        metadata.setdefault(self.UNIQUE_ID, signal_num)
        metadata.setdefault(self.STATUS, self.STATUS_SUCCESS)
        return metadata


class UpdateWaitConditionHandle(aws_wch.WaitConditionHandle):
    """WaitConditionHandle that clears signals and changes handle on update.

    This works similarly to an AWS::CloudFormation::WaitConditionHandle, except
    that on update it clears all signals received and changes the handle. Using
    this handle means that you must setup the signal senders to send their
    signals again any time the update handle changes. This allows us to roll
    out new configurations and be confident that they are rolled out once
    UPDATE COMPLETE is reached.
    """

    support_status = support.SupportStatus(version='2014.1')

    def update(self, after, before=None, prev_resource=None):
        raise resource.UpdateReplace(self.name)


def resource_mapping():
    return {
        'OS::Heat::WaitConditionHandle': HeatWaitConditionHandle,
        'OS::Heat::UpdateWaitConditionHandle': UpdateWaitConditionHandle,
    }
