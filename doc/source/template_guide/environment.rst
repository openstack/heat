.. highlight: yaml
   :linenothreshold: 5

..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

.. _environments:

============
Environments
============

The environment affects the runtime behavior of a template. It provides a way
to override the resource implementations and a mechanism to place parameters
that the service needs.

To fully understand the runtime behavior you have to consider what plug-ins are
installed on the cloud you're using.

Environment file format
~~~~~~~~~~~~~~~~~~~~~~~
The environment is a yaml text file that contains two main sections:

``parameters``
    A list of key/value pairs.

``resource_registry``
    Definition of custom resources.

It also can contain some other sections:

``parameter_defaults``
    Default parameters passed to all template resources.

``encrypted_parameters``
    List of encrypted parameters.

``event_sinks``
    List of endpoints that would receive stack events.

``parameter_merge_strategies``
    Merge strategies for merging parameters and parameter defaults from the
    environment file.

Use the `-e` option of the :command:`openstack stack create` command to create
a stack using the environment defined in such a file.

You can also provide environment parameters as a list of key/value pairs using
the `--parameter` option of the :command:`openstack stack create` command.

In the following example the environment is read from the :file:`my_env.yaml`
file and an extra parameter is provided using the `--parameter` option::

   $ openstack stack create my_stack -e my_env.yaml --parameter "param1=val1;param2=val2" -t my_tmpl.yaml

Environment Merging
~~~~~~~~~~~~~~~~~~~

Parameters and their defaults (``parameter_defaults``) are merged based on merge
strategies in an environment file.

There are three merge strategy types:

``overwrite``
    Overwrites a parameter, existing parameter values are replaced.

``merge``
    Merges the existing parameter value and the new value. String values
    are concatenated, comma delimited lists are extended and json values
    are updated.

``deep_merge``
    Json values are deep merged. Not useful for other types like comma
    delimited lists and strings. If specified for them, it falls back to
    ``merge``.

You can provide a default merge strategy and/or parameter specific merge strategies
per environment file. Parameter specific merge strategy is only used for that
parameter. An example of ``parameter_merge_strategies`` section in an environment file::

  parameter_merge_strategies:
    default: merge
    param1: overwrite
    param2: deep_merge

If no merge strategy is provided in an environment file, ``overwrite`` becomes the
default merge strategy for all ``parameters`` and ``parameter_defaults`` in that
environment file.

Global and effective environments
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The environment used for a stack is the combination of the environment you
use with the template for the stack, and a global environment that is
determined by your cloud operator. An entry in the user environment takes
precedence over the global environment. OpenStack includes a default global
environment, but your cloud operator can add additional environment entries.

The cloud operator can add to the global environment
by putting environment files in a configurable directory wherever
the Orchestration engine runs. The configuration variable is named
``environment_dir`` and is found in the ``[DEFAULT]`` section
of :file:`/etc/heat/heat.conf`. The default for that directory is
:file:`/etc/heat/environment.d`. Its contents are combined in whatever
order the shell delivers them when the service starts up,
which is the time when these files are read.
If the :file:`my_env.yaml` file from the example above had been put in the
``environment_dir`` then the user's command line could be this::

    openstack stack create my_stack --parameter "some_parm=bla" -t my_tmpl.yaml

Global templates
----------------
A global template directory allows files to be pre-loaded in the global
environment. A global template is determined by your cloud operator.
An entry in the user template takes precedence over the global environment.
OpenStack includes a default global template, but your cloud operator
can add additional template entries.

The cloud operator can add new global templates by putting template
files in a configurable directory wherever the Orchestration engine runs.
The configuration variable is named ``template_dir`` and is found in the
``[DEFAULT]`` section of :file:`/etc/heat/heat.conf`. The default for
that directory is :file:`/etc/heat/templates`. Its contents are
combined in whatever order the shell delivers them when the service
starts up, which is the time when these files are read.
If the :file:`my_tmpl.yaml` file from the example below has been put in the
``template_dir``, other templates which we used to create stacks could
contain following way to include `my_tmpl.yaml` in it::

    resourceA:
      type: {get_file: "my_tmpl.yaml"}

Usage examples
~~~~~~~~~~~~~~

Define values for template arguments
------------------------------------
You can define values for the template arguments in the ``parameters`` section
of an environment file::

  parameters:
    KeyName: heat_key
    InstanceType: m1.micro
    ImageId: F18-x86_64-cfntools

