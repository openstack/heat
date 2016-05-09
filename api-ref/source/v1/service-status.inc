.. -*- rst -*-

==============
Manage service
==============




Show orchestration engine status
================================

.. rest_method::  GET /v1/{tenant_id}/services

Enables administrative users to view details for all orchestration engines.

Orchestration engine details include ``engine_id``, topic name,
last updated time, health status, and host name.

Troubleshooting

- A ``503`` error code indicates that the heat engines are not
  operational. Run the heat-manage service list command or contact
  your cloud provider to determine why the heat engines are not
  operational.


Normal response codes: 200
Error response codes:403,503,


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - status: status
   - binary: binary
   - report_interval: report_interval
   - created_at: created_at
   - hostname: hostname
   - updated_at: updated_at
   - topic: topic
   - services: services
   - deleted_at: deleted_at
   - id: id



Response Example
----------------

.. literalinclude:: samples/services-list-response.json
   :language: javascript





