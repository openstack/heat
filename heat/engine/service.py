
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

import functools
import json

from oslo.config import cfg
import webob

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')
cfg.CONF.import_opt('max_resources_per_stack', 'heat.common.config')
cfg.CONF.import_opt('max_stacks_per_tenant', 'heat.common.config')

from heat.openstack.common import timeutils
from heat.common import context
from heat.db import api as db_api
from heat.engine import api
from heat.rpc import api as rpc_api
from heat.engine import attributes
from heat.engine import clients
from heat.engine.event import Event
from heat.engine import environment
from heat.common import exception
from heat.common import identifier
from heat.common import heat_keystoneclient as hkc
from heat.engine import parameter_groups
from heat.engine import parser
from heat.engine import properties
from heat.engine import resource
from heat.engine import resources
from heat.engine import stack_lock
from heat.engine import watchrule

from heat.openstack.common import log as logging
from heat.openstack.common import threadgroup
from heat.openstack.common.gettextutils import _
from heat.openstack.common.rpc import common as rpc_common
from heat.openstack.common.rpc import proxy
from heat.openstack.common.rpc import service
from heat.openstack.common import excutils
from heat.openstack.common import uuidutils

logger = logging.getLogger(__name__)


def request_context(func):
    @functools.wraps(func)
    def wrapped(self, ctx, *args, **kwargs):
        if ctx is not None and not isinstance(ctx, context.RequestContext):
            ctx = context.RequestContext.from_dict(ctx.to_dict())
        try:
            return func(self, ctx, *args, **kwargs)
        except exception.HeatException:
            raise rpc_common.ClientException()
    return wrapped


class ThreadGroupManager(object):

    def __init__(self):
        super(ThreadGroupManager, self).__init__()
        self.groups = {}

        # Create dummy service task, because when there is nothing queued
        # on self.tg the process exits
        self.add_timer(cfg.CONF.periodic_interval, self._service_task)

    def _service_task(self):
        """
        This is a dummy task which gets queued on the service.Service
        threadgroup.  Without this service.Service sees nothing running
        i.e has nothing to wait() on, so the process exits..
        This could also be used to trigger periodic non-stack-specific
        housekeeping tasks
        """
        pass

    def start(self, stack_id, func, *args, **kwargs):
        """
        Run the given method in a sub-thread.
        """
        if stack_id not in self.groups:
            self.groups[stack_id] = threadgroup.ThreadGroup()
        return self.groups[stack_id].add_thread(func, *args, **kwargs)

    def start_with_lock(self, cnxt, stack, engine_id, func, *args, **kwargs):
        """
        Try to acquire a stack lock and, if successful, run the given
        method in a sub-thread.  Release the lock when the thread
        finishes.

        :param cnxt: RPC context
        :param stack: Stack to be operated on
        :type stack: heat.engine.parser.Stack
        :param engine_id: The UUID of the engine acquiring the lock
        :param func: Callable to be invoked in sub-thread
        :type func: function or instancemethod
        :param args: Args to be passed to func
        :param kwargs: Keyword-args to be passed to func.
        """
        lock = stack_lock.StackLock(cnxt, stack, engine_id)
        lock.acquire()
        self.start_with_acquired_lock(stack, lock, func, *args, **kwargs)

    def start_with_acquired_lock(self, stack, lock, func, *args, **kwargs):
        """
        Run the given method in a sub-thread and release the provided lock
        when the thread finishes.

        :param stack: Stack to be operated on
        :type stack: heat.engine.parser.Stack
        :param lock: The acquired stack lock
        :type lock: heat.engine.stack_lock.StackLock
        :param func: Callable to be invoked in sub-thread
        :type func: function or instancemethod
        :param args: Args to be passed to func
        :param kwargs: Keyword-args to be passed to func

        """
        def release(gt, *args):
            """
            Callback function that will be passed to GreenThread.link().
            """
            lock.release(*args)

        try:
            th = self.start(stack.id, func, *args, **kwargs)
            th.link(release, stack.id)
        except:
            with excutils.save_and_reraise_exception():
                lock.release(stack.id)

    def add_timer(self, stack_id, func, *args, **kwargs):
        """
        Define a periodic task, to be run in a separate thread, in the stack
        threadgroups.  Periodicity is cfg.CONF.periodic_interval
        """
        if stack_id not in self.groups:
            self.groups[stack_id] = threadgroup.ThreadGroup()
        self.groups[stack_id].add_timer(cfg.CONF.periodic_interval,
                                        func, *args, **kwargs)

    def stop_timers(self, stack_id):
        if stack_id in self.groups:
            self.groups[stack_id].stop_timers()

    def stop(self, stack_id):
        '''Stop any active threads on a stack.'''
        if stack_id in self.groups:
            self.groups[stack_id].stop()
            del self.groups[stack_id]


