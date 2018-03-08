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

"""Client side of the heat engine RPC API."""

import warnings

from oslo_utils import excutils
from oslo_utils import reflection

from heat.common import messaging
from heat.rpc import api as rpc_api


class EngineClient(object):
    """Client side of the heat engine rpc API.

    API version history::

        1.0 - Initial version.
        1.1 - Add support_status argument to list_resource_types()
        1.4 - Add support for service list
        1.9 - Add template_type option to generate_template()
        1.10 - Add support for software config list
        1.11 - Add support for template versions list
        1.12 - Add with_detail option for stack resources list
        1.13 - Add support for template functions list
        1.14 - Add cancel_with_rollback option to stack_cancel_update
        1.15 - Add preview_update_stack() call
        1.16 - Adds version, type_name to list_resource_types()
        1.17 - Add files to validate_template
        1.18 - Add show_nested to validate_template
        1.19 - Add show_output and list_outputs for returning stack outputs
        1.20 - Add resolve_outputs to stack show
        1.21 - Add deployment_id to create_software_deployment
        1.22 - Add support for stack export
        1.23 - Add environment_files to create/update/preview/validate
        1.24 - Adds ignorable_errors to validate_template
        1.25 - list_stack_resource filter update
        1.26 - Add mark_unhealthy
        1.27 - Add check_software_deployment
        1.28 - Add get_environment call
        1.29 - Add template_id to create_stack/update_stack
        1.30 - Add possibility to resource_type_* return descriptions
        1.31 - Add nested_depth to list_events, when nested_depth is specified
               add root_stack_id to response
        1.32 - Add get_files call
        1.33 - Remove tenant_safe from list_stacks, count_stacks
               and list_software_configs
        1.34 - Add migrate_convergence_1 call
        1.35 - Add with_condition to list_template_functions
        1.36 - Add files_container to create/update/preview/validate
    """

    BASE_RPC_API_VERSION = '1.0'

    def __init__(self):
        self._client = messaging.get_rpc_client(
            topic=rpc_api.ENGINE_TOPIC,
            version=self.BASE_RPC_API_VERSION)

    @staticmethod
    def make_msg(method, **kwargs):
        return method, kwargs

    def call(self, ctxt, msg, version=None, timeout=None):
        method, kwargs = msg

        if version is not None:
            client = self._client.prepare(version=version)
        else:
            client = self._client

        if timeout is not None:
            client = client.prepare(timeout=timeout)

        return client.call(ctxt, method, **kwargs)

    def cast(self, ctxt, msg, version=None):
        method, kwargs = msg
        if version is not None:
            client = self._client.prepare(version=version)
        else:
            client = self._client
        return client.cast(ctxt, method, **kwargs)

    def local_error_name(self, error):
        """Returns the name of the error with any _Remote postfix removed.

        :param error: Remote raised error to derive the name from.
        """
        error_name = reflection.get_class_name(error, fully_qualified=False)
        return error_name.split('_Remote')[0]

    def ignore_error_by_name(self, name):
        """Returns a context manager that filters exceptions with a given name.

        :param name: Name to compare the local exception name to.
        """
        def error_name_matches(err):
            return self.local_error_name(err) == name

        return excutils.exception_filter(error_name_matches)

    def ignore_error_named(self, error, name):
        """Raises the error unless its local name matches the supplied name.

        :param error: Remote raised error to derive the local name from.
        :param name: Name to compare local name to.
        """
        warnings.warn("Use ignore_error_by_name() to get a context manager "
                      "instead.",
                      DeprecationWarning)
        return self.ignore_error_by_name(name)(error)

    def identify_stack(self, ctxt, stack_name):
        """Returns the full stack identifier for a single, live stack.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see,
                           or None to see all
        """
        return self.call(ctxt, self.make_msg('identify_stack',
                                             stack_name=stack_name))

    def list_stacks(self, ctxt, limit=None, marker=None, sort_keys=None,
                    sort_dir=None, filters=None,
                    show_deleted=False, show_nested=False, show_hidden=False,
                    tags=None, tags_any=None, not_tags=None,
                    not_tags_any=None):
        """Returns attributes of all stacks.

        It supports pagination (``limit`` and ``marker``), sorting
        (``sort_keys`` and ``sort_dir``) and filtering (``filters``) of the
        results.

        :param ctxt: RPC context.
        :param limit: the number of stacks to list (integer or string)
        :param marker: the ID of the last item in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc')
        :param filters: a dict with attribute:value to filter the list
        :param show_deleted: if true, show soft-deleted stacks
        :param show_nested: if true, show nested stacks
        :param show_hidden: if true, show hidden stacks
        :param tags: show stacks containing these tags. If multiple tags
            are passed, they will be combined using the boolean AND expression
        :param tags_any: show stacks containing these tags. If multiple tags
            are passed, they will be combined using the boolean OR expression
        :param not_tags: show stacks not containing these tags. If multiple
            tags are passed, they will be combined using the boolean AND
            expression
        :param not_tags_any: show stacks not containing these tags. If
            multiple tags are passed, they will be combined using the boolean
            OR expression
        :returns: a list of stacks
        """
        return self.call(ctxt,
                         self.make_msg('list_stacks', limit=limit,
                                       sort_keys=sort_keys, marker=marker,
                                       sort_dir=sort_dir, filters=filters,
                                       show_deleted=show_deleted,
                                       show_nested=show_nested,
                                       show_hidden=show_hidden,
                                       tags=tags, tags_any=tags_any,
                                       not_tags=not_tags,
                                       not_tags_any=not_tags_any),
                         version='1.33')

    def count_stacks(self, ctxt, filters=None,
                     show_deleted=False, show_nested=False, show_hidden=False,
                     tags=None, tags_any=None, not_tags=None,
                     not_tags_any=None):
        """Returns the number of stacks that match the given filters.

        :param ctxt: RPC context.
        :param filters: a dict of ATTR:VALUE to match against stacks
        :param show_deleted: if true, count will include the deleted stacks
        :param show_nested: if true, count will include nested stacks
        :param show_hidden: if true, count will include hidden stacks
        :param tags: count stacks containing these tags. If multiple tags are
            passed, they will be combined using the boolean AND expression
        :param tags_any: count stacks containing these tags. If multiple tags
            are passed, they will be combined using the boolean OR expression
        :param not_tags: count stacks not containing these tags. If multiple
            tags are passed, they will be combined using the boolean AND
            expression
        :param not_tags_any: count stacks not containing these tags. If
            multiple tags are passed, they will be combined using the boolean
            OR expression
        :returns: an integer representing the number of matched stacks
        """
        return self.call(ctxt, self.make_msg('count_stacks',
                                             filters=filters,
                                             show_deleted=show_deleted,
                                             show_nested=show_nested,
                                             show_hidden=show_hidden,
                                             tags=tags,
                                             tags_any=tags_any,
                                             not_tags=not_tags,
                                             not_tags_any=not_tags_any),
                         version='1.33')

    def show_stack(self, ctxt, stack_identity, resolve_outputs=True):
        """Returns detailed information about one or all stacks.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to show, or None to
                               show all
        :param resolve_outputs: If True, stack outputs will be resolved
        """
        return self.call(ctxt, self.make_msg('show_stack',
                                             stack_identity=stack_identity,
                                             resolve_outputs=resolve_outputs),
                         version='1.20')

    def preview_stack(self, ctxt, stack_name, template, params, files,
                      args, environment_files=None, files_container=None):
        """Simulates a new stack using the provided template.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param files_container: name of swift container
        """
        return self.call(ctxt,
                         self.make_msg('preview_stack', stack_name=stack_name,
                                       template=template,
                                       params=params, files=files,
                                       environment_files=environment_files,
                                       files_container=files_container,
                                       args=args),
                         version='1.36')

    def create_stack(self, ctxt, stack_name, template, params, files,
                     args, environment_files=None, files_container=None):
        """Creates a new stack using the template provided.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param files_container: name of swift container
        """
        return self._create_stack(ctxt, stack_name, template, params, files,
                                  args, environment_files=environment_files,
                                  files_container=files_container)

    def _create_stack(self, ctxt, stack_name, template, params, files,
                      args, environment_files=None, files_container=None,
                      owner_id=None, nested_depth=0, user_creds_id=None,
                      stack_user_project_id=None, parent_resource_name=None,
                      template_id=None):
        """Internal interface for engine-to-engine communication via RPC.

        Allows some additional options which should not be exposed to users via
        the API:

        :param owner_id: parent stack ID for nested stacks
        :param nested_depth: nested depth for nested stacks
        :param user_creds_id: user_creds record for nested stack
        :param stack_user_project_id: stack user project for nested stack
        :param parent_resource_name: the parent resource name
        :param template_id: the ID of a pre-stored template in the DB
        """
        return self.call(
            ctxt, self.make_msg('create_stack', stack_name=stack_name,
                                template=template,
                                params=params, files=files,
                                environment_files=environment_files,
                                files_container=files_container,
                                args=args, owner_id=owner_id,
                                nested_depth=nested_depth,
                                user_creds_id=user_creds_id,
                                stack_user_project_id=stack_user_project_id,
                                parent_resource_name=parent_resource_name,
                                template_id=template_id),
            version='1.36')

    def update_stack(self, ctxt, stack_identity, template, params,
                     files, args, environment_files=None,
                     files_container=None):
        """Updates an existing stack based on the provided template and params.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param files_container: name of swift container
        """
        return self._update_stack(ctxt, stack_identity, template, params,
                                  files, args,
                                  environment_files=environment_files,
                                  files_container=files_container)

    def _update_stack(self, ctxt, stack_identity, template, params,
                      files, args, environment_files=None,
                      files_container=None, template_id=None):
        """Internal interface for engine-to-engine communication via RPC.

        Allows an additional option which should not be exposed to users via
        the API:

        :param template_id: the ID of a pre-stored template in the DB
        """
        return self.call(ctxt,
                         self.make_msg('update_stack',
                                       stack_identity=stack_identity,
                                       template=template,
                                       params=params,
                                       files=files,
                                       environment_files=environment_files,
                                       files_container=files_container,
                                       args=args,
                                       template_id=template_id),
                         version='1.36')

    def preview_update_stack(self, ctxt, stack_identity, template, params,
                             files, args, environment_files=None,
                             files_container=None):
        """Returns the resources that would be changed in an update.

        Based on the provided template and parameters.

        Requires RPC version 1.15 or above.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you wish to update.
        :param template: New template for the stack.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment.
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param files_container: name of swift container
        """
        return self.call(ctxt,
                         self.make_msg('preview_update_stack',
                                       stack_identity=stack_identity,
                                       template=template,
                                       params=params,
                                       files=files,
                                       environment_files=environment_files,
                                       files_container=files_container,
                                       args=args,
                                       ),
                         version='1.36')

    def validate_template(self, ctxt, template, params=None, files=None,
                          environment_files=None, files_container=None,
                          show_nested=False, ignorable_errors=None):
        """Uses the stack parser to check the validity of a template.

        :param ctxt: RPC context.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params/Environment
        :param files: files referenced from the environment/template.
        :param environment_files: ordered list of environment file names
                                  included in the files dict
        :param files_container: name of swift container
        :param show_nested: if True nested templates will be validated
        :param ignorable_errors: List of error_code to be ignored as part of
                                 validation
        """
        return self.call(ctxt, self.make_msg(
            'validate_template',
            template=template,
            params=params,
            files=files,
            show_nested=show_nested,
            environment_files=environment_files,
            files_container=files_container,
            ignorable_errors=ignorable_errors),
            version='1.36')

    def authenticated_to_backend(self, ctxt):
        """Validate the credentials in the RPC context.

        Verify that the credentials in the RPC context are valid for the
        current cloud backend.

        :param ctxt: RPC context.
        """
        return self.call(ctxt, self.make_msg('authenticated_to_backend'))

    def get_template(self, ctxt, stack_identity):
        """Get the template.

        :param ctxt: RPC context.
        :param stack_name: Name of the stack you want to see.
        """
        return self.call(ctxt, self.make_msg('get_template',
                                             stack_identity=stack_identity))

    def get_environment(self, context, stack_identity):
        """Returns the environment for an existing stack.

        :param context: RPC context
        :param stack_identity: identifies the stack
        :rtype: dict
        """

        return self.call(context,
                         self.make_msg('get_environment',
                                       stack_identity=stack_identity),
                         version='1.28')

    def get_files(self, context, stack_identity):
        """Returns the files for an existing stack.

        :param context: RPC context
        :param stack_identity: identifies the stack
        :rtype: dict
        """

        return self.call(context,
                         self.make_msg('get_files',
                                       stack_identity=stack_identity),
                         version='1.32')

    def delete_stack(self, ctxt, stack_identity, cast=False):
        """Deletes a given stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to delete.
        :param cast: cast the message instead of using call (default: False)

        You probably never want to use cast(). If you do, you'll never hear
        about any exceptions the call might raise.
        """
        rpc_method = self.cast if cast else self.call
        return rpc_method(ctxt,
                          self.make_msg('delete_stack',
                                        stack_identity=stack_identity))

    def abandon_stack(self, ctxt, stack_identity):
        """Deletes a given stack but resources would not be deleted.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to abandon.
        """
        return self.call(ctxt,
                         self.make_msg('abandon_stack',
                                       stack_identity=stack_identity))

    def list_resource_types(self,
                            ctxt,
                            support_status=None,
                            type_name=None,
                            heat_version=None,
                            with_description=False):
        """Get a list of valid resource types.

        :param ctxt: RPC context.
        :param support_status: Support status of resource type
        :param type_name: Resource type's name (regular expression allowed)
        :param heat_version: Heat version
        :param with_description: Either return resource type description or not
        """
        return self.call(ctxt,
                         self.make_msg('list_resource_types',
                                       support_status=support_status,
                                       type_name=type_name,
                                       heat_version=heat_version,
                                       with_description=with_description),
                         version='1.30')

    def list_template_versions(self, ctxt):
        """Get a list of available template versions.

        :param ctxt: RPC context.
        """
        return self.call(ctxt, self.make_msg('list_template_versions'),
                         version='1.11')

    def list_template_functions(self, ctxt, template_version,
                                with_condition=False):
        """Get a list of available functions in a given template type.

        :param ctxt: RPC context
        :param template_version: template format/version tuple for which you
                                 want to get the list of functions.
        :param with_condition: return includes condition functions.
        """
        return self.call(ctxt,
                         self.make_msg('list_template_functions',
                                       template_version=template_version,
                                       with_condition=with_condition),
                         version='1.35')

    def resource_schema(self, ctxt, type_name, with_description=False):
        """Get the schema for a resource type.

        :param ctxt: RPC context.
        :param with_description: Return resource with description or not.
        """
        return self.call(ctxt,
                         self.make_msg('resource_schema',
                                       type_name=type_name,
                                       with_description=with_description),
                         version='1.30')

    def generate_template(self, ctxt, type_name, template_type='cfn'):
        """Generate a template based on the specified type.

        :param ctxt: RPC context.
        :param type_name: The resource type name to generate a template for.
        :param template_type: the template type to generate, cfn or hot.
        """
        return self.call(ctxt, self.make_msg('generate_template',
                                             type_name=type_name,
                                             template_type=template_type),
                         version='1.9')

    def list_events(self, ctxt, stack_identity, filters=None, limit=None,
                    marker=None, sort_keys=None, sort_dir=None,
                    nested_depth=None):
        """Lists all events associated with a given stack.

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
        :param nested_depth: Levels of nested stacks to list events for.
        """
        return self.call(ctxt, self.make_msg('list_events',
                                             stack_identity=stack_identity,
                                             filters=filters,
                                             limit=limit,
                                             marker=marker,
                                             sort_keys=sort_keys,
                                             sort_dir=sort_dir,
                                             nested_depth=nested_depth),
                         version='1.31')

    def describe_stack_resource(self, ctxt, stack_identity, resource_name,
                                with_attr=False):
        """Get detailed resource information about a particular resource.

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
        """Return an identifier for the resource.

        :param ctxt: RPC context.
        :param physcial_resource_id: The physical resource ID to look up.
        """
        return self.call(ctxt,
                         self.make_msg(
                             'find_physical_resource',
                             physical_resource_id=physical_resource_id))

    def describe_stack_resources(self, ctxt, stack_identity, resource_name):
        """Get detailed resource information about one or more resources.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param resource_name: the Resource.
        """
        return self.call(ctxt, self.make_msg('describe_stack_resources',
                                             stack_identity=stack_identity,
                                             resource_name=resource_name))

    def list_stack_resources(self, ctxt, stack_identity,
                             nested_depth=0, with_detail=False,
                             filters=None):
        """List the resources belonging to a stack.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param nested_depth: Levels of nested stacks of which list resources.
        :param with_detail: show detail for resources in list.
        :param filters: a dict with attribute:value to search the resources
        """
        return self.call(ctxt,
                         self.make_msg('list_stack_resources',
                                       stack_identity=stack_identity,
                                       nested_depth=nested_depth,
                                       with_detail=with_detail,
                                       filters=filters),
                         version='1.25')

    def stack_suspend(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_suspend',
                                             stack_identity=stack_identity))

    def stack_resume(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_resume',
                                             stack_identity=stack_identity))

    def stack_check(self, ctxt, stack_identity):
        return self.call(ctxt, self.make_msg('stack_check',
                                             stack_identity=stack_identity))

    def stack_cancel_update(self, ctxt, stack_identity,
                            cancel_with_rollback=True):
        return self.call(ctxt,
                         self.make_msg(
                             'stack_cancel_update',
                             stack_identity=stack_identity,
                             cancel_with_rollback=cancel_with_rollback),
                         version='1.14')

    def resource_signal(self, ctxt, stack_identity, resource_name, details,
                        sync_call=False):
        """Generate an alarm on the resource.

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

    def resource_mark_unhealthy(self, ctxt, stack_identity, resource_name,
                                mark_unhealthy, resource_status_reason=None):
        """Mark the resource as unhealthy or healthy.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack.
        :param resource_name: the Resource.
        :param mark_unhealthy: indicates whether the resource is unhealthy.
        :param resource_status_reason: reason for health change.
        """
        return self.call(
            ctxt,
            self.make_msg('resource_mark_unhealthy',
                          stack_identity=stack_identity,
                          resource_name=resource_name,
                          mark_unhealthy=mark_unhealthy,
                          resource_status_reason=resource_status_reason),
            version='1.26')

    def get_revision(self, ctxt):
        return self.call(ctxt, self.make_msg('get_revision'))

    def show_software_config(self, cnxt, config_id):
        return self.call(cnxt, self.make_msg('show_software_config',
                                             config_id=config_id))

    def list_software_configs(self, cnxt, limit=None, marker=None):
        return self.call(cnxt,
                         self.make_msg('list_software_configs',
                                       limit=limit,
                                       marker=marker),
                         version='1.33')

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

    def check_software_deployment(self, cnxt, deployment_id, timeout):
        return self.call(cnxt, self.make_msg('check_software_deployment',
                                             deployment_id=deployment_id,
                                             timeout=timeout),
                         timeout=timeout, version='1.27')

    def create_software_deployment(self, cnxt, server_id, config_id=None,
                                   input_values=None, action='INIT',
                                   status='COMPLETE', status_reason='',
                                   stack_user_project_id=None,
                                   deployment_id=None):
        input_values = input_values or {}
        return self.call(cnxt, self.make_msg(
            'create_software_deployment',
            server_id=server_id,
            config_id=config_id,
            deployment_id=deployment_id,
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

    def list_outputs(self, cntx, stack_identity):
        return self.call(cntx, self.make_msg('list_outputs',
                                             stack_identity=stack_identity),
                         version='1.19')

    def show_output(self, cntx, stack_identity, output_key):
        return self.call(cntx, self.make_msg('show_output',
                                             stack_identity=stack_identity,
                                             output_key=output_key),
                         version='1.19')

    def export_stack(self, ctxt, stack_identity):
        """Exports the stack data in JSON format.

        :param ctxt: RPC context.
        :param stack_identity: Name of the stack you want to export.
        """
        return self.call(ctxt,
                         self.make_msg('export_stack',
                                       stack_identity=stack_identity),
                         version='1.22')

    def migrate_convergence_1(self, ctxt, stack_id):
        """Migrate the stack to convergence engine

        :param ctxt: RPC context
        :param stack_name: Name of the stack you want to migrate
        """
        return self.call(ctxt,
                         self.make_msg('migrate_convergence_1',
                                       stack_id=stack_id),
                         version='1.34')
