"""A fake Soapstone server for LINK's tests (build plan §8.2); not a test module.

An in-process gRPC server on 127.0.0.1 at a free port. It serves the seven methods on DataPiler's list and nothing
else, through grpc.method_handlers_generic_handler, so any other method answers UNIMPLEMENTED. Its data is invented:
NpcParam and TalkParam rows with ids from 9000000, invented row names that must never come out of the link, one text
cell, maps m99_00_00_00 to m99_00_00_14 and placed characters with models of the form c999x. It records every call
and its request."""

from __future__ import annotations

import threading
from concurrent import futures

import grpc

from soapstone import common_pb2 as common
from soapstone import internal_pb2 as pb

SERVICE = "SoapstoneLib.Proto.Internal.Soapstone"

# Invented strings the link must never return or log.
PLANTED = ("Quillon Marrowgate", "the Lamplighter of Corrow", "Ostrel Vanehollow", "Brannoc of the Pale Ford",
           "Sister Wenmarrow")

NPC_IDS = tuple(range(9000000, 9000030))
TALK_IDS = tuple(range(9100000, 9100020))
DUPLICATE_ID = 9000005              # two NpcParam rows share this id
TEXT_CELL_ID = 9000017              # its nameId cell holds text
MAPS = tuple("m99_00_00_%02d" % i for i in range(15))
LOADED_AT_START = ("m99_00_00_00", "m99_00_00_01")
MAP_FILE = "map/mapstudio/%s.msb"


def _npc_row(rid: int, index: int, twin: bool = False) -> pb.GetParamRowResponse:
    k = rid - 9000000
    name_id = "the Lamplighter of Corrow" if rid == TEXT_CELL_ID else str(9500000 + k)
    values = [
        pb.ParamFieldValue(internal_name="nameId", value=name_id, def_type="s32"),
        pb.ParamFieldValue(internal_name="teamType", value=str(k % 7), def_type="u8"),
        pb.ParamFieldValue(internal_name="npcType", value=str(3 if twin else k % 4), def_type="u8"),
        pb.ParamFieldValue(internal_name="hitHeight", value="%.2f" % (1.5 + k / 10), def_type="f32"),
        pb.ParamFieldValue(internal_name="isGhost", value="True" if k % 2 else "False", def_type="b32"),
        pb.ParamFieldValue(internal_name="padFlags:4", value=str(k % 16), def_type="u8"),
        pb.ParamFieldValue(internal_name="epithet", value=PLANTED[k % len(PLANTED)], def_type="fixstrW"),
    ]
    return pb.GetParamRowResponse(param_name="NpcParam", row_id=rid, row_name=PLANTED[k % len(PLANTED)],
                                  values=values, row_index=index)


def _talk_row(rid: int, index: int) -> pb.GetParamRowResponse:
    k = rid - 9100000
    values = [pb.ParamFieldValue(internal_name="msgId", value=str(9600000 + k), def_type="s32")]
    return pb.GetParamRowResponse(param_name="TalkParam", row_id=rid, row_name="Sister Wenmarrow, line %d" % k,
                                  values=values, row_index=index)


def _parts(map_id: str) -> list[tuple[pb.PrimaryKey, dict[str, pb.PropertyValue]]]:
    """Three placed characters and one map piece per map; the last character's model is not of the form c0000."""
    m = int(map_id[-2:])
    out = []
    for j, model in enumerate(("c9990", "c9991", "Ostrel Vanehollow")):
        key = pb.PrimaryKey(file=MAP_FILE % map_id, namespace=common.KEY_NAMESPACE_MAP_PART, index=0,
                            str_id="%s %s %d" % (PLANTED[j], map_id, j))
        props = {
            "EntityID": pb.PropertyValue(u32_value=9990000 + m * 10 + j),
            "NPCParamID": pb.PropertyValue(s32_value=9000000 + j),
            "TalkID": pb.PropertyValue(s32_value=9100000 + j),
            "ModelName": pb.PropertyValue(string_value=model),
            "Name": pb.PropertyValue(string_value=PLANTED[j]),
        }
        out.append((key, props))
    piece = pb.PrimaryKey(file=MAP_FILE % map_id, namespace=common.KEY_NAMESPACE_MAP_PART, index=0,
                          str_id="Brannoc of the Pale Ford piece")
    out.append((piece, {"EntityID": pb.PropertyValue(u32_value=0),
                        "ModelName": pb.PropertyValue(string_value="m9999")}))
    return out


def _matches(props: dict[str, pb.PropertyValue], search: pb.PropertySearch) -> bool:
    for group in search.all_of_any_conditions:
        ok = False
        for c in group.conditions:
            v = props.get(c.key)
            if v is None:
                continue
            which = v.WhichOneof("value")
            want_which = c.value.WhichOneof("value")
            if which is None or want_which is None or which == "string_value":
                continue
            have, want = getattr(v, which), getattr(c.value, want_which)
            if c.type == common.GREATER and have > want:
                ok = True
            elif c.type == common.EQUAL and have == want:
                ok = True
        if not ok:
            return False
    return True