class StackWatch(object):
    def __init__(self, thread_group_mgr):
        self.thread_group_mgr = thread_group_mgr

    def start_watch_task(self, stack_id, cnxt):

        def stack_has_a_watchrule(sid):
            wrs = db_api.watch_rule_get_all_by_stack(cnxt, sid)

            now = timeutils.utcnow()
            start_watch_thread = False
            for wr in wrs:
                # reset the last_evaluated so we don't fire off alarms when
                # the engine has not been running.
                db_api.watch_rule_update(cnxt, wr.id, {'last_evaluated': now})

                if wr.state != rpc_api.WATCH_STATE_CEILOMETER_CONTROLLED:
                    start_watch_thread = True

            children = db_api.stack_get_all_by_owner_id(cnxt, sid)
            for child in children:
                if stack_has_a_watchrule(child.id):
                    start_watch_thread = True

            return start_watch_thread

        if stack_has_a_watchrule(stack_id):
            self.thread_group_mgr.add_timer(
                stack_id,
                self.periodic_watcher_task,
                sid=stack_id)

    def check_stack_watches(self, sid):
        # Retrieve the stored credentials & create context
        # Require tenant_safe=False to the stack_get to defeat tenant
        # scoping otherwise we fail to retrieve the stack
        logger.debug(_("Periodic watcher task for stack %s") % sid)
        admin_context = context.get_admin_context()
        stack = db_api.stack_get(admin_context, sid, tenant_safe=False)
        if not stack:
            logger.error(_("Unable to retrieve stack %s for periodic task") %
                         sid)
            return
        stack_context = EngineService.load_user_creds(stack.user_creds_id)

        # recurse into any nested stacks.
        children = db_api.stack_get_all_by_owner_id(admin_context, sid)
        for child in children:
            self.check_stack_watches(child.id)

        # Get all watchrules for this stack and evaluate them
        try:
            wrs = db_api.watch_rule_get_all_by_stack(stack_context, sid)
        except Exception as ex:
            logger.warn(_('periodic_task db error (%(msg)s) %(ex)s') % {
                        'msg': 'watch rule removed?', 'ex': str(ex)})
            return

        def run_alarm_action(actions, details):
            for action in actions:
                action(details=details)

            stk = parser.Stack.load(stack_context, stack=stack)
            for res in stk.itervalues():
                res.metadata_update()

        for wr in wrs:
            rule = watchrule.WatchRule.load(stack_context, watch=wr)
            actions = rule.evaluate()
            if actions:
                self.thread_group_mgr.start(sid, run_alarm_action, actions,
                                            rule.get_details())

    def periodic_watcher_task(self, sid):
        """
        Periodic task, created for each stack, triggers watch-rule
        evaluation for all rules defined for the stack
        sid = stack ID
        """
        self.check_stack_watches(sid)


class EngineListener(service.Service):
    '''
    Listen on an AMQP queue named for the engine.  Allows individual
    engines to communicate with each other for multi-engine support.
    '''
    def __init__(self, host, engine_id, thread_group_mgr):
        super(EngineListener, self).__init__(host, engine_id)

        self.thread_group_mgr = thread_group_mgr
        self.engine_id = engine_id

    def listening(self, ctxt):
        '''
        Respond affirmatively to confirm that the engine performing the
        action is still alive.
        '''
        return True

    def stop_stack(self, ctxt, stack_identity):
        '''Stop any active threads on a stack.'''
        stack_id = stack_identity['stack_id']
        self.thread_group_mgr.stop(stack_id)


