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

import routes
import six

from heat.api.openstack.v1 import actions
from heat.api.openstack.v1 import build_info
from heat.api.openstack.v1 import events
from heat.api.openstack.v1 import resources
from heat.api.openstack.v1 import services
from heat.api.openstack.v1 import software_configs
from heat.api.openstack.v1 import software_deployments
from heat.api.openstack.v1 import stacks
from heat.common import wsgi


class API(wsgi.Router):

    """WSGI router for Heat v1 REST API requests."""

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()
        default_resource = wsgi.Resource(wsgi.DefaultMethodController(),
                                         wsgi.JSONRequestDeserializer())

        def connect(controller, path_prefix, routes):
            """Connects list of routes to given controller with path_prefix.

            This function connects the list of routes to the given
            controller, prepending the given path_prefix. Then for each URL it
            finds which request methods aren't handled and configures those
            to return a 405 error. Finally, it adds a handler for the
            OPTIONS method to all URLs that returns the list of allowed
            methods with 204 status code.
            """
            # register the routes with the mapper, while keeping track of which
            # methods are defined for each URL
            urls = {}
            for r in routes:
                url = path_prefix + r['url']
                methods = r['method']
                if isinstance(methods, six.string_types):
                    methods = [methods]
                methods_str = ','.join(methods)
                mapper.connect(r['name'], url, controller=controller,
                               action=r['action'],
                               conditions={'method': methods_str})
                if url not in urls:
                    urls[url] = methods
                else:
                    urls[url] += methods

            # now register the missing methods to return 405s, and register
            # a handler for OPTIONS that returns the list of allowed methods
            for url, methods in urls.items():
                all_methods = ['HEAD', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE']
                missing_methods = [m for m in all_methods if m not in methods]
                allowed_methods_str = ','.join(methods)
                mapper.connect(url,
                               controller=default_resource,
                               action='reject',
                               allowed_methods=allowed_methods_str,
                               conditions={'method': missing_methods})
                if 'OPTIONS' not in methods:
                    mapper.connect(url,
                                   controller=default_resource,
                                   action='options',
                                   allowed_methods=allowed_methods_str,
                                   conditions={'method': 'OPTIONS'})

        # Stacks
        stacks_resource = stacks.create_resource(conf)
        connect(controller=stacks_resource,
                path_prefix='/{tenant_id}',
                routes=[
                    # Template handling
                    {
                        'name': 'template_validate',
                        'url': '/validate',
                        'action': 'validate_template',
                        'method': 'POST'
                    },
                    {
                        'name': 'resource_types',
                        'url': '/resource_types',
                        'action': 'list_resource_types',
                        'method': 'GET'
                    },
                    {
                        'name': 'resource_schema',
                        'url': '/resource_types/{type_name}',
                        'action': 'resource_schema',
                        'method': 'GET'
                    },
                    {
                        'name': 'generate_template',
                        'url': '/resource_types/{type_name}/template',
                        'action': 'generate_template',
                        'method': 'GET'
                    },

                    {
                        'name': 'template_versions',
                        'url': '/template_versions',
                        'action': 'list_template_versions',
                        'method': 'GET'
                    },

                    {
                        'name': 'template_functions',
                        'url': '/template_versions/{template_version}'
                               '/functions',
                        'action': 'list_template_functions',
                        'method': 'GET'
                    },

                    # Stack collection
                    {
                        'name': 'stack_index',
                        'url': '/stacks',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_create',
                        'url': '/stacks',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'stack_preview',
                        'url': '/stacks/preview',
                        'action': 'preview',
                        'method': 'POST'
                    },
                    {
                        'name': 'stack_detail',
                        'url': '/stacks/detail',
                        'action': 'detail',
                        'method': 'GET'
                    },

                    # Stack data
                    {
                        'name': 'stack_lookup',
                        'url': '/stacks/{stack_name}',
                        'action': 'lookup',
                        'method': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
                    },
                    # \x3A matches on a colon.
                    # Routes treats : specially in its regexp
                    {
                        'name': 'stack_lookup',
                        'url': r'/stacks/{stack_name:arn\x3A.*}',
                        'action': 'lookup',
                        'method': ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
                    },
                    {
                        'name': 'stack_lookup_subpath',
                        'url': '/stacks/{stack_name}/'
                               '{path:resources|events|template|actions'
                               '|environment|files}',
                        'action': 'lookup',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_lookup_subpath_post',
                        'url': '/stacks/{stack_name}/'
                               '{path:resources|events|template|actions}',
                        'action': 'lookup',
                        'method': 'POST'
                    },
                    {
                        'name': 'stack_show',
                        'url': '/stacks/{stack_name}/{stack_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_lookup',
                        'url': '/stacks/{stack_name}/{stack_id}/template',
                        'action': 'template',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_lookup',
                        'url': '/stacks/{stack_name}/{stack_id}/environment',
                        'action': 'environment',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_lookup',
                        'url': '/stacks/{stack_name}/{stack_id}/files',
                        'action': 'files',
                        'method': 'GET'
                    },

                    # Stack update/delete
                    {
                        'name': 'stack_update',
                        'url': '/stacks/{stack_name}/{stack_id}',
                        'action': 'update',
                        'method': 'PUT'
                    },
                    {
                        'name': 'stack_update_patch',
                        'url': '/stacks/{stack_name}/{stack_id}',
                        'action': 'update_patch',
                        'method': 'PATCH'
                    },
                    {
                        'name': 'preview_stack_update',
                        'url': '/stacks/{stack_name}/{stack_id}/preview',
                        'action': 'preview_update',
                        'method': 'PUT'
                    },
                    {
                        'name': 'preview_stack_update_patch',
                        'url': '/stacks/{stack_name}/{stack_id}/preview',
                        'action': 'preview_update_patch',
                        'method': 'PATCH'
                    },
                    {
                        'name': 'stack_delete',
                        'url': '/stacks/{stack_name}/{stack_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    },

                    # Stack abandon
                    {
                        'name': 'stack_abandon',
                        'url': '/stacks/{stack_name}/{stack_id}/abandon',
                        'action': 'abandon',
                        'method': 'DELETE'
                    },
                    {
                        'name': 'stack_export',
                        'url': '/stacks/{stack_name}/{stack_id}/export',
                        'action': 'export',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_snapshot',
                        'url': '/stacks/{stack_name}/{stack_id}/snapshots',
                        'action': 'snapshot',
                        'method': 'POST'
                    },
                    {
                        'name': 'stack_snapshot_show',
                        'url': '/stacks/{stack_name}/{stack_id}/snapshots/'
                               '{snapshot_id}',
                        'action': 'show_snapshot',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_snapshot_delete',
                        'url': '/stacks/{stack_name}/{stack_id}/snapshots/'
                               '{snapshot_id}',
                        'action': 'delete_snapshot',
                        'method': 'DELETE'
                    },
                    {
                        'name': 'stack_list_snapshots',
                        'url': '/stacks/{stack_name}/{stack_id}/snapshots',
                        'action': 'list_snapshots',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_snapshot_restore',
                        'url': '/stacks/{stack_name}/{stack_id}/snapshots/'
                               '{snapshot_id}/restore',
                        'action': 'restore_snapshot',
                        'method': 'POST'
                    },

                    # Stack outputs
                    {
                        'name': 'stack_output_list',
                        'url': '/stacks/{stack_name}/{stack_id}/outputs',
                        'action': 'list_outputs',
                        'method': 'GET'
                    },
                    {
                        'name': 'stack_output_show',
                        'url': '/stacks/{stack_name}/{stack_id}/outputs/'
                               '{output_key}',
                        'action': 'show_output',
                        'method': 'GET'
                    }
                ])

        # Resources
        resources_resource = resources.create_resource(conf)
        stack_path = '/{tenant_id}/stacks/{stack_name}/{stack_id}'
        connect(controller=resources_resource, path_prefix=stack_path,
                routes=[
                    # Resource collection
                    {
                        'name': 'resource_index',
                        'url': '/resources',
                        'action': 'index',
                        'method': 'GET'
                    },

                    # Resource data
                    {
                        'name': 'resource_show',
                        'url': '/resources/{resource_name}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'resource_metadata_show',
                        'url': '/resources/{resource_name}/metadata',
                        'action': 'metadata',
                        'method': 'GET'
                    },
                    {
                        'name': 'resource_signal',
                        'url': '/resources/{resource_name}/signal',
                        'action': 'signal',
                        'method': 'POST'
                    },
                    {
                        'name': 'resource_mark_unhealthy',
                        'url': '/resources/{resource_name}',
                        'action': 'mark_unhealthy',
                        'method': 'PATCH'
                    }
                ])

        # Events
        events_resource = events.create_resource(conf)
        connect(controller=events_resource, path_prefix=stack_path,
                routes=[
                    # Stack event collection
                    {
                        'name': 'event_index_stack',
                        'url': '/events',
                        'action': 'index',
                        'method': 'GET'
                    },

                    # Resource event collection
                    {
                        'name': 'event_index_resource',
                        'url': '/resources/{resource_name}/events',
                        'action': 'index',
                        'method': 'GET'
                    },

                    # Event data
                    {
                        'name': 'event_show',
                        'url': '/resources/{resource_name}/events/{event_id}',
                        'action': 'show',
                        'method': 'GET'
                    }
                ])

        # Actions
        actions_resource = actions.create_resource(conf)
        connect(controller=actions_resource, path_prefix=stack_path,
                routes=[
                    {
                        'name': 'action_stack',
                        'url': '/actions',
                        'action': 'action',
                        'method': 'POST'
                    }
                ])

        # Info
        info_resource = build_info.create_resource(conf)
        connect(controller=info_resource, path_prefix='/{tenant_id}',
                routes=[
                    {
                        'name': 'build_info',
                        'url': '/build_info',
                        'action': 'build_info',
                        'method': 'GET'
                    }
                ])

        # Software configs
        software_config_resource = software_configs.create_resource(conf)
        connect(controller=software_config_resource,
                path_prefix='/{tenant_id}/software_configs',
                routes=[
                    {
                        'name': 'software_config_index',
                        'url': '',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'software_config_create',
                        'url': '',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'software_config_show',
                        'url': '/{config_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'software_config_delete',
                        'url': '/{config_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    }
                ])

        # Software deployments
        sd_resource = software_deployments.create_resource(conf)
        connect(controller=sd_resource,
                path_prefix='/{tenant_id}/software_deployments',
                routes=[
                    {
                        'name': 'software_deployment_index',
                        'url': '',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'software_deployment_metadata',
                        'url': '/metadata/{server_id}',
                        'action': 'metadata',
                        'method': 'GET'
                    },
                    {
                        'name': 'software_deployment_create',
                        'url': '',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'software_deployment_show',
                        'url': '/{deployment_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'software_deployment_update',
                        'url': '/{deployment_id}',
                        'action': 'update',
                        'method': 'PUT'
                    },
                    {
                        'name': 'software_deployment_delete',
                        'url': '/{deployment_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    }
                ])

        # Services
        service_resource = services.create_resource(conf)
        with mapper.submapper(
            controller=service_resource,
            path_prefix='/{tenant_id}/services'
        ) as sa_mapper:

            sa_mapper.connect("service_index",
                              "",
                              action="index",
                              conditions={'method': 'GET'})

        # now that all the routes are defined, add a handler for
        super(API, self).__init__(mapper)
