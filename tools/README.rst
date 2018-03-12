Files in this directory are general developer tools or examples of how
to do certain activities.

If you're running on Fedora, see the instructions at https://docs.openstack.org/heat/latest/getting_started/on_fedora.html

Tools
=====

heat-db-drop
  This script drops the heat database from mysql in the case of developer
  data corruption or erasing heat.

cfn-json2yaml
  (bulk) convert AWS CloudFormation templates written in JSON
  to HeatTemplateFormatVersion YAML templates

Package lists
=============

Lists of Linux packages to install in order to successfully run heat's
unit test suit on a clean new Linux distribution.

test-requires-deb
  list of DEB packages as of Ubuntu 14.04 Trusty

test-requires-rpm
  list of RPM packages as of Fedora 20

Review dashboards
=================

Generate gerrit review URL for heat. This can pop up some patches
that might requires reviews. You can generate it with following
command under `gerrit-dash-creator` repo
( https://git.openstack.org/cgit/openstack/gerrit-dash-creator )

    $ ./gerrit-dash-creator heat.dash

The sample of heat.dash can be found under ./dashboards/

Get the output URL and add it to your gerrit menu
(at ``https://review.openstack.org/#/settings/preferences``).
