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

Contributed Heat Resource Types
===============================

.. rubric:: These resources are not enabled by default.

.. contribrespages:: OS::


Rackspace Cloud Resource Types
------------------------------

.. rubric:: These resources are not enabled by default.

The resources in this module are for using Heat with the Rackspace
Cloud. These resources either allow using Rackspace services that don't
have equivalent services in OpenStack or account for differences between
a generic Openstack deployment and the Rackspace Cloud.

Rackspace resources depend on the dev branch of
`pyrax <https://github.com/rackspace/pyrax/tree/dev>`_ to work
properly. More information about them can be found in the
`RACKSPACE_README
<https://github.com/openstack/heat/blob/master/contrib/rackspace/README.md>`_.


.. contribrespages:: Rackspace::


DockerInc Resource
------------------

.. rubric:: This resource is not enabled by default.

This plugin enables the use of  Docker containers in a Heat template and
requires the `docker-py <https://pypi.python.org/pypi/docker-py>`_
package. You can find more information in the `DOCKER_README
<https://github.com/openstack/heat/blob/master/contrib/heat_docker/README.md>`_.

.. contribrespages:: DockerInc::
