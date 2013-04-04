==========
heat-watch
==========

.. program:: heat-watch


SYNOPSIS
========

``heat-watch [OPTIONS] COMMAND [COMMAND_OPTIONS]``


DESCRIPTION
===========
heat-watch is a command-line utility for heat-api-cloudwatch.
It allows manipulation of the watch alarms and metric data via the heat
cloudwatch API, so this service must be running and accessibe on the host
specified in your boto config (cloudwatch_region_endpoint)


CONFIGURATION
=============

heat-watch uses the boto client library, and expects some configuration files
to exist in your environment, see our wiki for an example configuration file:

https://wiki.openstack.org/wiki/Heat/Using-Boto


COMMANDS
========

``describe``

  Provide detailed information about the specified watch rule, or if no arguments are given all watch rules

``set-state``

  Temporarily set the state of a watch rule

``metric-list``

  List data-points for a specified metric

``metric-put-data``

  Publish data-point for specified  metric

  Note the metric must be associated with a CloudWatch Alarm (specified in a heat stack template), publishing arbitrary metric data is not supported.

``help``

  Provide help/usage information on each command


OPTIONS
=======

.. cmdoption:: --version

  show program version number and exit

.. cmdoption:: -h, --help

  show this help message and exit

.. cmdoption:: -v, --verbose

  Print more verbose output

.. cmdoption:: -d, --debug

  Print debug output

.. cmdoption:: -p, --port

  Specify port the heat CW API host listens on. Default: 8003


EXAMPLES
========

  heat-watch describe

  heat-watch metric-list

  heat-watch metric-put-data HttpFailureAlarm system/linux ServiceFailure Count 1

  heat-watch set-state HttpFailureAlarm ALARM


BUGS
====
Heat bugs are managed through Launchpad <https://launchpad.net/heat>
