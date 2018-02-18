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

import copy

from oslo_serialization import jsonutils
import six
import yaml

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import signal_responder
from heat.engine import support
from heat.engine import translation


class Workflow(signal_responder.SignalResponder,
               resource.Resource):
    """A resource that implements Mistral workflow.

    Workflow represents a process that can be described in a various number of
    ways and that can do some job interesting to the end user. Each workflow
    consists of tasks (at least one) describing what exact steps should be made
    during workflow execution.

    For detailed description how to use Workflow, read Mistral documentation.
    """

    support_status = support.SupportStatus(version='2015.1')

    default_client_name = 'mistral'

    entity = 'workflows'

    PROPERTIES = (
        NAME, TYPE, DESCRIPTION, INPUT, OUTPUT, TASKS, PARAMS,
        TASK_DEFAULTS, USE_REQUEST_BODY_AS_INPUT, TAGS
    ) = (
        'name', 'type', 'description', 'input', 'output', 'tasks', 'params',
        'task_defaults', 'use_request_body_as_input', 'tags'
    )

    _TASKS_KEYS = (
        TASK_NAME, TASK_DESCRIPTION, ON_ERROR, ON_COMPLETE, ON_SUCCESS,
        POLICIES, ACTION, WORKFLOW, PUBLISH, TASK_INPUT, REQUIRES,
        RETRY, WAIT_BEFORE, WAIT_AFTER, PAUSE_BEFORE, TIMEOUT,
        WITH_ITEMS, KEEP_RESULT, TARGET, JOIN, CONCURRENCY
    ) = (
        'name', 'description', 'on_error', 'on_complete', 'on_success',
        'policies', 'action', 'workflow', 'publish', 'input', 'requires',
        'retry', 'wait_before', 'wait_after', 'pause_before', 'timeout',
        'with_items', 'keep_result', 'target', 'join', 'concurrency'
    )

    _TASKS_TASK_DEFAULTS = [
        ON_ERROR, ON_COMPLETE, ON_SUCCESS,
        REQUIRES, RETRY, WAIT_BEFORE, WAIT_AFTER, PAUSE_BEFORE, TIMEOUT,
        CONCURRENCY
    ]

    _SIGNAL_DATA_KEYS = (
        SIGNAL_DATA_INPUT, SIGNAL_DATA_PARAMS
    ) = (
        'input', 'params'
    )

    ATTRIBUTES = (
        WORKFLOW_DATA, ALARM_URL, EXECUTIONS
    ) = (
        'data', 'alarm_url', 'executions'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _('Workflow name.')
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Workflow type.'),
            constraints=[
                constraints.AllowedValues(['direct', 'reverse'])
            ],
            required=True,
            update_allowed=True
        ),
        USE_REQUEST_BODY_AS_INPUT: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Defines the method in which the request body for signaling a '
              'workflow would be parsed. In case this property is set to '
              'True, the body would be parsed as a simple json where each '
              'key is a workflow input, in other cases body would be parsed '
              'expecting a specific json format with two keys: "input" and '
              '"params".'),
            update_allowed=True,
            support_status=support.SupportStatus(version='6.0.0')
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            _('List of tags to set on the workflow.'),
            update_allowed=True,
            support_status=support.SupportStatus(version='10.0.0')
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Workflow description.'),
            update_allowed=True
        ),
        INPUT: properties.Schema(
            properties.Schema.MAP,
            _('Dictionary which contains input for workflow.'),
            update_allowed=True
        ),
        OUTPUT: properties.Schema(
            properties.Schema.MAP,
            _('Any data structure arbitrarily containing YAQL '
              'expressions that defines workflow output. May be '
              'nested.'),
            update_allowed=True
        ),
        PARAMS: properties.Schema(
            properties.Schema.MAP,
            _("Workflow additional parameters. If Workflow is reverse typed, "
              "params requires 'task_name', which defines initial task."),
            update_allowed=True
        ),
        TASK_DEFAULTS: properties.Schema(
            properties.Schema.MAP,
            _("Default settings for some of task "
              "attributes defined "
              "at workflow level."),
            support_status=support.SupportStatus(version='5.0.0'),
            schema={
                ON_SUCCESS: properties.Schema(
                    properties.Schema.LIST,
                    _('List of tasks which will run after '
                      'the task has completed successfully.')
                ),
                ON_ERROR: properties.Schema(
                    properties.Schema.LIST,
                    _('List of tasks which will run after '
                      'the task has completed with an error.')
                ),
                ON_COMPLETE: properties.Schema(
                    properties.Schema.LIST,
                    _('List of tasks which will run after '
                      'the task has completed regardless of whether '
                      'it is successful or not.')
                ),
                REQUIRES: properties.Schema(
                    properties.Schema.LIST,
                    _('List of tasks which should be executed before '
                      'this task. Used only in reverse workflows.')
                ),
                RETRY: properties.Schema(
                    properties.Schema.MAP,
                    _('Defines a pattern how task should be repeated in '
                      'case of an error.')
                ),
                WAIT_BEFORE: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Defines a delay in seconds that Mistral Engine '
                      'should wait before starting a task.')
                ),
                WAIT_AFTER: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Defines a delay in seconds that Mistral Engine '
                      'should wait after a task has completed before '
                      'starting next tasks defined in '
                      'on-success, on-error or on-complete.')
                ),
                PAUSE_BEFORE: properties.Schema(
                    properties.Schema.BOOLEAN,
                    _('Defines whether Mistral Engine should put the '
                      'workflow on hold or not before starting a task.')
                ),
                TIMEOUT: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Defines a period of time in seconds after which '
                      'a task will be failed automatically '
                      'by engine if hasn\'t completed.')
                ),
                CONCURRENCY: properties.Schema(
                    properties.Schema.INTEGER,
                    _('Defines a max number of actions running simultaneously '
                      'in a task. Applicable only for tasks that have '
                      'with-items.'),
                    support_status=support.SupportStatus(version='8.0.0')
                )
            },
            update_allowed=True
        ),
        TASKS: properties.Schema(
            properties.Schema.LIST,
            _('Dictionary containing workflow tasks.'),
            schema=properties.Schema(
                properties.Schema.MAP,
                schema={
                    TASK_NAME: properties.Schema(
                        properties.Schema.STRING,
                        _('Task name.'),
                        required=True
                    ),
                    TASK_DESCRIPTION: properties.Schema(
                        properties.Schema.STRING,
                        _('Task description.')
                    ),
                    TASK_INPUT: properties.Schema(
                        properties.Schema.MAP,
                        _('Actual input parameter values of the task.')
                    ),
                    ACTION: properties.Schema(
                        properties.Schema.STRING,
                        _('Name of the action associated with the task. '
                          'Either action or workflow may be defined in the '
                          'task.')
                    ),
                    WORKFLOW: properties.Schema(
                        properties.Schema.STRING,
                        _('Name of the workflow associated with the task. '
                          'Can be defined by intrinsic function get_resource '
                          'or by name of the referenced workflow, i.e. '
                          '{ workflow: wf_name } or '
                          '{ workflow: { get_resource: wf_name }}. Either '
                          'action or workflow may be defined in the task.'),
                        constraints=[
                            constraints.CustomConstraint('mistral.workflow')
                        ]
                    ),
                    PUBLISH: properties.Schema(
                        properties.Schema.MAP,
                        _('Dictionary of variables to publish to '
                          'the workflow context.')
                    ),
                    ON_SUCCESS: properties.Schema(
                        properties.Schema.LIST,
                        _('List of tasks which will run after '
                          'the task has completed successfully.')
                    ),
                    ON_ERROR: properties.Schema(
                        properties.Schema.LIST,
                        _('List of tasks which will run after '
                          'the task has completed with an error.')
                    ),
                    ON_COMPLETE: properties.Schema(
                        properties.Schema.LIST,
                        _('List of tasks which will run after '
                          'the task has completed regardless of whether '
                          'it is successful or not.')
                    ),
                    POLICIES: properties.Schema(
                        properties.Schema.MAP,
                        _('Dictionary-like section defining task policies '
                          'that influence how Mistral Engine runs tasks. Must '
                          'satisfy Mistral DSL v2.'),
                        support_status=support.SupportStatus(
                            status=support.HIDDEN,
                            version='8.0.0',
                            message=_('Add needed policies directly to '
                                      'the task, Policy keyword is not '
                                      'needed'),
                            previous_status=support.SupportStatus(
                                status=support.DEPRECATED,
                                version='5.0.0',
                                previous_status=support.SupportStatus(
                                    version='2015.1')
                            )
                        )
                    ),
                    REQUIRES: properties.Schema(
                        properties.Schema.LIST,
                        _('List of tasks which should be executed before '
                          'this task. Used only in reverse workflows.')
                    ),
                    RETRY: properties.Schema(
                        properties.Schema.MAP,
                        _('Defines a pattern how task should be repeated in '
                          'case of an error.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    WAIT_BEFORE: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Defines a delay in seconds that Mistral Engine '
                          'should wait before starting a task.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    WAIT_AFTER: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Defines a delay in seconds that Mistral '
                          'Engine should wait after '
                          'a task has completed before starting next tasks '
                          'defined in on-success, on-error or on-complete.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    PAUSE_BEFORE: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _('Defines whether Mistral Engine should '
                          'put the workflow on hold '
                          'or not before starting a task.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    TIMEOUT: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Defines a period of time in seconds after which a '
                          'task will be failed automatically by engine '
                          'if hasn\'t completed.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    WITH_ITEMS: properties.Schema(
                        properties.Schema.STRING,
                        _('If configured, it allows to run action or workflow '
                          'associated with a task multiple times '
                          'on a provided list of items.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    KEEP_RESULT: properties.Schema(
                        properties.Schema.BOOLEAN,
                        _('Allowing not to store action results '
                          'after task completion.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    CONCURRENCY: properties.Schema(
                        properties.Schema.INTEGER,
                        _('Defines a max number of actions running '
                          'simultaneously in a task. Applicable only for '
                          'tasks that have with-items.'),
                        support_status=support.SupportStatus(version='8.0.0')
                    ),
                    TARGET: properties.Schema(
                        properties.Schema.STRING,
                        _('It defines an executor to which task action '
                          'should be sent to.'),
                        support_status=support.SupportStatus(version='5.0.0')
                    ),
                    JOIN: properties.Schema(
                        properties.Schema.STRING,
                        _('Allows to synchronize multiple parallel workflow '
                          'branches and aggregate their data. '
                          'Valid inputs: all - the task will run only if '
                          'all upstream tasks are completed. '
                          'Any numeric value - then the task will run once '
                          'at least this number of upstream tasks are '
                          'completed and corresponding conditions have '
                          'triggered.'),
                        support_status=support.SupportStatus(version='6.0.0')
                    ),
                },
            ),
            required=True,
            update_allowed=True,
            constraints=[constraints.Length(min=1)]
        )
    }

    attributes_schema = {
        WORKFLOW_DATA: attributes.Schema(
            _('A dictionary which contains name and input of the workflow.'),
            type=attributes.Schema.MAP
        ),
        ALARM_URL: attributes.Schema(
            _("A signed url to create executions for workflows specified in "
              "Workflow resource."),
            type=attributes.Schema.STRING
        ),
        EXECUTIONS: attributes.Schema(
            _("List of workflows' executions, each of them is a dictionary "
              "with information about execution. Each dictionary returns "
              "values for next keys: id, workflow_name, created_at, "
              "updated_at, state for current execution state, input, output."),
            type=attributes.Schema.LIST
        )
    }

    def translation_rules(self, properties):
        policies_keys = [self.PAUSE_BEFORE, self.WAIT_AFTER, self.WAIT_BEFORE,
                         self.TIMEOUT, self.CONCURRENCY, self.RETRY]
        rules = []
        for key in policies_keys:
            rules.append(
                translation.TranslationRule(
                    properties,
                    translation.TranslationRule.REPLACE,
                    [self.TASKS, key],
                    value_name=self.POLICIES,
                    custom_value_path=[key]
                )
            )
        # after executing rules above properties data contains policies key
        # with empty dict value, so need to remove policies from properties.
        rules.append(
            translation.TranslationRule(
                properties,
                translation.TranslationRule.DELETE,
                [self.TASKS, self.POLICIES]
            )
        )
        return rules

    def get_reference_id(self):
        return self._workflow_name()

    def _get_inputs_and_params(self, data):
        inputs = None
        params = None
        if self.properties.get(self.USE_REQUEST_BODY_AS_INPUT):
            inputs = data
        else:
            if data is not None:
                inputs = data.get(self.SIGNAL_DATA_INPUT)
                params = data.get(self.SIGNAL_DATA_PARAMS)
        return inputs, params

    def _validate_signal_data(self, inputs, params):
        if inputs is not None:
            if not isinstance(inputs, dict):
                message = (_('Input in signal data must be a map, '
                             'find a %s') % type(inputs))
                raise exception.StackValidationFailed(
                    error=_('Signal data error'),
                    message=message)
            for key in inputs:
                if (self.properties.get(self.INPUT) is None or
                        key not in self.properties.get(self.INPUT)):
                    message = _('Unknown input %s') % key
                    raise exception.StackValidationFailed(
                        error=_('Signal data error'),
                        message=message)
        if params is not None and not isinstance(params, dict):
                message = (_('Params must be a map, find a '
                             '%s') % type(params))
                raise exception.StackValidationFailed(
                    error=_('Signal data error'),
                    message=message)

    def validate(self):
        super(Workflow, self).validate()
        if self.properties.get(self.TYPE) == 'reverse':
            params = self.properties.get(self.PARAMS)
            if params is None or not params.get('task_name'):
                raise exception.StackValidationFailed(
                    error=_('Mistral resource validation error'),
                    path=[self.name,
                          ('properties'
                           if self.stack.t.VERSION == 'heat_template_version'
                           else 'Properties'),
                          self.PARAMS],
                    message=_("'task_name' is not assigned in 'params' "
                              "in case of reverse type workflow.")
                )
        for task in self.properties.get(self.TASKS):
            wf_value = task.get(self.WORKFLOW)
            action_value = task.get(self.ACTION)
            if wf_value and action_value:
                raise exception.ResourcePropertyConflict(self.WORKFLOW,
                                                         self.ACTION)
            if not wf_value and not action_value:
                raise exception.PropertyUnspecifiedError(self.WORKFLOW,
                                                         self.ACTION)
            if (task.get(self.REQUIRES) is not None
                    and self.properties.get(self.TYPE)) == 'direct':
                msg = _("task %(task)s contains property 'requires' "
                        "in case of direct workflow. Only reverse workflows "
                        "can contain property 'requires'.") % {
                    'name': self.name,
                    'task': task.get(self.TASK_NAME)
                }
                raise exception.StackValidationFailed(
                    error=_('Mistral resource validation error'),
                    path=[self.name,
                          ('properties'
                           if self.stack.t.VERSION == 'heat_template_version'
                           else 'Properties'),
                          self.TASKS,
                          task.get(self.TASK_NAME),
                          self.REQUIRES],
                    message=msg)

            if task.get(self.POLICIES) is not None:
                for task_item in task.get(self.POLICIES):
                    if task.get(task_item) is not None:
                        msg = _('Property %(policies)s and %(item)s cannot be '
                                'used both at one time.') % {
                            'policies': self.POLICIES,
                            'item': task_item
                        }
                        raise exception.StackValidationFailed(message=msg)

            if (task.get(self.WITH_ITEMS) is None and
                    task.get(self.CONCURRENCY) is not None):
                raise exception.ResourcePropertyDependency(
                    prop1=self.CONCURRENCY, prop2=self.WITH_ITEMS)

    def _workflow_name(self):
        return self.properties.get(self.NAME) or self.physical_resource_name()

    def build_tasks(self, props):
        for task in props[self.TASKS]:
            current_task = {}
            wf_value = task.get(self.WORKFLOW)
            if wf_value is not None:
                current_task.update({self.WORKFLOW: wf_value})

            # backward support for kilo.
            if task.get(self.POLICIES) is not None:
                task.update(task.get(self.POLICIES))

            task_keys = [key for key in self._TASKS_KEYS
                         if key not in [
                             self.WORKFLOW,
                             self.TASK_NAME,
                             self.POLICIES
                         ]]
            for task_prop in task_keys:
                if task.get(task_prop) is not None:
                    current_task.update(
                        {task_prop.replace('_', '-'): task[task_prop]})

            yield {task[self.TASK_NAME]: current_task}

    def prepare_properties(self, props):
        """Prepare correct YAML-formatted definition for Mistral."""
        defn_name = self._workflow_name()
        definition = {'version': '2.0',
                      defn_name: {self.TYPE: props.get(self.TYPE),
                                  self.DESCRIPTION: props.get(
                                      self.DESCRIPTION),
                                  self.TAGS: props.get(self.TAGS),
                                  self.OUTPUT: props.get(self.OUTPUT)}}
        for key in list(definition[defn_name].keys()):
            if definition[defn_name][key] is None:
                del definition[defn_name][key]
        if props.get(self.INPUT) is not None:
            definition[defn_name][self.INPUT] = list(props.get(
                self.INPUT).keys())
        definition[defn_name][self.TASKS] = {}
        for task in self.build_tasks(props):
            definition.get(defn_name).get(self.TASKS).update(task)

        if props.get(self.TASK_DEFAULTS) is not None:
            definition[defn_name][self.TASK_DEFAULTS.replace('_', '-')] = {
                k.replace('_', '-'): v for k, v in
                six.iteritems(props.get(self.TASK_DEFAULTS)) if v}

        return yaml.dump(definition, Dumper=yaml.CSafeDumper
                         if hasattr(yaml, 'CSafeDumper')
                         else yaml.SafeDumper)

    def handle_create(self):
        super(Workflow, self).handle_create()
        props = self.prepare_properties(self.properties)
        try:
            workflow = self.client().workflows.create(props)
        except Exception as ex:
            raise exception.ResourceFailure(ex, self)
        # NOTE(prazumovsky): Mistral uses unique names for resource
        # identification.
        self.resource_id_set(workflow[0].name)

    def handle_signal(self, details=None):
        inputs, params = self._get_inputs_and_params(details)
        self._validate_signal_data(inputs, params)

        inputs_result = copy.deepcopy(self.properties[self.INPUT])
        params_result = copy.deepcopy(self.properties[self.PARAMS]) or {}
        # NOTE(prazumovsky): Signal can contains some data, interesting
        # for workflow, e.g. inputs. So, if signal data contains input
        # we update override inputs, other leaved defined in template.
        if inputs:
            inputs_result.update(inputs)
        if params:
            params_result.update(params)

        try:
            execution = self.client().executions.create(
                self._workflow_name(),
                workflow_input=jsonutils.dumps(inputs_result),
                **params_result)
        except Exception as ex:
            raise exception.ResourceFailure(ex, self)
        executions = [execution.id]
        if self.EXECUTIONS in self.data():
            executions.extend(self.data().get(self.EXECUTIONS).split(','))
        self.data_set(self.EXECUTIONS, ','.join(executions))

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if prop_diff:
            props = json_snippet.properties(self.properties_schema,
                                            self.context)
            new_props = self.prepare_properties(props)
            try:
                workflow = self.client().workflows.update(new_props)
            except Exception as ex:
                raise exception.ResourceFailure(ex, self)
            self.data_set(self.NAME, workflow[0].name)
            self.resource_id_set(workflow[0].name)

    def _delete_executions(self):
        if self.data().get(self.EXECUTIONS):
            for id in self.data().get(self.EXECUTIONS).split(','):
                with self.client_plugin().ignore_not_found:
                    self.client().executions.delete(id)

            self.data_delete('executions')

    def handle_delete(self):
        self._delete_executions()
        return super(Workflow, self).handle_delete()

    def _resolve_attribute(self, name):
        if name == self.EXECUTIONS:
            if self.EXECUTIONS not in self.data():
                return []

            def parse_execution_response(execution):
                return {
                    'id': execution.id,
                    'workflow_name': execution.workflow_name,
                    'created_at': execution.created_at,
                    'updated_at': execution.updated_at,
                    'state': execution.state,
                    'input': jsonutils.loads(six.text_type(execution.input)),
                    'output': jsonutils.loads(six.text_type(execution.output))
                }

            return [parse_execution_response(
                self.client().executions.get(exec_id))
                for exec_id in
                self.data().get(self.EXECUTIONS).split(',')]

        elif name == self.WORKFLOW_DATA:
            return {self.NAME: self.resource_id,
                    self.INPUT: self.properties.get(self.INPUT)}

        elif name == self.ALARM_URL and self.resource_id is not None:
            return six.text_type(self._get_ec2_signed_url())


def resource_mapping():
    return {
        'OS::Mistral::Workflow': Workflow
    }
