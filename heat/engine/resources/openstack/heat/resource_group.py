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
import itertools

import six
from six.moves import range

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.common import timeutils
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine.resources import stack_resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine import support
from heat.engine import template

template_template = {
    "heat_template_version": "2013-05-23",
    "resources": {}
}


class ResourceGroup(stack_resource.StackResource):
    """
    A resource that creates one or more identically configured nested
    resources.

    In addition to the `refs` attribute, this resource implements synthetic
    attributes that mirror those of the resources in the group.  When
    getting an attribute from this resource, however, a list of attribute
    values for each resource in the group is returned. To get attribute values
    for a single resource in the group, synthetic attributes of the form
    `resource.{resource index}.{attribute name}` can be used. The resource ID
    of a particular resource in the group can be obtained via the synthetic
    attribute `resource.{resource index}`.

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
        COUNT, INDEX_VAR, RESOURCE_DEF, REMOVAL_POLICIES
    ) = (
        'count', 'index_var', 'resource_def', 'removal_policies'
    )

    _RESOURCE_DEF_KEYS = (
        RESOURCE_DEF_TYPE, RESOURCE_DEF_PROPERTIES,
    ) = (
        'type', 'properties',
    )

    _REMOVAL_POLICIES_KEYS = (
        REMOVAL_RSRC_LIST,
    ) = (
        'resource_list',
    )

    _ROLLING_UPDATES_SCHEMA_KEYS = (
        MIN_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME,
    ) = (
        'min_in_service', 'max_batch_size', 'pause_time',
    )

    _UPDATE_POLICY_SCHEMA_KEYS = (ROLLING_UPDATE,) = ('rolling_update',)

    ATTRIBUTES = (
        REFS, ATTR_ATTRIBUTES,
    ) = (
        'refs', 'attributes',
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
                    _('The type of the resources in the group'),
                    required=True
                ),
                RESOURCE_DEF_PROPERTIES: properties.Schema(
                    properties.Schema.MAP,
                    _('Property values for the resources in the group')
                ),
            },
            required=True,
            update_allowed=True
        ),
        REMOVAL_POLICIES: properties.Schema(
            properties.Schema.LIST,
            _('Policies for removal of resources on update'),
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
                          "the 'refs' attribute "
                          "Note this is destructive on update when specified; "
                          "even if the count is not being reduced, and once "
                          "a resource name is removed, it's name is never "
                          "reused in subsequent updates"
                          ),
                        default=[]
                    ),
                },
            ),
            update_allowed=True,
            default=[],
            support_status=support.SupportStatus(version='2015.1')
        ),
    }

    attributes_schema = {
        REFS: attributes.Schema(
            _("A list of resource IDs for the resources in the group"),
            type=attributes.Schema.LIST
        ),
        ATTR_ATTRIBUTES: attributes.Schema(
            _("A map of resource names to the specified attribute of each "
              "individual resource.  "
              "Requires heat_template_version: 2014-10-16."),
            support_status=support.SupportStatus(version='2014.2'),
            type=attributes.Schema.MAP
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
            constraints=[constraints.Range(min=0)],
            default=1),
        PAUSE_TIME: properties.Schema(
            properties.Schema.NUMBER,
            _('The number of seconds to wait between batches of '
              'updates.'),
            constraints=[constraints.Range(min=0)],
            default=0),
    }

    update_policy_schema = {
        ROLLING_UPDATE: properties.Schema(properties.Schema.MAP,
                                          schema=rolling_update_schema)
    }

    def __init__(self, name, json_snippet, stack):
        super(ResourceGroup, self).__init__(name, json_snippet, stack)
        self.update_policy = self.t.update_policy(self.update_policy_schema,
                                                  self.context)

    def get_size(self):
        return self.properties.get(self.COUNT)

    def validate(self):
        """
        Validation for update_policy
        """
        super(ResourceGroup, self).validate()

        if self.update_policy is not None:
            self.update_policy.validate()
            policy_name = self.ROLLING_UPDATE
            if (policy_name in self.update_policy and
                    self.update_policy[policy_name] is not None):
                pause_time = self.update_policy[policy_name][self.PAUSE_TIME]
                if pause_time > 3600:
                    msg = _('Maximum %(arg1)s allowed is 1hr(3600s),'
                            ' provided %(arg2)s seconds.') % dict(
                        arg1=self.PAUSE_TIME,
                        arg2=pause_time)
                    raise ValueError(msg)

    def validate_nested_stack(self):
        # Only validate the resource definition (which may be a
        # nested template) if count is non-zero, to enable folks
        # to disable features via a zero count if they wish
        if not self.get_size():
            return

        test_tmpl = self._assemble_nested(["0"], include_all=True)
        val_templ = template.Template(test_tmpl)
        res_def = val_templ.resource_definitions(self.stack)["0"]
        # make sure we can resolve the nested resource type
        try:
            self.stack.env.get_class(res_def.resource_type)
        except exception.TemplateNotFound:
            # its a template resource
            pass

        try:
            name = "%s-%s" % (self.stack.name, self.name)
            nested_stack = self._parse_nested_stack(
                name,
                test_tmpl,
                self.child_params())
            nested_stack.strict_validate = False
            nested_stack.validate()
        except Exception as ex:
            msg = _("Failed to validate: %s") % six.text_type(ex)
            raise exception.StackValidationFailed(message=msg)

    def _name_blacklist(self):
        """Resolve the remove_policies to names for removal."""

        nested = self.nested()

        # To avoid reusing names after removal, we store a comma-separated
        # blacklist in the resource data
        db_rsrc_names = self.data().get('name_blacklist')
        if db_rsrc_names:
            current_blacklist = db_rsrc_names.split(',')
        else:
            current_blacklist = []

        # Now we iterate over the removal policies, and update the blacklist
        # with any additional names
        rsrc_names = set(current_blacklist)
        for r in self.properties[self.REMOVAL_POLICIES]:
            if self.REMOVAL_RSRC_LIST in r:
                # Tolerate string or int list values
                for n in r[self.REMOVAL_RSRC_LIST]:
                    str_n = six.text_type(n)
                    if str_n in nested:
                        rsrc_names.add(str_n)
                        continue
                    rsrc = nested.resource_by_refid(str_n)
                    if rsrc:
                        rsrc_names.add(rsrc.name)

        # If the blacklist has changed, update the resource data
        if rsrc_names != set(current_blacklist):
            self.data_set('name_blacklist', ','.join(rsrc_names))
        return rsrc_names

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

    def _get_resources(self):
        """Get templates for resources."""
        return [(resource.name, resource.t.render_hot())
                for resource in grouputils.get_members(self)]

    def _count_black_listed(self):
        """Get black list count"""
        return len(self._name_blacklist()
                   & set(grouputils.get_member_names(self)))

    def handle_create(self):
        names = self._resource_names()
        self.create_with_template(self._assemble_nested(names),
                                  {},
                                  self.stack.timeout_mins)

    def _run_to_completion(self, template, timeout):
        updater = self.update_with_template(template, {},
                                            timeout)

        while not super(ResourceGroup,
                        self).check_update_complete(updater):
            yield

    def check_update_complete(self, checkers):
        for checker in checkers:
            if not checker.started():
                checker.start()
            if not checker.step():
                return False
        return True

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if tmpl_diff:
            # parse update policy
            if rsrc_defn.UPDATE_POLICY in tmpl_diff:
                up = json_snippet.update_policy(self.update_policy_schema,
                                                self.context)
                self.update_policy = up

        checkers = []
        self.properties = json_snippet.properties(self.properties_schema,
                                                  self.context)
        if prop_diff and self.RESOURCE_DEF in prop_diff:
            updaters = self._try_rolling_update()
            if updaters:
                checkers.extend(updaters)
        resizer = scheduler.TaskRunner(
            self._run_to_completion,
            self._assemble_nested_for_size(self.get_size()),
            self.stack.timeout_mins)

        checkers.append(resizer)
        checkers[0].start()
        return checkers

    def _assemble_nested_for_size(self, new_capacity):
        new_names = self._resource_names(new_capacity)
        return self._assemble_nested(new_names)

    def FnGetAtt(self, key, *path):
        if key.startswith("resource."):
            return grouputils.get_nested_attrs(self, key, False, *path)

        names = self._resource_names()
        if key == self.REFS:
            vals = [grouputils.get_rsrc_id(self, key, False, n) for n in names]
            return attributes.select_from_attribute(vals, path)
        if key == self.ATTR_ATTRIBUTES:
            if not path:
                raise exception.InvalidTemplateAttribute(
                    resource=self.name, key=key)
            return dict((n, grouputils.get_rsrc_attr(
                self, key, False, n, *path)) for n in names)

        path = [key] + list(path)
        return [grouputils.get_rsrc_attr(self, key, False, n, *path)
                for n in names]

    def _build_resource_definition(self, include_all=False):
        res_def = self.properties[self.RESOURCE_DEF]
        if res_def[self.RESOURCE_DEF_PROPERTIES] is None:
            res_def[self.RESOURCE_DEF_PROPERTIES] = {}
        if not include_all:
            resource_def_props = res_def[self.RESOURCE_DEF_PROPERTIES]
            clean = dict((k, v) for k, v in resource_def_props.items()
                         if v is not None)
            res_def[self.RESOURCE_DEF_PROPERTIES] = clean
        return res_def

    def _handle_repl_val(self, res_name, val):
        repl_var = self.properties[self.INDEX_VAR]
        recurse = lambda x: self._handle_repl_val(res_name, x)
        if isinstance(val, six.string_types):
            return val.replace(repl_var, res_name)
        elif isinstance(val, collections.Mapping):
            return dict(zip(val, map(recurse, six.itervalues(val))))
        elif isinstance(val, collections.Sequence):
            return map(recurse, val)
        return val

    def _do_prop_replace(self, res_name, res_def_template):
        res_def = copy.deepcopy(res_def_template)
        props = res_def[self.RESOURCE_DEF_PROPERTIES]
        if props:
            props = self._handle_repl_val(res_name, props)
            res_def[self.RESOURCE_DEF_PROPERTIES] = props
        return res_def

    def _assemble_nested(self, names, include_all=False):
        res_def = self._build_resource_definition(include_all)
        resources = dict((k, self._do_prop_replace(k, res_def))
                         for k in names)
        child_template = copy.deepcopy(template_template)
        child_template['resources'] = resources
        return child_template

    def _assemble_for_rolling_update(self, names, name_blacklist,
                                     include_all=False):
        old_resources = self._get_resources()
        res_def = self._build_resource_definition(include_all)
        child_template = copy.deepcopy(template_template)
        resources = dict((k, v)
                         for k, v in old_resources if k not in name_blacklist)
        resources.update(dict((k, self._do_prop_replace(k, res_def))
                         for k in names))
        child_template['resources'] = resources
        return child_template

    def _try_rolling_update(self):
        if self.update_policy[self.ROLLING_UPDATE]:
            policy = self.update_policy[self.ROLLING_UPDATE]
            return self._replace(policy[self.MIN_IN_SERVICE],
                                 policy[self.MAX_BATCH_SIZE],
                                 policy[self.PAUSE_TIME])

    def _update_timeout(self, efft_capacity, efft_bat_sz, pause_sec):
        batch_cnt = (efft_capacity + efft_bat_sz - 1) // efft_bat_sz
        if pause_sec * (batch_cnt - 1) >= self.stack.timeout_secs():
            msg = _('The current %s will result in stack update '
                    'timeout.') % rsrc_defn.UPDATE_POLICY
            raise ValueError(msg)
        update_timeout = self.stack.timeout_secs() - (
            pause_sec * (batch_cnt - 1))
        return update_timeout

    def _replace(self, min_in_service, batch_size, pause_sec):

        def pause_between_batch(pause_sec):
            duration = timeutils.Duration(pause_sec)
            while not duration.expired():
                yield

        def get_batched_names(names, batch_size):
            for i in range(0, len(names), batch_size):
                yield names[0:i + batch_size]

        # blacklisted names exiting and new
        name_blacklist = self._name_blacklist()

        # blacklist count existing
        num_blacklist = self._count_black_listed()

        # current capacity not including existing blacklisted
        curr_cap = len(self.nested()) - num_blacklist if self.nested() else 0

        # final capacity expected after replace
        capacity = min(curr_cap, self.get_size())

        efft_bat_sz = min(batch_size, capacity)
        efft_min_sz = min(min_in_service, capacity)

        # effective capacity taking into account min_in_service and batch_size
        efft_capacity = max(capacity - efft_bat_sz, efft_min_sz) + efft_bat_sz

        # Reset effective capacity, if there are enough resources
        if efft_capacity <= curr_cap:
            efft_capacity = capacity

        if efft_capacity > 0:
            update_timeout = self._update_timeout(efft_capacity,
                                                  efft_bat_sz, pause_sec)
        checkers = []
        remainder = efft_capacity
        # filtered names for effective capacity
        new_names = self._resource_names(efft_capacity)
        # batched names in reverse order, we've to add new
        # resources if required before modifing existing
        batched_names = get_batched_names(list(new_names)[::-1], efft_bat_sz)
        while remainder > 0:
            checkers.append(scheduler.TaskRunner(
                self._run_to_completion,
                self._assemble_for_rolling_update(next(batched_names),
                                                  name_blacklist),
                update_timeout))
            remainder -= efft_bat_sz

            if remainder > 0 and pause_sec > 0:
                checkers.append(scheduler.TaskRunner(pause_between_batch,
                                                     pause_sec))
        return checkers

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


def resource_mapping():
    return {
        'OS::Heat::ResourceGroup': ResourceGroup,
    }
