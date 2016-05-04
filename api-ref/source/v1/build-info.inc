.. -*- rst -*-

==========
Build info
==========




Show build information
======================

.. rest_method::  GET /v1/{tenant_id}/build_info

Shows build information for an Orchestration deployment.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id




Response Example
----------------

.. literalinclude:: samples/build-info-response.json
   :language: javascript