class FakeSoapstone:
    def __init__(self, *, load_after: int = 2, port: int = 0):
        """load_after: how many looks at the loaded maps an opened map takes to show as loaded. port: 0 for a free
        one (the tests); a fixed one only for a run by hand against a whole DataPiler."""
        self.lock = threading.Lock()
        self.calls: list[tuple[str, object]] = []
        self.loaded: set[str] = set(LOADED_AT_START)
        self.pending: dict[str, int] = {}
        self.max_pending = 0
        self.load_after = load_after
        self.list_params_extra = ("Bad Name!", "x" * 70)
        self._server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
        served = (
            ("ListParams", self.list_params),
            ("ListParamRows", self.list_param_rows),
            ("GetParamRows", self.get_param_rows),
            ("SearchObjects", self.search_objects),
            ("GetObject", self.get_object),
            ("BatchGetObjects", self.batch_get_objects),
            ("OpenResource", self.open_resource),
        )
        handlers = {name: self._h(name, fn) for name, fn in served}
        self._server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, handlers),))
        self.port = self._server.add_insecure_port("127.0.0.1:%d" % port)

    # ---- life

    def start(self) -> "FakeSoapstone":
        self._server.start()
        return self

    def stop(self) -> None:
        self._server.stop(0).wait(5)

    def methods(self) -> list[str]:
        with self.lock:
            return [m for m, _ in self.calls]

    def requests(self, method: str) -> list:
        with self.lock:
            return [r for m, r in self.calls if m == method]

    def _h(self, name: str, fn):
        req, resp = getattr(pb, name + "Request"), getattr(pb, name + "Response")

        def handler(request, context):
            with self.lock:
                self.calls.append((name, request))
            return fn(request, context)
        return grpc.unary_unary_rpc_method_handler(handler, request_deserializer=req.FromString,
                                                   response_serializer=resp.SerializeToString)

    # ---- params

    def _rows(self, name: str) -> list[pb.GetParamRowResponse]:
        if name == "NpcParam":
            rows = []
            for i, rid in enumerate(NPC_IDS):
                rows.append(_npc_row(rid, len(rows)))
                if rid == DUPLICATE_ID:
                    rows.append(_npc_row(rid, len(rows), twin=True))
            return rows
        if name == "TalkParam":
            return [_talk_row(rid, i) for i, rid in enumerate(TALK_IDS)]
        return []

    def list_params(self, request, context):
        return pb.ListParamsResponse(param_names=["NpcParam", "TalkParam", *self.list_params_extra])

    def list_param_rows(self, request, context):
        rows = self._rows(request.param_name)
        if not rows:
            context.abort(grpc.StatusCode.NOT_FOUND, "no such param: Quillon Marrowgate")
        return pb.ListParamRowsResponse(param_name=request.param_name, rows=[
            pb.ParamRowSummary(id=r.row_id, name=r.row_name, index=r.row_index) for r in rows])

    def get_param_rows(self, request, context):
        rows = [r for r in self._rows(request.param_name) if r.row_id == request.row_id]
        return pb.GetParamRowsResponse(param_name=request.param_name, row_id=request.row_id, count=len(rows),
                                       rows=rows)

    # ---- maps

    def _look_at_maps(self) -> set[str]:
        with self.lock:
            for m in list(self.pending):
                self.pending[m] += 1
                if self.pending[m] >= self.load_after:
                    del self.pending[m]
                    self.loaded.add(m)
            return set(self.loaded)

    def search_objects(self, request, context):
        res = request.resource
        if res.type != common.EDITOR_RESOURCE_TYPE_MAP:
            return pb.SearchObjectsResponse()
        loaded = self._look_at_maps()
        if request.result_type.category == pb.PRIMARY_KEY_CATEGORY_FILE:
            maps = sorted(loaded) if res.name == "" else [res.name] if res.name in loaded else []
            return pb.SearchObjectsResponse(results=[pb.GameObject(key=pb.PrimaryKey(file=MAP_FILE % m))
                                                     for m in maps])
        if res.name not in loaded:
            return pb.SearchObjectsResponse()
        out = []
        for key, props in _parts(res.name):
            if _matches(props, request.search):
                out.append(pb.GameObject(key=key, properties=[
                    pb.GameProperty(key=p.key, value=props[p.key]) for p in request.properties if p.key in props]))
        return pb.SearchObjectsResponse(results=out)

    def _object(self, map_id: str, key: pb.PrimaryKey, wanted) -> pb.GameObject | None:
        for k, props in _parts(map_id):
            if k == key:
                return pb.GameObject(key=k, properties=[
                    pb.GameProperty(key=p.key, value=props[p.key]) for p in wanted if p.key in props])
        return None

    def get_object(self, request, context):
        obj = self._object(request.resource.name, request.key, request.properties)
        return pb.GetObjectResponse(result=obj) if obj is not None else pb.GetObjectResponse()

    def batch_get_objects(self, request, context):
        if request.resource.name not in self._look_at_maps():
            return pb.BatchGetObjectsResponse()
        out = [self._object(request.resource.name, k, request.properties) for k in request.keys]
        return pb.BatchGetObjectsResponse(results=[o for o in out if o is not None])

    def open_resource(self, request, context):
        res = request.resource
        if res.type != common.EDITOR_RESOURCE_TYPE_MAP or res.name not in MAPS:
            context.abort(grpc.StatusCode.NOT_FOUND, "no such resource: Ostrel Vanehollow")
        with self.lock:
            if res.name not in self.loaded and res.name not in self.pending:
                self.pending[res.name] = 0
            self.max_pending = max(self.max_pending, len(self.pending))
        return pb.OpenResourceResponse()
