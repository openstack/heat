#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import six

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import resource
from heat.engine.resources import signal_responder
from heat.engine import support
from heat.engine import translation

# NOTE(tlashchova): copied from sahara/utils/api_validator.py
SAHARA_NAME_REGEX = r"^[a-zA-Z0-9][a-zA-Z0-9\-_\.]*$"


class SaharaJob(signal_responder.SignalResponder, resource.Resource):
    """A resource for creating Sahara Job.

    A job specifies the type of the job and lists all of the individual
    job binary objects. Can be launched using resource-signal.
    """

    support_status = support.SupportStatus(version='8.0.0')

    PROPERTIES = (
        NAME, TYPE, MAINS, LIBS, DESCRIPTION,
        DEFAULT_EXECUTION_DATA, IS_PUBLIC, IS_PROTECTED
    ) = (
        'name', 'type', 'mains', 'libs', 'description',
        'default_execution_data', 'is_public', 'is_protected'
    )

    _EXECUTION_DATA_KEYS = (
        CLUSTER, INPUT, OUTPUT, CONFIGS, PARAMS, ARGS,
        IS_PUBLIC, INTERFACE
    ) = (
        'cluster', 'input', 'output', 'configs', 'params', 'args',
        'is_public', 'interface'
    )

    ATTRIBUTES = (
        EXECUTIONS, DEFAULT_EXECUTION_URL
    ) = (
        'executions', 'default_execution_url'
    )

    properties_schema = {
        NAME: properties.Schema(
            properties.Schema.STRING,
            _("Name of the job."),
            constraints=[
                constraints.Length(min=1, max=50),
                constraints.AllowedPattern(SAHARA_NAME_REGEX),
            ],
            update_allowed=True
        ),
        TYPE: properties.Schema(
            properties.Schema.STRING,
            _("Type of the job."),
            constraints=[
                constraints.CustomConstraint('sahara.job_type')
            ],
            required=True
        ),
        MAINS: properties.Schema(
            properties.Schema.LIST,
            _("IDs or names of job's main job binary. In case of specific "
              "Sahara service, this property designed as a list, but accepts "
              "only one item."),
            schema=properties.Schema(
                properties.Schema.STRING,
                _("ID of job's main job binary."),
                constraints=[constraints.CustomConstraint('sahara.job_binary')]
            ),
            constraints=[constraints.Length(max=1)],
            default=[]
        ),
        LIBS: properties.Schema(
            properties.Schema.LIST,
            _("IDs or names of job's lib job binaries."),
            schema=properties.Schema(
                properties.Schema.STRING,
                constraints=[
                    constraints.CustomConstraint('sahara.job_binary')
                ]
            ),
            default=[]
        ),
        DESCRIPTION: properties.Schema(
            properties.Schema.STRING,
            _('Description of the job.'),
            update_allowed=True
        ),
        IS_PUBLIC: properties.Schema(
            properties.Schema.BOOLEAN,
            _('If True, job will be shared across the tenants.'),
            update_allowed=True,
            default=False
        ),
        IS_PROTECTED: properties.Schema(
            properties.Schema.BOOLEAN,
            _('If True, job will be protected from modifications and '
              'can not be deleted until this property is set to False.'),
            update_allowed=True,
            default=False
        ),
        DEFAULT_EXECUTION_DATA: properties.Schema(
            properties.Schema.MAP,
            _('Default execution data to use when run signal.'),
            schema={
                CLUSTER: properties.Schema(
                    properties.Schema.STRING,
                    _('ID or name of the cluster to run the job in.'),
                    constraints=[
                        constraints.CustomConstraint('sahara.cluster')
                    ],
                    required=True
                ),
                INPUT: properties.Schema(
                    properties.Schema.STRING,
                    _('ID or name of the input data source.'),
                    constraints=[
                        constraints.CustomConstraint('sahara.data_source')
                    ]
                ),
                OUTPUT: properties.Schema(
                    properties.Schema.STRING,
                    _('ID or name of the output data source.'),
                    constraints=[
                        constraints.CustomConstraint('sahara.data_source')
                    ]
                ),
                CONFIGS: properties.Schema(
                    properties.Schema.MAP,
                    _('Config parameters to add to the job.'),
                    default={}
                ),
                PARAMS: properties.Schema(
                    properties.Schema.MAP,
                    _('Parameters to add to the job.'),
                    default={}
                ),
                ARGS: properties.Schema(
                    properties.Schema.LIST,
                    _('Arguments to add to the job.'),
                    schema=properties.Schema(
                        properties.Schema.STRING,
                    ),
                    default=[]
                ),
                IS_PUBLIC: properties.Schema(
                    properties.Schema.BOOLEAN,
                    _('If True, execution will be shared across the tenants.'),
                    default=False
                ),
                INTERFACE: properties.Schema(
                    properties.Schema.MAP,
                    _('Interface arguments to add to the job.'),
                    default={}
                )
            },
            update_allowed=True
        )
    }

    attributes_schema = {
        DEFAULT_EXECUTION_URL: attributes.Schema(
            _("A signed url to create execution specified in "
              "default_execution_data property."),
            type=attributes.Schema.STRING
        ),
        EXECUTIONS: attributes.Schema(
            _("List of the job executions."),
            type=attributes.Schema.LIST
        )
    }

    default_client_name = 'sahara'

    entity = 'jobs'

    def translation_rules(self, properties):
        return [
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.MAINS],
                client_plugin=self.client_plugin(),
                finder='find_resource_by_name_or_id',
                entity='job_binaries'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.LIBS],
                client_plugin=self.client_plugin(),
                finder='find_resource_by_name_or_id',
                entity='job_binaries'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DEFAULT_EXECUTION_DATA, self.CLUSTER],
                client_plugin=self.client_plugin(),
                finder='find_resource_by_name_or_id',
                entity='clusters'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DEFAULT_EXECUTION_DATA, self.INPUT],
                client_plugin=self.client_plugin(),
                finder='find_resource_by_name_or_id',
                entity='data_sources'
            ),
            translation.TranslationRule(
                properties,
                translation.TranslationRule.RESOLVE,
                [self.DEFAULT_EXECUTION_DATA, self.OUTPUT],
                client_plugin=self.client_plugin(),
                finder='find_resource_by_name_or_id',
                entity='data_sources'
            )
        ]

    def handle_create(self):
        args = {
            'name': self.properties[
                self.NAME] or self.physical_resource_name(),
            'type': self.properties[self.TYPE],
            # Note: sahara accepts only one main binary but schema demands
            # that it should be in a list.
            'mains': self.properties[self.MAINS],
            'libs': self.properties[self.LIBS],
            'description': self.properties[self.DESCRIPTION],
            'is_public': self.properties[self.IS_PUBLIC],
            'is_protected': self.properties[self.IS_PROTECTED]
        }

        job = self.client().jobs.create(**args)
        self.resource_id_set(job.id)

    def handle_update(self, json_snippet, tmpl_diff, prop_diff):
        if self.NAME in prop_diff:
            name = prop_diff[self.NAME] or self.physical_resource_name()
            prop_diff[self.NAME] = name
        if self.DEFAULT_EXECUTION_DATA in prop_diff:
            del prop_diff[self.DEFAULT_EXECUTION_DATA]

        if prop_diff:
            self.client().jobs.update(self.resource_id, **prop_diff)

    def handle_signal(self, details):
        data = details or self.properties.get(self.DEFAULT_EXECUTION_DATA)
        execution_args = {
            'job_id': self.resource_id,
            'cluster_id': data.get(self.CLUSTER),
            'input_id': data.get(self.INPUT),
            'output_id': data.get(self.OUTPUT),
            'is_public': data.get(self.IS_PUBLIC),
            'interface': data.get(self.INTERFACE),
            'configs': {
                'configs': data.get(self.CONFIGS),
                'params': data.get(self.PARAMS),
                'args': data.get(self.ARGS)
            },
            'is_protected': False
        }
        try:
            self.client().job_executions.create(**execution_args)
        except Exception as ex:
            raise exception.ResourceFailure(ex, self)

    def handle_delete(self):
        if self.resource_id is None:
            return

        with self.client_plugin().ignore_not_found:
            job_exs = self.client().job_executions.find(id=self.resource_id)
            for ex in job_exs:
                self.client().job_executions.delete(ex.id)
        super(SaharaJob, self).handle_delete()

    def _resolve_attribute(self, name):
        if name == self.DEFAULT_EXECUTION_URL:
            return six.text_type(self._get_ec2_signed_url())
        elif name == self.EXECUTIONS:
            try:
                job_execs = self.client().job_executions.find(
                    id=self.resource_id)
            except Exception:
                return []
            return [execution.to_dict() for execution in job_execs]


def resource_mapping():
    return {
        'OS::Sahara::Job': SaharaJob
    }
