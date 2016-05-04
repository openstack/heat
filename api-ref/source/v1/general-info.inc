.. -*- rst -*-

=======================
General API information
=======================

Authenticated calls that target a known URI but that use an HTTP
method that the implementation does not support return a ``405
Method Not Allowed`` error code. In addition, the HTTP ``OPTIONS``
method is supported for each known URI. In both cases, the
``Allow`` response header indicates the HTTP methods that are
supported for the resource.

