#
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

from heat.common import messaging
from heat.rpc import api as rpc_api


class EngineClient(object):
    '''Client side of the heat engine rpc API.

    API version history::

        1.0 - Initial version.
        1.1 - Add support_status argument to list_resource_types()
        1.4 - Add support for service list
    '''

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        self._client = messaging.get_rpc_client(
            topic=rpc_api.ENGINE_TOPIC,
            version=self.BASE_RPC_API_VERSION)

    @staticmethod
    def make_msg(method, **kwargs):
        return method, kwargs

    def call(self, ctxt, msg, version=None):
        method, kwargs = msg
        if version is not None:
            client = self._client.prepare(version=version)
        else:
            client = self._client
        return client.call(ctxt, method, **kwargs)

    def cast(self, ctxt, msg, version=None):
        method, kwargs = msg
        if version is not None:
            client = self._client.prepare(version=version)
        else:
            client = self._client
        return client.cast(ctxt, method, **kwargs)

    def local_error_name(self, error):
        """
        Returns the name of the error with any _Remote postfix removed.

        :param error: Remote raised error to derive the name from.
        """
        error_name = error.__class__.__name__
        return error_name.split('_Remote')[0]

    def ignore_error_named(self, error, name):
        """
        Raises the error unless its local name matches the supplied name

        :param error: Remote raised error to derive the local name from.
        :param name: Name to compare local name to.
        """
        if self.local_error_name(error) != name:
            raise error

    def identify_stack(self, ctxt, stack_name):
        """
        The identify_stack method returns the full stack identifier for a
        single, live stack given the stack name.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('identify_stack',
                                             stack_name=stack_name))

    def list_stacks(self, ctxt, limit=None, marker=None, sort_keys=None,
                    sort_dir=None, filters=None, tenant_safe=True,
                    show_deleted=False, show_nested=False, show_hidden=False):
        """
        The list_stacks method returns attributes of all stacks.  It supports
        pagination (``limit`` and ``marker``), sorting (``sort_keys`` and
        ``sort_dir``) and filtering (``filters``) of the results.

        :param ctxt: RPC context.
        :param limit: the number of stacks to list (integer or string)
        :param marker: the ID of the last item in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc')
        :param filters: a dict with attribute:value to filter the list
        :param tenant_safe: if true, scope the request by the current tenant
        :param show_deleted: if true, show soft-deleted stacks
        :param show_nested: if true, show nested stacks
        :param show_hidden: if true, show hidden stacks
        :returns: a list of stacks
        """
        return self.call(ctxt,
                         self.make_msg('list_stacks', limit=limit,
                                       sort_keys=sort_keys, marker=marker,
                                       sort_dir=sort_dir, filters=filters,
                                       tenant_safe=tenant_safe,
                                       show_deleted=show_deleted,
                                       show_nested=show_nested,
                                       show_hidden=show_hidden))

    def count_stacks(self, ctxt, filters=None, tenant_safe=True,
                     show_deleted=False, show_nested=False, show_hidden=False):
        """
        Return the number of stacks that match the given filters
        :param ctxt: RPC context.
        :param filters: a dict of ATTR:VALUE to match against stacks
        :param tenant_safe: if true, scope the request by the current tenant
        :param show_deleted: if true, count will include the deleted stacks
        :param show_nested: if true, count will include nested stacks
        :param show_hidden: if true, show hidden stacks
        :returns: a integer representing the number of matched stacks
        """
        return self.call(ctxt, self.make_msg('count_stacks',
                                             filters=filters,
                                             tenant_safe=tenant_safe,
                                             show_deleted=show_deleted,
                                             show_nested=show_nested,
                                             show_hidden=show_hidden))

    def show_stack(self, ctxt, stack_identity):
        """
        Return detailed information about one or all stacks.
        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to show, or None to
        show all
        """
        return self.call(ctxt, self.make_msg('show_stack',
                                             stack_identity=stack_identity))

    def preview_stack(self, ctxt, stack_name, template, params, files, args):
        """
        Simulates a new stack using the provided template.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        """
        return self.call(ctxt,
                         self.make_msg('preview_stack', stack_name=stack_name,
                                       template=template,
                                       params=params, files=files, args=args))

    def create_stack(self, ctxt, stack_name, template, params, files, args):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        """
        return self._create_stack(ctxt, stack_name, template, params, files,
                                  args)

    def _create_stack(self, ctxt, stack_name, template, params, files, args,
                      owner_id=None, nested_depth=0, user_creds_id=None,
                      stack_user_project_id=None):
        """
        Internal create_stack interface for engine-to-engine communication via
        RPC.  Allows some additional options which should not be exposed to
        users via the API:
        :param owner_id: parent stack ID for nested stacks
        :param nested_depth: nested depth for nested stacks
        :param user_creds_id: user_creds record for nested stack
        :param stack_user_project_id: stack user project for nested stack
        """
        return self.call(
            ctxt, self.make_msg('create_stack', stack_name=stack_name,
                                template=template,
                                params=params, files=files, args=args,
                                owner_id=owner_id,
                                nested_depth=nested_depth,
                                user_creds_id=user_creds_id,
                                stack_user_project_id=stack_user_project_id),
            version='1.2')

    def update_stack(self, ctxt, stack_identity, template, params,
                     files, args):
        """
        The update_stack method updates an existing stack based on the
        provided template and parameters.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        """
        return self.call(ctxt, self.make_msg('update_stack',
                                             stack_identity=stack_identity,
                                             template=template,
                                             params=params,
                                             files=files,
                                             args=args))

    def validate_template(self, ctxt, template, params=None):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        :param ctxt: RPC context.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        """
        return self.call(ctxt, self.make_msg('validate_template',
                                             template=template,
                                             params=params))

    def authenticated_to_backend(self, ctxt):
        """
        Verify that the credentials in the RPC context are valid for the
        current cloud backend.

        :param ctxt: RPC context.
        """
        return self.call(ctxt, self.make_msg('authenticated_to_backend'))

    def get_template(self, ctxt, stack_identity):
        """
        Get the template.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see.
        """
        return self.call(ctxt, self.make_msg('get_template',
                                             stack_identity=stack_identity))

    def delete_stack(self, ctxt, stack_identity, cast=True):
        """
        The delete_stack method deletes a given stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to delete.
        :param cast: cast the message or use call (default: True)
        """
        rpc_method = self.cast if cast else self.call
        return rpc_method(ctxt,
                          self.make_msg('delete_stack',
                                        stack_identity=stack_identity))

    def abandon_stack(self, ctxt, stack_identity):
        """
        The abandon_stack method deletes a given stack but
        resources would not be deleted.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to abandon.
        """
        return self.call(ctxt,
                         self.make_msg('abandon_stack',
                                       stack_identity=stack_identity))

    def list_resource_types(self, ctxt, support_status=None):
        """
        Get a list of valid resource types.

        :param ctxt: RPC context.
        """
        return self.call(ctxt, self.make_msg('list_resource_types',
                                             support_status=support_status),
                         version='1.1')

    def resource_schema(self, ctxt, type_name):
        """
        Get the schema for a resource type.

        :param ctxt: RPC context.
        """
        return self.call(ctxt, self.make_msg('resource_schema',
                                             type_name=type_name))

    def generate_template(self, ctxt, type_name):
        """
        Generate a template based on the specified type.

        :param ctxt: RPC context.
        :param type_name: The resource type name to generate a template for.
        """
        return self.call(ctxt, self.make_msg('generate_template',
                                             type_name=type_name))

    def list_events(self, ctxt, stack_identity, filters=None, limit=None,
                    marker=None, sort_keys=None, sort_dir=None,):
        """
        The list_events method lists all events associated with a given stack.
        It supports pagination (``limit`` and ``marker``),
        sorting (``sort_keys`` and ``sort_dir``) and filtering(filters)
        of the results.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to get events for
        :param filters: a dict with attribute:value to filter the list
        :param limit: the number of events to list (integer or string)
        :param marker: the ID of the last event in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc').
        """
        return self.call(ctxt, self.make_msg('list_events',
                                             stack_identity=stack_identity,
                                             filters=filters,
                                             limit=limit,
                                             marker=marker,
                                             sort_keys=sort_keys,
                                             sort_dir=sort_dir))

    def describe_stack_resource(self, ctxt, stack_identity, resource_name,
                                with_attr=None):
        """
        Get detailed resource information about a particular resource.
        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param resource_name: the Resource.
        """
        return self.call(ctxt,
                         self.make_msg('describe_stack_resource',
                                       stack_identity=stack_identity,
                                       resource_name=resource_name,
                                       with_attr=with_attr),
                         version='1.2')

    def find_physical_resource(self, ctxt, physical_resource_id):
        """
        Return an identifier for the resource with the specified physical
        resource ID.
        :param ctxt RPC context.
        :param physcial_resource_id The physical resource ID to look up.
        """
        return self.call(ctxt,
                         self.make_msg(
                             'find_physical_resource',
                             physical_resource_id=physical_resource_id))

    def describe_stack_resources(self, ctxt, stack_identity, resource_name):
        """
        Get detailed resource information about one or more resources.
        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param resource_name: the Resource.
        """
        return self.call(ctxt, self.make_msg('describe_stack_resources',
                                             stack_identity=stack_identity,
                                             resource_name=resource_name))

    def list_stack_resources(self, ctxt, stack_identity, nested_depth=0):
        """
        List the resources belonging to a stack.
        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param nested_depth: Levels of nested stacks of which list resources.
        """
        return self.call(ctxt, self.make_msg('list_stack_resources',
                                             stack_identity=stack_identity,
                                             nested_depth=nested_depth))

    def stack_suspend(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_suspend',
                                             stack_identity=stack_identity))

    def stack_resume(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_resume',
                                             stack_identity=stack_identity))

    def stack_check(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_check',
                                             stack_identity=stack_identity))

    def stack_cancel_update(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_cancel_update',
                                             stack_identity=stack_identity))

    def metadata_update(self, ctxt, stack_identity, resource_name, metadata):
        """
        Update the metadata for the given resource.
        """
        return self.call(ctxt, self.make_msg('metadata_update',
                                             stack_identity=stack_identity,
                                             resource_name=resource_name,
                                             metadata=metadata))

    def resource_signal(self, ctxt, stack_identity, resource_name, details,
                        sync_call=False):
        """
        Generate an alarm on the resource.
        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param resource_name: the Resource.
        :param details: the details of the signal.
        """
        return self.call(ctxt, self.make_msg('resource_signal',
                                             stack_identity=stack_identity,
                                             resource_name=resource_name,
                                             details=details,
                                             sync_call=sync_call),

                         version='1.3')

    def create_watch_data(self, ctxt, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        :param ctxt: RPC context.
        :param watch_name: Name of the watch/alarm
        :param stats_data: The data to post.
        '''
        return self.call(ctxt, self.make_msg('create_watch_data',
                                             watch_name=watch_name,
                                             stats_data=stats_data))

    def show_watch(self, ctxt, watch_name):
        """
        The show_watch method returns the attributes of one watch
        or all watches if no watch_name is passed

        :param ctxt: RPC context.
        :param watch_name: Name of the watch/alarm you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('show_watch',
                                             watch_name=watch_name))

    def show_watch_metric(self, ctxt, metric_namespace=None, metric_name=None):
        """
        The show_watch_metric method returns the datapoints associated
        with a specified metric, or all metrics if no metric_name is passed

        :param ctxt: RPC context.
        :param metric_namespace: Name of the namespace you want to see,
                           or None to see all
        :param metric_name: Name of the metric you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('show_watch_metric',
                                             metric_namespace=metric_namespace,
                                             metric_name=metric_name))

    def set_watch_state(self, ctxt, watch_name, state):
        '''
        Temporarily set the state of a given watch
        :param ctxt: RPC context.
        :param watch_name: Name of the watch
        :param state: State (must be one defined in WatchRule class)
        '''
        return self.call(ctxt, self.make_msg('set_watch_state',
                                             watch_name=watch_name,
                                             state=state))

    def get_revision(self, ctxt):
        return self.call(ctxt, self.make_msg('get_revision'))

    def show_software_config(self, cnxt, config_id):
        return self.call(cnxt, self.make_msg('show_software_config',
                                             config_id=config_id))

    def create_software_config(self, cnxt, group, name, config,
                               inputs=None, outputs=None, options=None):
        inputs = inputs or []
        outputs = outputs or []
        options = options or {}
        return self.call(cnxt, self.make_msg('create_software_config',
                                             group=group,
                                             name=name,
                                             config=config,
                                             inputs=inputs,
                                             outputs=outputs,
                                             options=options))

    def delete_software_config(self, cnxt, config_id):
        return self.call(cnxt, self.make_msg('delete_software_config',
                                             config_id=config_id))

    def list_software_deployments(self, cnxt, server_id=None):
        return self.call(cnxt, self.make_msg('list_software_deployments',
                                             server_id=server_id))

    def metadata_software_deployments(self, cnxt, server_id):
        return self.call(cnxt, self.make_msg('metadata_software_deployments',
                                             server_id=server_id))

    def show_software_deployment(self, cnxt, deployment_id):
        return self.call(cnxt, self.make_msg('show_software_deployment',
                                             deployment_id=deployment_id))

    def create_software_deployment(self, cnxt, server_id, config_id=None,
                                   input_values=None, action='INIT',
                                   status='COMPLETE', status_reason='',
                                   stack_user_project_id=None):
        input_values = input_values or {}
        return self.call(cnxt, self.make_msg(
            'create_software_deployment',
            server_id=server_id,
            config_id=config_id,
            input_values=input_values,
            action=action,
            status=status,
            status_reason=status_reason,
            stack_user_project_id=stack_user_project_id))

    def update_software_deployment(self, cnxt, deployment_id,
                                   config_id=None, input_values=None,
                                   output_values=None, action=None,
                                   status=None, status_reason=None,
                                   updated_at=None):
        return self.call(
            cnxt, self.make_msg('update_software_deployment',
                                deployment_id=deployment_id,
                                config_id=config_id,
                                input_values=input_values,
                                output_values=output_values,
                                action=action,
                                status=status,
                                status_reason=status_reason,
                                updated_at=updated_at),
            version='1.5')

    def delete_software_deployment(self, cnxt, deployment_id):
        return self.call(cnxt, self.make_msg('delete_software_deployment',
                                             deployment_id=deployment_id))

    def signal_software_deployment(self, cnxt, deployment_id, details,
                                   updated_at=None):
        return self.call(
            cnxt, self.make_msg('signal_software_deployment',
                                deployment_id=deployment_id,
                                details=details,
                                updated_at=updated_at),
            version='1.6')

    def stack_snapshot(self, ctxt, stack_identity, name):
        return self.call(ctxt, self.make_msg('stack_snapshot',
                                             stack_identity=stack_identity,
                                             name=name))

    def show_snapshot(self, cnxt, stack_identity, snapshot_id):
        return self.call(cnxt, self.make_msg('show_snapshot',
                                             stack_identity=stack_identity,
                                             snapshot_id=snapshot_id))

    def delete_snapshot(self, cnxt, stack_identity, snapshot_id):
        return self.call(cnxt, self.make_msg('delete_snapshot',
                                             stack_identity=stack_identity,
                                             snapshot_id=snapshot_id))

    def stack_list_snapshots(self, cnxt, stack_identity):
        return self.call(cnxt, self.make_msg('stack_list_snapshots',
                                             stack_identity=stack_identity))

    def stack_restore(self, cnxt, stack_identity, snapshot_id):
        return self.call(cnxt, self.make_msg('stack_restore',
                                             stack_identity=stack_identity,
                                             snapshot_id=snapshot_id))

    def list_services(self, cnxt):
        return self.call(cnxt, self.make_msg('list_services'), version='1.4')
