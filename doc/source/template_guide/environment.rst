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

The environment is used to affect the runtime behaviour of the
template. It provides a way to override the resource
implementations and provide a mechanism to place parameters
that the service needs.

To fully understand the runtime behavior you also have to consider
what plug-ins the cloud operator has installed.

------
Format
------

It is a yaml text file with three main sections "resource_registry",
"parameters" and "parameter_defaults".

------------------
Command line usage
------------------
::

   heat stack-create my_stack -e my_env.yaml -P "some_parm=bla" -f my_tmpl.yaml

---------------------------------
Global and effective environments
---------------------------------

The environment used for a stack is the combination of (1) the
environment given by the user with the template for the stack and (2)
a global environment that is determined by the cloud operator.
Combination is asymmetric: an entry in the user environment takes
precedence over the global environment.  The OpenStack software
includes a default global environment, which supplies some resource
types that are included in the standard documentation.  The cloud
operator can add additional environment entries.

The cloud operator can add to the global environment
by putting environment files in a configurable directory wherever
the heat engine runs.  The configuration variable is named
"environment_dir" is found in the "[DEFAULT]" section
of "/etc/heat/heat.conf".  The default for that directory is
"/etc/heat/environment.d".  Its contents are combined in whatever
order the shell delivers them when the service starts up,
which is the time when these files are read.

If the "my_env.yaml" file from the example above had been put in the
"environment_dir" then the user's command line could be this:

::

   heat stack-create my_stack -P "some_parm=bla" -f my_tmpl.yaml

--------------
Usage examples
--------------

1) Pass parameters into Heat
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  parameters:
    KeyName: heat_key
    InstanceType: m1.micro
    ImageId: F18-x86_64-cfntools

2) Define defaults to parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This is especially useful when you have many template resources and
you want the same value in each. Note: these defaults will get passed
down into all template resources.
::

  parameter_defaults:
    KeyName: heat_key


3) Deal with the mapping of Quantum to Neutron
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "OS::Quantum*": "OS::Neutron*"

So all existing resources which can be matched with "OS::Neutron*"
will be mapped to "OS::Quantum*" accordingly.

4) Override a resource type with a custom template resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "AWS::EC2::Instance": file:///home/mine/my_instance_with_better_defaults.yaml

Please note that the template resource URL here must end with ".yaml"
or ".template", or it will not be treated as a custom template
resource. The supported URL types are "http, https and file".

5) Always map resource type X to Y
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "OS::Networking::FloatingIP": "OS::Nova::FloatingIP"


6) Use default resources except one for a particular resource in the template
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    resources:
      my_db_server:
        "OS::DBInstance": file:///home/mine/all_my_cool_templates/db.yaml


7) Pause stack creation/update on a given resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
If you want to debug your stack as it's being created or updated or if you want
to run it in phases you can set `pre-create` and `pre-update` hooks in the
`resources` section of `resource_registry`.

To set a hook, add either `hooks: pre-create` or `hooks: pre-update` to the
resource's dictionary. You can also use the `[pre-create, pre-update]` to stop
on both actions.

Hooks can be combined with other `resources` properties (e.g. provider
templates or type mapping).

Example:

::

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

When Heat encounters a resource that has a hook, it will pause the resource
action until the hook is cleared. Any resources that depend on it will wait as
well. Any resources that don't will be created in parallel (unless they have
hooks, too).

It is also possible to do a partial match by putting an asterisk (`*`) in the
name.

This example:

::

  resource_registry:
    resources:
      "*_server":
        hooks: pre-create

will pause while creating `app_server` and `database_server` but not `server`
or `app_network`.

Hook is cleared by signalling the resource with `{unset_hook: pre-create}` (or
`pre-update`).
