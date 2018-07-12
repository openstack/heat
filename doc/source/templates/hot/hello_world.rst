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

========================
Hello World HOT Template
========================

https://git.openstack.org/cgit/openstack/heat-templates/tree/hot/hello_world.yaml

Description
-----------

Hello world HOT template that just defines a single compute instance. Contains
just base features to verify base HOT support.


Parameters
----------

*key_name* :mod:`(required)`
    *type*
        *string*
    *description*
        Name of an existing key pair to use for the instance
*flavor* :mod:`(optional)`
    *type*
        *string*
    *description*
        Flavor for the instance to be created
*image* :mod:`(required)`
    *type*
        *string*
    *description*
        Image *ID* or image name to use for the instance
*admin_pass* :mod:`(required)`
    *type*
        *string*
    *description*
        The admin password for the instance
*db_port* :mod:`(optional)`
    *type*
        *number*
    *description*
        The database port number
