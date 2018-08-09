#!/usr/bin/env python
from __future__ import print_function

import re
import os
import site
import sys
import json
from importlib import import_module
from time import time
from uuid import uuid4

__version__ = "1.4.3"

methods_order = ["GET", "POST", "PUT", "PATCH", "DELETE", "COPY", "HEAD",
                 "OPTIONS", "LINK", "UNLINK", "PURGE"]

var_re = re.compile(r"(?P<var><([a-zA-Z0-9_]+:)?(?P<var_name>[a-zA-Z0-9_]+)>)")

venv_warning = ("WARNING: Attempting to work in a virtualenv. If you encounter "
                "problems, please install flask2postman inside the virtualenv.")


PY2 = sys.version_info[0] < 3
if PY2:
    maxint = sys.maxint
else:
    maxint = sys.maxsize


def get_time():
    return int(round(time() * 1000))


class Collection:

    def __init__(self, name):
        self._folders = []
        self._requests = []

        self.id = str(uuid4())
        self.name = name
        self.timestamp = get_time()

    def reorder_requests(self):
        def _get_key(request):
            return str(methods_order.index(request.method)) + request.name
        self._requests = sorted(self._requests, key=_get_key)

    def add_folder(self, folder):
        folder.collection_id = self.id
        self._folders.append(folder)

    def find_folder(self, name):
        for folder in self._folders:
            if folder.name == name:
                return folder

    def get_folder(self, name):
        folder = self.find_folder(name)
        if not folder:
            folder = Folder(name)
            self.add_folder(folder)
        return folder

    def add_request(self, request):
        request.collection_id = self.id
        self._requests.append(request)
        self.reorder_requests()

    @property
    def order(self):
        return [request.id for request in self._requests if not request._folder]

    @property
    def requests(self):
        return [request.to_dict() for request in self._requests]

    @property
    def folders(self):
        return [folder.to_dict() for folder in self._folders]

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        d.update(requests=self.requests, order=self.order, folders=self.folders)
        return d


class Folder:

    def __init__(self, name):
        self._requests = []

        self.id = str(uuid4())
        self.name = name

    def reorder_requests(self):
        def _get_key(request):
            return str(methods_order.index(request.method)) + request.name
        self._requests = sorted(self._requests, key=_get_key)

    def add_request(self, request):
        request._folder = self
        self._requests.append(request)
        self.reorder_requests()

    @property
    def order(self):
        return [request.id for request in self._requests]

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        d["collectionId"] = d.pop("collection_id")
        d.update(order=self.order)
        return d


class Request:

    def __init__(self, name, url, method, collection_id="", data_mode="params", **kwargs):
        self._folder = None

        lower_method = method.lower()
        self.id = str(uuid4())
        self.collection_id = collection_id
        self.data_mode = data_mode
        self.description = kwargs.get("description", "")
        documentation = kwargs.get("documentation", {})

        self.apiHeader = kwargs.get(
            "apiHeader",
            documentation.get(lower_method, {}).get('apiHeader')
        )
        self.apiParam = kwargs.get(
            "apiParam",
            documentation.get(lower_method, {}).get('apiParam')
        )
        self.apiParamExample = kwargs.get(
            "apiParamExample",
            documentation.get(lower_method, {}).get('apiParamExample')
        )
        self.apiSuccessExample = kwargs.get(
            "apiSuccessExample",
            documentation.get(lower_method, {}).get('apiSuccessExample')
        )

        self.method = method
        self.name = kwargs.get("view_name", name)
        self.time = get_time()
        self.url = url

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        d["collectionId"] = d.pop("collection_id")
        d["dataMode"] = d.pop("data_mode")
        return d

    @classmethod
    def from_werkzeug(cls, rule, method, base_url, **kwargs):
        name = rule.endpoint.rsplit('.', 1)[-1]
        name = name.split("_", 1)[-1]
        name = name.replace("_", " ")

        url = base_url + rule.rule
        for match in re.finditer(var_re, url):
            var = match.group("var")
            var_name = "{{" + match.group("var_name") + "}}"
            url = url.replace(var, var_name)

        return cls(name, url, method, **kwargs)


# ramnes: shamelessly stolen from https://www.python.org/dev/peps/pep-0257/
def trim(docstring):
    if not docstring:
        return ""
    lines = docstring.expandtabs().splitlines()
    indent = maxint
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    trimmed = [lines[0].strip()]
    if indent < maxint:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    return '\n'.join(trimmed)


# ramnes: shamelessly stolen from IPython
def init_virtualenv():
    venv = os.environ.get("VIRTUAL_ENV", None)
    if not venv:
        return

    p = os.path.normcase(sys.executable)
    paths = [p]
    while os.path.islink(p):
        p = os.path.normcase(os.path.join(os.path.dirname(p), os.readlink(p)))
        paths.append(p)
    venv_path = os.path.normcase(venv)
    if any(p.startswith(venv_path) for p in paths):
        return

    print(venv_warning, file=sys.stderr)
    if sys.platform == "win32":
        path = os.path.join(venv, 'Lib', 'site-packages')
    else:
        python = "python{}.{}".format(*sys.version_info[:2])
        path = os.path.join(venv, 'lib', python, 'site-packages')
    sys.path.insert(0, path)
    site.addsitedir(path)


