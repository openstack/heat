========
heat-cfn
========

.. program:: heat-cfn

SYNOPSIS
========

``heat-cfn [OPTIONS] COMMAND [COMMAND_OPTIONS]``

DESCRIPTION
===========
heat-cfn is a command-line utility for heat. It is simply an
interface for adding, modifying, and retrieving information about the stacks
belonging to a user.  It is a convenience application that talks to the heat
CloudFormation API compatable server.


CONFIGURATION
=============

heat-cfn uses keystone authentication, and expects some variables to be
set in your environment, without these heat will not be able to establish
an authenticated connection with the heat API server.

Example:

export ADMIN_TOKEN=<keystone admin token>

export OS_USERNAME=admin

export OS_PASSWORD=verybadpass

export OS_TENANT_NAME=admin

export OS_AUTH_URL=http://127.0.0.1:5000/v2.0/

export OS_AUTH_STRATEGY=keystone



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

.. cmdoption:: -S, --auth_strategy

  Authentication strategy

.. cmdoption:: -A, --auth_token

  Authentication token to use to identify the client to the heat server

.. cmdoption:: -N, --auth_url

  Authentication URL for keystone authentication

.. cmdoption:: -d, --debug

  Enable verbose debug level output

.. cmdoption:: -H, --host

  Specify the hostname running the heat API service

.. cmdoption:: -k, --insecure

  Use plain HTTP instead of HTTPS

.. cmdoption:: -P, --parameters

  Stack input parameters

.. cmdoption:: -K, --password

  Password used to acquire an authentication token

.. cmdoption:: -p, --port

  Specify the port to connect to for the heat API service

.. cmdoption:: -R, --region

  Region name. When using keystone authentication "version 2.0 or later this identifies the region

.. cmdoption:: -f, --template-file

  Path to file containing the stack template

.. cmdoption:: -u, --template-url

  URL to stack template

.. cmdoption:: -T, --tenant

  Tenant name used for Keystone authentication

.. cmdoption:: -t, --timeout

  Stack creation timeout (default is 60 minutes)

.. cmdoption:: -U, --url

  URL of heat service

.. cmdoption:: -I, --username

  User name used to acquire an authentication token

.. cmdoption:: -v, --verbose

  Enable verbose output

.. cmdoption:: -y, --yes

  Do not prompt for confirmation, assume yes


EXAMPLES
========
  heat-cfn -d create wordpress --template-
  file=templates/WordPress_Single_Instance.template
  --parameters="InstanceType=m1.xlarge;DBUsername=${USER};DBPassword=verybadpass;KeyName=${USER}_key"

  heat-cfn list

  heat-cfn describe wordpress

  heat-cfn resource-list wordpress

  heat-cfn resource-list-details wordpress

  heat-cfn resource-list-details wordpress WikiDatabase

  heat-cfn resource wordpress WikiDatabase

  heat-cfn event-list

  heat-cfn delete wordpress

BUGS
====
Heat bugs are managed through Launchpad <https://launchpad.net/heat>