class EngineService(service.Service):
    """
    Manages the running instances from creation to destruction.
    All the methods in here are called from the RPC backend.  This is
    all done dynamically so if a call is made via RPC that does not
    have a corresponding method here, an exception will be thrown when
    it attempts to call into this class.  Arguments to these methods
    are also dynamically added and will be named as keyword arguments
    by the RPC caller.
    """

    RPC_API_VERSION = '1.1'

    def __init__(self, host, topic, manager=None):
        super(EngineService, self).__init__(host, topic)
        resources.initialise()

        self.engine_id = stack_lock.StackLock.generate_engine_id()
        self.thread_group_mgr = ThreadGroupManager()
        self.stack_watch = StackWatch(self.thread_group_mgr)
        self.listener = EngineListener(host, self.engine_id,
                                       self.thread_group_mgr)
        logger.debug(_("Starting listener for engine %s") % self.engine_id)
        self.listener.start()

    def start(self):
        super(EngineService, self).start()

        # Create a periodic_watcher_task per-stack
        admin_context = context.get_admin_context()
        stacks = db_api.stack_get_all(admin_context, tenant_safe=False)
        for s in stacks:
            self.stack_watch.start_watch_task(s.id, admin_context)

    @staticmethod
    def load_user_creds(creds_id):
        user_creds = db_api.user_creds_get(creds_id)
        stored_context = context.RequestContext.from_dict(user_creds)
        # heat_keystoneclient populates the context with an auth_token
        # either via the stored user/password or trust_id, depending
        # on how deferred_auth_method is configured in the conf file
        hkc.KeystoneClient(stored_context)
        return stored_context

    @request_context
    def identify_stack(self, cnxt, stack_name):
        """
        The identify_stack method returns the full stack identifier for a
        single, live stack given the stack name.

        :param cnxt: RPC context.
        :param stack_name: Name or UUID of the stack to look up.
        """
        if uuidutils.is_uuid_like(stack_name):
            s = db_api.stack_get(cnxt, stack_name, show_deleted=True)
            # may be the name is in uuid format, so if get by id returns None,
            # we should get the info by name again
            if not s:
                s = db_api.stack_get_by_name(cnxt, stack_name)
        else:
            s = db_api.stack_get_by_name(cnxt, stack_name)
        if s:
            stack = parser.Stack.load(cnxt, stack=s)
            return dict(stack.identifier())
        else:
            raise exception.StackNotFound(stack_name=stack_name)

    def _get_stack(self, cnxt, stack_identity, show_deleted=False):
        identity = identifier.HeatIdentifier(**stack_identity)

        s = db_api.stack_get(cnxt, identity.stack_id,
                             show_deleted=show_deleted)

        if s is None:
            raise exception.StackNotFound(stack_name=identity.stack_name)

        if cnxt.tenant_id not in (identity.tenant, s.stack_user_project_id):
            # The DB API should not allow this, but sanity-check anyway..
            raise exception.InvalidTenant(target=identity.tenant,
                                          actual=cnxt.tenant_id)

        if identity.path or s.name != identity.stack_name:
            raise exception.StackNotFound(stack_name=identity.stack_name)

        return s

    @request_context
    def show_stack(self, cnxt, stack_identity):
        """
        Return detailed information about one or all stacks.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to show, or None
            to show all
        """
        if stack_identity is not None:
            stacks = [self._get_stack(cnxt, stack_identity, show_deleted=True)]
        else:
            stacks = db_api.stack_get_all(cnxt) or []

        def format_stack_detail(s):
            stack = parser.Stack.load(cnxt, stack=s)
            return api.format_stack(stack)

        return [format_stack_detail(s) for s in stacks]

    def get_revision(self, cnxt):
        return cfg.CONF.revision['heat_revision']

    @request_context
    def list_stacks(self, cnxt, limit=None, marker=None, sort_keys=None,
                    sort_dir=None, filters=None, tenant_safe=True):
        """
        The list_stacks method returns attributes of all stacks.  It supports
        pagination (``limit`` and ``marker``), sorting (``sort_keys`` and
        ``sort_dir``) and filtering (``filters``) of the results.

        :param cnxt: RPC context
        :param limit: the number of stacks to list (integer or string)
        :param marker: the ID of the last item in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc')
        :param filters: a dict with attribute:value to filter the list
        :param tenant_safe: if true, scope the request by the current tenant
        :returns: a list of formatted stacks
        """

        def format_stack_details(stacks):
            for s in stacks:
                try:
                    stack = parser.Stack.load(cnxt, stack=s,
                                              resolve_data=False)
                except exception.NotFound:
                    # The stack may have been deleted between listing
                    # and formatting
                    pass
                else:
                    yield api.format_stack(stack)

        stacks = db_api.stack_get_all(cnxt, limit, sort_keys, marker,
                                      sort_dir, filters, tenant_safe) or []
        return list(format_stack_details(stacks))

    @request_context
    def count_stacks(self, cnxt, filters=None, tenant_safe=True):
        """
        Return the number of stacks that match the given filters
        :param ctxt: RPC context.
        :param filters: a dict of ATTR:VALUE to match against stacks
        :returns: a integer representing the number of matched stacks
        """
        return db_api.stack_count_all(cnxt, filters=filters,
                                      tenant_safe=tenant_safe)

    def _validate_deferred_auth_context(self, cnxt, stack):
        if cfg.CONF.deferred_auth_method != 'password':
            return

        if not stack.requires_deferred_auth():
            return

        if cnxt.username is None:
            raise exception.MissingCredentialError(required='X-Auth-User')
        if cnxt.password is None:
            raise exception.MissingCredentialError(required='X-Auth-Key')

    def _validate_new_stack(self, cnxt, stack_name, parsed_template):
        if db_api.stack_get_by_name(cnxt, stack_name):
            raise exception.StackExists(stack_name=stack_name)

        tenant_limit = cfg.CONF.max_stacks_per_tenant
        if db_api.stack_count_all(cnxt) >= tenant_limit:
            message = _("You have reached the maximum stacks per tenant, %d."
                        " Please delete some stacks.") % tenant_limit
            raise exception.RequestLimitExceeded(message=message)

        num_resources = len(parsed_template[parsed_template.RESOURCES])
        if num_resources > cfg.CONF.max_resources_per_stack:
            message = exception.StackResourceLimitExceeded.msg_fmt
            raise exception.RequestLimitExceeded(message=message)

    @request_context
    def preview_stack(self, cnxt, stack_name, template, params, files, args):
        """
        Simulates a new stack using the provided template.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        """

        logger.info(_('previewing stack %s') % stack_name)
        tmpl = parser.Template(template, files=files)
        self._validate_new_stack(cnxt, stack_name, tmpl)

        common_params = api.extract_args(args)
        env = environment.Environment(params)
        stack = parser.Stack(cnxt, stack_name, tmpl, env, **common_params)

        self._validate_deferred_auth_context(cnxt, stack)
        stack.validate()

        return api.format_stack_preview(stack)

    @request_context
    def create_stack(self, cnxt, stack_name, template, params, files, args):
        """
        The create_stack method creates a new stack using the template
        provided.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        """
        logger.info(_('template is %s') % template)

        def _stack_create(stack):
            # Create/Adopt a stack, and create the periodic task if successful
            if stack.adopt_stack_data:
                stack.adopt()
            else:
                stack.create()

            if (stack.action in (stack.CREATE, stack.ADOPT)
                    and stack.status == stack.COMPLETE):
                # Schedule a periodic watcher task for this stack
                self.stack_watch.start_watch_task(stack.id, cnxt)
            else:
                logger.warning(_("Stack create failed, status %s") %
                               stack.status)

        tmpl = parser.Template(template, files=files)
        self._validate_new_stack(cnxt, stack_name, tmpl)

        # Extract the common query parameters
        common_params = api.extract_args(args)
        env = environment.Environment(params)
        stack = parser.Stack(cnxt, stack_name, tmpl,
                             env, **common_params)

        self._validate_deferred_auth_context(cnxt, stack)

        stack.validate()

        stack.store()

        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_create, stack)

        return dict(stack.identifier())

    @request_context
    def update_stack(self, cnxt, stack_identity, template, params,
                     files, args):
        """
        The update_stack method updates an existing stack based on the
        provided template and parameters.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        """
        logger.info(_('template is %s') % template)

        # Get the database representation of the existing stack
        db_stack = self._get_stack(cnxt, stack_identity)

        current_stack = parser.Stack.load(cnxt, stack=db_stack)

        if current_stack.action == current_stack.SUSPEND:
            msg = _('Updating a stack when it is suspended')
            raise exception.NotSupported(feature=msg)

        if current_stack.status == current_stack.IN_PROGRESS:
            msg = _('Updating a stack when another action is in progress')
            raise exception.NotSupported(feature=msg)

        # Now parse the template and any parameters for the updated
        # stack definition.
        tmpl = parser.Template(template, files=files)
        if len(tmpl[tmpl.RESOURCES]) > cfg.CONF.max_resources_per_stack:
            raise exception.RequestLimitExceeded(
                message=exception.StackResourceLimitExceeded.msg_fmt)
        stack_name = current_stack.name
        common_params = api.extract_args(args)
        common_params.setdefault(rpc_api.PARAM_TIMEOUT,
                                 current_stack.timeout_mins)
        env = environment.Environment(params)
        updated_stack = parser.Stack(cnxt, stack_name, tmpl,
                                     env, **common_params)
        updated_stack.parameters.set_stack_id(current_stack.identifier())

        self._validate_deferred_auth_context(cnxt, updated_stack)
        updated_stack.validate()

        self.thread_group_mgr.start_with_lock(cnxt, current_stack,
                                              self.engine_id,
                                              current_stack.update,
                                              updated_stack)

        return dict(current_stack.identifier())

    @request_context
    def validate_template(self, cnxt, template, params=None):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        :param cnxt: RPC context.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        """
        logger.info(_('validate_template'))
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        tmpl = parser.Template(template)
        try:
            tmpl_resources = tmpl['Resources']
        except KeyError as ex:
            return {'Error': str(ex)}

        # validate overall template (top-level structure)
        tmpl.validate()

        if not tmpl_resources:
            return {'Error': 'At least one Resources member must be defined.'}

        env = environment.Environment(params)

        for res in tmpl_resources.values():
            try:
                if not res.get('Type'):
                    return {'Error':
                            'Every Resource object must '
                            'contain a Type member.'}
            except AttributeError:
                type_res = type(res)
                if isinstance(res, unicode):
                    type_res = "string"
                return {'Error':
                        'Resources must contain Resource. '
                        'Found a [%s] instead' % type_res}

            ResourceClass = env.get_class(res['Type'])
            if ResourceClass == resources.template_resource.TemplateResource:
                # we can't validate a TemplateResource unless we instantiate
                # it as we need to download the template and convert the
                # paramerters into properties_schema.
                continue

            props = properties.Properties(ResourceClass.properties_schema,
                                          res.get('Properties', {}),
                                          context=cnxt)
            try:
                ResourceClass.validate_deletion_policy(res)
                props.validate(with_value=False)
            except Exception as ex:
                return {'Error': str(ex)}

        tmpl_params = tmpl.parameters(None, {})
        tmpl_params.validate(validate_value=False, context=cnxt)
        is_real_param = lambda p: p.name not in tmpl_params.PSEUDO_PARAMETERS
        params = tmpl_params.map(api.format_validate_parameter, is_real_param)
        param_groups = parameter_groups.ParameterGroups(tmpl)

        result = {
            'Description': tmpl.get('Description', ''),
            'Parameters': params,
        }

        if param_groups.parameter_groups:
            result['ParameterGroups'] = param_groups.parameter_groups

        return result

    @request_context
    def authenticated_to_backend(self, cnxt):
        """
        Verify that the credentials in the RPC context are valid for the
        current cloud backend.
        """
        return clients.Clients(cnxt).authenticated()

    @request_context
    def get_template(self, cnxt, stack_identity):
        """
        Get the template.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to see.
        """
        s = self._get_stack(cnxt, stack_identity, show_deleted=True)
        if s:
            return s.raw_template.template
        return None

    @request_context
    def delete_stack(self, cnxt, stack_identity):
        """
        The delete_stack method deletes a given stack.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to delete.
        """
        def remote_stop(lock_engine_id):
            rpc = proxy.RpcProxy(lock_engine_id, "1.0")
            msg = rpc.make_msg("stop_stack", stack_identity=stack_identity)
            timeout = cfg.CONF.engine_life_check_timeout
            try:
                rpc.call(cnxt, msg, topic=lock_engine_id, timeout=timeout)
            except rpc_common.Timeout:
                return False

        st = self._get_stack(cnxt, stack_identity)
        logger.info(_('Deleting stack %s') % st.name)
        stack = parser.Stack.load(cnxt, stack=st)

        lock = stack_lock.StackLock(cnxt, stack, self.engine_id)
        acquire_result = lock.try_acquire()

        # Successfully acquired lock
        if acquire_result is None:
            self.thread_group_mgr.stop_timers(stack.id)
            self.thread_group_mgr.start_with_acquired_lock(stack, lock,
                                                           stack.delete)
            return

        # Current engine has the lock
        elif acquire_result == self.engine_id:
            self.thread_group_mgr.stop(stack.id)

        # Another active engine has the lock
        elif stack_lock.StackLock.engine_alive(cnxt, acquire_result):
            stop_result = remote_stop(acquire_result)
            if stop_result is None:
                logger.debug(_("Successfully stopped remote task on engine %s")
                             % acquire_result)
            else:
                raise exception.StopActionFailed(stack_name=stack.name,
                                                 engine_id=acquire_result)

        # If the lock isn't released here, then the call to
        # start_with_lock below will raise an ActionInProgress
        # exception.  Ideally, we wouldn't be calling another
        # release() here, since it should be called as soon as the
        # ThreadGroup is stopped.  But apparently there's a race
        # between release() the next call to lock.acquire().
        db_api.stack_lock_release(stack.id, acquire_result)

        # There may be additional resources that we don't know about
        # if an update was in-progress when the stack was stopped, so
        # reload the stack from the database.
        st = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=st)

        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              stack.delete)
        return None

    @request_context
    def abandon_stack(self, cnxt, stack_identity):
        """
        The abandon_stack method abandons a given stack.
        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to abandon.
        """
        st = self._get_stack(cnxt, stack_identity)
        logger.info(_('abandoning stack %s') % st.name)
        stack = parser.Stack.load(cnxt, stack=st)

        # Get stack details before deleting it.
        stack_info = stack.get_abandon_data()
        # Set deletion policy to 'Retain' for all resources in the stack.
        stack.set_deletion_policy(resource.RETAIN)
        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              stack.delete)
        return stack_info

    def list_resource_types(self, cnxt, support_status=None):
        """
        Get a list of supported resource types.

        :param cnxt: RPC context.
        """
        return resource.get_types(support_status)

    def resource_schema(self, cnxt, type_name):
        """
        Return the schema of the specified type.

        :param cnxt: RPC context.
        :param type_name: Name of the resource type to obtain the schema of.
        """
        try:
            resource_class = resource.get_class(type_name)
        except exception.StackValidationFailed:
            raise exception.ResourceTypeNotFound(type_name=type_name)

        def properties_schema():
            for name, schema_dict in resource_class.properties_schema.items():
                schema = properties.Schema.from_legacy(schema_dict)
                if schema.implemented:
                    yield name, dict(schema)

        def attributes_schema():
            for schema_item in resource_class.attributes_schema.items():
                schema = attributes.Attribute(*schema_item)
                yield schema.name, {schema.DESCRIPTION: schema.description}

        return {
            rpc_api.RES_SCHEMA_RES_TYPE: type_name,
            rpc_api.RES_SCHEMA_PROPERTIES: dict(properties_schema()),
            rpc_api.RES_SCHEMA_ATTRIBUTES: dict(attributes_schema()),
        }

    def generate_template(self, cnxt, type_name):
        """
        Generate a template based on the specified type.

        :param cnxt: RPC context.
        :param type_name: Name of the resource type to generate a template for.
        """
        try:
            return \
                resource.get_class(type_name).resource_to_template(type_name)
        except exception.StackValidationFailed:
            raise exception.ResourceTypeNotFound(type_name=type_name)

    @request_context
    def list_events(self, cnxt, stack_identity):
        """
        The list_events method lists all events associated with a given stack.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to get events for.
        """

        if stack_identity is not None:
            st = self._get_stack(cnxt, stack_identity, show_deleted=True)

            events = db_api.event_get_all_by_stack(cnxt, st.id)
        else:
            events = db_api.event_get_all_by_tenant(cnxt)

        stacks = {}

        def get_stack(stack_id):
            if stack_id not in stacks:
                stacks[stack_id] = parser.Stack.load(cnxt, stack_id)
            return stacks[stack_id]

        return [api.format_event(Event.load(cnxt,
                                            e.id, e,
                                            get_stack(e.stack_id)))
                for e in events]

    def _authorize_stack_user(self, cnxt, stack, resource_name):
        '''
        Filter access to describe_stack_resource for stack in-instance users
        - The user must map to a User resource defined in the requested stack
        - The user resource must validate OK against any Policy specified
        '''
        # first check whether access is allowd by context user_id
        if stack.access_allowed(cnxt.user_id, resource_name):
            return True

        # fall back to looking for EC2 credentials in the context
        try:
            ec2_creds = json.loads(cnxt.aws_creds).get('ec2Credentials')
        except (TypeError, AttributeError):
            ec2_creds = None

        if not ec2_creds:
            return False

        access_key = ec2_creds.get('access')
        return stack.access_allowed(access_key, resource_name)

    @request_context
    def describe_stack_resource(self, cnxt, stack_identity, resource_name):
        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)

        if cfg.CONF.heat_stack_user_role in cnxt.roles:
            if not self._authorize_stack_user(cnxt, stack, resource_name):
                logger.warning(_("Access denied to resource %s")
                               % resource_name)
                raise exception.Forbidden()

        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        resource = stack[resource_name]
        if resource.id is None:
            raise exception.ResourceNotAvailable(resource_name=resource_name)

        return api.format_stack_resource(stack[resource_name])

    @request_context
    def resource_signal(self, cnxt, stack_identity, resource_name, details):
        s = self._get_stack(cnxt, stack_identity)

        # This is not "nice" converting to the stored context here,
        # but this happens because the keystone user associated with the
        # signal doesn't have permission to read the secret key of
        # the user associated with the cfn-credentials file
        stack_context = self.load_user_creds(s.user_creds_id)
        stack = parser.Stack.load(stack_context, stack=s)

        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        resource = stack[resource_name]
        if resource.id is None:
            raise exception.ResourceNotAvailable(resource_name=resource_name)

        if callable(stack[resource_name].signal):
            stack[resource_name].signal(details)

    @request_context
    def find_physical_resource(self, cnxt, physical_resource_id):
        """
        Return an identifier for the resource with the specified physical
        resource ID.

        :param cnxt: RPC context.
        :param physical_resource_id: The physical resource ID to look up.
        """
        rs = db_api.resource_get_by_physical_resource_id(cnxt,
                                                         physical_resource_id)
        if not rs:
            raise exception.PhysicalResourceNotFound(
                resource_id=physical_resource_id)

        stack = parser.Stack.load(cnxt, stack=rs.stack)
        resource = stack[rs.name]

        return dict(resource.identifier())

    @request_context
    def describe_stack_resources(self, cnxt, stack_identity, resource_name):
        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)

        return [api.format_stack_resource(resource)
                for name, resource in stack.iteritems()
                if resource_name is None or name == resource_name]

    @request_context
    def list_stack_resources(self, cnxt, stack_identity):
        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)

        return [api.format_stack_resource(resource, detail=False)
                for resource in stack.values()]

    @request_context
    def stack_suspend(self, cnxt, stack_identity):
        '''
        Handle request to perform suspend action on a stack
        '''
        def _stack_suspend(stack):
            logger.debug(_("suspending stack %s") % stack.name)
            stack.suspend()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_suspend, stack)

    @request_context
    def stack_resume(self, cnxt, stack_identity):
        '''
        Handle request to perform a resume action on a stack
        '''
        def _stack_resume(stack):
            logger.debug(_("resuming stack %s") % stack.name)
            stack.resume()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_resume, stack)

    @request_context
    def metadata_update(self, cnxt, stack_identity,
                        resource_name, metadata):
        """
        Update the metadata for the given resource.
        """
        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        resource = stack[resource_name]
        resource.metadata_update(new_metadata=metadata)

        # This is not "nice" converting to the stored context here,
        # but this happens because the keystone user associated with the
        # WaitCondition doesn't have permission to read the secret key of
        # the user associated with the cfn-credentials file
        stack_context = self.load_user_creds(s.user_creds_id)
        refresh_stack = parser.Stack.load(stack_context, stack=s)

        # Refresh the metadata for all other resources, since we expect
        # resource_name to be a WaitCondition resource, and other
        # resources may refer to WaitCondition Fn::GetAtt Data, which
        # is updated here.
        for res in refresh_stack.dependencies:
            if res.name != resource_name and res.id is not None:
                res.metadata_update()

        return resource.metadata

    @request_context
    def create_watch_data(self, cnxt, watch_name, stats_data):
        '''
        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        '''
        def get_matching_watches():
            if watch_name:
                yield watchrule.WatchRule.load(cnxt, watch_name)
            else:
                for wr in db_api.watch_rule_get_all(cnxt):
                    if watchrule.rule_can_use_sample(wr, stats_data):
                        yield watchrule.WatchRule.load(cnxt, watch=wr)

        rule_run = False
        for rule in get_matching_watches():
            rule.create_watch_data(stats_data)
            rule_run = True

        if not rule_run:
            if watch_name is None:
                watch_name = 'Unknown'
            raise exception.WatchRuleNotFound(watch_name=watch_name)

        return stats_data

    @request_context
    def show_watch(self, cnxt, watch_name):
        """
        The show_watch method returns the attributes of one watch/alarm

        :param cnxt: RPC context.
        :param watch_name: Name of the watch you want to see, or None to see
            all
        """
        if watch_name:
            wrn = [watch_name]
        else:
            try:
                wrn = [w.name for w in db_api.watch_rule_get_all(cnxt)]
            except Exception as ex:
                logger.warn(_('show_watch (all) db error %s') % str(ex))
                return

        wrs = [watchrule.WatchRule.load(cnxt, w) for w in wrn]
        result = [api.format_watch(w) for w in wrs]
        return result

    @request_context
    def show_watch_metric(self, cnxt, metric_namespace=None, metric_name=None):
        """
        The show_watch method returns the datapoints for a metric

        :param cnxt: RPC context.
        :param metric_namespace: Name of the namespace you want to see, or None
            to see all
        :param metric_name: Name of the metric you want to see, or None to see
            all
        """

        # DB API and schema does not yet allow us to easily query by
        # namespace/metric, but we will want this at some point
        # for now, the API can query all metric data and filter locally
        if metric_namespace is not None or metric_name is not None:
            logger.error(_("Filtering by namespace/metric not yet supported"))
            return

        try:
            wds = db_api.watch_data_get_all(cnxt)
        except Exception as ex:
            logger.warn(_('show_metric (all) db error %s') % str(ex))
            return

        result = [api.format_watch_data(w) for w in wds]
        return result

    @request_context
    def set_watch_state(self, cnxt, watch_name, state):
        """
        Temporarily set the state of a given watch

        :param cnxt: RPC context.
        :param watch_name: Name of the watch
        :param state: State (must be one defined in WatchRule class
        """
        wr = watchrule.WatchRule.load(cnxt, watch_name)
        if wr.state == rpc_api.WATCH_STATE_CEILOMETER_CONTROLLED:
            return
        actions = wr.set_watch_state(state)
        for action in actions:
            self.thread_group_mgr.start(wr.stack_id, action)

        # Return the watch with the state overriden to indicate success
        # We do not update the timestamps as we are not modifying the DB
        result = api.format_watch(wr)
        result[rpc_api.WATCH_STATE_VALUE] = state
        return result

    @request_context
    def show_software_config(self, cnxt, config_id):
        sc = db_api.software_config_get(cnxt, config_id)
        return api.format_software_config(sc)

    @request_context
    def create_software_config(self, cnxt, group, name, config,
                               inputs, outputs, options):

        sc = db_api.software_config_create(cnxt, {
            'group': group,
            'name': name,
            'config': {
                'inputs': inputs,
                'outputs': outputs,
                'options': options,
                'config': config
            },
            'tenant': cnxt.tenant_id})
        return api.format_software_config(sc)

    @request_context
    def delete_software_config(self, cnxt, config_id):
        db_api.software_config_delete(cnxt, config_id)

    @request_context
    def list_software_deployments(self, cnxt, server_id):
        all_sd = db_api.software_deployment_get_all(cnxt, server_id)
        result = [api.format_software_deployment(sd) for sd in all_sd]
        return result

    @request_context
    def metadata_software_deployments(self, cnxt, server_id):
        if not server_id:
            raise ValueError(_('server_id must be specified'))
        all_sd = db_api.software_deployment_get_all(cnxt, server_id)
        # sort the configs by config name, to give the list of metadata a
        # deterministic and controllable order.
        all_sd_s = sorted(all_sd, key=lambda sd: sd.config.name)
        result = [api.format_software_config(sd.config) for sd in all_sd_s]
        return result

    @request_context
    def show_software_deployment(self, cnxt, deployment_id):
        sd = db_api.software_deployment_get(cnxt, deployment_id)
        return api.format_software_deployment(sd)

    @request_context
    def create_software_deployment(self, cnxt, server_id, config_id,
                                   input_values, action, status,
                                   status_reason, stack_user_project_id):

        sd = db_api.software_deployment_create(cnxt, {
            'config_id': config_id,
            'server_id': server_id,
            'input_values': input_values,
            'tenant': cnxt.tenant_id,
            'stack_user_project_id': stack_user_project_id,
            'action': action,
            'status': status,
            'status_reason': status_reason})
        return api.format_software_deployment(sd)

    @request_context
    def update_software_deployment(self, cnxt, deployment_id, config_id,
                                   input_values, output_values, action,
                                   status, status_reason):
        update_data = {}
        if config_id:
            update_data['config_id'] = config_id
        if input_values:
            update_data['input_values'] = input_values
        if output_values:
            update_data['output_values'] = output_values
        if action:
            update_data['action'] = action
        if status:
            update_data['status'] = status
        if status_reason:
            update_data['status_reason'] = status_reason
        sd = db_api.software_deployment_update(cnxt,
                                               deployment_id, update_data)
        return api.format_software_deployment(sd)

    @request_context
    def delete_software_deployment(self, cnxt, deployment_id):
        db_api.software_deployment_delete(cnxt, deployment_id)
