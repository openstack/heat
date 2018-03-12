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

Installing OpenStack and Heat on RHEL/Fedora/CentOS
---------------------------------------------------

Go to the `OpenStack Documentation
<https://docs.openstack.org/#install-guides>`_ for the latest version of the
Installation Guide for Red Hat Enterprise Linux, CentOS and Fedora which
includes a chapter on installing the Orchestration module (Heat).

There are instructions for `installing the RDO OpenStack
<https://www.rdoproject.org/install/tripleo/>`_ on Fedora and CentOS.

If installing with packstack, you can install heat by specifying
``--os-heat-install=y`` in your packstack invocation, or setting
``CONFIG_HEAT_INSTALL=y`` in your answers file.

If installing with `TripleO
<https://www.rdoproject.org/tripleo>`_ Heat will be installed by
default.
