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

ENGINE_TOPIC = 'engine'
LISTENER_TOPIC = 'heat-engine-listener'

PARAM_KEYS = (
    PARAM_TIMEOUT, PARAM_DISABLE_ROLLBACK, PARAM_ADOPT_STACK_DATA,
    PARAM_SHOW_DELETED, PARAM_SHOW_NESTED, PARAM_EXISTING,
    PARAM_CLEAR_PARAMETERS, PARAM_GLOBAL_TENANT, PARAM_LIMIT,
    PARAM_NESTED_DEPTH, PARAM_TAGS, PARAM_SHOW_HIDDEN, PARAM_TAGS_ANY,
    PARAM_NOT_TAGS, PARAM_NOT_TAGS_ANY, TEMPLATE_TYPE, PARAM_WITH_DETAIL,
    RESOLVE_OUTPUTS, PARAM_IGNORE_ERRORS, PARAM_CONVERGE
) = (
    'timeout_mins', 'disable_rollback', 'adopt_stack_data',
    'show_deleted', 'show_nested', 'existing',
    'clear_parameters', 'global_tenant', 'limit',
    'nested_depth', 'tags', 'show_hidden', 'tags_any',
    'not_tags', 'not_tags_any', 'template_type', 'with_detail',
    'resolve_outputs', 'ignore_errors', 'converge'
)

STACK_KEYS = (
    STACK_NAME, STACK_ID,
    STACK_CREATION_TIME, STACK_UPDATED_TIME, STACK_DELETION_TIME,
    STACK_NOTIFICATION_TOPICS,
    STACK_DESCRIPTION, STACK_TMPL_DESCRIPTION,
    STACK_PARAMETERS, STACK_OUTPUTS, STACK_ACTION,
    STACK_STATUS, STACK_STATUS_DATA, STACK_CAPABILITIES,
    STACK_DISABLE_ROLLBACK, STACK_TIMEOUT, STACK_OWNER,
    STACK_PARENT, STACK_USER_PROJECT_ID, STACK_TAGS
) = (
    'stack_name', 'stack_identity',
    'creation_time', 'updated_time', 'deletion_time',
    'notification_topics',
    'description', 'template_description',
    'parameters', 'outputs', 'stack_action',
    'stack_status', 'stack_status_reason', 'capabilities',
    'disable_rollback', 'timeout_mins', 'stack_owner',
    'parent', 'stack_user_project_id', 'tags'
)

STACK_OUTPUT_KEYS = (
    OUTPUT_DESCRIPTION,
    OUTPUT_KEY, OUTPUT_VALUE,
    OUTPUT_ERROR,
) = (
    'description',
    'output_key', 'output_value',
    'output_error',
)

RES_KEYS = (
    RES_DESCRIPTION, RES_CREATION_TIME, RES_UPDATED_TIME,
    RES_NAME, RES_PHYSICAL_ID, RES_METADATA,
    RES_ACTION, RES_STATUS, RES_STATUS_DATA,
    RES_TYPE, RES_ID, RES_STACK_ID, RES_STACK_NAME,
    RES_REQUIRED_BY, RES_NESTED_STACK_ID, RES_NESTED_RESOURCES,
    RES_PARENT_RESOURCE, RES_PROPERTIES, RES_ATTRIBUTES,
) = (
    'description', 'creation_time', 'updated_time',
    'resource_name', 'physical_resource_id', 'metadata',
    'resource_action', 'resource_status', 'resource_status_reason',
    'resource_type', 'resource_identity', STACK_ID, STACK_NAME,
    'required_by', 'nested_stack_id', 'nested_resources',
    'parent_resource', 'properties', 'attributes',
)

RES_SCHEMA_KEYS = (
    RES_SCHEMA_RES_TYPE, RES_SCHEMA_PROPERTIES, RES_SCHEMA_ATTRIBUTES,
    RES_SCHEMA_SUPPORT_STATUS, RES_SCHEMA_DESCRIPTION
) = (
    RES_TYPE, 'properties', 'attributes', 'support_status', 'description'
)

EVENT_KEYS = (
    EVENT_ID,
    EVENT_STACK_ID, EVENT_STACK_NAME,
    EVENT_TIMESTAMP,
    EVENT_RES_NAME, EVENT_RES_PHYSICAL_ID, EVENT_RES_ACTION,
    EVENT_RES_STATUS, EVENT_RES_STATUS_DATA, EVENT_RES_TYPE,
    EVENT_RES_PROPERTIES, EVENT_ROOT_STACK_ID
) = (
    'event_identity',
    STACK_ID, STACK_NAME,
    'event_time',
    RES_NAME, RES_PHYSICAL_ID, RES_ACTION,
    RES_STATUS, RES_STATUS_DATA, RES_TYPE,
    'resource_properties', 'root_stack_id'
)