def get_apidoc_data(actual_json):
    f = open('apidoc.py', 'w')
    request_id_to_group_name_map = {}
    for folder in actual_json.get('folders', []):
        for rid in folder['order']:
            request_id_to_group_name_map[rid] = folder['name']

    for req in actual_json.get('requests', []):
        print("\"\"\"", file=f)
        print(
            '@api {{{method}}} {endpoint} {method}-{name}'.format(
                method=req["method"].lower(),
                endpoint=req["url"].replace("{{base_url}}", "").replace("{{", ":").replace("}}", ""),
                name=req["name"]
            ), file=f
        )
        print(
            '@apiName {method}{name}'.format(method=req["method"].lower(), name=req["name"]), file=f
        )
        if req.get("description"):
            print(
                "@apiDescription {description}".format(description=req["description"]), file=f
            )

        if req.get("apiHeader"):
            for header in req["apiHeader"]:
                print(
                    "@apiHeader {{String}} {key} {description}.".format(
                        key=header["key"] if header.get("required") else "[" + header["key"] + "]",
                        description=header["description"]
                    ), file=f
                )

        if req.get("apiParam"):
            for param in req["apiParam"]:
                print(
                    "@apiParam {{String}} {key} {description}.".format(
                        key=param["key"] if param.get("required") else "[" + param["key"] + "]",
                        description=param["description"]
                    ), file=f
                )

        if req.get("apiParamExample"):
            print(
                "@apiParamExample {{json}} Request-Example \n {example}.".format(
                    example=json.dumps(req["apiParamExample"])
                ), file=f
            )

        if req.get("apiSuccessExample"):
            print(
                "@apiSuccessExample {{json}} Success-Response \n {example}.".format(
                    example=json.dumps(req["apiSuccessExample"])
                ), file=f
            )

        if req["id"]:
            print(
                "@apiGroup {idToName}".format(
                    idToName=request_id_to_group_name_map.get(req["id"], "Others")
                ), file=f
            )

        print("\"\"\"", file=f)


def main():
    import json
    import logging
    from argparse import ArgumentParser

    from flask import Flask, current_app

    sys.path.insert(0, os.getcwd())
    init_virtualenv()

    parser = ArgumentParser()
    parser.add_argument("flask_instance")
    parser.add_argument("-n", "--name", default=os.path.basename(os.getcwd()),
                        help="Postman collection name (default: current directory name)")
    parser.add_argument("-b", "--base_url", default="{{base_url}}",
                        help="the base of every URL (default: {{base_url}})")
    parser.add_argument("-a", "--all", action="store_true",
                        help="also generate OPTIONS/HEAD methods")
    parser.add_argument("-s", "--static", action="store_true",
                        help="also generate /static/{{filename}} (Flask internal)")
    parser.add_argument("-i", "--indent", action="store_true",
                        help="indent the output")
    parser.add_argument("-f", "--folders", action="store_true",
                        help="add Postman folders for blueprints")
    args = parser.parse_args()

    logging.disable(logging.CRITICAL)

    try:
        app_path, app_name = args.flask_instance.rsplit('.', 1)
        app = getattr(import_module(app_path), app_name)
    except Exception as e:
        msg = "can't import \"{}\": {}"
        parser.error(msg.format(args.flask_instance, str(e)))

    if not isinstance(app, Flask):
        try:
            app = app()
        except Exception as e:
            pass
        if not isinstance(app, Flask):
            msg = '"{}" is not (or did not return) a Flask instance (type: {})'
            parser.error(msg.format(args.flask_instance, type(app)))

    with app.app_context():
        collection = Collection(args.name)
        for rule in current_app.url_map.iter_rules():
            if rule.endpoint == "static" and not args.static:
                continue

            folder = None
            if args.folders:
                try:
                    blueprint_name, _ = rule.endpoint.split('.', 1)
                except ValueError:
                    pass
                else:
                    folder = collection.get_folder(blueprint_name)

            endpoint = current_app.view_functions[rule.endpoint]
            description = trim(endpoint.__doc__)

            documentation = {}
            view_class = getattr(endpoint, "view_class", None)
            view_name = endpoint.__name__
            if view_class:
                view_name = view_class.__name__
                if hasattr(view_class, "get_documentation"):
                    documentation = view_class.get_documentation()

            for method in rule.methods:
                if method in ["OPTIONS", "HEAD"] and not args.all:
                    continue
                request = Request.from_werkzeug(
                    rule, method, args.base_url,
                    description=description,
                    documentation=documentation,
                    view_name=view_name
                )
                if args.folders and folder:
                    folder.add_request(request)
                collection.add_request(request)

    actual_json = collection.to_dict()
    if args.indent:
        json = json.dumps(actual_json, indent=4, sort_keys=True)
    else:
        json = json.dumps(actual_json)

    print(json)
    get_apidoc_data(actual_json)



if __name__ == "__main__":
    main()
