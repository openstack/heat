.. -*- rst -*-

============
Stack events
============




Show event details
==================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events/{event_id}

Shows details for an event.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - event_id: event_id
   - stack_id: stack_id




Response Example
----------------

.. literalinclude:: samples/event-show-response.json
   :language: javascript




Find stack events
=================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/events

Finds the canonical URL for the event list of a stack.

Error response codes:302,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id






List stack events
=================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/events

Lists events for a stack.


Normal response codes: 200
Error response codes:404,500,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - resource_action: resource_action
   - resource_status: resource_status
   - resource_name: resource_name
   - resource_type: resource_type
   - limit: limit
   - marker: marker
   - sort_keys: sort_keys
   - sort_dir: sort_dir




Response Example
----------------

.. literalinclude:: samples/events-list-response.json
   :language: javascript








List resource events
====================

.. rest_method::  GET /v1/{tenant_id}/stacks/{stack_name}/{stack_id}/resources/{resource_name}/events

Lists events for a stack resource.


Normal response codes: 200
Error response codes:404,401,400,


Request
-------

.. rest_parameters:: parameters.yaml

   - resource_name: resource_name
   - stack_name: stack_name
   - tenant_id: tenant_id
   - stack_id: stack_id
   - resource_action: resource_action
   - resource_status: resource_status
   - resource_type: resource_type
   - limit: limit
   - marker: marker
   - sort_keys: sort_keys
   - sort_dir: sort_dir




Response Example
----------------

.. literalinclude:: samples/events-list-response.json
   :language: javascript






