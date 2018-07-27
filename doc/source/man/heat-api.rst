========
heat-api
========

.. program:: heat-api

SYNOPSIS
========
``heat-api [options]``

DESCRIPTION
===========
heat-api provides an external REST API to the heat project.

INVENTORY
=========
heat-api is a service that exposes an external REST based api to the
heat-engine service. The communication between the heat-api and
heat-engine uses message queue based RPC.

OPTIONS
=======
.. cmdoption:: --config-file

  Path to a config file to use. Multiple config files can be specified, with
  values in later files taking precedence.


.. cmdoption:: --config-dir

  Path to a config directory to pull .conf files from. This file set is
  sorted, so as to provide a predictable parse order if individual options are
  over-ridden. The set is parsed after the file(s), if any, specified via
  --config-file, hence over-ridden options in the directory take precedence.

.. cmdoption:: --version

  Show program's version number and exit. The output could be empty if
  the distribution didn't specify any version information.

FILES
========

* /etc/heat/heat.conf
