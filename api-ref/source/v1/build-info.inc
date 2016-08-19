.. -*- rst -*-

==========
Build info
==========

Show build information
======================

.. rest_method::  GET /v1/{tenant_id}/build_info

Shows build information for an Orchestration deployment.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 401

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - api: build_api
   - engine: build_engine

Response Example
----------------

.. literalinclude:: samples/build-info-response.json
   :language: javascript