NOTIFY_KEYS = (
    NOTIFY_TENANT_ID,
    NOTIFY_USER_ID,
    NOTIFY_USERID,
    NOTIFY_USERNAME,
    NOTIFY_STACK_ID,
    NOTIFY_STACK_NAME,
    NOTIFY_STATE,
    NOTIFY_STATE_REASON,
    NOTIFY_CREATE_AT,
    NOTIFY_DESCRIPTION,
    NOTIFY_UPDATE_AT,
    NOTIFY_TAGS,
) = (
    'tenant_id',
    'user_id',
    'user_identity',
    'username',
    STACK_ID,
    STACK_NAME,
    'state',
    'state_reason',
    'create_at',
    STACK_DESCRIPTION,
    'updated_at',
    STACK_TAGS,
)

VALIDATE_PARAM_KEYS = (
    PARAM_TYPE, PARAM_DEFAULT, PARAM_NO_ECHO,
    PARAM_ALLOWED_VALUES, PARAM_ALLOWED_PATTERN, PARAM_MAX_LENGTH,
    PARAM_MIN_LENGTH, PARAM_MAX_VALUE, PARAM_MIN_VALUE,
    PARAM_STEP, PARAM_OFFSET,
    PARAM_DESCRIPTION, PARAM_CONSTRAINT_DESCRIPTION, PARAM_LABEL,
    PARAM_CUSTOM_CONSTRAINT, PARAM_VALUE, PARAM_TAG
) = (
    'Type', 'Default', 'NoEcho',
    'AllowedValues', 'AllowedPattern', 'MaxLength',
    'MinLength', 'MaxValue', 'MinValue', 'Step', 'Offset',
    'Description', 'ConstraintDescription', 'Label',
    'CustomConstraint', 'Value', 'Tags'
)

VALIDATE_PARAM_TYPES = (
    PARAM_TYPE_STRING, PARAM_TYPE_NUMBER, PARAM_TYPE_COMMA_DELIMITED_LIST,
    PARAM_TYPE_JSON, PARAM_TYPE_BOOLEAN
) = (
    'String', 'Number', 'CommaDelimitedList',
    'Json', 'Boolean'
)

SOFTWARE_CONFIG_KEYS = (
    SOFTWARE_CONFIG_ID,
    SOFTWARE_CONFIG_NAME,
    SOFTWARE_CONFIG_GROUP,
    SOFTWARE_CONFIG_CONFIG,
    SOFTWARE_CONFIG_INPUTS,
    SOFTWARE_CONFIG_OUTPUTS,
    SOFTWARE_CONFIG_OPTIONS,
    SOFTWARE_CONFIG_CREATION_TIME,
    SOFTWARE_CONFIG_PROJECT
) = (
    'id',
    'name',
    'group',
    'config',
    'inputs',
    'outputs',
    'options',
    'creation_time',
    'project'
)

SOFTWARE_DEPLOYMENT_KEYS = (
    SOFTWARE_DEPLOYMENT_ID,
    SOFTWARE_DEPLOYMENT_CONFIG_ID,
    SOFTWARE_DEPLOYMENT_SERVER_ID,
    SOFTWARE_DEPLOYMENT_INPUT_VALUES,
    SOFTWARE_DEPLOYMENT_OUTPUT_VALUES,
    SOFTWARE_DEPLOYMENT_ACTION,
    SOFTWARE_DEPLOYMENT_STATUS,
    SOFTWARE_DEPLOYMENT_STATUS_REASON,
    SOFTWARE_DEPLOYMENT_CREATION_TIME,
    SOFTWARE_DEPLOYMENT_UPDATED_TIME
) = (
    'id',
    'config_id',
    'server_id',
    'input_values',
    'output_values',
    'action',
    'status',
    'status_reason',
    'creation_time',
    'updated_time'
)

SOFTWARE_DEPLOYMENT_STATUSES = (
    SOFTWARE_DEPLOYMENT_IN_PROGRESS,
    SOFTWARE_DEPLOYMENT_FAILED,
    SOFTWARE_DEPLOYMENT_COMPLETE
) = (
    'IN_PROGRESS',
    'FAILED',
    'COMPLETE'
)

SOFTWARE_DEPLOYMENT_OUTPUTS = (
    SOFTWARE_DEPLOYMENT_OUTPUT_STDOUT,
    SOFTWARE_DEPLOYMENT_OUTPUT_STDERR,
    SOFTWARE_DEPLOYMENT_OUTPUT_STATUS_CODE
) = (
    'deploy_stdout',
    'deploy_stderr',
    'deploy_status_code'
)

SNAPSHOT_KEYS = (
    SNAPSHOT_ID,
    SNAPSHOT_NAME,
    SNAPSHOT_STACK_ID,
    SNAPSHOT_DATA,
    SNAPSHOT_STATUS,
    SNAPSHOT_STATUS_REASON,
    SNAPSHOT_CREATION_TIME,
) = (
    'id',
    'name',
    'stack_id',
    'data',
    'status',
    'status_reason',
    'creation_time'
)

THREAD_MESSAGES = (THREAD_CANCEL,
                   THREAD_CANCEL_WITH_ROLLBACK
                   ) = ('cancel', 'cancel_with_rollback')
