#
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2013 IBM Corp.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Utility methods for working with WSGI servers."""

import abc
import sys

from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils
from paste.deploy import loadwsgi
from routes import middleware
import webob.dec
import webob.exc

from heat.api.aws import exception as aws_exception
from heat.common import exception
from heat.common.i18n import _
from heat.common import serializers


LOG = logging.getLogger(__name__)
URL_LENGTH_LIMIT = 50000

json_size_opt = cfg.IntOpt('max_json_body_size',
                           default=1048576,
                           help=_('Maximum raw byte size of JSON request body.'
                                  ' Should be larger than max_template_size.'))
cfg.CONF.register_opt(json_size_opt)


def list_opts():
    yield None, [json_size_opt]


class Middleware(object):
    """Base WSGI middleware wrapper.

    These classes require an application to be initialized that will be called
    next. By default the middleware will simply call its wrapped app, or you
    can override __call__ to customize its behavior.
    """

    def __init__(self, application):
        self.application = application

    def process_request(self, req):
        """Called on each request.

        If this returns None, the next application down the stack will be
        executed. If it returns a response then that response will be returned
        and execution will stop here.
        """
        return None

    def process_response(self, response):
        """Do whatever you'd like to the response."""
        return response

    @webob.dec.wsgify
    def __call__(self, req):
        response = self.process_request(req)
        if response:
            return response
        response = req.get_response(self.application)
        return self.process_response(response)


class Debug(Middleware):
    """Helper class to get information about the request and response.

    Helper class that can be inserted into any WSGI application chain
    to get information about the request and response.
    """

    @webob.dec.wsgify
    def __call__(self, req):
        print(("*" * 40) + " REQUEST ENVIRON")
        for key, value in req.environ.items():
            print(key, "=", value)
        print('')
        resp = req.get_response(self.application)

        print(("*" * 40) + " RESPONSE HEADERS")
        for (key, value) in resp.headers.items():
            print(key, "=", value)
        print('')

        resp.app_iter = self.print_generator(resp.app_iter)

        return resp

    @staticmethod
    def print_generator(app_iter):
        """Prints the contents of a wrapper string iterator when iterated."""
        print(("*" * 40) + " BODY")
        for part in app_iter:
            sys.stdout.write(part)
            sys.stdout.flush()
            yield part
        print('')


def debug_filter(app, conf, **local_conf):
    return Debug(app)


class DefaultMethodController(object):
    """Controller that handles the OPTIONS request method.

    This controller handles the OPTIONS request method and any of the HTTP
    methods that are not explicitly implemented by the application.
    """
    def options(self, req, allowed_methods, *args, **kwargs):
        """Return a response that includes the 'Allow' header.

        Return a response that includes the 'Allow' header listing the methods
        that are implemented. A 204 status code is used for this response.
        """
        raise webob.exc.HTTPNoContent(headers=[('Allow', allowed_methods)])

    def reject(self, req, allowed_methods, *args, **kwargs):
        """Return a 405 method not allowed error.

        As a convenience, the 'Allow' header with the list of implemented
        methods is included in the response as well.
        """
        raise webob.exc.HTTPMethodNotAllowed(
            headers=[('Allow', allowed_methods)])


