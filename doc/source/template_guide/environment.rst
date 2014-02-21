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
template. It provides a way to override the default resource
implementation and the parameters passed to Heat.

------
Format
------

It is a yaml text file with two main sections "resource_registry" and
"parameters".

------------------
Command line usage
------------------
::

   heat stack-create my_stack -e my_env.yaml -P "some_parm=bla" -f my_tmpl.yaml

If you do not like the option "-e my_env.yaml", you can put file
my_env.yaml in "/etc/heat/environment.d/" and restart heat engine.
Then, you can use the heat client as in the example below:

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


2) Deal with the mapping of Quantum to Neutron
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "OS::Quantum*": "OS::Neutron*"

So all existing resources which can be matched with "OS::Neutron*"
will be mapped to "OS::Quantum*" accordingly.

3) Override a resource type with a custom template resource
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "AWS::EC2::Instance": file:///home/mine/my_instance_with_better_defaults.yaml

Please note that the template resource URL here must end with ".yaml"
or ".template", or it will not be treated as a custom template
resource.

4) Always map resource type X to Y
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    "OS::Networking::FloatingIP": "OS::Nova::FloatingIP"


5) Use default resources except one for a particular resource in the template
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
::

  resource_registry:
    resources:
      my_db_server:
        "OS::DBInstance": file:///home/mine/all_my_cool_templates/db.yaml
