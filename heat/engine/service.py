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

import functools
import json

from oslo.config import cfg
import webob

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
from heat.engine import parameters
from heat.engine import parser
from heat.engine import properties
from heat.engine import resource
from heat.engine import resources
from heat.engine import template as tpl
from heat.engine import watchrule

from heat.openstack.common import log as logging
from heat.openstack.common import threadgroup
from heat.openstack.common.gettextutils import _
from heat.openstack.common.rpc import service
from heat.openstack.common import uuidutils


logger = logging.getLogger(__name__)


def request_context(func):
    @functools.wraps(func)
    def wrapped(self, ctx, *args, **kwargs):
        if ctx is not None and not isinstance(ctx, context.RequestContext):
            ctx = context.RequestContext.from_dict(ctx.to_dict())
        return func(self, ctx, *args, **kwargs)
    return wrapped


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
    def __init__(self, host, topic, manager=None):
        super(EngineService, self).__init__(host, topic)
        # stg == "Stack Thread Groups"
        self.stg = {}
        resources.initialise()

    def _start_in_thread(self, stack_id, func, *args, **kwargs):
        if stack_id not in self.stg:
            self.stg[stack_id] = threadgroup.ThreadGroup()
        self.stg[stack_id].add_thread(func, *args, **kwargs)

    def _timer_in_thread(self, stack_id, func, *args, **kwargs):
        """
        Define a periodic task, to be run in a separate thread, in the stack
        threadgroups.  Periodicity is cfg.CONF.periodic_interval
        """
        if stack_id not in self.stg:
            self.stg[stack_id] = threadgroup.ThreadGroup()
        self.stg[stack_id].add_timer(cfg.CONF.periodic_interval,
                                     func, *args, **kwargs)

    def _service_task(self):
        """
        This is a dummy task which gets queued on the service.Service
        threadgroup.  Without this service.Service sees nothing running
        i.e has nothing to wait() on, so the process exits..
        This could also be used to trigger periodic non-stack-specific
        housekeeping tasks
        """
        pass

    def _start_watch_task(self, stack_id, cnxt):

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
            self._timer_in_thread(stack_id, self._periodic_watcher_task,
                                  sid=stack_id)

    def start(self):
        super(EngineService, self).start()

        # Create dummy service task, because when there is nothing queued
        # on self.tg the process exits
        self.tg.add_timer(cfg.CONF.periodic_interval,
                          self._service_task)

        # Create a periodic_watcher_task per-stack
        admin_context = context.get_admin_context()
        stacks = db_api.stack_get_all(admin_context)
        for s in stacks:
            self._start_watch_task(s.id, admin_context)

    @request_context
    def identify_stack(self, cnxt, stack_name):
        """
        The identify_stack method returns the full stack identifier for a
        single, live stack given the stack name.
        arg1 -> RPC context.
        arg2 -> Name or UUID of the stack to look up.
        """
        if uuidutils.is_uuid_like(stack_name):
            s = db_api.stack_get(cnxt, stack_name, show_deleted=True)
        else:
            s = db_api.stack_get_by_name(cnxt, stack_name)
        if s:
            stack = parser.Stack.load(cnxt, stack=s)
            return dict(stack.identifier())
        else:
            raise exception.StackNotFound(stack_name=stack_name)

    def _get_stack(self, cnxt, stack_identity, show_deleted=False):
        identity = identifier.HeatIdentifier(**stack_identity)

        if identity.tenant != cnxt.tenant_id:
            raise exception.InvalidTenant(target=identity.tenant,
                                          actual=cnxt.tenant_id)

        s = db_api.stack_get(cnxt, identity.stack_id,
                             show_deleted=show_deleted)

        if s is None:
            raise exception.StackNotFound(stack_name=identity.stack_name)

        if identity.path or s.name != identity.stack_name:
            raise exception.StackNotFound(stack_name=identity.stack_name)

        return s

    @request_context
    def show_stack(self, cnxt, stack_identity):
        """
        Return detailed information about one or all stacks.
        arg1 -> RPC cnxt.
        arg2 -> Name of the stack you want to show, or None to show all
        """
        if stack_identity is not None:
            stacks = [self._get_stack(cnxt, stack_identity, show_deleted=True)]
        else:
            stacks = db_api.stack_get_all_by_tenant(cnxt) or []

        def format_stack_detail(s):
            stack = parser.Stack.load(cnxt, stack=s)
            return api.format_stack(stack)

        return [format_stack_detail(s) for s in stacks]

    @request_context
    def list_stacks(self, cnxt):
        """
        The list_stacks method returns attributes of all stacks.
        arg1 -> RPC cnxt.
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

        stacks = db_api.stack_get_all_by_tenant(cnxt) or []
        return list(format_stack_details(stacks))

    def _validate_deferred_auth_context(self, cnxt, stack):
        if cfg.CONF.deferred_auth_method != 'password':
            return

        if not stack.requires_deferred_auth():
            return

        if cnxt.username is None:
            raise exception.MissingCredentialError(required='X-Auth-User')
        if cnxt.password is None:
            raise exception.MissingCredentialError(required='X-Auth-Key')

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
                      (currently provider templates).
        :param args: Request parameters/args passed from API
        """
        logger.info('template is %s' % template)

        def _stack_create(stack):
            # Create the stack, and create the periodic task if successful
            stack.create()
            if stack.action == stack.CREATE and stack.status == stack.COMPLETE:
                # Schedule a periodic watcher task for this stack
                self._start_watch_task(stack.id, cnxt)
            else:
                logger.warning("Stack create failed, status %s" % stack.status)

        if db_api.stack_get_by_name(cnxt, stack_name):
            raise exception.StackExists(stack_name=stack_name)
        tenant_limit = cfg.CONF.max_stacks_per_tenant
        if db_api.stack_count_all_by_tenant(cnxt) >= tenant_limit:
            message = _("You have reached the maximum stacks per tenant, %d."
                        " Please delete some stacks.") % tenant_limit
            raise exception.RequestLimitExceeded(message=message)

        tmpl = parser.Template(template, files=files)

        if len(tmpl[tpl.RESOURCES]) > cfg.CONF.max_resources_per_stack:
            raise exception.RequestLimitExceeded(
                message=exception.StackResourceLimitExceeded.message)

        # Extract the common query parameters
        common_params = api.extract_args(args)
        env = environment.Environment(params)
        stack = parser.Stack(cnxt, stack_name, tmpl,
                             env, **common_params)

        self._validate_deferred_auth_context(cnxt, stack)

        stack.validate()

        stack_id = stack.store()

        self._start_in_thread(stack_id, _stack_create, stack)

        return dict(stack.identifier())

    @request_context
    def update_stack(self, cnxt, stack_identity, template, params,
                     files, args):
        """
        The update_stack method updates an existing stack based on the
        provided template and parameters.
        Note that at this stage the template has already been fetched from the
        heat-api process if using a template-url.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to create.
        arg3 -> Template of stack you want to create.
        arg4 -> Stack Input Params
        arg4 -> Request parameters/args passed from API
        """
        logger.info('template is %s' % template)

        # Get the database representation of the existing stack
        db_stack = self._get_stack(cnxt, stack_identity)

        current_stack = parser.Stack.load(cnxt, stack=db_stack)

        if current_stack.action == current_stack.SUSPEND:
            msg = _('Updating a stack when it is suspended')
            raise exception.NotSupported(feature=msg)

        # Now parse the template and any parameters for the updated
        # stack definition.
        tmpl = parser.Template(template, files=files)
        if len(tmpl[tpl.RESOURCES]) > cfg.CONF.max_resources_per_stack:
            raise exception.RequestLimitExceeded(
                message=exception.StackResourceLimitExceeded.message)
        stack_name = current_stack.name
        common_params = api.extract_args(args)
        env = environment.Environment(params)
        updated_stack = parser.Stack(cnxt, stack_name, tmpl,
                                     env, **common_params)

        self._validate_deferred_auth_context(cnxt, updated_stack)
        updated_stack.validate()

        self._start_in_thread(db_stack.id, current_stack.update, updated_stack)

        return dict(current_stack.identifier())

    @request_context
    def validate_template(self, cnxt, template):
        """
        The validate_template method uses the stack parser to check
        the validity of a template.

        arg1 -> RPC context.
        arg3 -> Template of stack you want to create.
        arg4 -> Stack Input Params
        """
        logger.info('validate_template')
        if template is None:
            msg = _("No Template provided.")
            return webob.exc.HTTPBadRequest(explanation=msg)

        tmpl = parser.Template(template)
        tmpl_resources = tmpl.get('Resources', [])

        if not tmpl_resources:
            return {'Error': 'At least one Resources member must be defined.'}

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

            ResourceClass = resource.get_class(res['Type'])
            if ResourceClass == resources.template_resource.TemplateResource:
                # we can't validate a TemplateResource unless we instantiate
                # it as we need to download the template and convert the
                # paramerters into properties_schema.
                continue

            props = properties.Properties(ResourceClass.properties_schema,
                                          res.get('Properties', {}))
            try:
                ResourceClass.validate_deletion_policy(res)
                props.validate(with_value=False)
            except Exception as ex:
                return {'Error': str(ex)}

        tmpl_params = parser.Parameters(None, tmpl, validate_value=False)
        format_validate_parameter = lambda p: dict(p.schema)
        is_real_param = lambda p: p.name not in parameters.PSEUDO_PARAMETERS
        params = tmpl_params.map(format_validate_parameter, is_real_param)

        result = {
            'Description': tmpl.get('Description', ''),
            'Parameters': params,
        }
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
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to see.
        """
        s = self._get_stack(cnxt, stack_identity, show_deleted=True)
        if s:
            return s.raw_template.template
        return None

    @request_context
    def delete_stack(self, cnxt, stack_identity):
        """
        The delete_stack method deletes a given stack.
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to delete.
        """
        st = self._get_stack(cnxt, stack_identity)

        logger.info('deleting stack %s' % st.name)

        stack = parser.Stack.load(cnxt, stack=st)

        # Kill any pending threads by calling ThreadGroup.stop()
        if st.id in self.stg:
            self.stg[st.id].stop()
            del self.stg[st.id]
        # use the service ThreadGroup for deletes
        self.tg.add_thread(stack.delete)
        return None

    def list_resource_types(self, cnxt):
        """
        Get a list of supported resource types.
        arg1 -> RPC context.
        """
        return list(resource.get_types())

    def resource_schema(self, cnxt, type_name):
        """
        Return the schema of the specified type.
        arg1 -> RPC context.
        arg2 -> Name of the resource type to obtain the schema of.
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
        arg1 -> RPC context.
        arg2 -> Name of the resource type to generate a template for.
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
        arg1 -> RPC context.
        arg2 -> Name of the stack you want to get events for.
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
        # We're expecting EC2 credentials because all in-instance credentials
        # are deployed as ec2 keypairs
        try:
            ec2_creds = json.loads(cnxt.aws_creds).get('ec2Credentials')
        except (TypeError, AttributeError):
            ec2_creds = None

        if ec2_creds:
            access_key = ec2_creds.get('access')
            # Then we look up the AccessKey resource and check the stack
            try:
                akey_rsrc = self.find_physical_resource(cnxt, access_key)
            except exception.PhysicalResourceNotFound:
                logger.warning("access_key % not found!" % access_key)
                return False

            akey_rsrc_id = identifier.ResourceIdentifier(**akey_rsrc)
            if stack.identifier() == akey_rsrc_id.stack():
                # The stack matches, so check if access is allowed to this
                # resource via the AccessKey resource access_allowed()
                ak_akey_rsrc = stack[akey_rsrc_id.resource_name]
                return ak_akey_rsrc.access_allowed(resource_name)
            else:
                logger.warning("Cannot access resource from wrong stack!")
        else:
            logger.warning("Cannot access resource, invalid credentials!")

        return False

    @request_context
    def describe_stack_resource(self, cnxt, stack_identity, resource_name):
        s = self._get_stack(cnxt, stack_identity)
        stack = parser.Stack.load(cnxt, stack=s)

        if cfg.CONF.heat_stack_user_role in cnxt.roles:
            if not self._authorize_stack_user(cnxt, stack, resource_name):
                logger.warning("Access denied to resource %s" % resource_name)
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
        stack_context = self._load_user_creds(s.user_creds_id)
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
        arg1 -> RPC context.
        arg2 -> The physical resource ID to look up.
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

        if resource_name is not None:
            name_match = lambda r: r.name == resource_name
        else:
            name_match = lambda r: True

        return [api.format_stack_resource(resource)
                for resource in stack if name_match(resource)]

    @request_context
    def list_stack_resources(self, cnxt, stack_identity):
        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)

        return [api.format_stack_resource(resource, detail=False)
                for resource in stack]

    @request_context
    def stack_suspend(self, cnxt, stack_identity):
        '''
        Handle request to perform suspend action on a stack
        '''
        def _stack_suspend(stack):
            logger.debug("suspending stack %s" % stack.name)
            stack.suspend()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self._start_in_thread(stack.id, _stack_suspend, stack)

    @request_context
    def stack_resume(self, cnxt, stack_identity):
        '''
        Handle request to perform a resume action on a stack
        '''
        def _stack_resume(stack):
            logger.debug("resuming stack %s" % stack.name)
            stack.resume()

        s = self._get_stack(cnxt, stack_identity)

        stack = parser.Stack.load(cnxt, stack=s)
        self._start_in_thread(stack.id, _stack_resume, stack)

    def _load_user_creds(self, creds_id):
        user_creds = db_api.user_creds_get(creds_id)
        stored_context = context.RequestContext.from_dict(user_creds)
        # heat_keystoneclient populates the context with an auth_token
        # either via the stored user/password or trust_id, depending
        # on how deferred_auth_method is configured in the conf file
        kc = hkc.KeystoneClient(stored_context)
        return stored_context

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
        stack_context = self._load_user_creds(s.user_creds_id)
        refresh_stack = parser.Stack.load(stack_context, stack=s)

        # Refresh the metadata for all other resources, since we expect
        # resource_name to be a WaitCondition resource, and other
        # resources may refer to WaitCondition Fn::GetAtt Data, which
        # is updated here.
        for res in refresh_stack:
            if res.name != resource_name and res.id is not None:
                res.metadata_update()

        return resource.metadata

    def _check_stack_watches(self, sid):
        # Retrieve the stored credentials & create context
        # Require admin=True to the stack_get to defeat tenant
        # scoping otherwise we fail to retrieve the stack
        logger.debug("Periodic watcher task for stack %s" % sid)
        admin_context = context.get_admin_context()
        stack = db_api.stack_get(admin_context, sid, admin=True)
        if not stack:
            logger.error("Unable to retrieve stack %s for periodic task" %
                         sid)
            return
        stack_context = self._load_user_creds(stack.user_creds_id)

        # recurse into any nested stacks.
        children = db_api.stack_get_all_by_owner_id(admin_context, sid)
        for child in children:
            self._check_stack_watches(child.id)

        # Get all watchrules for this stack and evaluate them
        try:
            wrs = db_api.watch_rule_get_all_by_stack(stack_context, sid)
        except Exception as ex:
            logger.warn('periodic_task db error (%s) %s' %
                        ('watch rule removed?', str(ex)))
            return

        def run_alarm_action(actions, details):
            for action in actions:
                action(details=details)

            stk = parser.Stack.load(stack_context, stack=stack)
            for res in stk:
                res.metadata_update()

        for wr in wrs:
            rule = watchrule.WatchRule.load(stack_context, watch=wr)
            actions = rule.evaluate()
            if actions:
                self._start_in_thread(sid, run_alarm_action, actions,
                                      rule.get_details())

    def _periodic_watcher_task(self, sid):
        """
        Periodic task, created for each stack, triggers watch-rule
        evaluation for all rules defined for the stack
        sid = stack ID
        """
        self._check_stack_watches(sid)

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
        '''
        The show_watch method returns the attributes of one watch/alarm
        arg1 -> RPC context.
        arg2 -> Name of the watch you want to see, or None to see all
        '''
        if watch_name:
            wrn = [watch_name]
        else:
            try:
                wrn = [w.name for w in db_api.watch_rule_get_all(cnxt)]
            except Exception as ex:
                logger.warn('show_watch (all) db error %s' % str(ex))
                return

        wrs = [watchrule.WatchRule.load(cnxt, w) for w in wrn]
        result = [api.format_watch(w) for w in wrs]
        return result

    @request_context
    def show_watch_metric(self, cnxt, metric_namespace=None, metric_name=None):
        '''
        The show_watch method returns the datapoints for a metric
        arg1 -> RPC context.
        arg2 -> Name of the namespace you want to see, or None to see all
        arg3 -> Name of the metric you want to see, or None to see all
        '''

        # DB API and schema does not yet allow us to easily query by
        # namespace/metric, but we will want this at some point
        # for now, the API can query all metric data and filter locally
        if metric_namespace is not None or metric_name is not None:
            logger.error("Filtering by namespace/metric not yet supported")
            return

        try:
            wds = db_api.watch_data_get_all(cnxt)
        except Exception as ex:
            logger.warn('show_metric (all) db error %s' % str(ex))
            return

        result = [api.format_watch_data(w) for w in wds]
        return result

    @request_context
    def set_watch_state(self, cnxt, watch_name, state):
        '''
        Temporarily set the state of a given watch
        arg1 -> RPC context.
        arg2 -> Name of the watch
        arg3 -> State (must be one defined in WatchRule class
        '''
        wr = watchrule.WatchRule.load(cnxt, watch_name)
        if wr.state == rpc_api.WATCH_STATE_CEILOMETER_CONTROLLED:
            return
        actions = wr.set_watch_state(state)
        for action in actions:
            self._start_in_thread(wr.stack_id, action)

        # Return the watch with the state overriden to indicate success
        # We do not update the timestamps as we are not modifying the DB
        result = api.format_watch(wr)
        result[rpc_api.WATCH_STATE_VALUE] = state
        return result