Define defaults to parameters
--------------------------------
You can define default values for all template arguments in the
``parameter_defaults`` section of an environment file. These defaults are
passed into all template resources::

  parameter_defaults:
    KeyName: heat_key

Mapping resources
-----------------
You can map one resource to another in the ``resource_registry`` section
of an environment file. The resource you provide in this manner must have an
identifier, and must reference either another resource's ID or the URL of an
existing template file.

The following example maps a new ``OS::Networking::FloatingIP``
resource to an existing ``OS::Nova::FloatingIP`` resource::

  resource_registry:
    "OS::Networking::FloatingIP": "OS::Nova::FloatingIP"

You can use wildcards to map multiple resources, for example to map all
``OS::Neutron`` resources to ``OS::Network``::

  resource_registry:
    "OS::Network*": "OS::Neutron*"



Override a resource with a custom resource
------------------------------------------
To create or override a resource with a custom resource, create a template file
to define this resource, and provide the URL to the template file in the
environment file::

  resource_registry:
    "AWS::EC2::Instance": file:///path/to/my_instance.yaml

The supported URL schemes are ``file``, ``http`` and ``https``.

.. note::

  The template file extension must be ``.yaml`` or ``.template``, or it will
  not be treated as a custom template resource.

You can limit the usage of a custom resource to a specific resource of the
template::

   resource_registry:
     resources:
       my_db_server:
         "OS::DBInstance": file:///home/mine/all_my_cool_templates/db.yaml

Pause stack creation, update or deletion on a given resource
------------------------------------------------------------
If you want to debug your stack as it's being created, updated or deleted, or
if you want to run it in phases, you can set ``pre-create``, ``pre-update``,
``pre-delete``, ``post-create``, ``post-update`` and ``post-delete`` hooks in
the ``resources`` section of ``resource_registry``.

To set a hook, add either ``hooks: $hook_name`` (for example ``hooks:
pre-update``) to the resource's dictionary. You can also use a list (``hooks:
[pre-create, pre-update]``) to stop on several actions.

You can combine hooks with other ``resources`` properties such as provider
templates or type mapping::

  resource_registry:
    resources:
      my_server:
        "OS::DBInstance": file:///home/mine/all_my_cool_templates/db.yaml
        hooks: pre-create
      nested_stack:
        nested_resource:
          hooks: pre-update
        another_resource:
          hooks: [pre-create, pre-update]

When heat encounters a resource that has a hook, it pauses the resource
action until the hook clears. Any resources that depend on the paused action
wait as well. Non-dependent resources are created in parallel unless they have
their own hooks.

It is possible to perform a wild card match using an asterisk (`*`) in the
resource name. For example, the following entry pauses while creating
``app_server`` and ``database_server``, but not ``server`` or ``app_network``::

  resource_registry:
    resources:
      "*_server":
        hooks: pre-create

Clear hooks by signaling the resource with ``{unset_hook: $hook_name}`` (for
example ``{unset_hook: pre-update}``).

Retrieving events
-----------------

By default events are stored in the database and can be retrieved via the API.
Using the environment, you can register an endpoint which will receive events
produced by your stack, so that you don't have to poll Heat.

You can specify endpoints using the ``event_sinks`` property::

  event_sinks:
    - type: zaqar-queue
      target: myqueue
      ttl: 1200

Restrict update or replace of a given resource
-----------------------------------------------
If you want to restrict update or replace of a resource when your stack is
being updated, you can set ``restricted_actions`` in the ``resources``
section of ``resource_registry``.

To restrict update or replace, add ``restricted_actions: update`` or
``restricted_actions: replace`` to the resource dictionary. You can also
use ``[update, replace]`` to restrict both actions.

You can combine restricted actions with other ``resources`` properties such
as provider templates or type mapping or hooks::

  resource_registry:
    resources:
      my_server:
        "OS::DBInstance": file:///home/mine/all_my_cool_templates/db.yaml
        restricted_actions: replace
        hooks: pre-create
      nested_stack:
        nested_resource:
          restricted_actions: update
        another_resource:
          restricted_actions: [update, replace]

It is possible to perform a wild card match using an asterisk (`*`) in the
resource name. For example, the following entry restricts replace for
``app_server`` and ``database_server``, but not ``server`` or ``app_network``::

  resource_registry:
    resources:
      "*_server":
        restricted_actions: replace
