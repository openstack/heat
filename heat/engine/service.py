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

import collections
import datetime
import itertools
import os
import socket

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_service import service
from oslo_service import threadgroup
from oslo_utils import timeutils
from oslo_utils import uuidutils
from osprofiler import profiler
import six
import webob

from heat.common import context
from heat.common import environment_format as env_fmt
from heat.common import exception
from heat.common.i18n import _
from heat.common.i18n import _LE
from heat.common.i18n import _LI
from heat.common.i18n import _LW
from heat.common import identifier
from heat.common import messaging as rpc_messaging
from heat.common import policy
from heat.common import service_utils
from heat.engine import api
from heat.engine import attributes
from heat.engine.cfn import template as cfntemplate
from heat.engine import clients
from heat.engine import environment
from heat.engine import event as evt
from heat.engine.hot import functions as hot_functions
from heat.engine import parameter_groups
from heat.engine import properties
from heat.engine import resources
from heat.engine import service_software_config
from heat.engine import service_stack_watch
from heat.engine import stack as parser
from heat.engine import stack_lock
from heat.engine import support
from heat.engine import template as templatem
from heat.engine import update
from heat.engine import watchrule
from heat.engine import worker
from heat.objects import event as event_object
from heat.objects import resource as resource_objects
from heat.objects import service as service_objects
from heat.objects import snapshot as snapshot_object
from heat.objects import stack as stack_object
from heat.objects import watch_data
from heat.objects import watch_rule
from heat.rpc import api as rpc_api
from heat.rpc import worker_api as rpc_worker_api
from heatclient.common import environment_format
from heatclient.common import template_utils

cfg.CONF.import_opt('engine_life_check_timeout', 'heat.common.config')
cfg.CONF.import_opt('max_resources_per_stack', 'heat.common.config')
cfg.CONF.import_opt('max_stacks_per_tenant', 'heat.common.config')
cfg.CONF.import_opt('enable_stack_abandon', 'heat.common.config')
cfg.CONF.import_opt('enable_stack_adopt', 'heat.common.config')
cfg.CONF.import_opt('convergence_engine', 'heat.common.config')

LOG = logging.getLogger(__name__)


class ThreadGroupManager(object):

    def __init__(self):
        super(ThreadGroupManager, self).__init__()
        self.groups = {}
        self.events = collections.defaultdict(list)

        # Create dummy service task, because when there is nothing queued
        # on self.tg the process exits
        self.add_timer(cfg.CONF.periodic_interval, self._service_task)

    def _service_task(self):
        """Dummy task which gets queued on the service.Service threadgroup.

        Without this, service.Service sees nothing running i.e has nothing to
        wait() on, so the process exits. This could also be used to trigger
        periodic non-stack-specific housekeeping tasks.
        """
        pass

    def _serialize_profile_info(self):
        prof = profiler.get()
        trace_info = None
        if prof:
            trace_info = {
                "hmac_key": prof.hmac_key,
                "base_id": prof.get_base_id(),
                "parent_id": prof.get_id()
            }
        return trace_info

    def _start_with_trace(self, trace, func, *args, **kwargs):
        if trace:
            profiler.init(**trace)
        return func(*args, **kwargs)

    def start(self, stack_id, func, *args, **kwargs):
        """Run the given method in a sub-thread."""
        if stack_id not in self.groups:
            self.groups[stack_id] = threadgroup.ThreadGroup()

        def log_exceptions(gt):
            try:
                gt.wait()
            except Exception:
                LOG.exception(_LE('Unhandled error in asynchronous task'))
            except BaseException:
                pass

        th = self.groups[stack_id].add_thread(self._start_with_trace,
                                              self._serialize_profile_info(),
                                              func, *args, **kwargs)
        th.link(log_exceptions)
        return th

    def start_with_lock(self, cnxt, stack, engine_id, func, *args, **kwargs):
        """Run the method in sub-thread after acquiring the stack lock.

        Release the lock when the thread finishes.

        :param cnxt: RPC context
        :param stack: Stack to be operated on
        :type stack: heat.engine.parser.Stack
        :param engine_id: The UUID of the engine/worker acquiring the lock
        :param func: Callable to be invoked in sub-thread
        :type func: function or instancemethod
        :param args: Args to be passed to func
        :param kwargs: Keyword-args to be passed to func.
        """
        lock = stack_lock.StackLock(cnxt, stack.id, engine_id)
        with lock.thread_lock():
            th = self.start_with_acquired_lock(stack, lock,
                                               func, *args, **kwargs)
            return th

    def start_with_acquired_lock(self, stack, lock, func, *args, **kwargs):
        """Run the given method in a sub-thread with an existing stack lock.

        Release the provided lock when the thread finishes.

        :param stack: Stack to be operated on
        :type stack: heat.engine.parser.Stack
        :param lock: The acquired stack lock
        :type lock: heat.engine.stack_lock.StackLock
        :param func: Callable to be invoked in sub-thread
        :type func: function or instancemethod
        :param args: Args to be passed to func
        :param kwargs: Keyword-args to be passed to func

        """
        def release(gt):
            """Callback function that will be passed to GreenThread.link().

            Persist the stack state to COMPLETE and FAILED close to
            releasing the lock to avoid race condtitions.
            """
            if stack is not None and stack.action not in (
                    stack.DELETE, stack.ROLLBACK, stack.UPDATE):
                stack.persist_state_and_release_lock(lock.engine_id)
            else:
                lock.release()

        # Link to self to allow the stack to run tasks
        stack.thread_group_mgr = self
        th = self.start(stack.id, func, *args, **kwargs)
        th.link(release)
        return th

    def add_timer(self, stack_id, func, *args, **kwargs):
        """Define a periodic task in the stack threadgroups.

        The task is run in a separate greenthread.

        Periodicity is cfg.CONF.periodic_interval
        """
        if stack_id not in self.groups:
            self.groups[stack_id] = threadgroup.ThreadGroup()
        self.groups[stack_id].add_timer(cfg.CONF.periodic_interval,
                                        func, *args, **kwargs)

    def add_event(self, stack_id, event):
        self.events[stack_id].append(event)

    def remove_event(self, gt, stack_id, event):
        for e in self.events.pop(stack_id, []):
            if e is not event:
                self.add_event(stack_id, e)

    def stop_timers(self, stack_id):
        if stack_id in self.groups:
            self.groups[stack_id].stop_timers()

    def stop(self, stack_id, graceful=False):
        """Stop any active threads on a stack."""
        if stack_id in self.groups:
            self.events.pop(stack_id, None)
            threadgroup = self.groups.pop(stack_id)
            threads = threadgroup.threads[:]

            threadgroup.stop(graceful)
            threadgroup.wait()

            # Wait for link()ed functions (i.e. lock release)
            links_done = dict((th, False) for th in threads)

            def mark_done(gt, th):
                links_done[th] = True

            for th in threads:
                th.link(mark_done, th)
            while not all(six.itervalues(links_done)):
                eventlet.sleep()

    def send(self, stack_id, message):
        for event in self.events.pop(stack_id, []):
            event.send(message)


@profiler.trace_cls("rpc")
class EngineListener(service.Service):
    """Listen on an AMQP queue named for the engine.

    Allows individual engines to communicate with each other for multi-engine
    support.
    """

    ACTIONS = (STOP_STACK, SEND) = ('stop_stack', 'send')

    def __init__(self, host, engine_id, thread_group_mgr):
        super(EngineListener, self).__init__()
        self.thread_group_mgr = thread_group_mgr
        self.engine_id = engine_id
        self.host = host

    def start(self):
        super(EngineListener, self).start()
        self.target = messaging.Target(
            server=self.engine_id,
            topic=rpc_api.LISTENER_TOPIC)
        server = rpc_messaging.get_rpc_server(self.target, self)
        server.start()

    def listening(self, ctxt):
        """Respond to a watchdog request.

        Respond affirmatively to confirm that the engine performing the action
        is still alive.
        """
        return True

    def stop_stack(self, ctxt, stack_identity):
        """Stop any active threads on a stack."""
        stack_id = stack_identity['stack_id']
        self.thread_group_mgr.stop(stack_id)

    def send(self, ctxt, stack_identity, message):
        stack_id = stack_identity['stack_id']
        self.thread_group_mgr.send(stack_id, message)


