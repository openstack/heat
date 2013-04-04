=========
heat-boto
=========

.. program:: heat-boto

SYNOPSIS
========

``heat-boto [OPTIONS] COMMAND [COMMAND_OPTIONS]``

DESCRIPTION
===========
heat-boto is a command-line utility for heat. It is a variant of the heat-cfn
tool which uses the boto client library (instead of the heat CFN client
library)

The tool provides an interface for adding, modifying, and retrieving
information about the stacks belonging to a user.  It is a convenience
application that talks to the heat CloudFormation API.


CONFIGURATION
=============

heat-watch uses the boto client library, and expects some configuration files
to exist in your environment, see our wiki for an example configuration file:

https://wiki.openstack.org/wiki/Heat/Using-Boto


COMMANDS
========

``create``

  Create stack as defined in template file

``delete``

  Delete specified stack

``describe``

  Provide detailed information about the specified stack, or if no arguments are given all stacks

``estimate-template-cost``

  Currently not implemented

``event-list``

  List events related to specified stacks, or if no arguments are given all stacks

``gettemplate``

  Get the template for a running stack

``help``

  Provide help/usage information

``list``

  List summary information for all stacks

``resource``

  List information about a specific resource

``resource-list``

  List all resources for a specified stack

``resource-list-details``

  List details of all resources for a specified stack or physical resource ID, optionally filtered by a logical resource ID

``update``

  Update a running stack with a modified template or template parameters - currently not implemented

``validate``

  Validate a template file syntax


OPTIONS
=======

Note some options are marked as having no effect due to the common implementation with heat-cfn.
These are options which work with heat-cfn, but not with heat-boto, in most cases the information
should be specified via your boto configuration file instead.

.. cmdoption:: -S, --auth_strategy

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -A, --auth_token

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -N, --auth_url

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -d, --debug

  Enable verbose debug level output

.. cmdoption:: -H, --host

  Note, this option does not work for heat-boto due to limitations of the boto library
  You should specify cfn_region_endpoint option in your boto config.

.. cmdoption:: -k, --insecure

  This option has no effect, is_secure should be specified in your boto config

.. cmdoption:: -P, --parameters

  Stack input parameters

.. cmdoption:: -K, --password

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -p, --port

  Specify the port to connect to for the heat API service

.. cmdoption:: -R, --region

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -f, --template-file

  Path to file containing the stack template

.. cmdoption:: -u, --template-url

  URL to stack template

.. cmdoption:: -T, --tenant

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -t, --timeout

  Stack creation timeout (default is 60 minutes)

.. cmdoption:: -U, --url

  This option has no effect, cfn_region_endpoint should be specified in your boto config

.. cmdoption:: -I, --username

  This option has no effect, credentials should be specified in your boto config

.. cmdoption:: -v, --verbose

  Enable verbose output

.. cmdoption:: -y, --yes

  Do not prompt for confirmation, assume yes


EXAMPLES
========
  heat-boto -d create wordpress \\
      --template-file=templates/WordPress_Single_Instance.template\\
      --parameters="InstanceType=m1.xlarge;DBUsername=${USER};\\
      DBPassword=verybadpass;KeyName=${USER}_key"

  heat-boto list

  heat-boto describe wordpress

  heat-boto resource-list wordpress

  heat-boto resource-list-details wordpress

  heat-boto resource-list-details wordpress WikiDatabase

  heat-boto resource wordpress WikiDatabase

  heat-boto event-list

  heat-boto delete wordpress

BUGS
====
Heat bugs are managed through Launchpad <https://launchpad.net/heat>
