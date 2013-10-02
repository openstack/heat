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

Getting Started With Heat on Fedora
===================================

..
  This file is a ReStructuredText document, but can be converted to a script
  using the accompanying rst2script.sed script. Any blocks that are indented by
  4 spaces (including comment blocks) will appear in the script. To document
  code that should not appear in the script, use an indent of less than 4
  spaces. (Using a Quoted instead of Indented Literal block also works.)
  To include code in the script that should not appear in the output, make it
  a comment block.

Installing OpenStack and Heat on Fedora
---------------------------------------

Either the Grizzly, or Havana release of OpenStack is required.  If you are using Grizzly, you should use the stable/grizzly branch of Heat.

Instructions for installing the RDO OpenStack distribution on Fedora are available at ``http://openstack.redhat.com/Quickstart``

Instructions for installing Heat on RDO are also available at ``http://openstack.redhat.com/Docs``

Alternatively, if you require a development environment not a package-based install, the suggested method is devstack, see instructions at :doc:`on_devstack`

Example Templates
-----------------
Check out the example templates at ``https://github.com/openstack/heat-templates``.  Here you can view example templates which will work with several Fedora versions.