@profiler.trace_cls("rpc")
class EngineService(service.Service):
    """Manages the running instances from creation to destruction.

    All the methods in here are called from the RPC backend.  This is
    all done dynamically so if a call is made via RPC that does not
    have a corresponding method here, an exception will be thrown when
    it attempts to call into this class.  Arguments to these methods
    are also dynamically added and will be named as keyword arguments
    by the RPC caller.
    """

    RPC_API_VERSION = '1.29'

    def __init__(self, host, topic):
        super(EngineService, self).__init__()
        resources.initialise()
        self.host = host
        self.topic = topic
        self.binary = 'heat-engine'
        self.hostname = socket.gethostname()

        # The following are initialized here, but assigned in start() which
        # happens after the fork when spawning multiple worker processes
        self.stack_watch = None
        self.listener = None
        self.worker_service = None
        self.engine_id = None
        self.thread_group_mgr = None
        self.target = None
        self.service_id = None
        self.manage_thread_grp = None
        self._rpc_server = None
        self.software_config = service_software_config.SoftwareConfigService()
        self.resource_enforcer = policy.ResourceEnforcer()

        if cfg.CONF.trusts_delegated_roles:
            LOG.warning(_LW('The default value of "trusts_delegated_roles" '
                            'option in heat.conf is changed to [] in Kilo '
                            'and heat will delegate all roles of trustor. '
                            'Please keep the same if you do not want to '
                            'delegate subset roles when upgrading.'))

    def create_periodic_tasks(self):
        LOG.debug("Starting periodic watch tasks pid=%s" % os.getpid())
        # Note with multiple workers, the parent process hasn't called start()
        # so we need to create a ThreadGroupManager here for the periodic tasks
        if self.thread_group_mgr is None:
            self.thread_group_mgr = ThreadGroupManager()
        self.stack_watch = service_stack_watch.StackWatch(
            self.thread_group_mgr)

        def create_watch_tasks():
            while True:
                try:
                    # Create a periodic_watcher_task per-stack
                    admin_context = context.get_admin_context()
                    stacks = stack_object.Stack.get_all(
                        admin_context,
                        tenant_safe=False,
                        show_hidden=True)
                    for s in stacks:
                        self.stack_watch.start_watch_task(s.id, admin_context)
                    LOG.info(_LI("Watch tasks created"))
                    return
                except Exception as e:
                    LOG.error(_LE("Watch task creation attempt failed, %s"), e)
                    eventlet.sleep(5)

        if self.manage_thread_grp is None:
            self.manage_thread_grp = threadgroup.ThreadGroup()
        self.manage_thread_grp.add_thread(create_watch_tasks)

    def start(self):
        self.engine_id = stack_lock.StackLock.generate_engine_id()
        if self.thread_group_mgr is None:
            self.thread_group_mgr = ThreadGroupManager()
        self.listener = EngineListener(self.host, self.engine_id,
                                       self.thread_group_mgr)
        LOG.debug("Starting listener for engine %s" % self.engine_id)
        self.listener.start()

        if cfg.CONF.convergence_engine:
            self.worker_service = worker.WorkerService(
                host=self.host,
                topic=rpc_worker_api.TOPIC,
                engine_id=self.engine_id,
                thread_group_mgr=self.thread_group_mgr
            )
            self.worker_service.start()

        target = messaging.Target(
            version=self.RPC_API_VERSION, server=self.host,
            topic=self.topic)

        self.target = target
        self._rpc_server = rpc_messaging.get_rpc_server(target, self)
        self._rpc_server.start()
        self._client = rpc_messaging.get_rpc_client(
            version=self.RPC_API_VERSION)

        self._configure_db_conn_pool_size()
        self.service_manage_cleanup()
        if self.manage_thread_grp is None:
            self.manage_thread_grp = threadgroup.ThreadGroup()
        self.manage_thread_grp.add_timer(cfg.CONF.periodic_interval,
                                         self.service_manage_report)
        self.manage_thread_grp.add_thread(self.reset_stack_status)

        super(EngineService, self).start()

    def _configure_db_conn_pool_size(self):
        # bug #1491185
        # Set the DB max_overflow to match the thread pool size.
        # The overflow connections are automatically closed when they are
        # not used; setting it is better than setting DB max_pool_size.
        worker_pool_size = cfg.CONF.executor_thread_pool_size
        # Update max_overflow only if it is not adequate
        if ((cfg.CONF.database.max_overflow is None) or
                (cfg.CONF.database.max_overflow < worker_pool_size)):
            cfg.CONF.set_override('max_overflow', worker_pool_size,
                                  group='database', enforce_type=True)

    def _stop_rpc_server(self):
        # Stop rpc connection at first for preventing new requests
        if self._rpc_server is None:
            return
        LOG.debug("Attempting to stop engine service...")
        try:
            self._rpc_server.stop()
            self._rpc_server.wait()
            LOG.info(_LI("Engine service is stopped successfully"))
        except Exception as e:
            LOG.error(_LE("Failed to stop engine service, %s"), e)

    def stop(self):
        self._stop_rpc_server()

        if cfg.CONF.convergence_engine and self.worker_service:
            # Stop the WorkerService
            self.worker_service.stop()

        # Wait for all active threads to be finished
        if self.thread_group_mgr:
            for stack_id in list(self.thread_group_mgr.groups.keys()):
                # Ignore dummy service task
                if stack_id == cfg.CONF.periodic_interval:
                    continue
                LOG.info(_LI("Waiting stack %s processing to be finished"),
                         stack_id)
                # Stop threads gracefully
                self.thread_group_mgr.stop(stack_id, True)
                LOG.info(_LI("Stack %s processing was finished"), stack_id)
        if self.manage_thread_grp:
            self.manage_thread_grp.stop()
            ctxt = context.get_admin_context()
            service_objects.Service.delete(ctxt, self.service_id)
            LOG.info(_LI('Service %s is deleted'), self.service_id)

        # Terminate the engine process
        LOG.info(_LI("All threads were gone, terminating engine"))
        super(EngineService, self).stop()

    def reset(self):
        super(EngineService, self).reset()
        logging.setup(cfg.CONF, 'heat')

    @context.request_context
    def identify_stack(self, cnxt, stack_name):
        """The full stack identifier for a single, live stack with stack_name.

        :param cnxt: RPC context.
        :param stack_name: Name or UUID of the stack to look up.
        """
        if uuidutils.is_uuid_like(stack_name):
            s = stack_object.Stack.get_by_id(
                cnxt,
                stack_name,
                show_deleted=True)
            # may be the name is in uuid format, so if get by id returns None,
            # we should get the info by name again
            if not s:
                s = stack_object.Stack.get_by_name(cnxt, stack_name)
        else:
            s = stack_object.Stack.get_by_name(cnxt, stack_name)
        if s:
            stack = parser.Stack.load(cnxt, stack=s)
            return dict(stack.identifier())
        else:
            raise exception.EntityNotFound(entity='Stack', name=stack_name)

    def _get_stack(self, cnxt, stack_identity, show_deleted=False):
        identity = identifier.HeatIdentifier(**stack_identity)

        s = stack_object.Stack.get_by_id(
            cnxt,
            identity.stack_id,
            show_deleted=show_deleted,
            eager_load=True)

        if s is None:
            raise exception.EntityNotFound(entity='Stack',
                                           name=identity.stack_name)

        if cnxt.tenant_id not in (identity.tenant, s.stack_user_project_id):
            # The DB API should not allow this, but sanity-check anyway..
            raise exception.InvalidTenant(target=identity.tenant,
                                          actual=cnxt.tenant_id)

        if identity.path or s.name != identity.stack_name:
            raise exception.EntityNotFound(entity='Stack',
                                           name=identity.stack_name)

        return s

    @context.request_context
    def show_stack(self, cnxt, stack_identity, resolve_outputs=True):
        """Return detailed information about one or all stacks.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to show, or None
            to show all
        :param resolve_outputs: If True, outputs for given stack/stacks will
            be resolved
        """
        if stack_identity is not None:
            db_stack = self._get_stack(cnxt, stack_identity, show_deleted=True)
            stacks = [parser.Stack.load(cnxt, stack=db_stack,
                                        resolve_data=resolve_outputs)]
        else:
            stacks = parser.Stack.load_all(cnxt, resolve_data=resolve_outputs)

        return [api.format_stack(
            stack, resolve_outputs=resolve_outputs) for stack in stacks]

    def get_revision(self, cnxt):
        return cfg.CONF.revision['heat_revision']

    @context.request_context
    def list_stacks(self, cnxt, limit=None, marker=None, sort_keys=None,
                    sort_dir=None, filters=None, tenant_safe=True,
                    show_deleted=False, show_nested=False, show_hidden=False,
                    tags=None, tags_any=None, not_tags=None,
                    not_tags_any=None):
        """Returns attributes of all stacks.

        It supports pagination (``limit`` and ``marker``),
        sorting (``sort_keys`` and ``sort_dir``) and filtering (``filters``)
        of the results.

        :param cnxt: RPC context
        :param limit: the number of stacks to list (integer or string)
        :param marker: the ID of the last item in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc')
        :param filters: a dict with attribute:value to filter the list
        :param tenant_safe: if true, scope the request by the current tenant
        :param show_deleted: if true, show soft-deleted stacks
        :param show_nested: if true, show nested stacks
        :param show_hidden: if true, show hidden stacks
        :param tags: show stacks containing these tags, combine multiple
            tags using the boolean AND expression
        :param tags_any: show stacks containing these tags, combine multiple
            tags using the boolean OR expression
        :param not_tags: show stacks not containing these tags, combine
            multiple tags using the boolean AND expression
        :param not_tags_any: show stacks not containing these tags, combine
            multiple tags using the boolean OR expression
        :returns: a list of formatted stacks
        """
        if filters is not None:
            filters = api.translate_filters(filters)

        stacks = parser.Stack.load_all(cnxt, limit, marker, sort_keys,
                                       sort_dir, filters, tenant_safe,
                                       show_deleted, resolve_data=False,
                                       show_nested=show_nested,
                                       show_hidden=show_hidden,
                                       tags=tags, tags_any=tags_any,
                                       not_tags=not_tags,
                                       not_tags_any=not_tags_any)
        return [api.format_stack(stack) for stack in stacks]

    @context.request_context
    def count_stacks(self, cnxt, filters=None, tenant_safe=True,
                     show_deleted=False, show_nested=False, show_hidden=False,
                     tags=None, tags_any=None, not_tags=None,
                     not_tags_any=None):
        """Return the number of stacks that match the given filters.

        :param cnxt: RPC context.
        :param filters: a dict of ATTR:VALUE to match against stacks
        :param tenant_safe: if true, scope the request by the current tenant
        :param show_deleted: if true, count will include the deleted stacks
        :param show_nested: if true, count will include nested stacks
        :param show_hidden: if true, count will include hidden stacks
        :param tags: count stacks containing these tags, combine multiple tags
            using the boolean AND expression
        :param tags_any: count stacks containing these tags, combine multiple
            tags using the boolean OR expression
        :param not_tags: count stacks not containing these tags, combine
            multiple tags using the boolean AND expression
        :param not_tags_any: count stacks not containing these tags, combine
            multiple tags using the boolean OR expression
        :returns: an integer representing the number of matched stacks
        """
        return stack_object.Stack.count_all(
            cnxt,
            filters=filters,
            tenant_safe=tenant_safe,
            show_deleted=show_deleted,
            show_nested=show_nested,
            show_hidden=show_hidden,
            tags=tags,
            tags_any=tags_any,
            not_tags=not_tags,
            not_tags_any=not_tags_any)

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
        if stack_object.Stack.get_by_name(cnxt, stack_name):
            raise exception.StackExists(stack_name=stack_name)

        tenant_limit = cfg.CONF.max_stacks_per_tenant
        if stack_object.Stack.count_all(cnxt) >= tenant_limit:
            message = _("You have reached the maximum stacks per tenant, "
                        "%d. Please delete some stacks.") % tenant_limit
            raise exception.RequestLimitExceeded(message=message)
        self._validate_template(cnxt, parsed_template)

    def _validate_template(self, cnxt, parsed_template):
        try:
            parsed_template.validate()
        except AssertionError:
            raise
        except Exception as ex:
            raise exception.StackValidationFailed(message=six.text_type(ex))

        max_resources = cfg.CONF.max_resources_per_stack
        if max_resources == -1:
            return
        num_resources = len(parsed_template[parsed_template.RESOURCES])
        if num_resources > max_resources:
            message = exception.StackResourceLimitExceeded.msg_fmt
            raise exception.RequestLimitExceeded(message=message)

    def _parse_template_and_validate_stack(self, cnxt, stack_name, template,
                                           params, files, environment_files,
                                           args, owner_id=None,
                                           nested_depth=0, user_creds_id=None,
                                           stack_user_project_id=None,
                                           convergence=False,
                                           parent_resource_name=None,
                                           template_id=None):
        common_params = api.extract_args(args)

        # If it is stack-adopt, use parameters from adopt_stack_data
        if rpc_api.PARAM_ADOPT_STACK_DATA in common_params:
            if not cfg.CONF.enable_stack_adopt:
                raise exception.NotSupported(feature='Stack Adopt')

            # Override the params with values given with -P option
            new_params = {}
            if 'environment' in common_params[rpc_api.PARAM_ADOPT_STACK_DATA]:
                new_params = common_params[rpc_api.PARAM_ADOPT_STACK_DATA][
                    'environment'].get(rpc_api.STACK_PARAMETERS, {}).copy()
            new_params.update(params.get(rpc_api.STACK_PARAMETERS, {}))
            params[rpc_api.STACK_PARAMETERS] = new_params

        if template_id is not None:
            tmpl = templatem.Template.load(cnxt, template_id)
            env = tmpl.env
        else:
            self._merge_environments(environment_files, files, params)
            env = environment.Environment(params)
            tmpl = templatem.Template(template, files=files, env=env)
        self._validate_new_stack(cnxt, stack_name, tmpl)

        stack = parser.Stack(cnxt, stack_name, tmpl,
                             owner_id=owner_id,
                             nested_depth=nested_depth,
                             user_creds_id=user_creds_id,
                             stack_user_project_id=stack_user_project_id,
                             convergence=convergence,
                             parent_resource=parent_resource_name,
                             **common_params)

        self._validate_deferred_auth_context(cnxt, stack)
        stack.validate()
        # For the root stack print a summary of the TemplateResources loaded
        if nested_depth == 0:
            env.registry.log_resource_info(prefix=stack_name)
        return stack

    @staticmethod
    def _merge_environments(environment_files, files, params):
        """Merges environment files into the stack input parameters.

        If a list of environment files have been specified, this call will
        pull the contents of each from the files dict, parse them as
        environments, and merge them into the stack input params. This
        behavior is the same as earlier versions of the Heat client that
        performed this params population client-side.

        :param environment_files: ordered names of the environment files
               found in the files dict
        :type  environment_files: list or None
        :param files: mapping of stack filenames to contents
        :type  files: dict
        :param params: parameters describing the stack
        :type  dict:
        """
        if environment_files:
            for filename in environment_files:
                raw_env = files[filename]
                parsed_env = environment_format.parse(raw_env)
                template_utils.deep_update(params, parsed_env)

    @context.request_context
    def preview_stack(self, cnxt, stack_name, template, params, files,
                      args, environment_files=None):
        """Simulate a new stack using the provided template.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        """

        LOG.info(_LI('previewing stack %s'), stack_name)

        conv_eng = cfg.CONF.convergence_engine
        stack = self._parse_template_and_validate_stack(cnxt,
                                                        stack_name,
                                                        template,
                                                        params,
                                                        files,
                                                        environment_files,
                                                        args,
                                                        convergence=conv_eng)

        self.resource_enforcer.enforce_stack(stack)
        return api.format_stack_preview(stack)

    @context.request_context
    def create_stack(self, cnxt, stack_name, template, params, files,
                     args, environment_files=None,
                     owner_id=None, nested_depth=0, user_creds_id=None,
                     stack_user_project_id=None, parent_resource_name=None,
                     template_id=None):
        """Create a new stack using the template provided.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_name: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param owner_id: parent stack ID for nested stacks, only expected when
                         called from another heat-engine (not a user option)
        :param nested_depth: the nested depth for nested stacks, only expected
                         when called from another heat-engine
        :param user_creds_id: the parent user_creds record for nested stacks
        :param stack_user_project_id: the parent stack_user_project_id for
                         nested stacks
        :param parent_resource_name: the parent resource name
        :param template_id: the ID of a pre-stored template in the DB
        """
        LOG.info(_LI('Creating stack %s'), stack_name)

        def _create_stack_user(stack):
            if not stack.stack_user_project_id:
                try:
                    stack.create_stack_user_project_id()
                except exception.AuthorizationFailure as ex:
                    stack.state_set(stack.action, stack.FAILED,
                                    six.text_type(ex))

        def _stack_create(stack):
            # Create/Adopt a stack, and create the periodic task if successful
            if stack.adopt_stack_data:
                stack.adopt()
            elif stack.status != stack.FAILED:
                stack.create()

            if (stack.action in (stack.CREATE, stack.ADOPT)
                    and stack.status == stack.COMPLETE):
                if self.stack_watch:
                    # Schedule a periodic watcher task for this stack
                    self.stack_watch.start_watch_task(stack.id, cnxt)
            else:
                LOG.info(_LI("Stack create failed, status %s"), stack.status)

        convergence = cfg.CONF.convergence_engine

        stack = self._parse_template_and_validate_stack(
            cnxt, stack_name, template, params, files, environment_files,
            args, owner_id, nested_depth, user_creds_id,
            stack_user_project_id, convergence, parent_resource_name,
            template_id)

        self.resource_enforcer.enforce_stack(stack)
        stack_id = stack.store()
        if cfg.CONF.reauthentication_auth_method == 'trusts':
            stack = parser.Stack.load(
                cnxt, stack_id=stack_id, use_stored_context=True)
        _create_stack_user(stack)
        if convergence:
            action = stack.CREATE
            if stack.adopt_stack_data:
                action = stack.ADOPT
            stack.thread_group_mgr = self.thread_group_mgr
            stack.converge_stack(template=stack.t, action=action)
        else:
            self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                                  _stack_create, stack)

        return dict(stack.identifier())

    def _prepare_stack_updates(self, cnxt, current_stack, template, params,
                               files, args, template_id=None):
        """Return the current and updated stack for a given transition.

        Changes *will not* be persisted, this is a helper method for
        update_stack and preview_update_stack.

        :param cnxt: RPC context.
        :param stack: A stack to be updated.
        :param template: Template of stack you want to update to.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        :param template_id: the ID of a pre-stored template in the DB
        """

        # Now parse the template and any parameters for the updated
        # stack definition.  If PARAM_EXISTING is specified, we merge
        # any environment provided into the existing one and attempt
        # to use the existing stack template, if one is not provided.
        if args.get(rpc_api.PARAM_EXISTING):
            existing_env = current_stack.env.user_env_as_dict()
            existing_params = existing_env[env_fmt.PARAMETERS]
            clear_params = set(args.get(rpc_api.PARAM_CLEAR_PARAMETERS, []))
            retained = dict((k, v) for k, v in existing_params.items()
                            if k not in clear_params)
            existing_env[env_fmt.PARAMETERS] = retained
            new_env = environment.Environment(existing_env)
            new_env.load(params)

            new_files = current_stack.t.files.copy()
            new_files.update(files or {})

            assert template_id is None, \
                "Cannot specify template_id with PARAM_EXISTING"

            if template is not None:
                new_template = template
            elif (current_stack.convergence or
                  current_stack.status == current_stack.COMPLETE):
                # If convergence is enabled, or the stack is complete, we can
                # just use the current template...
                new_template = current_stack.t.t
            else:
                # ..but if it's FAILED without convergence things may be in an
                # inconsistent state, so we try to fall back on a stored copy
                # of the previous template
                if current_stack.prev_raw_template_id is not None:
                    # Use the stored previous template
                    prev_t = templatem.Template.load(
                        cnxt, current_stack.prev_raw_template_id)
                    new_template = prev_t.t
                else:
                    # Nothing we can do, the failed update happened before
                    # we started storing prev_raw_template_id
                    LOG.error(_LE('PATCH update to FAILED stack only '
                                  'possible if convergence enabled or '
                                  'previous template stored'))
                    msg = _('PATCH update to non-COMPLETE stack')
                    raise exception.NotSupported(feature=msg)
            tmpl = templatem.Template(new_template, files=new_files,
                                      env=new_env)
            for key in list(new_env.params.keys()):
                if key not in tmpl.param_schemata():
                    new_env.params.pop(key)
        else:
            if template_id is not None:
                tmpl = templatem.Template.load(cnxt, template_id)
            else:
                tmpl = templatem.Template(template, files=files,
                                          env=environment.Environment(params))

        max_resources = cfg.CONF.max_resources_per_stack
        if max_resources != -1 and len(tmpl[tmpl.RESOURCES]) > max_resources:
            raise exception.RequestLimitExceeded(
                message=exception.StackResourceLimitExceeded.msg_fmt)

        stack_name = current_stack.name
        current_kwargs = current_stack.get_kwargs_for_cloning()

        common_params = api.extract_args(args)
        common_params.setdefault(rpc_api.PARAM_TIMEOUT,
                                 current_stack.timeout_mins)
        common_params.setdefault(rpc_api.PARAM_DISABLE_ROLLBACK,
                                 current_stack.disable_rollback)

        current_kwargs.update(common_params)
        updated_stack = parser.Stack(cnxt, stack_name, tmpl,
                                     **current_kwargs)

        invalid_params = current_stack.parameters.immutable_params_modified(
            updated_stack.parameters, tmpl.env.params)
        if invalid_params:
            raise exception.ImmutableParameterModified(*invalid_params)

        self.resource_enforcer.enforce_stack(updated_stack)
        updated_stack.parameters.set_stack_id(current_stack.identifier())

        self._validate_deferred_auth_context(cnxt, updated_stack)
        updated_stack.validate()

        return tmpl, current_stack, updated_stack

    @context.request_context
    def update_stack(self, cnxt, stack_identity, template, params,
                     files, args, environment_files=None, template_id=None):
        """Update an existing stack based on the provided template and params.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to create.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param args: Request parameters/args passed from API
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param template_id: the ID of a pre-stored template in the DB
        """
        # Handle server-side environment file resolution
        self._merge_environments(environment_files, files, params)

        # Get the database representation of the existing stack
        db_stack = self._get_stack(cnxt, stack_identity)
        LOG.info(_LI('Updating stack %s'), db_stack.name)
        if cfg.CONF.reauthentication_auth_method == 'trusts':
            current_stack = parser.Stack.load(
                cnxt, stack=db_stack, use_stored_context=True)
        else:
            current_stack = parser.Stack.load(cnxt, stack=db_stack)
        self.resource_enforcer.enforce_stack(current_stack)

        if current_stack.action == current_stack.SUSPEND:
            msg = _('Updating a stack when it is suspended')
            raise exception.NotSupported(feature=msg)

        if current_stack.action == current_stack.DELETE:
            msg = _('Updating a stack when it is deleting')
            raise exception.NotSupported(feature=msg)

        tmpl, current_stack, updated_stack = self._prepare_stack_updates(
            cnxt, current_stack, template, params, files, args, template_id)

        if current_stack.convergence:
            current_stack.thread_group_mgr = self.thread_group_mgr
            current_stack.converge_stack(template=tmpl,
                                         new_stack=updated_stack)
        else:
            event = eventlet.event.Event()
            th = self.thread_group_mgr.start_with_lock(cnxt, current_stack,
                                                       self.engine_id,
                                                       current_stack.update,
                                                       updated_stack,
                                                       event=event)
            th.link(self.thread_group_mgr.remove_event,
                    current_stack.id, event)
            self.thread_group_mgr.add_event(current_stack.id, event)
        return dict(current_stack.identifier())

    @context.request_context
    def preview_update_stack(self, cnxt, stack_identity, template, params,
                             files, args, environment_files=None):
        """Shows the resources that would be updated.

        The preview_update_stack method shows the resources that would be
        changed with an update to an existing stack based on the provided
        template and parameters. See update_stack for description of
        parameters.

        This method *cannot* guarantee that an update will have the actions
        specified because resource plugins can influence changes/replacements
        at runtime.

        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        """
        # Handle server-side environment file resolution
        self._merge_environments(environment_files, files, params)

        # Get the database representation of the existing stack
        db_stack = self._get_stack(cnxt, stack_identity)
        LOG.info(_LI('Previewing update of stack %s'), db_stack.name)

        current_stack = parser.Stack.load(cnxt, stack=db_stack)

        tmpl, current_stack, updated_stack = self._prepare_stack_updates(
            cnxt, current_stack, template, params, files, args)

        update_task = update.StackUpdate(current_stack, updated_stack, None)

        actions = update_task.preview()

        def fmt_action_map(current, updated, act):
            def fmt_updated_res(k):
                return api.format_stack_resource(updated.resources.get(k))

            def fmt_current_res(k):
                return api.format_stack_resource(current.resources.get(k))

            return {
                'unchanged': map(fmt_updated_res, act.get('unchanged', [])),
                'updated': map(fmt_current_res, act.get('updated', [])),
                'replaced': map(fmt_updated_res, act.get('replaced', [])),
                'added': map(fmt_updated_res, act.get('added', [])),
                'deleted': map(fmt_current_res, act.get('deleted', [])),
            }

        updated_stack.id = current_stack.id
        fmt_actions = fmt_action_map(current_stack, updated_stack, actions)

        if args.get(rpc_api.PARAM_SHOW_NESTED):
            # Note preview_resources is needed here to build the tree
            # of nested resources/stacks in memory, otherwise the
            # nested/has_nested() tests below won't work
            updated_stack.preview_resources()

            def nested_fmt_actions(current, updated, act):
                updated.id = current.id

                # Recurse for resources deleted from the current stack,
                # which is all those marked as deleted or replaced
                def _n_deleted(stk, deleted):
                    for rsrc in deleted:
                        deleted_rsrc = stk.resources.get(rsrc)
                        if deleted_rsrc.has_nested():
                            nested_stk = deleted_rsrc.nested()
                            nested_rsrc = nested_stk.resources.keys()
                            n_fmt = fmt_action_map(
                                nested_stk, None, {'deleted': nested_rsrc})
                            fmt_actions['deleted'].extend(n_fmt['deleted'])
                            _n_deleted(nested_stk, nested_rsrc)
                _n_deleted(current, act['deleted'] + act['replaced'])

                # Recurse for all resources added to the updated stack,
                # which is all those marked added or replaced
                def _n_added(stk, added):
                    for rsrc in added:
                        added_rsrc = stk.resources.get(rsrc)
                        if added_rsrc.has_nested():
                            nested_stk = added_rsrc.nested()
                            nested_rsrc = nested_stk.resources.keys()
                            n_fmt = fmt_action_map(
                                None, nested_stk, {'added': nested_rsrc})
                            fmt_actions['added'].extend(n_fmt['added'])
                            _n_added(nested_stk, nested_rsrc)
                _n_added(updated, act['added'] + act['replaced'])

                # Recursively preview all "updated" resources
                for rsrc in act['updated']:
                    current_rsrc = current.resources.get(rsrc)
                    updated_rsrc = updated.resources.get(rsrc)
                    if current_rsrc.has_nested() and updated_rsrc.has_nested():
                        current_nested = current_rsrc.nested()
                        updated_nested = updated_rsrc.nested()
                        update_task = update.StackUpdate(
                            current_nested, updated_nested, None)
                        n_actions = update_task.preview()
                        n_fmt_actions = fmt_action_map(
                            current_nested, updated_nested, n_actions)
                        for k in fmt_actions:
                            fmt_actions[k].extend(n_fmt_actions[k])
                        nested_fmt_actions(current_nested, updated_nested,
                                           n_actions)
            # Start the recursive nested_fmt_actions with the parent stack.
            nested_fmt_actions(current_stack, updated_stack, actions)

        return fmt_actions

    @context.request_context
    def stack_cancel_update(self, cnxt, stack_identity,
                            cancel_with_rollback=True):
        """Cancel currently running stack update.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack for which to cancel update.
        :param cancel_with_rollback: Force rollback when cancel update.
        """
        # Get the database representation of the existing stack
        db_stack = self._get_stack(cnxt, stack_identity)

        current_stack = parser.Stack.load(cnxt, stack=db_stack)
        if current_stack.state != (current_stack.UPDATE,
                                   current_stack.IN_PROGRESS):
            state = '_'.join(current_stack.state)
            msg = _("Cancelling update when stack is %s"
                    ) % str(state)
            raise exception.NotSupported(feature=msg)
        LOG.info(_LI('Starting cancel of updating stack %s'), db_stack.name)
        # stop the running update and take the lock
        # as we cancel only running update, the acquire_result is
        # always some engine_id, not None
        lock = stack_lock.StackLock(cnxt, current_stack.id,
                                    self.engine_id)
        engine_id = lock.try_acquire()

        if cancel_with_rollback:
            cancel_message = rpc_api.THREAD_CANCEL_WITH_ROLLBACK
        else:
            cancel_message = rpc_api.THREAD_CANCEL

        # Current engine has the lock
        if engine_id == self.engine_id:
            self.thread_group_mgr.send(current_stack.id, cancel_message)

        # Another active engine has the lock
        elif stack_lock.StackLock.engine_alive(cnxt, engine_id):
            cancel_result = self._remote_call(
                cnxt, engine_id, self.listener.SEND,
                stack_identity=stack_identity, message=cancel_message)
            if cancel_result is None:
                LOG.debug("Successfully sent %(msg)s message "
                          "to remote task on engine %(eng)s" % {
                              'eng': engine_id, 'msg': cancel_message})
            else:
                raise exception.EventSendFailed(stack_name=current_stack.name,
                                                engine_id=engine_id)

    @context.request_context
    def validate_template(self, cnxt, template, params=None, files=None,
                          environment_files=None, show_nested=False,
                          ignorable_errors=None):
        """Check the validity of a template.

        Checks, so far as we can, that a template is valid, and returns
        information about the parameters suitable for producing a user
        interface through which to specify the parameter values.

        :param cnxt: RPC context.
        :param template: Template of stack you want to create.
        :param params: Stack Input Params
        :param files: Files referenced from the template
        :param environment_files: optional ordered list of environment file
               names included in the files dict
        :type  environment_files: list or None
        :param show_nested: if True, any nested templates will be checked
        :param ignorable_errors: List of error_code to be ignored as part of
        validation
        """
        LOG.info(_LI('validate_template'))
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        service_check_defer = False
        if ignorable_errors:
            invalid_codes = (set(ignorable_errors) -
                             set(exception.ERROR_CODE_MAP.keys()))
            if invalid_codes:
                msg = (_("Invalid codes in ignore_errors : %s") %
                       list(invalid_codes))
                return webob.exc.HTTPBadRequest(explanation=msg)

            service_check_defer = True

        self._merge_environments(environment_files, files, params)
        env = environment.Environment(params)
        tmpl = templatem.Template(template, files=files, env=env)
        try:
            self._validate_template(cnxt, tmpl)
        except Exception as ex:
            return {'Error': six.text_type(ex)}

        stack_name = 'dummy'
        stack = parser.Stack(cnxt, stack_name, tmpl,
                             strict_validate=False,
                             resource_validate=False,
                             service_check_defer=service_check_defer)
        try:
            stack.validate(ignorable_errors=ignorable_errors,
                           validate_by_deps=False)
        except exception.StackValidationFailed as ex:
            return {'Error': six.text_type(ex)}

        def filter_parameter(p):
            return p.name not in stack.parameters.PSEUDO_PARAMETERS

        params = stack.parameters.map(api.format_validate_parameter,
                                      filter_func=filter_parameter)

        result = {
            'Description': tmpl.get('Description', ''),
            'Parameters': params
        }

        param_groups = parameter_groups.ParameterGroups(tmpl)
        if param_groups.parameter_groups:
            result['ParameterGroups'] = param_groups.parameter_groups

        if show_nested:
            # Note preview_resources is needed here to build the tree
            # of nested resources/stacks in memory, otherwise the
            # nested/has_nested() tests below won't work
            stack.preview_resources()

            def nested_params(stk):
                n_result = {}
                for r in stk:
                    if stk[r].has_nested():
                        n_params = stk[r].nested().parameters.map(
                            api.format_validate_parameter,
                            filter_func=filter_parameter)
                        n_result[r] = {
                            'Type': stk[r].type(),
                            'Description': stk[r].nested().t.get(
                                'Description', ''),
                            'Parameters': n_params
                        }
                        n_result[r].update(nested_params(stk[r].nested()))
                return {'NestedParameters': n_result} if n_result else {}

            result.update(nested_params(stack))

        return result

    @context.request_context
    def authenticated_to_backend(self, cnxt):
        """Validate the credentials in the RPC context.

        Verify that the credentials in the RPC context are valid for the
        current cloud backend.
        """
        return clients.Clients(cnxt).authenticated()

    @context.request_context
    def get_template(self, cnxt, stack_identity):
        """Get the template.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to see.
        """
        s = self._get_stack(cnxt, stack_identity, show_deleted=True)
        if s:
            return s.raw_template.template
        return None

    @context.request_context
    def get_environment(self, cnxt, stack_identity):
        """Returns the environment for an existing stack.

        :param cnxt: RPC context
        :param stack_identity: identifies the stack
        :rtype: dict
        """
        s = self._get_stack(cnxt, stack_identity, show_deleted=True)
        if s:
            return s.raw_template.environment
        return None

    @context.request_context
    def list_outputs(self, cntx, stack_identity):
        """Get a list of stack outputs.

        :param cntx: RPC context.
        :param stack_identity: Name of the stack you want to see.
        :return: list of stack outputs in defined format.
        """
        s = self._get_stack(cntx, stack_identity)
        stack = parser.Stack.load(cntx, stack=s, resolve_data=False)

        return api.format_stack_outputs(stack, stack.t[stack.t.OUTPUTS])

    @context.request_context
    def show_output(self, cntx, stack_identity, output_key):
        """Returns dict with specified output key, value and description.

        :param cntx: RPC context.
        :param stack_identity: Name of the stack you want to see.
        :param output_key: key of desired stack output.
        :return: dict with output key, value and description in defined format.
        """
        s = self._get_stack(cntx, stack_identity)
        stack = parser.Stack.load(cntx, stack=s, resolve_data=False)

        outputs = stack.t[stack.t.OUTPUTS]

        if output_key not in outputs:
            raise exception.NotFound(_('Specified output key %s not '
                                       'found.') % output_key)
        output = stack.resolve_static_data(outputs[output_key])

        if not stack.outputs:
            stack.outputs.update({output_key: output})

        return api.format_stack_output(stack, {output_key: output}, output_key)

    def _remote_call(self, cnxt, lock_engine_id, call, **kwargs):
        timeout = cfg.CONF.engine_life_check_timeout
        self.cctxt = self._client.prepare(
            version='1.0',
            timeout=timeout,
            topic=rpc_api.LISTENER_TOPIC,
            server=lock_engine_id)
        try:
            self.cctxt.call(cnxt, call, **kwargs)
        except messaging.MessagingTimeout:
            return False

    @context.request_context
    def delete_stack(self, cnxt, stack_identity):
        """Delete a given stack.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to delete.
        """

        st = self._get_stack(cnxt, stack_identity)
        LOG.info(_LI('Deleting stack %s'), st.name)
        stack = parser.Stack.load(cnxt, stack=st)
        self.resource_enforcer.enforce_stack(stack)

        if stack.convergence and cfg.CONF.convergence_engine:
            template = templatem.Template.create_empty_template()
            stack.thread_group_mgr = self.thread_group_mgr
            stack.converge_stack(template=template, action=stack.DELETE)
            return

        lock = stack_lock.StackLock(cnxt, stack.id, self.engine_id)
        with lock.try_thread_lock() as acquire_result:

            # Successfully acquired lock
            if acquire_result is None:
                self.thread_group_mgr.stop_timers(stack.id)
                self.thread_group_mgr.start_with_acquired_lock(stack, lock,
                                                               stack.delete)
                return

        # Current engine has the lock
        if acquire_result == self.engine_id:
            # give threads which are almost complete an opportunity to
            # finish naturally before force stopping them
            eventlet.sleep(0.2)
            self.thread_group_mgr.stop(stack.id)

        # Another active engine has the lock
        elif stack_lock.StackLock.engine_alive(cnxt, acquire_result):
            stop_result = self._remote_call(
                cnxt, acquire_result, self.listener.STOP_STACK,
                stack_identity=stack_identity)
            if stop_result is None:
                LOG.debug("Successfully stopped remote task on engine %s"
                          % acquire_result)
            else:
                raise exception.StopActionFailed(stack_name=stack.name,
                                                 engine_id=acquire_result)

        # There may be additional resources that we don't know about
        # if an update was in-progress when the stack was stopped, so
        # reload the stack from the database.
        st = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=st)

        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              stack.delete)
        return None

    @context.request_context
    def export_stack(self, cnxt, stack_identity):
        """Exports the stack data json.

        Intended to be used to safely retrieve the stack data before
        performing the abandon action.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to export.
        """
        return self.abandon_stack(cnxt, stack_identity, abandon=False)

    @context.request_context
    def abandon_stack(self, cnxt, stack_identity, abandon=True):
        """Abandon a given stack.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to abandon.
        :param abandon: Delete Heat stack but not physical resources.
        """
        if not cfg.CONF.enable_stack_abandon:
            raise exception.NotSupported(feature='Stack Abandon')

        st = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=st)
        lock = stack_lock.StackLock(cnxt, stack.id, self.engine_id)
        with lock.thread_lock():
            # Get stack details before deleting it.
            stack_info = stack.prepare_abandon()
            if abandon:
                LOG.info(_LI('abandoning stack %s'), st.name)
                self.thread_group_mgr.start_with_acquired_lock(stack,
                                                               lock,
                                                               stack.delete,
                                                               abandon=True)
            else:
                LOG.info(_LI('exporting stack %s'), st.name)
            return stack_info

    def list_resource_types(self,
                            cnxt,
                            support_status=None,
                            type_name=None,
                            heat_version=None):
        """Get a list of supported resource types.

        :param cnxt: RPC context.
        :param support_status: Support status of resource type
        :param type_name: Resource type's name (regular expression allowed)
        :param heat_version: Heat version
        """
        return resources.global_env().get_types(cnxt,
                                                support_status=support_status,
                                                type_name=type_name,
                                                version=heat_version)

    def list_template_versions(self, cnxt):
        mgr = templatem._get_template_extension_manager()
        _template_classes = [(name, mgr[name].plugin)
                             for name in mgr.names()]
        versions = []
        for t in _template_classes:
            if t[1] in [cfntemplate.CfnTemplate, cfntemplate.HeatTemplate]:
                versions.append({'version': t[0], 'type': 'cfn'})
            else:
                versions.append({'version': t[0], 'type': 'hot'})
        return versions

    def list_template_functions(self, cnxt, template_version):
        mgr = templatem._get_template_extension_manager()
        try:
            tmpl_class = mgr[template_version]
        except KeyError:
            raise exception.NotFound(_("Template with version %s not found") %
                                     template_version)

        functions = []
        for func_name, func in six.iteritems(tmpl_class.plugin.functions):
            if func is not hot_functions.Removed:
                if func.__doc__.split('\n')[0]:
                    desc = func.__doc__.split('\n')[0].strip()
                else:
                    desc = func.__doc__.split('\n')[1].strip()
                functions.append(
                    {'functions': func_name,
                     'description': desc}
                )
        return functions

    def resource_schema(self, cnxt, type_name):
        """Return the schema of the specified type.

        :param cnxt: RPC context.
        :param type_name: Name of the resource type to obtain the schema of.
        """
        self.resource_enforcer.enforce(cnxt, type_name)
        try:
            resource_class = resources.global_env().get_class(type_name)
        except exception.NotFound:
            LOG.exception(_LE('Error loading resource type %s '
                              'from global environment.'),
                          type_name)
            raise exception.InvalidGlobalResource(type_name=type_name)

        if resource_class.support_status.status == support.HIDDEN:
            raise exception.NotSupported(type_name)

        try:
            svc_available = resource_class.is_service_available(cnxt)
        except Exception as exc:
            raise exception.ResourceTypeUnavailable(
                service_name=resource_class.default_client_name,
                resource_type=type_name,
                reason=six.text_type(exc))
        else:
            if not svc_available:
                raise exception.ResourceTypeUnavailable(
                    service_name=resource_class.default_client_name,
                    resource_type=type_name,
                    reason='Service endpoint not in service catalog.')

        def properties_schema():
            for name, schema_dict in resource_class.properties_schema.items():
                schema = properties.Schema.from_legacy(schema_dict)
                if schema.implemented:
                    yield name, dict(schema)

        def attributes_schema():
            for name, schema_data in itertools.chain(
                    resource_class.attributes_schema.items(),
                    resource_class.base_attributes_schema.items()):
                schema = attributes.Schema.from_attribute(schema_data)
                yield name, dict(schema)

        return {
            rpc_api.RES_SCHEMA_RES_TYPE: type_name,
            rpc_api.RES_SCHEMA_PROPERTIES: dict(properties_schema()),
            rpc_api.RES_SCHEMA_ATTRIBUTES: dict(attributes_schema()),
            rpc_api.RES_SCHEMA_SUPPORT_STATUS:
                resource_class.support_status.to_dict(),
        }

    def generate_template(self, cnxt, type_name, template_type='cfn'):
        """Generate a template based on the specified type.

        :param cnxt: RPC context.
        :param type_name: Name of the resource type to generate a template for.
        :param template_type: the template type to generate, cfn or hot.
        """
        self.resource_enforcer.enforce(cnxt, type_name)
        try:
            resource_class = resources.global_env().get_class(type_name)
        except exception.NotFound:
            LOG.exception(_LE('Error loading resource type %s '
                              'from global environment.'),
                          type_name)
            raise exception.InvalidGlobalResource(type_name=type_name)
        else:
            if resource_class.support_status.status == support.HIDDEN:
                raise exception.NotSupported(type_name)
            return resource_class.resource_to_template(type_name,
                                                       template_type)

    @context.request_context
    def list_events(self, cnxt, stack_identity, filters=None, limit=None,
                    marker=None, sort_keys=None, sort_dir=None):
        """Lists all events associated with a given stack.

        It supports pagination (``limit`` and ``marker``),
        sorting (``sort_keys`` and ``sort_dir``) and filtering(filters)
        of the results.

        :param cnxt: RPC context.
        :param stack_identity: Name of the stack you want to get events for
        :param filters: a dict with attribute:value to filter the list
        :param limit: the number of events to list (integer or string)
        :param marker: the ID of the last event in the previous page
        :param sort_keys: an array of fields used to sort the list
        :param sort_dir: the direction of the sort ('asc' or 'desc').
        """

        if stack_identity is not None:
            st = self._get_stack(cnxt, stack_identity, show_deleted=True)

            events = event_object.Event.get_all_by_stack(
                cnxt,
                st.id,
                limit=limit,
                marker=marker,
                sort_keys=sort_keys,
                sort_dir=sort_dir,
                filters=filters)
        else:
            events = event_object.Event.get_all_by_tenant(
                cnxt, limit=limit,
                marker=marker,
                sort_keys=sort_keys,
                sort_dir=sort_dir,
                filters=filters)

        stacks = {}

        def get_stack(stack_id):
            if stack_id not in stacks:
                stacks[stack_id] = parser.Stack.load(cnxt, stack_id)
            return stacks[stack_id]

        return [api.format_event(evt.Event.load(cnxt,
                                                e.id, e,
                                                get_stack(e.stack_id)))
                for e in events]

    def _authorize_stack_user(self, cnxt, stack, resource_name):
        """Filter access to describe_stack_resource for in-instance users.

        - The user must map to a User resource defined in the requested stack
        - The user resource must validate OK against any Policy specified
        """
        # first check whether access is allowed by context user_id
        if stack.access_allowed(cnxt.user_id, resource_name):
            return True

        # fall back to looking for EC2 credentials in the context
        try:
            ec2_creds = jsonutils.loads(cnxt.aws_creds).get('ec2Credentials')
        except (TypeError, AttributeError):
            ec2_creds = None

        if not ec2_creds:
            return False

        access_key = ec2_creds.get('access')
        return stack.access_allowed(access_key, resource_name)

    def _verify_stack_resource(self, stack, resource_name):
        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        resource = stack[resource_name]
        if resource.id is None:
            raise exception.ResourceNotAvailable(resource_name=resource_name)

    @context.request_context
    def describe_stack_resource(self, cnxt, stack_identity, resource_name,
                                with_attr=None):
        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)

        if cfg.CONF.heat_stack_user_role in cnxt.roles:
            if not self._authorize_stack_user(cnxt, stack, resource_name):
                LOG.warning(_LW("Access denied to resource %s"), resource_name)
                raise exception.Forbidden()

        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        return api.format_stack_resource(stack[resource_name],
                                         with_attr=with_attr)

    @context.request_context
    def resource_signal(self, cnxt, stack_identity, resource_name, details,
                        sync_call=False):
        """Calls resource's signal for the specified resource.

        :param sync_call: indicates whether a synchronized call behavior is
                          expected. This is reserved for CFN WaitCondition
                          implementation.
        """

        def _resource_signal(stack, rsrc, details, need_check):
            LOG.debug("signaling resource %s:%s" % (stack.name, rsrc.name))
            needs_metadata_updates = rsrc.signal(details, need_check)

            if not needs_metadata_updates:
                return

            # Refresh the metadata for all other resources, since signals can
            # update metadata which is used by other resources, e.g
            # when signalling a WaitConditionHandle resource, and other
            # resources may refer to WaitCondition Fn::GetAtt Data
            for r in stack.dependencies:
                if (r.name != rsrc.name and r.id is not None and
                        r.action != r.INIT):
                    r.metadata_update()

        s = self._get_stack(cnxt, stack_identity)

        # This is not "nice" converting to the stored context here,
        # but this happens because the keystone user associated with the
        # signal doesn't have permission to read the secret key of
        # the user associated with the cfn-credentials file
        stack = parser.Stack.load(cnxt, stack=s, use_stored_context=True)
        self._verify_stack_resource(stack, resource_name)

        rsrc = stack[resource_name]

        if callable(rsrc.signal):
            rsrc._signal_check_action()
            rsrc._signal_check_hook(details)
            if sync_call:
                _resource_signal(stack, rsrc, details, False)
                return rsrc.metadata_get()
            else:
                self.thread_group_mgr.start(stack.id, _resource_signal,
                                            stack, rsrc, details, False)

    @context.request_context
    def resource_mark_unhealthy(self, cnxt, stack_identity, resource_name,
                                mark_unhealthy, resource_status_reason=None):
        """Mark the resource as healthy or unhealthy.

           Put the resource in CHECK_FAILED state if 'mark_unhealthy'
           is true. Put the resource in CHECK_COMPLETE if 'mark_unhealthy'
           is false and the resource is in CHECK_FAILED state.
           Otherwise, make no change.

        :param mark_unhealthy: indicates whether the resource is unhealthy.
        :param resource_status_reason: reason for health change.
        """
        def lock(rsrc):
            if rsrc.stack.convergence:
                return rsrc.lock(self.engine_id)
            else:
                return stack_lock.StackLock(cnxt,
                                            rsrc.stack.id,
                                            self.engine_id)

        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)
        if resource_name not in stack:
            raise exception.ResourceNotFound(resource_name=resource_name,
                                             stack_name=stack.name)

        if not isinstance(mark_unhealthy, bool):
            raise exception.Invalid(reason="mark_unhealthy is not a boolean")

        rsrc = stack[resource_name]
        reason = (resource_status_reason or
                  "state changed by resource_mark_unhealthy api")
        try:
            with lock(rsrc):
                if mark_unhealthy:
                    rsrc.state_set(rsrc.CHECK, rsrc.FAILED, reason=reason)
                elif rsrc.state == (rsrc.CHECK, rsrc.FAILED):
                    rsrc.state_set(rsrc.CHECK, rsrc.COMPLETE, reason=reason)

        except exception.UpdateInProgress:
            raise exception.ActionInProgress(stack_name=stack.name,
                                             action=stack.action)

    @context.request_context
    def find_physical_resource(self, cnxt, physical_resource_id):
        """Return an identifier for the specified resource.

        :param cnxt: RPC context.
        :param physical_resource_id: The physical resource ID to look up.
        """
        rs = resource_objects.Resource.get_by_physical_resource_id(
            cnxt,
            physical_resource_id)
        if not rs:
            raise exception.EntityNotFound(entity='Resource',
                                           name=physical_resource_id)

        stack = parser.Stack.load(cnxt, stack_id=rs.stack_id)
        resource = stack[rs.name]

        return dict(resource.identifier())

    @context.request_context
    def describe_stack_resources(self, cnxt, stack_identity, resource_name):
        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)

        return [api.format_stack_resource(resource)
                for name, resource in six.iteritems(stack)
                if resource_name is None or name == resource_name]

    @context.request_context
    def list_stack_resources(self, cnxt, stack_identity,
                             nested_depth=0, with_detail=False,
                             filters=None):
        s = self._get_stack(cnxt, stack_identity, show_deleted=True)
        stack = parser.Stack.load(cnxt, stack=s)
        depth = min(nested_depth, cfg.CONF.max_nested_stack_depth)

        return [api.format_stack_resource(resource, detail=with_detail)
                for resource in stack.iter_resources(depth,
                                                     filters=filters)]

    @context.request_context
    def stack_suspend(self, cnxt, stack_identity):
        """Handle request to perform suspend action on a stack."""
        def _stack_suspend(stack):
            LOG.debug("suspending stack %s" % stack.name)
            stack.suspend()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self.resource_enforcer.enforce_stack(stack)
        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_suspend, stack)

    @context.request_context
    def stack_resume(self, cnxt, stack_identity):
        """Handle request to perform a resume action on a stack."""
        def _stack_resume(stack):
            LOG.debug("resuming stack %s" % stack.name)
            stack.resume()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self.resource_enforcer.enforce_stack(stack)
        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_resume, stack)

    @context.request_context
    def stack_snapshot(self, cnxt, stack_identity, name):
        def _stack_snapshot(stack, snapshot):

            def save_snapshot(stack, action, status, reason):
                """Function that saves snapshot before snapshot complete."""
                data = stack.prepare_abandon()
                data["status"] = status
                snapshot_object.Snapshot.update(
                    cnxt, snapshot.id,
                    {'data': data, 'status': status,
                     'status_reason': reason})

            LOG.debug("Snapshotting stack %s" % stack.name)
            stack.snapshot(save_snapshot_func=save_snapshot)

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        if stack.status == stack.IN_PROGRESS:
            LOG.info(_LI('%(stack)s is in state %(action)s_IN_PROGRESS, '
                         'snapshot is not permitted.'), {
                             'stack': six.text_type(stack),
                             'action': stack.action})
            raise exception.ActionInProgress(stack_name=stack.name,
                                             action=stack.action)

        lock = stack_lock.StackLock(cnxt, stack.id, self.engine_id)

        with lock.thread_lock():
            snapshot = snapshot_object.Snapshot.create(cnxt, {
                'tenant': cnxt.tenant_id,
                'name': name,
                'stack_id': stack.id,
                'status': 'IN_PROGRESS'})
            self.thread_group_mgr.start_with_acquired_lock(
                stack, lock, _stack_snapshot, stack, snapshot)
            return api.format_snapshot(snapshot)

    @context.request_context
    def show_snapshot(self, cnxt, stack_identity, snapshot_id):
        s = self._get_stack(cnxt, stack_identity)
        snapshot = snapshot_object.Snapshot.get_snapshot_by_stack(
            cnxt, snapshot_id, s)
        return api.format_snapshot(snapshot)

    @context.request_context
    def delete_snapshot(self, cnxt, stack_identity, snapshot_id):
        def _delete_snapshot(stack, snapshot):
            stack.delete_snapshot(snapshot)
            snapshot_object.Snapshot.delete(cnxt, snapshot_id)

        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)
        snapshot = snapshot_object.Snapshot.get_snapshot_by_stack(
            cnxt, snapshot_id, s)
        if snapshot.status == stack.IN_PROGRESS:
            msg = _('Deleting in-progress snapshot')
            raise exception.NotSupported(feature=msg)

        self.thread_group_mgr.start(
            stack.id, _delete_snapshot, stack, snapshot)

    @context.request_context
    def stack_check(self, cnxt, stack_identity):
        """Handle request to perform a check action on a stack."""
        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)
        LOG.info(_LI("Checking stack %s"), stack.name)

        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              stack.check)

    @context.request_context
    def stack_restore(self, cnxt, stack_identity, snapshot_id):
        def _stack_restore(stack, snapshot):
            LOG.debug("restoring stack %s" % stack.name)
            stack.restore(snapshot)

        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)
        self.resource_enforcer.enforce_stack(stack)
        snapshot = snapshot_object.Snapshot.get_snapshot_by_stack(
            cnxt, snapshot_id, s)
        # FIXME(pas-ha) has to be amended to deny restoring stacks
        # that have disallowed for current user

        self.thread_group_mgr.start_with_lock(cnxt, stack, self.engine_id,
                                              _stack_restore, stack, snapshot)

    @context.request_context
    def stack_list_snapshots(self, cnxt, stack_identity):
        s = self._get_stack(cnxt, stack_identity)
        data = snapshot_object.Snapshot.get_all(cnxt, s.id)
        return [api.format_snapshot(snapshot) for snapshot in data]

    @context.request_context
    def create_watch_data(self, cnxt, watch_name, stats_data):
        """Creates data for CloudWatch and WaitConditions.

        This could be used by CloudWatch and WaitConditions
        and treat HA service events like any other CloudWatch.
        """
        def get_matching_watches():
            if watch_name:
                yield watchrule.WatchRule.load(cnxt, watch_name)
            else:
                for wr in watch_rule.WatchRule.get_all(cnxt):
                    if watchrule.rule_can_use_sample(wr, stats_data):
                        yield watchrule.WatchRule.load(cnxt, watch=wr)

        rule_run = False
        for rule in get_matching_watches():
            rule.create_watch_data(stats_data)
            rule_run = True

        if not rule_run:
            if watch_name is None:
                watch_name = 'Unknown'
            raise exception.EntityNotFound(entity='Watch Rule',
                                           name=watch_name)

        return stats_data

    @context.request_context
    def show_watch(self, cnxt, watch_name):
        """Return the attributes of one watch/alarm.

        :param cnxt: RPC context.
        :param watch_name: Name of the watch you want to see, or None to see
            all.
        """
        if watch_name:
            wrn = [watch_name]
        else:
            try:
                wrn = [w.name for w in watch_rule.WatchRule.get_all(cnxt)]
            except Exception as ex:
                LOG.warning(_LW('show_watch (all) db error %s'), ex)
                return

        wrs = [watchrule.WatchRule.load(cnxt, w) for w in wrn]
        result = [api.format_watch(w) for w in wrs]
        return result

    @context.request_context
    def show_watch_metric(self, cnxt, metric_namespace=None, metric_name=None):
        """Return the datapoints for a metric.

        :param cnxt: RPC context.
        :param metric_namespace: Name of the namespace you want to see, or None
            to see all.
        :param metric_name: Name of the metric you want to see, or None to see
            all.
        """

        # DB API and schema does not yet allow us to easily query by
        # namespace/metric, but we will want this at some point
        # for now, the API can query all metric data and filter locally
        if metric_namespace is not None or metric_name is not None:
            LOG.error(_LE("Filtering by namespace/metric not yet supported"))
            return

        try:
            wds = watch_data.WatchData.get_all(cnxt)
        except Exception as ex:
            LOG.warning(_LW('show_metric (all) db error %s'), ex)
            return

        result = [api.format_watch_data(w) for w in wds]
        return result

    @context.request_context
    def set_watch_state(self, cnxt, watch_name, state):
        """Temporarily set the state of a given watch.

        :param cnxt: RPC context.
        :param watch_name: Name of the watch.
        :param state: State (must be one defined in WatchRule class.
        """
        wr = watchrule.WatchRule.load(cnxt, watch_name)
        if wr.state == rpc_api.WATCH_STATE_CEILOMETER_CONTROLLED:
            return
        actions = wr.set_watch_state(state)
        for action in actions:
            self.thread_group_mgr.start(wr.stack_id, action)

        # Return the watch with the state overridden to indicate success
        # We do not update the timestamps as we are not modifying the DB
        result = api.format_watch(wr)
        result[rpc_api.WATCH_STATE_VALUE] = state
        return result

    @context.request_context
    def show_software_config(self, cnxt, config_id):
        return self.software_config.show_software_config(cnxt, config_id)

    @context.request_context
    def list_software_configs(self, cnxt, limit=None, marker=None,
                              tenant_safe=True):
        return self.software_config.list_software_configs(
            cnxt,
            limit=limit,
            marker=marker,
            tenant_safe=tenant_safe)

    @context.request_context
    def create_software_config(self, cnxt, group, name, config,
                               inputs, outputs, options):
        return self.software_config.create_software_config(
            cnxt,
            group=group,
            name=name,
            config=config,
            inputs=inputs,
            outputs=outputs,
            options=options)

    @context.request_context
    def delete_software_config(self, cnxt, config_id):
        return self.software_config.delete_software_config(cnxt, config_id)

    @context.request_context
    def list_software_deployments(self, cnxt, server_id):
        return self.software_config.list_software_deployments(
            cnxt, server_id)

    @context.request_context
    def metadata_software_deployments(self, cnxt, server_id):
        return self.software_config.metadata_software_deployments(
            cnxt, server_id)

    @context.request_context
    def show_software_deployment(self, cnxt, deployment_id):
        return self.software_config.show_software_deployment(
            cnxt, deployment_id)

    @context.request_context
    def check_software_deployment(self, cnxt, deployment_id, timeout):
        return self.software_config.check_software_deployment(
            cnxt, deployment_id, timeout)

    @context.request_context
    def create_software_deployment(self, cnxt, server_id, config_id,
                                   input_values, action, status,
                                   status_reason, stack_user_project_id,
                                   deployment_id=None):
        return self.software_config.create_software_deployment(
            cnxt, server_id=server_id,
            config_id=config_id,
            deployment_id=deployment_id,
            input_values=input_values,
            action=action,
            status=status,
            status_reason=status_reason,
            stack_user_project_id=stack_user_project_id)

    @context.request_context
    def signal_software_deployment(self, cnxt, deployment_id, details,
                                   updated_at):
        return self.software_config.signal_software_deployment(
            cnxt,
            deployment_id=deployment_id,
            details=details,
            updated_at=updated_at)

    @context.request_context
    def update_software_deployment(self, cnxt, deployment_id, config_id,
                                   input_values, output_values, action,
                                   status, status_reason, updated_at):
        return self.software_config.update_software_deployment(
            cnxt,
            deployment_id=deployment_id,
            config_id=config_id,
            input_values=input_values,
            output_values=output_values,
            action=action,
            status=status,
            status_reason=status_reason,
            updated_at=updated_at)

    @context.request_context
    def delete_software_deployment(self, cnxt, deployment_id):
        return self.software_config.delete_software_deployment(
            cnxt, deployment_id)

    @context.request_context
    def list_services(self, cnxt):
        result = [service_utils.format_service(srv)
                  for srv in service_objects.Service.get_all(cnxt)]
        return result

    def service_manage_report(self):
        cnxt = context.get_admin_context()

        if self.service_id is None:
            service_ref = service_objects.Service.create(
                cnxt,
                dict(host=self.host,
                     hostname=self.hostname,
                     binary=self.binary,
                     engine_id=self.engine_id,
                     topic=self.topic,
                     report_interval=cfg.CONF.periodic_interval)
            )
            self.service_id = service_ref['id']
            LOG.debug('Service %s is started' % self.service_id)

        try:
            service_objects.Service.update_by_id(
                cnxt,
                self.service_id,
                dict(deleted_at=None))
            LOG.debug('Service %s is updated' % self.service_id)
        except Exception as ex:
            LOG.error(_LE('Service %(service_id)s update '
                          'failed: %(error)s'),
                      {'service_id': self.service_id, 'error': ex})

    def service_manage_cleanup(self):
        cnxt = context.get_admin_context()
        last_updated_window = (3 * cfg.CONF.periodic_interval)
        time_line = timeutils.utcnow() - datetime.timedelta(
            seconds=last_updated_window)

        service_refs = service_objects.Service.get_all_by_args(
            cnxt, self.host, self.binary, self.hostname)
        for service_ref in service_refs:
            if (service_ref['id'] == self.service_id or
                    service_ref['deleted_at'] is not None or
                    service_ref['updated_at'] is None):
                continue
            if service_ref['updated_at'] < time_line:
                # hasn't been updated, assuming it's died.
                LOG.debug('Service %s was aborted' % service_ref['id'])
                service_objects.Service.delete(cnxt, service_ref['id'])

    def set_stack_and_resource_to_failed(self, stack):
        for name, rsrc in six.iteritems(stack.resources):
            if rsrc.status == rsrc.IN_PROGRESS:
                status_reason = ('Engine went down '
                                 'during resource %s' % rsrc.action)
                rsrc.state_set(rsrc.action,
                               rsrc.FAILED,
                               six.text_type(status_reason))
        reason = ('Engine went down during stack %s' % stack.action)
        stack.state_set(stack.action, stack.FAILED, six.text_type(reason))

    def reset_stack_status(self):
        cnxt = context.get_admin_context()
        filters = {
            'status': parser.Stack.IN_PROGRESS,
            'convergence': False
        }
        stacks = stack_object.Stack.get_all(cnxt,
                                            filters=filters,
                                            tenant_safe=False,
                                            show_nested=True) or []
        for s in stacks:
            stack_id = s.id
            lock = stack_lock.StackLock(cnxt, stack_id, self.engine_id)
            engine_id = lock.get_engine_id()
            try:
                with lock.thread_lock(retry=False):

                    # refetch stack and confirm it is still IN_PROGRESS
                    s = stack_object.Stack.get_by_id(
                        cnxt,
                        stack_id,
                        tenant_safe=False,
                        eager_load=True)
                    if s.status != parser.Stack.IN_PROGRESS:
                        lock.release()
                        continue

                    stk = parser.Stack.load(cnxt, stack=s,
                                            use_stored_context=True)
                    LOG.info(_LI('Engine %(engine)s went down when stack '
                                 '%(stack_id)s was in action %(action)s'),
                             {'engine': engine_id, 'action': stk.action,
                              'stack_id': stk.id})

                    # Set stack and resources status to FAILED in sub thread
                    self.thread_group_mgr.start_with_acquired_lock(
                        stk,
                        lock,
                        self.set_stack_and_resource_to_failed,
                        stk
                    )
            except exception.ActionInProgress:
                continue
            except Exception:
                LOG.exception(_LE('Error while resetting stack: %s')
                              % stack_id)
                continue
