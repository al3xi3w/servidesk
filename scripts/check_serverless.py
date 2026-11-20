"""Validación estática de los serverless.yml (sin AWS ni credenciales).

Comprueba en cada servicio:
- cada `handler` apunta a un archivo y a una función que existen;
- no hay rutas HTTP duplicadas y toda ruta (salvo /auth/login) usa jwtAuthorizer;
- todo !GetAtt / !Ref apunta a un recurso definido (o a uno que Serverless genera);
- cada consumidor SQS usa functionResponseType: ReportBatchItemFailures;
- cada cola suscrita a SNS tiene DLQ, política y FilterPolicy.

Uso: python scripts/check_serverless.py
"""

import ast
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES = ["identity", "cmdb", "incidents", "problems", "changes", "requests"]
PUBLIC_ROUTES = {("POST", "/auth/login")}
GENERATED = {"HttpApi", "AWS::Region", "AWS::AccountId", "CommonLambdaLayer", "AuthorizerLambdaFunction"}


class Tag:
    def __init__(self, tag, value):
        self.tag, self.value = tag, value


class Loader(yaml.SafeLoader):
    pass


def _construct(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return Tag(suffix, value)


Loader.add_multi_constructor("!", _construct)


def refs(node):
    """Recursos referenciados con !GetAtt X.Attr o !Ref X."""
    if isinstance(node, Tag):
        if node.tag == "GetAtt":
            target = node.value if isinstance(node.value, str) else node.value[0]
            yield target.split(".")[0]
        elif node.tag == "Ref":
            yield node.value
        else:
            yield from refs(node.value)
    elif isinstance(node, dict):
        for value in node.values():
            yield from refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from refs(value)


def functions_in(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            names.add(node.name)
    return names


def check_service(base, errors):
    cfg = yaml.load((base / "serverless.yml").read_text(encoding="utf-8"), Loader=Loader)
    resources = set((cfg.get("resources") or {}).get("Resources") or {})
    routes = {}
    summary = {"rutas": 0, "consumidores": 0, "colas": 0}

    for name, fn in (cfg.get("functions") or {}).items():
        module, func = fn["handler"].rsplit(".", 1)
        file = base / f"{module}.py"
        if not file.is_file():
            errors.append(f"{base.name}.{name}: no existe {file.relative_to(ROOT)}")
        elif func not in functions_in(file):
            errors.append(f"{base.name}.{name}: {module}.py no define {func}()")

        for event in fn.get("events") or []:
            if "httpApi" in event:
                http = event["httpApi"]
                key = (http["method"].upper(), http["path"])
                if key in routes:
                    errors.append(f"{base.name}: ruta duplicada {key} en {name} y {routes[key]}")
                routes[key] = name
                summary["rutas"] += 1
                has_auth = (http.get("authorizer") or {}).get("name") == "jwtAuthorizer"
                if key not in PUBLIC_ROUTES and not has_auth:
                    errors.append(f"{base.name}.{name}: ruta {key} sin jwtAuthorizer")
            if "sqs" in event:
                summary["consumidores"] += 1
                if event["sqs"].get("functionResponseType") != "ReportBatchItemFailures":
                    errors.append(f"{base.name}.{name}: consumidor SQS sin ReportBatchItemFailures")
            for target in refs(event):
                if target not in resources and target not in GENERATED:
                    errors.append(f"{base.name}.{name}: referencia a recurso inexistente {target}")

    for rname, res in ((cfg.get("resources") or {}).get("Resources") or {}).items():
        for target in refs(res):
            if target not in resources and target not in GENERATED:
                errors.append(f"{base.name}.{rname}: referencia a recurso inexistente {target}")
        if res.get("Type") == "AWS::SNS::Subscription" and res["Properties"].get("Protocol") == "sqs":
            summary["colas"] += 1
            queue = next(iter(refs(res["Properties"]["Endpoint"])))
            qprops = (cfg["resources"]["Resources"].get(queue) or {}).get("Properties") or {}
            if "RedrivePolicy" not in qprops:
                errors.append(f"{base.name}.{queue}: cola sin DLQ (RedrivePolicy)")
            if not res["Properties"].get("FilterPolicy"):
                errors.append(f"{base.name}.{rname}: suscripción sin FilterPolicy")
            policies = [r for r in cfg["resources"]["Resources"].values()
                        if r.get("Type") == "AWS::SQS::QueuePolicy" and queue in set(refs(r))]
            if not policies:
                errors.append(f"{base.name}.{queue}: sin AWS::SQS::QueuePolicy para SNS")

    return summary


def main():
    errors = []
    for svc in SERVICES:
        summary = check_service(ROOT / "services" / svc, errors)
        print(f"{svc:10} rutas={summary['rutas']:2}  consumidores={summary['consumidores']}  colas SNS={summary['colas']}")
    yaml.load((ROOT / "infra" / "serverless.yml").read_text(encoding="utf-8"), Loader=Loader)
    if errors:
        print("\nERRORES:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("\nOK: sin errores")


if __name__ == "__main__":
    main()
