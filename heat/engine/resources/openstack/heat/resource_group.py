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
import copy
import functools
import itertools
import six

from oslo_log import log as logging

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.common import timeutils
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import function
from heat.engine import output
from heat.engine import properties
from heat.engine.resources import stack_resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import support
from heat.scaling import rolling_update
from heat.scaling import template as scl_template

LOG = logging.getLogger(__name__)


class ResourceGroup(stack_resource.StackResource):
    """Creates one or more identically configured nested resources.

    In addition to the `refs` attribute, this resource implements synthetic
    attributes that mirror those of the resources in the group. When
    getting an attribute from this resource, however, a list of attribute
    values for each resource in the group is returned. To get attribute values
    for a single resource in the group, synthetic attributes of the form
    `resource.{resource index}.{attribute name}` can be used. The resource ID
    of a particular resource in the group can be obtained via the synthetic
    attribute `resource.{resource index}`. Note, that if you get attribute
    without `{resource index}`, e.g. `[resource, {attribute_name}]`, you'll get
    a list of this attribute's value for all resources in group.

    While each resource in the group will be identically configured, this
    resource does allow for some index-based customization of the properties
    of the resources in the group. For example::

      resources:
        my_indexed_group:
          type: OS::Heat::ResourceGroup
          properties:
            count: 3
            resource_def:
              type: OS::Nova::Server
              properties:
                # create a unique name for each server
                # using its index in the group
                name: my_server_%index%
                image: CentOS 6.5
                flavor: 4GB Performance

    would result in a group of three servers having the same image and flavor,
    but names of `my_server_0`, `my_server_1`, and `my_server_2`. The variable
    used for substitution can be customized by using the `index_var` property.
    """

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        COUNT, INDEX_VAR, RESOURCE_DEF, REMOVAL_POLICIES,
        REMOVAL_POLICIES_MODE,
    ) = (
        'count', 'index_var', 'resource_def', 'removal_policies',
        'removal_policies_mode'
    )

    _RESOURCE_DEF_KEYS = (
        RESOURCE_DEF_TYPE, RESOURCE_DEF_PROPERTIES, RESOURCE_DEF_METADATA,
    ) = (
        'type', 'properties', 'metadata',
    )

    _REMOVAL_POLICIES_KEYS = (
        REMOVAL_RSRC_LIST,
    ) = (
        'resource_list',
    )

    _REMOVAL_POLICY_MODES = (
        REMOVAL_POLICY_APPEND, REMOVAL_POLICY_UPDATE
    ) = (
        'append', 'update'
    )

    _ROLLING_UPDATES_SCHEMA_KEYS = (
        MIN_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME,
    ) = (
        'min_in_service', 'max_batch_size', 'pause_time',
    )

    _BATCH_CREATE_SCHEMA_KEYS = (
        MAX_BATCH_SIZE, PAUSE_TIME,
    ) = (
        'max_batch_size', 'pause_time',
    )

    _UPDATE_POLICY_SCHEMA_KEYS = (
        ROLLING_UPDATE, BATCH_CREATE,
    ) = (
        'rolling_update', 'batch_create',
    )

    ATTRIBUTES = (
        REFS, REFS_MAP, ATTR_ATTRIBUTES, REMOVED_RSRC_LIST
    ) = (
        'refs', 'refs_map', 'attributes', 'removed_rsrc_list'
    )

    properties_schema = {
        COUNT: properties.Schema(
            properties.Schema.INTEGER,
            _('The number of resources to create.'),
            default=1,
            constraints=[
                constraints.Range(min=0),
            ],
            update_allowed=True
        ),
        INDEX_VAR: properties.Schema(
            properties.Schema.STRING,
            _('A variable that this resource will use to replace with the '
              'current index of a given resource in the group. Can be used, '
              'for example, to customize the name property of grouped '
              'servers in order to differentiate them when listed with '
              'nova client.'),
            default="%index%",
            constraints=[
                constraints.Length(min=3)
            ],
            support_status=support.SupportStatus(version='2014.2')
        ),
        RESOURCE_DEF: properties.Schema(
            properties.Schema.MAP,
            _('Resource definition for the resources in the group. The value '
              'of this property is the definition of a resource just as if '
              'it had been declared in the template itself.'),
            schema={
                RESOURCE_DEF_TYPE: properties.Schema(
                    properties.Schema.STRING,
                    _('The type of the resources in the group.'),
                    required=True
                ),
                RESOURCE_DEF_PROPERTIES: properties.Schema(
                    properties.Schema.MAP,
                    _('Property values for the resources in the group.')
                ),
                RESOURCE_DEF_METADATA: properties.Schema(
                    properties.Schema.MAP,
                    _('Supplied metadata for the resources in the group.'),
                    support_status=support.SupportStatus(version='5.0.0')
                ),

            },
            required=True,
            update_allowed=True
        ),
        REMOVAL_POLICIES: properties.Schema(
            properties.Schema.LIST,
            _('Policies for removal of resources on update.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                _('Policy to be processed when doing an update which '
                  'requires removal of specific resources.'),
                schema={
                    REMOVAL_RSRC_LIST: properties.Schema(
                        properties.Schema.LIST,
                        _("List of resources to be removed "
                          "when doing an update which requires removal of "
                          "specific resources. "
                          "The resource may be specified several ways: "
                          "(1) The resource name, as in the nested stack, "
                          "(2) The resource reference returned from "
                          "get_resource in a template, as available via "
                          "the 'refs' attribute. "
                          "Note this is destructive on update when specified; "
                          "even if the count is not being reduced, and once "
                          "a resource name is removed, its name is never "
                          "reused in subsequent updates."
                          ),
                        default=[]
                    ),
                },
            ),
            update_allowed=True,
            default=[],
            support_status=support.SupportStatus(version='2015.1')
        ),
        REMOVAL_POLICIES_MODE: properties.Schema(
            properties.Schema.STRING,
            _('How to handle changes to removal_policies on update. '
              'The default "append" mode appends to the internal list, '
              '"update" replaces it on update.'),
            default=REMOVAL_POLICY_APPEND,
            constraints=[
                constraints.AllowedValues(_REMOVAL_POLICY_MODES)
            ],
            update_allowed=True,
            support_status=support.SupportStatus(version='10.0.0')
        ),
    }

    attributes_schema = {
        REFS: attributes.Schema(
            _("A list of resource IDs for the resources in the group."),
            type=attributes.Schema.LIST
        ),
        REFS_MAP: attributes.Schema(
            _("A map of resource names to IDs for the resources in "
              "the group."),
            type=attributes.Schema.MAP,
            support_status=support.SupportStatus(version='7.0.0'),
        ),
        ATTR_ATTRIBUTES: attributes.Schema(
            _("A map of resource names to the specified attribute of each "
              "individual resource. "
              "Requires heat_template_version: 2014-10-16."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.MAP
        ),
        REMOVED_RSRC_LIST: attributes.Schema(
            _("A list of removed resource names."),
            support_status=support.SupportStatus(version='7.0.0'),
            type=attributes.Schema.LIST
        ),
    }

    rolling_update_schema = {
        MIN_IN_SERVICE: properties.Schema(
            properties.Schema.INTEGER,
            _('The minimum number of resources in service while '
              'rolling updates are being executed.'),
            constraints=[constraints.Range(min=0)],
            default=0),
        MAX_BATCH_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum number of resources to replace at once.'),
            constraints=[constraints.Range(min=1)],
            default=1),
        PAUSE_TIME: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of seconds to wait between batches of '
              'updates.'),
            constraints=[constraints.Range(min=0)],
            default=0),
    }

    batch_create_schema = {
        MAX_BATCH_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('The maximum number of resources to create at once.'),
            constraints=[constraints.Range(min=1)],
            default=1
        ),
        PAUSE_TIME: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of seconds to wait between batches.'),
            constraints=[constraints.Range(min=0)],
            default=0
        ),
    }

    update_policy_schema = {
        ROLLING_UPDATE: properties.Schema(
            properties.Schema.MAP,
            schema=rolling_update_schema,
            support_status=support.SupportStatus(version='5.0.0')
        ),
        BATCH_CREATE: properties.Schema(
            properties.Schema.MAP,
            schema=batch_create_schema,
            support_status=support.SupportStatus(version='5.0.0')
        )
    }

    def get_size(self):
        return self.properties.get(self.COUNT)

    def validate_nested_stack(self):
        # Only validate the resource definition (which may be a
        # nested template) if count is non-zero, to enable folks
        # to disable features via a zero count if they wish
        if not self.get_size():
            return

        first_name = next(self._resource_names())
        test_tmpl = self._assemble_nested([first_name],
                                          include_all=True)
        res_def = next(six.itervalues(test_tmpl.resource_definitions(None)))
        # make sure we can resolve the nested resource type
        self.stack.env.get_class_to_instantiate(res_def.resource_type)

        try:
            name = "%s-%s" % (self.stack.name, self.name)
            nested_stack = self._parse_nested_stack(
                name,
                test_tmpl,
                self.child_params())
            nested_stack.strict_validate = False
            nested_stack.validate()
        except Exception as ex:
            path = "%s<%s>" % (self.name, self.template_url)
            raise exception.StackValidationFailed(
                ex, path=[self.stack.t.RESOURCES, path])

    def _current_blacklist(self):
        db_rsrc_names = self.data().get('name_blacklist')
        if db_rsrc_names:
            return db_rsrc_names.split(',')
        else:
            return []

    def _get_new_blacklist_entries(self, properties, current_blacklist):
        insp = grouputils.GroupInspector.from_parent_resource(self)

        # Now we iterate over the removal policies, and update the blacklist
        # with any additional names
        for r in properties.get(self.REMOVAL_POLICIES, []):
            if self.REMOVAL_RSRC_LIST in r:
                # Tolerate string or int list values
                for n in r[self.REMOVAL_RSRC_LIST]:
                    str_n = six.text_type(n)
                    if (str_n in current_blacklist or
                            self.resource_id is None or
                            str_n in insp.member_names(include_failed=True)):
                        yield str_n
                    elif isinstance(n, six.string_types):
                        try:
                            refids = self.get_output(self.REFS_MAP)
                        except (exception.NotFound,
                                exception.TemplateOutputError) as op_err:
                            LOG.debug('Falling back to resource_by_refid() '
                                      ' due to %s', op_err)
                            rsrc = self.nested().resource_by_refid(n)
                            if rsrc is not None:
                                yield rsrc.name
                        else:
                            if refids is not None:
                                for name, refid in refids.items():
                                    if refid == n:
                                        yield name
                                        break

        # Clear output cache from prior to stack update, so we don't get
        # outdated values after stack update.
        self._outputs = None

    def _update_name_blacklist(self, properties):
        """Resolve the remove_policies to names for removal."""
        # To avoid reusing names after removal, we store a comma-separated
        # blacklist in the resource data - in cases where you want to
        # overwrite the stored data, removal_policies_mode: update can be used
        curr_bl = set(self._current_blacklist())
        p_mode = properties.get(self.REMOVAL_POLICIES_MODE,
                                self.REMOVAL_POLICY_APPEND)
        if p_mode == self.REMOVAL_POLICY_UPDATE:
            init_bl = set()
        else:
            init_bl = curr_bl
        updated_bl = init_bl | set(self._get_new_blacklist_entries(properties,
                                                                   curr_bl))

        # If the blacklist has changed, update the resource data
        if updated_bl != curr_bl:
            self.data_set('name_blacklist', ','.join(sorted(updated_bl)))

    def _name_blacklist(self):
        """Get the list of resource names to blacklist."""
        bl = set(self._current_blacklist())
        if self.resource_id is None:
            bl |= set(self._get_new_blacklist_entries(self.properties, bl))
        return bl

    def _resource_names(self, size=None):
        name_blacklist = self._name_blacklist()
        if size is None:
            size = self.get_size()

        def is_blacklisted(name):
            return name in name_blacklist

        candidates = six.moves.map(six.text_type, itertools.count())

        return itertools.islice(six.moves.filterfalse(is_blacklisted,
                                                      candidates),
                                size)

    def _count_black_listed(self, existing_members):
        """Return the number of current resource names that are blacklisted."""
        return len(self._name_blacklist() & set(existing_members))

    def handle_create(self):
        self._update_name_blacklist(self.properties)
        if self.update_policy.get(self.BATCH_CREATE) and self.get_size():
            batch_create = self.update_policy[self.BATCH_CREATE]
            max_batch_size = batch_create[self.MAX_BATCH_SIZE]
            pause_sec = batch_create[self.PAUSE_TIME]
            checkers = self._replace(0, max_batch_size, pause_sec)
            if checkers:
                checkers[0].start()
            return checkers
        else:
            names = self._resource_names()
            self.create_with_template(self._assemble_nested(names),
                                      self.child_params())

    def check_create_complete(self, checkers=None):
        if checkers is None:
            return super(ResourceGroup, self).check_create_complete()
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True

    def _run_to_completion(self, template, timeout):
        updater = self.update_with_template(template, {},
                                            timeout)

        while not super(ResourceGroup,
                        self).check_update_complete(updater):
            yield

    def _run_update(self, total_capacity, max_updates, timeout):
        template = self._assemble_for_rolling_update(total_capacity,
                                                     max_updates)
        return self._run_to_completion(template, timeout)

    def check_update_complete(self, checkers):
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True

    def res_def_changed(self, prop_diff):
        return self.RESOURCE_DEF in prop_diff

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if tmpl_diff:
            # parse update policy
            if tmpl_diff.update_policy_changed():
                up = json_snippet.update_policy(self.update_policy_schema,
                                                self.context)
                self.update_policy = up

        checkers = []
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        self._update_name_blacklist(self.properties)
        if prop_diff and self.res_def_changed(prop_diff):
            updaters = self._try_rolling_update()
            if updaters:
                checkers.extend(updaters)

        if not checkers:
            resizer = scheduler.TaskRunner(
                self._run_to_completion,
                self._assemble_nested(self._resource_names()),
                self.stack.timeout_mins)
            checkers.append(resizer)

        checkers[0].start()
        return checkers

    def _attribute_output_name(self, *attr_path):
        if attr_path[0] == self.REFS:
            return self.REFS
        return ', '.join(six.text_type(a) for a in attr_path)

    def get_attribute(self, key, *path):
        if key == self.REMOVED_RSRC_LIST:
            return self._current_blacklist()
        if key == self.ATTR_ATTRIBUTES and not path:
            raise exception.InvalidTemplateAttribute(resource=self.name,
                                                     key=key)

        is_resource_ref = (key.startswith("resource.") and
                           not path and (len(key.split('.', 2)) == 2))
        if is_resource_ref:
            output_name = self.REFS_MAP
        else:
            output_name = self._attribute_output_name(key, *path)

        if self.resource_id is not None:
            try:
                output = self.get_output(output_name)
            except (exception.NotFound,
                    exception.TemplateOutputError) as op_err:
                LOG.debug('Falling back to grouputils due to %s', op_err)
            else:
                if is_resource_ref:
                    try:
                        target = key.split('.', 2)[1]
                        return output[target]
                    except KeyError:
                        raise exception.NotFound(_("Member '%(mem)s' not "
                                                   "found in group resource "
                                                   "'%(grp)s'.") %
                                                 {'mem': target,
                                                  'grp': self.name})
                if key == self.REFS:
                    return attributes.select_from_attribute(output, path)
                return output

        if key.startswith("resource."):
            return grouputils.get_nested_attrs(self, key, False, *path)

        names = self._resource_names()
        if key == self.REFS:
            vals = [grouputils.get_rsrc_id(self, key, False, n) for n in names]
            return attributes.select_from_attribute(vals, path)
        if key == self.REFS_MAP:
            refs_map = {n: grouputils.get_rsrc_id(self, key, False, n)
                        for n in names}
            return refs_map
        if key == self.ATTR_ATTRIBUTES:
            return dict((n, grouputils.get_rsrc_attr(
                self, key, False, n, *path)) for n in names)

        path = [key] + list(path)
        return [grouputils.get_rsrc_attr(self, key, False, n, *path)
                for n in names]

    def _nested_output_defns(self, resource_names, get_attr_fn, get_res_fn):
        for attr in self.referenced_attrs():
            if isinstance(attr, six.string_types):
                key, path = attr, []
            else:
                key, path = attr[0], list(attr[1:])
            output_name = self._attribute_output_name(key, *path)
            value = None

            if key.startswith("resource."):
                keycomponents = key.split('.', 2)
                res_name = keycomponents[1]
                attr_path = keycomponents[2:] + path
                if attr_path:
                    if res_name in resource_names:
                        value = get_attr_fn([res_name] + attr_path)
                else:
                    output_name = key = self.REFS_MAP
            elif key == self.ATTR_ATTRIBUTES and path:
                value = {r: get_attr_fn([r] + path) for r in resource_names}
            elif key not in self.ATTRIBUTES:
                value = [get_attr_fn([r, key] + path) for r in resource_names]

            if key == self.REFS:
                value = [get_res_fn(r) for r in resource_names]

            if value is not None:
                yield output.OutputDefinition(output_name, value)

        value = {r: get_res_fn(r) for r in resource_names}
        yield output.OutputDefinition(self.REFS_MAP, value)

    def build_resource_definition(self, res_name, res_defn):
        res_def = copy.deepcopy(res_defn)

        props = res_def.get(self.RESOURCE_DEF_PROPERTIES)
        if props:
            props = self._handle_repl_val(res_name, props)

        res_type = res_def[self.RESOURCE_DEF_TYPE]
        meta = res_def[self.RESOURCE_DEF_METADATA]

        return rsrc_defn.ResourceDefinition(res_name, res_type, props, meta)

    def get_resource_def(self, include_all=False):
        """Returns the resource definition portion of the group.

        :param include_all: if False, only properties for the resource
               definition that are not empty will be included
        :type include_all: bool
        :return: resource definition for the group
        :rtype: dict
        """

        # At this stage, we don't mind if all of the parameters have values
        # assigned. Pass in a custom resolver to the properties to not
        # error when a parameter does not have a user entered value.
        def ignore_param_resolve(snippet):
            if isinstance(snippet, function.Function):
                try:
                    return snippet.result()
                except exception.UserParameterMissing:
                    return None

            if isinstance(snippet, collections.Mapping):
                return dict((k, ignore_param_resolve(v))
                            for k, v in snippet.items())
            elif (not isinstance(snippet, six.string_types) and
                  isinstance(snippet, collections.Iterable)):
                return [ignore_param_resolve(v) for v in snippet]

            return snippet

        self.properties.resolve = ignore_param_resolve

        res_def = self.properties[self.RESOURCE_DEF]
        if not include_all:
            return self._clean_props(res_def)
        return res_def

    def _clean_props(self, res_defn):
        res_def = copy.deepcopy(res_defn)
        props = res_def.get(self.RESOURCE_DEF_PROPERTIES)
        if props:
            clean = dict((k, v) for k, v in props.items() if v is not None)
            props = clean
            res_def[self.RESOURCE_DEF_PROPERTIES] = props
        return res_def

    def _handle_repl_val(self, res_name, val):
        repl_var = self.properties[self.INDEX_VAR]

        def recurse(x):
            return self._handle_repl_val(res_name, x)

        if isinstance(val, six.string_types):
            return val.replace(repl_var, res_name)
        elif isinstance(val, collections.Mapping):
            return {k: recurse(v) for k, v in val.items()}
        elif isinstance(val, collections.Sequence):
            return [recurse(v) for v in val]
        return val

    def _add_output_defns_to_template(self, tmpl, resource_names):
        att_func = 'get_attr'
        get_attr = functools.partial(tmpl.functions[att_func], None, att_func)
        res_func = 'get_resource'
        get_res = functools.partial(tmpl.functions[res_func], None, res_func)
        for odefn in self._nested_output_defns(resource_names,
                                               get_attr, get_res):
            tmpl.add_output(odefn)

    def _assemble_nested(self, names, include_all=False,
                         template_version=('heat_template_version',
                                           '2015-04-30')):

        def_dict = self.get_resource_def(include_all)
        definitions = [(k, self.build_resource_definition(k, def_dict))
                       for k in names]
        tmpl = scl_template.make_template(definitions,
                                          version=template_version)
        self._add_output_defns_to_template(tmpl, [k for k, d in definitions])
        return tmpl

    def child_template_files(self, child_env):
        is_rolling_update = (self.action == self.UPDATE
                             and self.update_policy[self.ROLLING_UPDATE])
        return grouputils.get_child_template_files(self.context,
                                                   self.stack,
                                                   is_rolling_update,
                                                   self.old_template_id)

    def _assemble_for_rolling_update(self, total_capacity, max_updates,
                                     include_all=False,
                                     template_version=('heat_template_version',
                                                       '2015-04-30')):
        names = list(self._resource_names(total_capacity))
        name_blacklist = self._name_blacklist()

        valid_resources = [(n, d) for n, d in
                           grouputils.get_member_definitions(self)
                           if n not in name_blacklist]

        targ_cap = self.get_size()

        def replace_priority(res_item):
            name, defn = res_item
            try:
                index = names.index(name)
            except ValueError:
                # High priority - delete immediately
                return 0
            else:
                if index < targ_cap:
                    # Update higher indices first
                    return targ_cap - index
                else:
                    # Low priority - don't update
                    return total_capacity

        old_resources = sorted(valid_resources, key=replace_priority)
        existing_names = set(n for n, d in valid_resources)
        new_names = six.moves.filterfalse(lambda n: n in existing_names,
                                          names)
        res_def = self.get_resource_def(include_all)
        definitions = scl_template.member_definitions(
            old_resources, res_def,
            total_capacity,
            max_updates,
            lambda: next(new_names),
            self.build_resource_definition)
        tmpl = scl_template.make_template(definitions,
                                          version=template_version)
        self._add_output_defns_to_template(tmpl, names)
        return tmpl

    def _try_rolling_update(self):
        if self.update_policy[self.ROLLING_UPDATE]:
            policy = self.update_policy[self.ROLLING_UPDATE]
            return self._replace(policy[self.MIN_IN_SERVICE],
                                 policy[self.MAX_BATCH_SIZE],
                                 policy[self.PAUSE_TIME])

    def _resolve_attribute(self, name):
        if name == self.REMOVED_RSRC_LIST:
            return self._current_blacklist()

    def _update_timeout(self, batch_cnt, pause_sec):
        total_pause_time = pause_sec * max(batch_cnt - 1, 0)
        if total_pause_time >= self.stack.timeout_secs():
            msg = _('The current update policy will result in stack update '
                    'timeout.')
            raise ValueError(msg)
        return self.stack.timeout_secs() - total_pause_time

    @staticmethod
    def _get_batches(targ_cap, curr_cap, batch_size, min_in_service):
        updated = 0

        while rolling_update.needs_update(targ_cap, curr_cap, updated):
            new_cap, total_new = rolling_update.next_batch(targ_cap,
                                                           curr_cap,
                                                           updated,
                                                           batch_size,
                                                           min_in_service)

            yield new_cap, total_new

            updated += total_new - max(new_cap - max(curr_cap, targ_cap), 0)
            curr_cap = new_cap

    def _replace(self, min_in_service, batch_size, pause_sec):

        def pause_between_batch(pause_sec):
            duration = timeutils.Duration(pause_sec)
            while not duration.expired():
                yield

        # current capacity not including existing blacklisted
        inspector = grouputils.GroupInspector.from_parent_resource(self)
        num_blacklist = self._count_black_listed(
            inspector.member_names(include_failed=False))
        num_resources = inspector.size(include_failed=True)
        curr_cap = num_resources - num_blacklist

        batches = list(self._get_batches(self.get_size(), curr_cap, batch_size,
                                         min_in_service))
        update_timeout = self._update_timeout(len(batches), pause_sec)

        def tasks():
            for index, (curr_cap, max_upd) in enumerate(batches):
                yield scheduler.TaskRunner(self._run_update,
                                           curr_cap, max_upd,
                                           update_timeout)

                if index < (len(batches) - 1) and pause_sec > 0:
                    yield scheduler.TaskRunner(pause_between_batch, pause_sec)

        return list(tasks())

    def preview(self):
        # NOTE(pas-ha) just need to use include_all in _assemble_nested,
        # so this method is a simplified copy of preview() from StackResource,
        # and next two lines are basically a modified copy of child_template()
        names = self._resource_names()
        child_template = self._assemble_nested(names, include_all=True)
        params = self.child_params()
        name = "%s-%s" % (self.stack.name, self.name)
        self._nested = self._parse_nested_stack(name, child_template, params)

        return self.nested().preview_resources()

    def child_template(self):
        names = self._resource_names()
        return self._assemble_nested(names)

    def child_params(self):
        return {}

    def handle_adopt(self, resource_data):
        names = self._resource_names()
        if names:
            return self.create_with_template(self._assemble_nested(names),
                                             {},
                                             adopt_data=resource_data)

    def get_nested_parameters_stack(self):
        """Return a nested group of size 1 for validation."""
        names = self._resource_names(1)
        child_template = self._assemble_nested(names)
        params = self.child_params()
        name = "%s-%s" % (self.stack.name, self.name)
        return self._parse_nested_stack(name, child_template, params)


def resource_mapping():
    return {
        'OS::Heat::ResourceGroup': ResourceGroup,
    }
