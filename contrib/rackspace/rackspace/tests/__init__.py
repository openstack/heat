import six


if six.PY3:
    from mox3 import mox
    import sys
    sys.modules['mox'] = mox
