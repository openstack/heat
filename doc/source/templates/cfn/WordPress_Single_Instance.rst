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

======================================
AWS Wordpress Single Instance Template
======================================

https://git.openstack.org/cgit/openstack/heat-templates/tree/cfn/F18/WordPress_Single_Instance.template

Description
-----------

AWS CloudFormation Sample Template WordPress_Single_Instance: WordPress is web
software you can use to create a beautiful website or blog. This template
installs a single-instance WordPress deployment using a local MySQL database to
store the data.


Parameters
----------

*KeyName* :mod:`(required)`
    *type*
        *string*
    *description*
        Name of an existing EC2 KeyPair to enable SSH access to the instance
*InstanceType* :mod:`(optional)`
    *type*
        *string*
    *description*
        The EC2 instance type
*DBName* :mod:`(optional)`
    *type*
        *string*
    *description*
        The WordPress database name
*DBUsernameName* :mod:`(optional)`
    *type*
        *string*
    *description*
        The WordPress database admin account username
*DBPassword* :mod:`(optional)`
    *type*
        *string*
    *description*
        The WordPress database admin account password
*DBRootPassword* :mod:`(optional)`
    *type*
        *string*
    *description*
        Root password for MySQL
*LinuxDistribution* :mod:`(optional)`
    *type*
        *string*
    *description*
        Linux distribution of choice