class Router(object):
    """WSGI middleware that maps incoming requests to WSGI apps."""

    def __init__(self, mapper):
        """Create a router for the given routes.Mapper.

        Each route in `mapper` must specify a 'controller', which is a
        WSGI app to call.  You'll probably want to specify an 'action' as
        well and have your controller be a wsgi.Controller, who will route
        the request to the action method.

        Examples:
          mapper = routes.Mapper()
          sc = ServerController()

          # Explicit mapping of one route to a controller+action
          mapper.connect(None, "/svrlist", controller=sc, action="list")

          # Actions are all implicitly defined
          mapper.resource("server", "servers", controller=sc)

          # Pointing to an arbitrary WSGI app.  You can specify the
          # {path_info:.*} parameter so the target app can be handed just that
          # section of the URL.
          mapper.connect(None, "/v1.0/{path_info:.*}", controller=BlogApp())
        """
        self.map = mapper
        self._router = middleware.RoutesMiddleware(self._dispatch, self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """Route the incoming request to a controller based on self.map.

        If no match, return a 404.
        """
        return self._router

    @staticmethod
    @webob.dec.wsgify
    def _dispatch(req):
        """Returns controller after matching the incoming request to a route.

        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ. Either returns 404 or the
        routed WSGI app's response.
        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return webob.exc.HTTPNotFound()
        app = match['controller']
        return app


class Request(webob.Request):
    """Add some OpenStack API-specific logic to the base webob.Request."""

    def best_match_content_type(self):
        """Determine the requested response content-type."""
        supported = ('application/json',)
        bm = self.accept.best_match(supported)
        return bm or 'application/json'

    def get_content_type(self, allowed_content_types):
        """Determine content type of the request body."""
        if "Content-Type" not in self.headers:
            raise exception.InvalidContentType(content_type=None)

        content_type = self.content_type

        if content_type not in allowed_content_types:
            raise exception.InvalidContentType(content_type=content_type)
        else:
            return content_type

    def best_match_language(self):
        """Determines best available locale from the Accept-Language header.

        :returns: the best language match or None if the 'Accept-Language'
                  header was not available in the request.
        """
        if not self.accept_language:
            return None
        all_languages = i18n.get_available_languages('heat')
        return self.accept_language.best_match(all_languages)


def is_json_content_type(request):
    if request.method == 'GET':
        try:
            aws_content_type = request.params.get("ContentType")
        except Exception:
            aws_content_type = None
        # respect aws_content_type when both available
        content_type = aws_content_type or request.content_type
    else:
        content_type = request.content_type
    # bug #1887882
    # for back compatible for null or plain content type
    if not content_type or content_type.startswith('text/plain'):
        content_type = 'application/json'
    if (content_type in ('JSON', 'application/json')
            and request.body.startswith(b'{')):
        return True
    return False


class JSONRequestDeserializer(object):
    def has_body(self, request):
        """Returns whether a Webob.Request object will possess an entity body.

        :param request:  Webob.Request object
        """
        if (int(request.content_length or 0) > 0 and
                is_json_content_type(request)):
            return True

        return False

    def from_json(self, datastring):
        try:
            if len(datastring) > cfg.CONF.max_json_body_size:
                msg = _('JSON body size (%(len)s bytes) exceeds maximum '
                        'allowed size (%(limit)s bytes).'
                        ) % {'len': len(datastring),
                             'limit': cfg.CONF.max_json_body_size}
                raise exception.RequestLimitExceeded(message=msg)
            return jsonutils.loads(datastring)
        except ValueError as ex:
            raise webob.exc.HTTPBadRequest(str(ex))

    def default(self, request):
        if self.has_body(request):
            return {'body': self.from_json(request.body)}
        else:
            return {}


class Resource(object):
    """WSGI app that handles (de)serialization and controller dispatch.

    Reads routing information supplied by RoutesMiddleware and calls
    the requested action method upon its deserializer, controller,
    and serializer. Those three objects may implement any of the basic
    controller action methods (create, update, show, index, delete)
    along with any that may be specified in the api router. A 'default'
    method may also be implemented to be used in place of any
    non-implemented actions. Deserializer methods must accept a request
    argument and return a dictionary. Controller methods must accept a
    request argument. Additionally, they must also accept keyword
    arguments that represent the keys returned by the Deserializer. They
    may raise a webob.exc exception or return a dict, which will be
    serialized by requested content type.
    """
    def __init__(self, controller, deserializer, serializer=None):
        """Initialisation of the WSGI app.

        :param controller: object that implement methods created by routes lib
        :param deserializer: object that supports webob request deserialization
                             through controller-like actions
        :param serializer: object that supports webob response serialization
                           through controller-like actions
        """
        self.controller = controller
        self.deserializer = deserializer
        self.serializer = serializer

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        # From reading the boto code, and observation of real AWS api responses
        # it seems that the AWS api ignores the content-type in the html header
        # Instead it looks at a "ContentType" GET query parameter
        # This doesn't seem to be documented in the AWS cfn API spec, but it
        # would appear that the default response serialization is XML, as
        # described in the API docs, but passing a query parameter of
        # ContentType=JSON results in a JSON serialized response...
        content_type = request.params.get("ContentType")

        LOG.info("Processing request: %(method)s %(path)s",
                 {'method': request.method, 'path': request.path})

        try:
            deserialized_request = self.dispatch(self.deserializer,
                                                 action, request)
            action_args.update(deserialized_request)

            LOG.debug(('Calling %(controller)s.%(action)s'),
                      {'controller': type(self.controller).__name__,
                       'action': action})

            action_result = self.dispatch(self.controller, action,
                                          request, **action_args)
        except TypeError as err:
            LOG.error('Exception handling resource: %s', err)
            msg = _('The server could not comply with the request since '
                    'it is either malformed or otherwise incorrect.')
            err = webob.exc.HTTPBadRequest(msg)
            http_exc = translate_exception(err, request.best_match_language())
            # NOTE(luisg): We disguise HTTP exceptions, otherwise they will be
            # treated by wsgi as responses ready to be sent back and they
            # won't make it into the pipeline app that serializes errors
            raise exception.HTTPExceptionDisguise(http_exc)
        except webob.exc.HTTPException as err:
            if isinstance(err, aws_exception.HeatAPIException):
                # The AWS compatible API's don't use faultwrap, so
                # we want to detect the HeatAPIException subclasses
                # and raise rather than wrapping in HTTPExceptionDisguise
                raise
            if not isinstance(err, webob.exc.HTTPError):
                # Some HTTPException are actually not errors, they are
                # responses ready to be sent back to the users, so we don't
                # error log, disguise or translate those
                raise
            if isinstance(err, webob.exc.HTTPServerError):
                LOG.error(
                    "Returning %(code)s to user: %(explanation)s",
                    {'code': err.code, 'explanation': err.explanation})
            http_exc = translate_exception(err, request.best_match_language())
            raise exception.HTTPExceptionDisguise(http_exc)
        except exception.HeatException as err:
            raise translate_exception(err, request.best_match_language())
        except Exception as err:
            log_exception(err, sys.exc_info())
            raise translate_exception(err, request.best_match_language())
        # Here we support either passing in a serializer or detecting it
        # based on the content type.
        try:
            serializer = self.serializer
            if serializer is None:
                if content_type == "JSON":
                    serializer = serializers.JSONResponseSerializer()
                else:
                    serializer = serializers.XMLResponseSerializer()

            response = webob.Response(request=request)
            self.dispatch(serializer, action, response, action_result)
            return response

        # return unserializable result (typically an exception)
        except Exception:
            # Here we should get API exceptions derived from HeatAPIException
            # these implement get_unserialized_body(), which allow us to get
            # a dict containing the unserialized error response.
            # We only need to serialize for JSON content_type, as the
            # exception body is pre-serialized to the default XML in the
            # HeatAPIException constructor
            # If we get something else here (e.g a webob.exc exception),
            # this will fail, and we just return it without serializing,
            # which will not conform to the expected AWS error response format
            if content_type == "JSON":
                try:
                    err_body = action_result.get_unserialized_body()
                    serializer.default(action_result, err_body)
                except Exception:
                    LOG.warning("Unable to serialize exception response")

            return action_result

    def dispatch(self, obj, action, *args, **kwargs):
        """Find action-specific method on self and call it."""
        try:
            method = getattr(obj, action)
        except AttributeError:
            method = getattr(obj, 'default')
        return method(*args, **kwargs)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        try:
            args = request_environment['wsgiorg.routing_args'][1].copy()
        except Exception:
            return {}

        try:
            del args['controller']
        except KeyError:
            pass

        try:
            del args['format']
        except KeyError:
            pass

        return args


def log_exception(err, exc_info):
    args = {'exc_info': exc_info} if cfg.CONF.debug else {}
    LOG.error("Unexpected error occurred serving API: %s", err,
              **args)


def translate_exception(exc, locale):
    """Translates all translatable elements of the given exception."""
    if isinstance(exc, exception.HeatException):
        exc.message = i18n.translate(exc.message, locale)
    else:
        exc.message = i18n.translate(str(exc), locale)

    if isinstance(exc, webob.exc.HTTPError):
        exc.explanation = i18n.translate(exc.explanation, locale)
        exc.detail = i18n.translate(getattr(exc, 'detail', ''), locale)
    return exc


class BasePasteFactory(object, metaclass=abc.ABCMeta):
    """A base class for paste app and filter factories.

    Sub-classes must override the KEY class attribute and provide
    a __call__ method.
    """

    KEY = None

    def __init__(self, conf):
        self.conf = conf

    @abc.abstractmethod
    def __call__(self, global_conf, **local_conf):
        return

    def _import_factory(self, local_conf):
        """Import an app/filter class.

        Lookup the KEY from the PasteDeploy local conf and import the
        class named there. This class can then be used as an app or
        filter factory.

        Note we support the <module>:<class> format.

        Note also that if you do e.g.

          key =
              value

        then ConfigParser returns a value with a leading newline, so
        we strip() the value before using it.
        """
        class_name = local_conf[self.KEY].replace(':', '.').strip()
        return importutils.import_class(class_name)


class AppFactory(BasePasteFactory):
    """A Generic paste.deploy app factory.

    This requires heat.app_factory to be set to a callable which returns a
    WSGI app when invoked. The format of the name is <module>:<callable> e.g.

      [app:apiv1app]
      paste.app_factory = heat.common.wsgi:app_factory
      heat.app_factory = heat.api.cfn.v1:API

    The WSGI app constructor must accept a ConfigOpts object and a local config
    dict as its two arguments.
    """

    KEY = 'heat.app_factory'

    def __call__(self, global_conf, **local_conf):
        """The actual paste.app_factory protocol method."""
        factory = self._import_factory(local_conf)
        return factory(self.conf, **local_conf)


class FilterFactory(AppFactory):
    """A Generic paste.deploy filter factory.

    This requires heat.filter_factory to be set to a callable which returns a
    WSGI filter when invoked. The format is <module>:<callable> e.g.

      [filter:cache]
      paste.filter_factory = heat.common.wsgi:filter_factory
      heat.filter_factory = heat.api.middleware.cache:CacheFilter

    The WSGI filter constructor must accept a WSGI app, a ConfigOpts object and
    a local config dict as its three arguments.
    """

    KEY = 'heat.filter_factory'

    def __call__(self, global_conf, **local_conf):
        """The actual paste.filter_factory protocol method."""
        factory = self._import_factory(local_conf)

        def filter(app):
            return factory(app, self.conf, **local_conf)

        return filter


def setup_paste_factories(conf):
    """Set up the generic paste app and filter factories.

    Set things up so that:

      paste.app_factory = heat.common.wsgi:app_factory

    and

      paste.filter_factory = heat.common.wsgi:filter_factory

    work correctly while loading PasteDeploy configuration.

    The app factories are constructed at runtime to allow us to pass a
    ConfigOpts object to the WSGI classes.

    :param conf: a ConfigOpts object
    """
    global app_factory, filter_factory
    app_factory = AppFactory(conf)
    filter_factory = FilterFactory(conf)


def teardown_paste_factories():
    """Reverse the effect of setup_paste_factories()."""
    global app_factory, filter_factory
    del app_factory
    del filter_factory


def paste_deploy_app(paste_config_file, app_name, conf):
    """Load a WSGI app from a PasteDeploy configuration.

    Use deploy.loadapp() to load the app from the PasteDeploy configuration,
    ensuring that the supplied ConfigOpts object is passed to the app and
    filter constructors.

    :param paste_config_file: a PasteDeploy config file
    :param app_name: the name of the app/pipeline to load from the file
    :param conf: a ConfigOpts object to supply to the app and its filters
    :returns: the WSGI app
    """
    setup_paste_factories(conf)
    try:
        return loadwsgi.loadapp("config:%s" % paste_config_file, name=app_name)
    finally:
        teardown_paste_factories()
