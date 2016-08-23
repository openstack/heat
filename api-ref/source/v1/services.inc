.. -*- rst -*-

==============
Manage service
==============

Show orchestration engine status
================================

.. rest_method::  GET /v1/{tenant_id}/services

Enables administrative users to view details for all orchestration engines.

Orchestration engine details include engine id, binary, topic name, host, 
report interval, last updated time, health status, and host name.

Response Codes
--------------

.. rest_status_code:: success status.yaml

   - 200

.. rest_status_code:: error status.yaml

   - 403
   - 503

Troubleshooting

- A ``503`` error code indicates that the heat engines are not operational.
  Run the ``heat-manage service list`` command or contact your cloud provider
  to determine why the heat engines are not operational.

Request Parameters
------------------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - X-Openstack-Request-Id: request_id
   - services: services
   - binary: binary
   - created_at: created_at
   - deleted_at: deleted_at
   - engine_id: engine_id
   - host: host
   - hostname: hostname
   - id: engine_record_id
   - report_interval: report_interval
   - status: engine_status
   - topic: topic
   - updated_at: updated_at

Response Example
----------------

.. literalinclude:: samples/services-list-response.json
   :language: javascript
