# Where `soapstone/` comes from

The message classes in this folder are generated from SoapstoneLib's `.proto` files, as Smithbox's repository carries
them. SoapstoneLib is MIT, "Copyright (c) 2022 thefifthmatt"; its licence is [LICENSE](LICENSE), as fetched. The
`.proto` files themselves are not in this repository; their hashes are below.

## The source

- **Repository:** Smithbox (`vawser/Smithbox` on GitHub), folder `src/Andre/SoapstoneLib/`.
- **Commit:** `e2dbcae7141f4ae2738f1c39c1feb955b0f33079`, the default branch's head on 2026-11-08 and the commit
  EldenNet's research note ER08 read (`e2dbcae`).
- **Fetched:** these four files only, each read by its path at that commit from GitHub's raw file host (the GitHub API
  was not open to this session: build plan §10, P6). Smithbox was not cloned and nothing else of it was fetched.

| File | sha256 |
|---|---|
| `src/Andre/SoapstoneLib/LICENSE` | `c210f332d2bb61e0cb24681a2cf3f96766af329e1c42297331e8996d2de59ddd` |
| `src/Andre/SoapstoneLib/Proto/common.proto` | `83032fa9d27363643a3d746ddb82e676368b2808596693abd158ec8f2e39a2d2` |
| `src/Andre/SoapstoneLib/Proto/internal.proto` | `e07127322e5af3a94e113d47269cf7d5182063996c93945e01c5c592fe6f3e36` |
| `src/Andre/SoapstoneLib/Proto/soapstone.proto` | `941294549f8adc038ed9e4c08796abd2d67eb98a647287a122a0e162107cd579` |

The three `.proto` files are a closed set: `soapstone.proto` imports `common.proto` and `internal.proto`, and
`internal.proto` imports `common.proto`.

## The generation

- **Tool:** `grpcio-tools` 1.85.1 (its `libprotoc` 35.1), in a virtual environment outside this repository. The code
  it writes is for protobuf 7.35.1 and checks for that runtime or newer at import; `requirements.lock` pins protobuf
  7.36.2.
- **Command**, run in the folder holding the three `.proto` files:

  ```
  python -m grpc_tools.protoc -I . --python_out=<DATAPILER>/soapstone common.proto internal.proto soapstone.proto
  ```

  There is no `--grpc_python_out`: no service stub exists, so no call outside DataPiler's list can be made through
  generated code.
- **One change after generation:** each import of a sibling module (`import common_pb2 as common__pb2`,
  `import internal_pb2 as internal__pb2`) became `from . import ...`, one line in `internal_pb2.py` and two in
  `soapstone_pb2.py`, so the classes load as the package `soapstone`. Nothing else was changed.

| Generated file | sha256 after that change |
|---|---|
| `common_pb2.py` | `2b0193c2c55cfb7ad86b18647cf4010cd52fcdc37af9939ce9f93d34de846831` |
| `internal_pb2.py` | `0ca427eba7338b741ca25c66c67951304f2cd32ad172e668f3c296bcb3d10d60` |
| `soapstone_pb2.py` | `edf041093f36e24b0d8f4980d398648d8f70df4c1e63b6dbe5f5fc87eaa35a3c` |

## The service and its methods

The service is `SoapstoneLib.Proto.Internal.Soapstone`, so each method's path is
`/SoapstoneLib.Proto.Internal.Soapstone/<Method>`. Its full method list at the commit above, in the order of
`soapstone.proto`, with the seven on DataPiler's list (`datapiler/link.py`, `ALLOWED`):

| Method | DataPiler | Request | Response |
|---|---|---|---|
| `GetServerInfo` | not allowed | `SoapstoneLib.Proto.ServerInfoRequest` | `SoapstoneLib.Proto.ServerInfoResponse` |
| `SearchObjects` | allowed | `SearchObjectsRequest` | `SearchObjectsResponse` |
| `GetObject` | allowed | `GetObjectRequest` | `GetObjectResponse` |
| `BatchGetObjects` | allowed | `BatchGetObjectsRequest` | `BatchGetObjectsResponse` |
| `OpenResource` | allowed | `OpenResourceRequest` | `OpenResourceResponse` |
| `OpenObject` | not allowed | `OpenObjectRequest` | `OpenObjectResponse` |
| `OpenSearch` | not allowed | `OpenSearchRequest` | `OpenSearchResponse` |
| `ExecuteMassEdit` | not allowed | `ExecuteMassEditRequest` | `ExecuteMassEditResponse` |
| `ReloadParams` | not allowed | `ReloadParamsRequest` | `ReloadParamsResponse` |
| `ListParams` | allowed | `ListParamsRequest` | `ListParamsResponse` |
| `DescribeParam` | not allowed | `DescribeParamRequest` | `DescribeParamResponse` |
| `GetParamRow` | not allowed | `GetParamRowRequest` | `GetParamRowResponse` |
| `GetParamRows` | allowed | `GetParamRowsRequest` | `GetParamRowsResponse` |
| `ListParamRows` | allowed | `ListParamRowsRequest` | `ListParamRowsResponse` |
| `SetParamCell` | not allowed | `SetParamCellRequest` | `SetParamCellResponse` |

Messages without a package name above are in `SoapstoneLib.Proto.Internal` (`internal_pb2`). `tests/test_link_static.py`
reads this table: no method marked "not allowed" may be named in any `.py` file outside `soapstone/*_pb2.py` and
`tests/`.

## Checked against ER08 §4.2

- The seven read calls ER08 names (`ListParams`, `ListParamRows`, `GetParamRows`, `SearchObjects`, `GetObject`,
  `BatchGetObjects`, `OpenResource`) are all in the service, under those names.
- `GetParamRows` takes `param_name`, `row_id` and `vanilla`, as ER08 says. `ListParamRows` takes `vanilla` too, and
  DataPiler sends `true` there as well. Every cell comes back as text with its field type (`ParamFieldValue`: the
  value, `def_type`); `link.py` turns only the numeric types into numbers and refuses the rest.
- Map objects come through `SearchObjects`, `GetObject` and `BatchGetObjects`, each scoped to an `EditorResource`, and
  `OpenResource` takes an `EditorResource`; `link.py` sends it only a map resource.

## What the protos answer for the build plan's §10, P5

- **Listing every map: no allowed call does.** The only call that lists resources is `GetServerInfo`, which is not on
  the list and lists only the open ones. So `Link.map_ids()` returns None, and a job's `"maps": "all"` for
  `load_maps` is refused in 0.1; maps are named by id.
- **The loaded maps** are read with `SearchObjects` on the map resource with an empty name, which `common.proto`'s
  `EditorResource` describes as "all open maps", asking for file keys of the form `map/mapstudio/{0}.msb` (the form
  `internal.proto`'s `PrimaryKey` and `PrimaryKeyType` describe). That the server answers this way is to be confirmed
  on the owner's PC.
- **The placements' numbers** come from object properties asked for by name. The protos do not name them: the
  names `link.py` uses (`PLACEMENT_PROPS`) are to be confirmed against the server's own answers on the owner's PC
  (EldenNet O48). A property that is missing or not a number stops the call with `LinkDataError`; nothing is guessed.
