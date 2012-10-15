# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

"""
Client side of the heat engine RPC API.
"""

from heat.openstack.common import cfg
from heat.openstack.common import exception
from heat.openstack.common import rpc
from heat.openstack.common.rpc import common as rpc_common
import heat.openstack.common.rpc.proxy


FLAGS = cfg.CONF


def _engine_topic(topic, ctxt, host):
    '''Get the topic to use for a message.

    :param topic: the base topic
    :param ctxt: request context
    :param host: explicit host to send the message to.

    :returns: A topic string
    '''
    if not host:
        host = cfg.CONF.host
    return rpc.queue_get_for(ctxt, topic, host)


class EngineAPI(heat.openstack.common.rpc.proxy.RpcProxy):
    '''Client side of the heat engine rpc API.

    API version history:

        1.0 - Initial version.
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        super(EngineAPI, self).__init__(
                topic=FLAGS.engine_topic,
                default_version=self.BASE_RPC_API_VERSION)

    def identify_stack(self, ctxt, stack_name):
        """
        The identify_stack method returns the full stack identifier for a
        single, live stack given the stack name.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('identify_stack',
                                             stack_name=stack_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def show_stack(self, ctxt, stack_identity):
        """
        The show_stack method returns the attributes of one stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to see,
                           or None to see all
        :param params: Dict of http request parameters passed in from API side.
        """
        return self.call(ctxt, self.make_msg('show_stack',
                                             stack_identity=stack_identity),
                         topic=_engine_topic(self.topic, ctxt, None))

    def create_stack(self, ctxt, stack_name, template, params, args):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param args: Request parameters/args passed from API
        """
        return self.call(ctxt,
                         self.make_msg('create_stack', stack_name=stack_name,
                                       template=template,
                                       params=params, args=args),
                         topic=_engine_topic(self.topic, ctxt, None))

    def update_stack(self, ctxt, stack_identity, template, params, args):
        """
        The update_stack method updates an existing stack based on the
        provided template and parameters.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param args: Request parameters/args passed from API
        """
        return self.call(ctxt, self.make_msg('update_stack',
                                             stack_identity=stack_identity,
                                             template=template,
                                             params=params, args=args),
                         topic=_engine_topic(self.topic, ctxt, None))

    def validate_template(self, ctxt, template):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        :param ctxt: RPC context.
        :param template: Template of stack you want to create.
        :param params: Params passed from API.
        """
        return self.call(ctxt, self.make_msg('validate_template',
                                             template=template),
                         topic=_engine_topic(self.topic, ctxt, None))

    def get_template(self, ctxt, stack_identity):
        """
        Get the template.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see.
        :param params: Dict of http request parameters passed in from API side.
        """
        return self.call(ctxt, self.make_msg('get_template',
                                             stack_identity=stack_identity),
                         topic=_engine_topic(self.topic, ctxt, None))

    def delete_stack(self, ctxt, stack_identity, cast=True):
        """
        The delete_stack method deletes a given stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to delete.
        :param params: Params passed from API.
        """
        rpc_method = self.cast if cast else self.call
        return rpc_method(ctxt, self.make_msg('delete_stack',
                                              stack_identity=stack_identity),
                  topic=_engine_topic(self.topic, ctxt, None))

    def list_events(self, ctxt, stack_identity):
        """
        The list_events method lists all events associated with a given stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to get events for.
        :param params: Params passed from API.
        """
        return self.call(ctxt, self.make_msg('list_events',
                                             stack_identity=stack_identity),
                         topic=_engine_topic(self.topic, ctxt, None))

    def describe_stack_resource(self, ctxt, stack_identity, resource_name):
        return self.call(ctxt, self.make_msg('describe_stack_resource',
                                             stack_identity=stack_identity,
                                             resource_name=resource_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def describe_stack_resources(self, ctxt, stack_identity,
                                 physical_resource_id, logical_resource_id):
        return self.call(ctxt, self.make_msg('describe_stack_resources',
                         stack_identity=stack_identity,
                         physical_resource_id=physical_resource_id,
                         logical_resource_id=logical_resource_id),
                         topic=_engine_topic(self.topic, ctxt, None))

    def list_stack_resources(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('list_stack_resources',
                                             stack_identity=stack_identity),
                         topic=_engine_topic(self.topic, ctxt, None))

    def metadata_list_stacks(self, ctxt):
        """
        Return the names of the stacks registered with Heat.
        """
        return self.call(ctxt, self.make_msg('metadata_list_stacks'),
                         topic=_engine_topic(self.topic, ctxt, None))

    def metadata_list_resources(self, ctxt, stack_name):
        """
        Return the resource IDs of the given stack.
        """
        return self.call(ctxt, self.make_msg('metadata_list_resources',
                         stack_name=stack_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def metadata_get_resource(self, ctxt, stack_name, resource_name):
        """
        Get the metadata for the given resource.
        """
        return self.call(ctxt, self.make_msg('metadata_get_resource',
                         stack_name=stack_name, resource_name=resource_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def metadata_update(self, ctxt, stack_id, resource_name, metadata):
        """
        Update the metadata for the given resource.
        """
        return self.call(ctxt, self.make_msg('metadata_update',
                         stack_id=stack_id,
                         resource_name=resource_name, metadata=metadata),
                         topic=_engine_topic(self.topic, ctxt, None))

    def event_create(self, ctxt, event):
        return self.call(ctxt, self.make_msg('event_create',
                         event=event),
                         topic=_engine_topic(self.topic, ctxt, None))

    def create_watch_data(self, ctxt, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        '''
        return self.call(ctxt, self.make_msg('create_watch_data',
                         watch_name=watch_name, stats_data=stats_data),
                         topic=_engine_topic(self.topic, ctxt, None))

    def show_watch(self, ctxt, watch_name):
        """
        The show_watch method returns the attributes of one watch
        or all watches if no watch_name is passed

        :param ctxt: RPC context.
        :param watch_name: Name of the watch/alarm you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('show_watch',
                         watch_name=watch_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def show_watch_metric(self, ctxt, namespace=None, metric_name=None):
        """
        The show_watch_metric method returns the datapoints associated
        with a specified metric, or all metrics if no metric_name is passed

        :param ctxt: RPC context.
        :param namespace: Name of the namespace you want to see,
                           or None to see all
        :param metric_name: Name of the metric you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('show_watch_metric',
                         namespace=namespace, metric_name=metric_name),
                         topic=_engine_topic(self.topic, ctxt, None))

    def set_watch_state(self, ctxt, watch_name, state):
        '''
        Temporarily set the state of a given watch
        arg1 -> RPC context.
        arg2 -> Name of the watch
        arg3 -> State (must be one defined in WatchRule class)
        '''
        return self.call(ctxt, self.make_msg('set_watch_state',
                         watch_name=watch_name, state=state),
                         topic=_engine_topic(self.topic, ctxt, None))
