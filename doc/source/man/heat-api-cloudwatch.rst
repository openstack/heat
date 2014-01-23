===================
heat-api-cloudwatch
===================

.. program:: heat-api-cloudwatch

SYNOPSIS
========
``heat-api-cloudwatch [options]``

DESCRIPTION
===========
heat-api-cloudwatch is a CloudWatch-like API service to the heat project.

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

FILES
========

* /etc/heat/heat.conf
