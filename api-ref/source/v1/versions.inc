.. -*- rst -*-

============
API versions
============

List versions
=============

.. rest_method::  GET /

Lists all Orchestration API versions.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 300

Request Parameters
------------------

This operation does not accept a request body.

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - versions: versions

Response Example
----------------

.. literalinclude:: samples/versions-list-response.json
   :language: javascript
