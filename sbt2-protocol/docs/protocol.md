# Protocol Documentation
<a name="top"></a>

## Table of Contents

- [sbt2/protocol/v1/config.proto](#sbt2_protocol_v1_config-proto)
    - [AddKnownGaps](#sbt2-protocol-v1-AddKnownGaps)
    - [ConfigWritten](#sbt2-protocol-v1-ConfigWritten)
    - [KnownGap](#sbt2-protocol-v1-KnownGap)
    - [KnownGaps](#sbt2-protocol-v1-KnownGaps)
    - [ListKnownGaps](#sbt2-protocol-v1-ListKnownGaps)
    - [ListModelKinds](#sbt2-protocol-v1-ListModelKinds)
    - [ModelArgumentKinds](#sbt2-protocol-v1-ModelArgumentKinds)
    - [ModelKind](#sbt2-protocol-v1-ModelKind)
    - [ModelKinds](#sbt2-protocol-v1-ModelKinds)
    - [ModelParameter](#sbt2-protocol-v1-ModelParameter)
    - [RemoveKnownGaps](#sbt2-protocol-v1-RemoveKnownGaps)

    - [AssetClass](#sbt2-protocol-v1-AssetClass)
    - [InstrumentClass](#sbt2-protocol-v1-InstrumentClass)
    - [ModelArgument](#sbt2-protocol-v1-ModelArgument)
    - [ParameterType](#sbt2-protocol-v1-ParameterType)

- [sbt2/protocol/v1/envelope.proto](#sbt2_protocol_v1_envelope-proto)
    - [ClientMessage](#sbt2-protocol-v1-ClientMessage)
    - [Hello](#sbt2-protocol-v1-Hello)
    - [ServerMessage](#sbt2-protocol-v1-ServerMessage)
    - [Welcome](#sbt2-protocol-v1-Welcome)

    - [Capability](#sbt2-protocol-v1-Capability)

- [sbt2/protocol/v1/results.proto](#sbt2_protocol_v1_results-proto)
    - [BenchmarkSelection](#sbt2-protocol-v1-BenchmarkSelection)
    - [GetMetrics](#sbt2-protocol-v1-GetMetrics)
    - [GetPanel](#sbt2-protocol-v1-GetPanel)
    - [GetRun](#sbt2-protocol-v1-GetRun)
    - [GetSeries](#sbt2-protocol-v1-GetSeries)
    - [GetStudy](#sbt2-protocol-v1-GetStudy)
    - [GetTearsheet](#sbt2-protocol-v1-GetTearsheet)
    - [HeadlineMetrics](#sbt2-protocol-v1-HeadlineMetrics)
    - [ListRuns](#sbt2-protocol-v1-ListRuns)
    - [ListStudies](#sbt2-protocol-v1-ListStudies)
    - [Metric](#sbt2-protocol-v1-Metric)
    - [Metrics](#sbt2-protocol-v1-Metrics)
    - [Panel](#sbt2-protocol-v1-Panel)
    - [RunFilter](#sbt2-protocol-v1-RunFilter)
    - [RunIds](#sbt2-protocol-v1-RunIds)
    - [RunList](#sbt2-protocol-v1-RunList)
    - [RunSummary](#sbt2-protocol-v1-RunSummary)
    - [Series](#sbt2-protocol-v1-Series)
    - [StudyDetail](#sbt2-protocol-v1-StudyDetail)
    - [StudyList](#sbt2-protocol-v1-StudyList)
    - [StudyRun](#sbt2-protocol-v1-StudyRun)
    - [StudySummary](#sbt2-protocol-v1-StudySummary)
    - [Tearsheet](#sbt2-protocol-v1-Tearsheet)

    - [BenchmarkKind](#sbt2-protocol-v1-BenchmarkKind)
    - [MetricGroup](#sbt2-protocol-v1-MetricGroup)
    - [PanelKind](#sbt2-protocol-v1-PanelKind)
    - [SeriesKind](#sbt2-protocol-v1-SeriesKind)

- [sbt2/protocol/v1/runs.proto](#sbt2_protocol_v1_runs-proto)
    - [CancelJob](#sbt2-protocol-v1-CancelJob)
    - [DescribeStrategy](#sbt2-protocol-v1-DescribeStrategy)
    - [Job](#sbt2-protocol-v1-Job)
    - [JobCancelled](#sbt2-protocol-v1-JobCancelled)
    - [JobSubmitted](#sbt2-protocol-v1-JobSubmitted)
    - [JobSubscribed](#sbt2-protocol-v1-JobSubscribed)
    - [JobUpdate](#sbt2-protocol-v1-JobUpdate)
    - [Jobs](#sbt2-protocol-v1-Jobs)
    - [ListJobs](#sbt2-protocol-v1-ListJobs)
    - [RunState](#sbt2-protocol-v1-RunState)
    - [SpecFile](#sbt2-protocol-v1-SpecFile)
    - [SpecPeriod](#sbt2-protocol-v1-SpecPeriod)
    - [StrategyModule](#sbt2-protocol-v1-StrategyModule)
    - [StrategyParameter](#sbt2-protocol-v1-StrategyParameter)
    - [StrategySchema](#sbt2-protocol-v1-StrategySchema)
    - [SubmitRun](#sbt2-protocol-v1-SubmitRun)
    - [SubscribeJob](#sbt2-protocol-v1-SubscribeJob)
    - [Unsubscribe](#sbt2-protocol-v1-Unsubscribe)
    - [Unsubscribed](#sbt2-protocol-v1-Unsubscribed)

    - [JobState](#sbt2-protocol-v1-JobState)
    - [RunStatus](#sbt2-protocol-v1-RunStatus)

- [sbt2/protocol/v1/types.proto](#sbt2_protocol_v1_types-proto)
    - [Error](#sbt2-protocol-v1-Error)
    - [Error.DetailsEntry](#sbt2-protocol-v1-Error-DetailsEntry)
    - [StudyConflict](#sbt2-protocol-v1-StudyConflict)

    - [ErrorCode](#sbt2-protocol-v1-ErrorCode)
    - [StudyConflictKind](#sbt2-protocol-v1-StudyConflictKind)

- [Scalar Value Types](#scalar-value-types)



<a name="sbt2_protocol_v1_config-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## sbt2/protocol/v1/config.proto



<a name="sbt2-protocol-v1-AddKnownGaps"></a>

### AddKnownGaps
Adds gaps not already listed, all or none, then answers one ConfigWritten.
INVALID_ARGUMENT means a source, data type, symbol or date is invalid.
No file changes on failure; writes are atomic and apply to the next run.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| gaps | [KnownGap](#sbt2-protocol-v1-KnownGap) | repeated | The gaps to read or change, as specified by the containing message. |






<a name="sbt2-protocol-v1-ConfigWritten"></a>

### ConfigWritten
The answer to a write that succeeded.






<a name="sbt2-protocol-v1-KnownGap"></a>

### KnownGap
A source-confirmed day without data, stored under the data root.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| source | [string](#string) |  | The source adapter registered with sbt2. |
| symbol | [string](#string) |  | The symbol in the source adapter format. |
| data_type | [string](#string) |  | The data type as the source&#39;s list names it, such as trades. |
| day | [string](#string) |  | An ISO 8601 date, YYYY-MM-DD, in UTC. |






<a name="sbt2-protocol-v1-KnownGaps"></a>

### KnownGaps
The current gaps, read from disk for each request.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| gaps | [KnownGap](#sbt2-protocol-v1-KnownGap) | repeated | The gaps to read or change, as specified by the containing message. |






<a name="sbt2-protocol-v1-ListKnownGaps"></a>

### ListKnownGaps
Reads the current gap file as one KnownGaps reply. An absent file returns an empty
list. Only the common ClientMessage errors apply.






<a name="sbt2-protocol-v1-ListModelKinds"></a>

### ListModelKinds
Lists all model arguments as one ModelKinds reply. Only the common ClientMessage
errors apply. The server holds no venue profiles.






<a name="sbt2-protocol-v1-ModelArgumentKinds"></a>

### ModelArgumentKinds
The supported implementations for one execution setting.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| argument | [ModelArgument](#sbt2-protocol-v1-ModelArgument) |  | The execution setting these implementations configure. |
| kinds | [ModelKind](#sbt2-protocol-v1-ModelKind) | repeated | Empty when the argument has no kind yet. |






<a name="sbt2-protocol-v1-ModelKind"></a>

### ModelKind
One supported implementation of an execution model.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | The name used to identify this record. |
| parameters | [ModelParameter](#sbt2-protocol-v1-ModelParameter) | repeated | The configuration parameters accepted by this implementation. |






<a name="sbt2-protocol-v1-ModelKinds"></a>

### ModelKinds
Available model implementations and their configuration parameters.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| arguments | [ModelArgumentKinds](#sbt2-protocol-v1-ModelArgumentKinds) | repeated | Every model argument, including those with no implementations. |






<a name="sbt2-protocol-v1-ModelParameter"></a>

### ModelParameter
One configuration parameter of a model implementation.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | The name used to identify this record. |
| type | [ParameterType](#sbt2-protocol-v1-ParameterType) |  | The representation used for this parameter. |
| required | [bool](#bool) |  | True when the caller must supply this parameter. |
| default | [google.protobuf.Value](#google-protobuf-Value) |  | Absent when the parameter has no default. |






<a name="sbt2-protocol-v1-RemoveKnownGaps"></a>

### RemoveKnownGaps
Removes gaps, all or none, then answers one ConfigWritten. Gaps not listed are
skipped. INVALID_ARGUMENT means a gap is invalid. No file changes on failure;
writes are atomic and apply to the next run.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| gaps | [KnownGap](#sbt2-protocol-v1-KnownGap) | repeated | The gaps to read or change, as specified by the containing message. |








<a name="sbt2-protocol-v1-AssetClass"></a>

### AssetClass
Nautilus&#39;s asset classes.

| Name | Number | Description |
| ---- | ------ | ----------- |
| ASSET_CLASS_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| ASSET_CLASS_FX | 1 | Foreign exchange. |
| ASSET_CLASS_EQUITY | 2 | Ownership shares in a company. |
| ASSET_CLASS_COMMODITY | 3 | Physical goods such as metals or energy. |
| ASSET_CLASS_DEBT | 4 | Debt instruments such as bonds. |
| ASSET_CLASS_INDEX | 5 | A basket used to track a market. |
| ASSET_CLASS_CRYPTOCURRENCY | 6 | Digital assets traded on a cryptocurrency venue. |
| ASSET_CLASS_ALTERNATIVE | 7 | Assets outside the other listed classes. |



<a name="sbt2-protocol-v1-InstrumentClass"></a>

### InstrumentClass
Nautilus&#39;s instrument classes.

| Name | Number | Description |
| ---- | ------ | ----------- |
| INSTRUMENT_CLASS_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| INSTRUMENT_CLASS_SPOT | 1 | Immediate exchange of the underlying asset. |
| INSTRUMENT_CLASS_SWAP | 2 | An exchange of cash flows, including perpetual contracts. |
| INSTRUMENT_CLASS_FUTURE | 3 | A standardized contract with a future expiry. |
| INSTRUMENT_CLASS_FUTURES_SPREAD | 4 | A combination of futures contracts. |
| INSTRUMENT_CLASS_FORWARD | 5 | A negotiated contract for delivery at a future date. |
| INSTRUMENT_CLASS_CFD | 6 | Contract for difference. |
| INSTRUMENT_CLASS_BOND | 7 | A debt security with repayment terms. |
| INSTRUMENT_CLASS_OPTION | 8 | The right to buy or sell an underlying asset. |
| INSTRUMENT_CLASS_OPTION_SPREAD | 9 | A combination of option contracts. |
| INSTRUMENT_CLASS_WARRANT | 10 | An issuer-backed right to buy or sell an asset. |
| INSTRUMENT_CLASS_SPORTS_BETTING | 11 | A contract settled by a sports result. |
| INSTRUMENT_CLASS_BINARY_OPTION | 12 | An option with a fixed payout if its condition holds. |



<a name="sbt2-protocol-v1-ModelArgument"></a>

### ModelArgument
An execution setting whose available implementations the server can list.

| Name | Number | Description |
| ---- | ------ | ----------- |
| MODEL_ARGUMENT_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| MODEL_ARGUMENT_FEE_MODEL | 1 | Calculates transaction fees. |
| MODEL_ARGUMENT_FILL_MODEL | 2 | Determines simulated order fills. |
| MODEL_ARGUMENT_LATENCY_MODEL | 3 | Determines simulated order delays. |
| MODEL_ARGUMENT_MARGIN_MODEL | 4 | Calculates margin requirements. |
| MODEL_ARGUMENT_MODULES | 5 | Simulation modules that extend venue behaviour. |



<a name="sbt2-protocol-v1-ParameterType"></a>

### ParameterType
The wire representation of a model or strategy parameter.

| Name | Number | Description |
| ---- | ------ | ----------- |
| PARAMETER_TYPE_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| PARAMETER_TYPE_STRING | 1 | Also a parameter whose type the server cannot tell. |
| PARAMETER_TYPE_INTEGER | 2 | An integral numeric value. |
| PARAMETER_TYPE_NUMBER | 3 | A numeric value stored as a protobuf double. |
| PARAMETER_TYPE_BOOLEAN | 4 | A true or false value. |
| PARAMETER_TYPE_DECIMAL | 5 | A decimal string, as everywhere in the protocol. |
| PARAMETER_TYPE_STRING_LIST | 6 | A list of strings; its default is a list value. |










<a name="sbt2_protocol_v1_envelope-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## sbt2/protocol/v1/envelope.proto



<a name="sbt2-protocol-v1-ClientMessage"></a>

### ClientMessage
One request per binary WebSocket frame. Send Hello first, using the sbt2.v1 WebSocket
subprotocol and bearer authentication. A request before Hello returns
INVALID_MESSAGE. Common errors: INVALID_ARGUMENT for request_id 0; INVALID_MESSAGE
for an unset body; UNIMPLEMENTED for an unhandled body; INTERNAL for an unexpected
server failure.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| request_id | [uint64](#uint64) |  | Chosen by the client, never 0 and distinct among outstanding requests. |
| hello | [Hello](#sbt2-protocol-v1-Hello) |  | Starts or repeats the Hello handshake. |
| list_runs | [ListRuns](#sbt2-protocol-v1-ListRuns) |  | Selects finished runs from the results store. |
| get_run | [GetRun](#sbt2-protocol-v1-GetRun) |  | Reads one stored run summary. |
| get_metrics | [GetMetrics](#sbt2-protocol-v1-GetMetrics) |  | Calculates the full metrics for a run. |
| get_series | [GetSeries](#sbt2-protocol-v1-GetSeries) |  | Reads an Arrow table from a run. |
| get_tearsheet | [GetTearsheet](#sbt2-protocol-v1-GetTearsheet) |  | Renders the run as HTML. |
| list_known_gaps | [ListKnownGaps](#sbt2-protocol-v1-ListKnownGaps) |  | Reads the data root gap file. |
| add_known_gaps | [AddKnownGaps](#sbt2-protocol-v1-AddKnownGaps) |  | Adds gaps in one atomic write. |
| remove_known_gaps | [RemoveKnownGaps](#sbt2-protocol-v1-RemoveKnownGaps) |  | Removes gaps in one atomic write. |
| list_model_kinds | [ListModelKinds](#sbt2-protocol-v1-ListModelKinds) |  | Lists execution model implementations and their parameters. |
| submit_run | [SubmitRun](#sbt2-protocol-v1-SubmitRun) |  | Checks a spec and queues its runs. |
| cancel_job | [CancelJob](#sbt2-protocol-v1-CancelJob) |  | Stops a job and its unfinished runs. |
| list_jobs | [ListJobs](#sbt2-protocol-v1-ListJobs) |  | Lists the jobs held by this server process. |
| subscribe_job | [SubscribeJob](#sbt2-protocol-v1-SubscribeJob) |  | Starts state and log pushes for a job. |
| unsubscribe | [Unsubscribe](#sbt2-protocol-v1-Unsubscribe) |  | Stops a subscription on this connection. |
| describe_strategy | [DescribeStrategy](#sbt2-protocol-v1-DescribeStrategy) |  | Inspects an uploaded strategy module in a separate process. |
| get_panel | [GetPanel](#sbt2-protocol-v1-GetPanel) |  | Reads one tearsheet panel as Arrow. |
| list_studies | [ListStudies](#sbt2-protocol-v1-ListStudies) |  | Lists named studies. |
| get_study | [GetStudy](#sbt2-protocol-v1-GetStudy) |  | Reads a study with its context, source and runs. |






<a name="sbt2-protocol-v1-Hello"></a>

### Hello
Starts a connection and answers one Welcome. Repeated Hello requests also get
Welcome. client_version is informational; the current server does not reject
versions. Common ClientMessage errors apply.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| client_version | [string](#string) |  | The client application version; not the protocol package version. |






<a name="sbt2-protocol-v1-ServerMessage"></a>

### ServerMessage
One binary WebSocket frame. Replies echo request_id and have subscription_id 0;
pushes use request_id 0. Chunked replies start at index 0, in order, with exactly one
last=true chunk, even for empty results. Requests can interleave; use distinct IDs
for outstanding requests. Each result envelope is at most 1,048,576 bytes. A
correlated Error ends the reply and invalidates earlier chunks.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| request_id | [uint64](#uint64) |  | 0 on a push, which carries the subscription it belongs to instead. |
| subscription_id | [uint64](#uint64) |  | 0 on an answer to a request. |
| error | [Error](#sbt2-protocol-v1-Error) |  | Terminates a failed request, including any partial reply. |
| welcome | [Welcome](#sbt2-protocol-v1-Welcome) |  | Answers Hello with the server version and capabilities. |
| run_list | [RunList](#sbt2-protocol-v1-RunList) |  | Chunk of finished run summaries. |
| run_summary | [RunSummary](#sbt2-protocol-v1-RunSummary) |  | The single reply to GetRun. |
| metrics | [Metrics](#sbt2-protocol-v1-Metrics) |  | Chunk of named metrics. |
| series | [Series](#sbt2-protocol-v1-Series) |  | Byte chunk of an Arrow table. |
| tearsheet | [Tearsheet](#sbt2-protocol-v1-Tearsheet) |  | Byte chunk of a UTF-8 HTML document. |
| config_written | [ConfigWritten](#sbt2-protocol-v1-ConfigWritten) |  | Acknowledges an atomic gap-file write. |
| known_gaps | [KnownGaps](#sbt2-protocol-v1-KnownGaps) |  | The gaps currently stored on disk. |
| model_kinds | [ModelKinds](#sbt2-protocol-v1-ModelKinds) |  | Execution model implementations and their configuration parameters. |
| job_submitted | [JobSubmitted](#sbt2-protocol-v1-JobSubmitted) |  | Accepts a checked spec and identifies its job and runs. |
| job_cancelled | [JobCancelled](#sbt2-protocol-v1-JobCancelled) |  | Acknowledges a cancellation. |
| jobs | [Jobs](#sbt2-protocol-v1-Jobs) |  | The jobs held by this server process. |
| job_subscribed | [JobSubscribed](#sbt2-protocol-v1-JobSubscribed) |  | Starts a subscription with current job state and recent logs. |
| job_update | [JobUpdate](#sbt2-protocol-v1-JobUpdate) |  | A subscription push; request_id is zero. |
| unsubscribed | [Unsubscribed](#sbt2-protocol-v1-Unsubscribed) |  | Acknowledges an unsubscribe request. |
| strategy_schema | [StrategySchema](#sbt2-protocol-v1-StrategySchema) |  | The strategy metadata and parameter schema. |
| panel | [Panel](#sbt2-protocol-v1-Panel) |  | Byte chunk of a panel Arrow table. |
| study_list | [StudyList](#sbt2-protocol-v1-StudyList) |  | Chunk of study summaries. |
| study_detail | [StudyDetail](#sbt2-protocol-v1-StudyDetail) |  | Chunk of study metadata and runs. |






<a name="sbt2-protocol-v1-Welcome"></a>

### Welcome
The answer to Hello.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| server_version | [string](#string) |  | The installed sbt2-server package version. |
| capabilities | [Capability](#sbt2-protocol-v1-Capability) | repeated | The protocol areas this server handles. |








<a name="sbt2-protocol-v1-Capability"></a>

### Capability
An area of the protocol available on this server.

| Name | Number | Description |
| ---- | ------ | ----------- |
| CAPABILITY_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| CAPABILITY_RESULTS | 1 | Reads stored runs, studies, metrics, tables and tearsheets. |
| CAPABILITY_CONFIG | 2 | Reads and edits known gaps; lists execution model kinds. |
| CAPABILITY_RUNS | 3 | Submits, cancels and follows jobs; inspects strategy modules. |










<a name="sbt2_protocol_v1_results-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## sbt2/protocol/v1/results.proto



<a name="sbt2-protocol-v1-BenchmarkSelection"></a>

### BenchmarkSelection
Chooses a benchmark. An absent selection, UNSPECIFIED or DEFAULT uses the strategy
default. Missing default dependencies return an error; there is no fallback. External
benchmark uploads are not supported.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| kind | [BenchmarkKind](#sbt2-protocol-v1-BenchmarkKind) |  | UNSPECIFIED and an absent selection both mean the strategy&#39;s default. |
| instrument_id | [string](#string) | optional | Only valid for BUY_AND_HOLD; absent uses the run&#39;s first instrument. |






<a name="sbt2-protocol-v1-GetMetrics"></a>

### GetMetrics
Calculates full metrics as Metrics chunks. Errors: NOT_FOUND for missing run data;
RESOURCE_EXHAUSTED if one metric cannot fit.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |






<a name="sbt2-protocol-v1-GetPanel"></a>

### GetPanel
Reads one panel as Panel byte chunks. Errors: INVALID_ARGUMENT for an unknown or
unset kind or invalid benchmark; NOT_FOUND for missing run data or benchmark
dependencies.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| kind | [PanelKind](#sbt2-protocol-v1-PanelKind) |  | The requested table or selection kind; see the enum for valid values. |
| benchmark | [BenchmarkSelection](#sbt2-protocol-v1-BenchmarkSelection) |  | Only BENCHMARK_RETURNS uses it; the rules are GetTearsheet&#39;s. |






<a name="sbt2-protocol-v1-GetRun"></a>

### GetRun
Common ClientMessage errors apply to every results request.
Reads one stored RunSummary. Errors: NOT_FOUND for an unknown run or missing summary;
RESOURCE_EXHAUSTED if the summary cannot fit.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |






<a name="sbt2-protocol-v1-GetSeries"></a>

### GetSeries
Reads a table as Series byte chunks. Errors: INVALID_ARGUMENT for an unknown or unset
kind; NOT_FOUND for a missing run or table.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| kind | [SeriesKind](#sbt2-protocol-v1-SeriesKind) |  | The requested table or selection kind; see the enum for valid values. |






<a name="sbt2-protocol-v1-GetStudy"></a>

### GetStudy
Reads a study as StudyDetail chunks. Errors: NOT_FOUND for an unknown study;
RESOURCE_EXHAUSTED if metadata or a run cannot fit.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | The name used to identify this record. |






<a name="sbt2-protocol-v1-GetTearsheet"></a>

### GetTearsheet
Renders a run as Tearsheet byte chunks. Errors: INVALID_ARGUMENT for an invalid
benchmark selection; NOT_FOUND for missing run data, benchmark strategy or prices.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| benchmark | [BenchmarkSelection](#sbt2-protocol-v1-BenchmarkSelection) |  | Benchmark choice; absent uses the strategy default. |






<a name="sbt2-protocol-v1-HeadlineMetrics"></a>

### HeadlineMetrics
Summary metrics in the settlement currency. Undefined optional values are absent, not
zero.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| net_return | [string](#string) | optional | Net return as a decimal fraction. |
| annualized_return | [string](#string) | optional | Annualized return as a decimal fraction. |
| sharpe | [string](#string) | optional | Annualized Sharpe ratio as a decimal string. |
| max_drawdown | [string](#string) | optional | Maximum drawdown as a decimal fraction. |
| trade_count | [uint64](#uint64) |  | Number of trades in the run. |
| total_fees | [string](#string) |  | Total fees as a decimal string in the settlement currency. |
| total_carry | [string](#string) |  | Total carry as a decimal string in the settlement currency. |






<a name="sbt2-protocol-v1-ListRuns"></a>

### ListRuns
Lists matching runs, oldest first, as RunList chunks. RESOURCE_EXHAUSTED means
a record cannot fit. Common ClientMessage errors also apply.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| filter | [RunFilter](#sbt2-protocol-v1-RunFilter) |  | Selection criteria; absent selects every finished run. |






<a name="sbt2-protocol-v1-ListStudies"></a>

### ListStudies
Lists studies as StudyList chunks. RESOURCE_EXHAUSTED means one record cannot fit.






<a name="sbt2-protocol-v1-Metric"></a>

### Metric
One named metric. Undefined values are absent, including NaN and infinity.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| group | [MetricGroup](#sbt2-protocol-v1-MetricGroup) |  | The report group this metric belongs to. |
| name | [string](#string) |  | The name used to identify this record. |
| value | [string](#string) | optional | Absent means undefined, not zero. Finite values are decimal strings. |
| instrument_id | [string](#string) | optional | Set only for a per-instrument metric. |






<a name="sbt2-protocol-v1-Metrics"></a>

### Metrics
Full metrics. Uses the ServerMessage chunk rules; metrics are never split.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| currency | [string](#string) |  | The settlement currency used to report these values. |
| entries | [Metric](#sbt2-protocol-v1-Metric) | repeated | Whole metrics in this chunk. |






<a name="sbt2-protocol-v1-Panel"></a>

### Panel
One Arrow IPC stream in byte chunks. Uses the ServerMessage chunk rules; join all
bytes before decoding.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| data | [bytes](#bytes) |  | Concatenate all chunks before decoding the Arrow IPC stream. It has the columns ts (UTC timestamp) and value (float64, a fraction, not percent). |






<a name="sbt2-protocol-v1-RunFilter"></a>

### RunFilter
Selects finished runs. Unset fields impose no restriction; set fields are combined.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| strategy | [string](#string) | optional | Selects this strategy class as module:Class. |
| part | [string](#string) | optional | Selects train, validation or test. |
| batch | [string](#string) | optional | Selects runs from this batch identifier. |
| study | [string](#string) | optional | Selects runs in this named study. |
| run_ids | [RunIds](#sbt2-protocol-v1-RunIds) |  | Absent selects all IDs; present and empty selects none. |






<a name="sbt2-protocol-v1-RunIds"></a>

### RunIds
A present ID selection; an empty values list selects no runs.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| values | [string](#string) | repeated | The run identifiers to select. |






<a name="sbt2-protocol-v1-RunList"></a>

### RunList
Run summaries, oldest first. Uses the ServerMessage chunk rules; records are never
split.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| runs | [RunSummary](#sbt2-protocol-v1-RunSummary) | repeated | Whole run records in this reply. |






<a name="sbt2-protocol-v1-RunSummary"></a>

### RunSummary
One stored run. GetRun returns one message; RunList embeds whole summaries.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| batch_id | [string](#string) | optional | The batch that created this run; absent for a run outside a batch. |
| study | [string](#string) | optional | The study this run belongs to; absent outside a study. |
| spec_hash | [string](#string) |  | The hash of the resolved run specification. |
| strategy | [string](#string) |  | The strategy class as module:Class. |
| params_json | [string](#string) |  | JSON retains the parameter and split documents&#39; heterogeneous value types. |
| instruments | [string](#string) | repeated | Nautilus instrument identifiers in specification order. |
| start_at | [google.protobuf.Timestamp](#google-protobuf-Timestamp) |  | Start of the period, in UTC. |
| end_at | [google.protobuf.Timestamp](#google-protobuf-Timestamp) |  | End of the period, in UTC. |
| split_json | [string](#string) |  | The stored split document as JSON, with its original value types. |
| part | [string](#string) |  | The run part: train, validation or test. |
| known_gaps | [string](#string) | repeated | Known gaps that overlap this run. |
| currency | [string](#string) |  | The settlement currency used to report these values. |
| headline | [HeadlineMetrics](#sbt2-protocol-v1-HeadlineMetrics) |  | Summary metrics; optional undefined values remain absent. |
| drawdown_tripped_at | [google.protobuf.Timestamp](#google-protobuf-Timestamp) |  | Time the drawdown guard tripped; absent if it did not trip. |






<a name="sbt2-protocol-v1-Series"></a>

### Series
One Arrow IPC stream in byte chunks. Uses the ServerMessage chunk rules. Join every
chunk before decoding; boundaries need not align with Arrow records. Arrow numbers
are not protobuf decimal strings.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| data | [bytes](#bytes) |  | Concatenate all chunks before decoding the Arrow IPC stream. |






<a name="sbt2-protocol-v1-StudyDetail"></a>

### StudyDetail
One study. Uses the ServerMessage chunk rules; runs are whole records. Metadata is
present only in chunk 0.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| name | [string](#string) |  | name, strategy, context_json and source are set only in the chunk with index 0. |
| strategy | [string](#string) |  | The strategy class as module:Class. |
| context_json | [string](#string) |  | A JSON object: the context every run of the study shares. |
| source | [string](#string) |  | The module source the study pinned. |
| runs | [StudyRun](#sbt2-protocol-v1-StudyRun) | repeated | Whole run records in this reply. |






<a name="sbt2-protocol-v1-StudyList"></a>

### StudyList
Study summaries. Uses the ServerMessage chunk rules; records are never split.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| studies | [StudySummary](#sbt2-protocol-v1-StudySummary) | repeated | Whole study records in this chunk. |






<a name="sbt2-protocol-v1-StudyRun"></a>

### StudyRun
One run of a study, with its varying parameters and headline metrics.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| part | [string](#string) |  | The run part: train, validation or test. |
| varying_params_json | [string](#string) |  | A JSON object of the parameters that vary across the study&#39;s runs. |
| headline | [HeadlineMetrics](#sbt2-protocol-v1-HeadlineMetrics) |  | Summary metrics; optional undefined values remain absent. |






<a name="sbt2-protocol-v1-StudySummary"></a>

### StudySummary
A named collection of runs with fixed strategy source and context.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | The name used to identify this record. |
| strategy | [string](#string) |  | The strategy class as module:Class. |
| run_count | [uint64](#uint64) |  | Number of stored runs in the study. |






<a name="sbt2-protocol-v1-Tearsheet"></a>

### Tearsheet
A UTF-8 HTML document in byte chunks. Uses the ServerMessage chunk rules. Join every
chunk before decoding; a boundary can split a UTF-8 character.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| index | [uint64](#uint64) |  | Chunk number, starting at zero for each request. |
| last | [bool](#bool) |  | True only on the final chunk, including an empty result. |
| data | [bytes](#bytes) |  | Concatenate all chunks to recover the UTF-8 HTML document. |








<a name="sbt2-protocol-v1-BenchmarkKind"></a>

### BenchmarkKind
The benchmark for a tearsheet or benchmark-return panel.

| Name | Number | Description |
| ---- | ------ | ----------- |
| BENCHMARK_KIND_UNSPECIFIED | 0 | Use the default declared by the strategy, as for DEFAULT. |
| BENCHMARK_KIND_DEFAULT | 1 | Use the default declared by the strategy. |
| BENCHMARK_KIND_NONE | 2 | Do not compare against a benchmark. |
| BENCHMARK_KIND_BUY_AND_HOLD | 3 | Buy and hold the selected instrument. |
| BENCHMARK_KIND_EQUAL_WEIGHT | 4 | Hold equal weights in the run instruments. |



<a name="sbt2-protocol-v1-MetricGroup"></a>

### MetricGroup
The group that owns a metric in the full metrics report.

| Name | Number | Description |
| ---- | ------ | ----------- |
| METRIC_GROUP_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| METRIC_GROUP_PNLS | 1 | Profit and loss metrics. |
| METRIC_GROUP_RETURNS | 2 | Statistics calculated from the run returns. |
| METRIC_GROUP_GENERAL | 3 | General run and trade statistics. |
| METRIC_GROUP_INSTRUMENT_PNLS | 4 | Profit and loss metrics per instrument. |
| METRIC_GROUP_PROBABILISTIC_SHARPE | 5 | Probability that the Sharpe ratio exceeds the reference ratio. |



<a name="sbt2-protocol-v1-PanelKind"></a>

### PanelKind
The tearsheet panel returned as an Arrow table.

| Name | Number | Description |
| ---- | ------ | ----------- |
| PANEL_KIND_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| PANEL_KIND_RETURNS | 1 | Statistics calculated from the run returns. |
| PANEL_KIND_BENCHMARK_RETURNS | 2 | Returns of the selected benchmark. |
| PANEL_KIND_DRAWDOWN | 3 | Equity decline from the preceding peak. |
| PANEL_KIND_MONTHLY_RETURNS | 4 | Returns aggregated by calendar month. |
| PANEL_KIND_YEARLY_RETURNS | 5 | Returns aggregated by calendar year. |
| PANEL_KIND_ROLLING_SHARPE | 6 | Sharpe ratio calculated over a rolling return window. |



<a name="sbt2-protocol-v1-SeriesKind"></a>

### SeriesKind
The Arrow table to read from a run.

| Name | Number | Description |
| ---- | ------ | ----------- |
| SERIES_KIND_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| SERIES_KIND_EQUITY | 1 | Settlement-currency equity on the run grid, including endpoints. Columns: ts_event (UTC nanoseconds), currency (string), total_equity (float64). |
| SERIES_KIND_FILLS | 2 | Stored fills with their rows, columns, types and index unchanged; Arrow pandas metadata describes the index. |
| SERIES_KIND_TRADES | 3 | One row per closed trade: a combo, or a position when a run has no combos. |
| SERIES_KIND_TRADE_STATISTICS | 4 | The statistics over the trades and the margin, with the columns name and value (float64, NaN when undefined). |
| SERIES_KIND_PORTFOLIO_GREEKS | 5 | The portfolio greeks of a run with an option chain, one row an hour, with the columns ts_event, theta (per day, in the settlement currency), theta_ratio (theta over equity) and beta_weighted_delta (in BTC), all float64 after the time. |










<a name="sbt2_protocol_v1_runs-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## sbt2/protocol/v1/runs.proto



<a name="sbt2-protocol-v1-CancelJob"></a>

### CancelJob
Stops a job and cancels unfinished runs; answers one JobCancelled. A finished job is
unchanged. NOT_FOUND means the job is unknown.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| job_id | [string](#string) |  | The identifier of a job in this server process. |






<a name="sbt2-protocol-v1-DescribeStrategy"></a>

### DescribeStrategy
Returns one StrategySchema for the uploaded module. It imports in a separate process,
outside the job queue. INVALID_ARGUMENT means no concrete strategy or more than one,
an import failure or timeout after 30 seconds, an unsupported parameter type, or an
invalid or installed module name.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| strategy | [StrategyModule](#sbt2-protocol-v1-StrategyModule) |  | The complete uploaded Python module to inspect. |






<a name="sbt2-protocol-v1-Job"></a>

### Job
A job held for the lifetime of the server process. The first failed run fails the job
and cancels later runs.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| job_id | [string](#string) |  | The identifier of a job in this server process. |
| state | [JobState](#sbt2-protocol-v1-JobState) |  | Current state; a final state ends further updates. |
| runs | [RunState](#sbt2-protocol-v1-RunState) | repeated | Every run in spec expansion order, including unfinished runs. |
| reason | [string](#string) |  | Why a failed job failed when no run is to blame; empty otherwise. |






<a name="sbt2-protocol-v1-JobCancelled"></a>

### JobCancelled
Acknowledges a cancellation, including a job that was already finished.






<a name="sbt2-protocol-v1-JobSubmitted"></a>

### JobSubmitted
Accepts a checked spec. Jobs run one at a time, in submission order.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| job_id | [string](#string) |  | The identifier of a job in this server process. |
| run_ids | [string](#string) | repeated | The runs the job makes, in the order the spec expands into them. |






<a name="sbt2-protocol-v1-JobSubscribed"></a>

### JobSubscribed
The initial subscription reply: current job state and recent log lines. On reconnect,
subscribe again to obtain a new subscription and current state.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| subscription_id | [uint64](#uint64) |  | Names the subscription in the pushes that follow, and in Unsubscribe. |
| job | [Job](#sbt2-protocol-v1-Job) |  | The complete current job state at subscription time. |
| log_lines | [string](#string) | repeated | The latest lines the job printed, oldest first. |






<a name="sbt2-protocol-v1-JobUpdate"></a>

### JobUpdate
A push with changed run states and stdout/stderr lines in print order, without
the run that printed them. A large update sends log lines first, then runs,
and the job state in its last message. Unset state in earlier messages does
not end the subscription.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| runs | [RunState](#sbt2-protocol-v1-RunState) | repeated | Only runs whose states changed since the preceding update. |
| log_lines | [string](#string) | repeated | Lines of the job&#39;s stdout and stderr, in the order they were printed. |
| state | [JobState](#sbt2-protocol-v1-JobState) |  | Current state; a final state ends further updates. |
| reason | [string](#string) |  | Failure reason; empty when no failure applies. |






<a name="sbt2-protocol-v1-Jobs"></a>

### Jobs
Jobs held by the current server process, including finished jobs.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| jobs | [Job](#sbt2-protocol-v1-Job) | repeated | Jobs known to this server process. |






<a name="sbt2-protocol-v1-ListJobs"></a>

### ListJobs
Lists jobs held by this server process as one Jobs reply. Only the common
ClientMessage errors apply.






<a name="sbt2-protocol-v1-RunState"></a>

### RunState
The current state of one run inside a job.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| run_id | [string](#string) |  | The stored run identifier. |
| state | [RunStatus](#sbt2-protocol-v1-RunStatus) |  | Current state; a final state ends further updates. |
| reason | [string](#string) |  | Why the run failed; empty otherwise. |






<a name="sbt2-protocol-v1-SpecFile"></a>

### SpecFile
A spec file&#39;s table, key for key.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| strategy | [string](#string) |  | The strategy&#39;s class in the uploaded module, as &#34;module:Class&#34;. |
| instruments | [string](#string) | repeated | Nautilus instrument identifiers in specification order. |
| period | [SpecPeriod](#sbt2-protocol-v1-SpecPeriod) |  | The complete period to run, before applying the split. |
| capital | [string](#string) |  | A nautilus money string, such as &#34;10000 USDT&#34;. |
| part | [string](#string) | repeated | The parts to run: train, validation or test. Empty runs train and validation. |
| split | [google.protobuf.Struct](#google-protobuf-Struct) |  | The split&#39;s table: validation_start and test_start as ISO 8601 strings, or validation and test as fractions. |
| seed | [int64](#int64) | optional | Random seed; absent uses the core default. |
| equity_interval | [string](#string) | optional | Equity sampling interval; absent uses the core default. |
| liquidation | [bool](#bool) | optional | Whether to enable liquidation; absent uses the core default. |
| bars | [string](#string) | optional | Internal bar specification; absent uses the strategy default. |
| params | [google.protobuf.Struct](#google-protobuf-Struct) |  | The strategy&#39;s parameters; a list value is a sweep, one run for each of its items. An integral number is read as an integer. |
| risk | [google.protobuf.Struct](#google-protobuf-Struct) |  | The risk table: drawdown_limit and the risk engine&#39;s limits. |
| study | [string](#string) | optional | The study to append to; absent runs outside a study. |
| chain | [google.protobuf.Struct](#google-protobuf-Struct) |  | The chain table: min_dte, max_dte and strike_band, which bound the contracts of an option chain named in the instruments. |
| capitals | [string](#string) | repeated | A nautilus money string for each currency of a run with several, such as &#34;1 BTC&#34; and &#34;20 ETH&#34;; the first reports the run. When set it wins over capital. |
| execution | [google.protobuf.Struct](#google-protobuf-Struct) |  | The execution table: fee_model, which is required, and the other BacktestVenueConfig arguments, such as fill_model and margin settings. A model is a table of its kind and config. An integral number is read as an integer. |






<a name="sbt2-protocol-v1-SpecPeriod"></a>

### SpecPeriod
The period a spec covers, before its split.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| start_at | [google.protobuf.Timestamp](#google-protobuf-Timestamp) |  | Start of the period, in UTC. |
| end_at | [google.protobuf.Timestamp](#google-protobuf-Timestamp) |  | End of the period, in UTC. |






<a name="sbt2-protocol-v1-StrategyModule"></a>

### StrategyModule
A single-module strategy, sent as source.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | A Python identifier that no module of the server&#39;s image already has. |
| source | [string](#string) |  | Python source of the complete module, encoded as UTF-8 text. |






<a name="sbt2-protocol-v1-StrategyParameter"></a>

### StrategyParameter
One parameter of the strategy Params type.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| name | [string](#string) |  | The name used to identify this record. |
| type | [ParameterType](#sbt2-protocol-v1-ParameterType) |  | The representation used for this parameter. |
| required | [bool](#bool) |  | True when the caller must supply this parameter. |
| default | [google.protobuf.Value](#google-protobuf-Value) |  | Absent when the parameter is required. A decimal is a string. |
| choices | [google.protobuf.Value](#google-protobuf-Value) | repeated | The allowed values when the parameter is a Literal; empty otherwise. |






<a name="sbt2-protocol-v1-StrategySchema"></a>

### StrategySchema
The strategy a module defines: the concrete Strategy subclasses whose module
is that one. Imported ones do not count.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| strategy | [string](#string) |  | The strategy&#39;s class, as &#34;module:Class&#34;. |
| description | [string](#string) |  | The strategy&#39;s docstring; empty when it has none. |
| params_description | [string](#string) |  | The docstring of its Params; empty when it has none. |
| parameters | [StrategyParameter](#sbt2-protocol-v1-StrategyParameter) | repeated | The parameters of the strategy Params type, including Literal choices. |






<a name="sbt2-protocol-v1-SubmitRun"></a>

### SubmitRun
Starts a job after checking the spec; answers one JobSubmitted or Error and starts no
job on rejection. INVALID_ARGUMENT means an invalid spec, module, missing input data
or study conflict; NOT_FOUND means a venue has no source. Strategy source executes
only in a job process and can import only installed packages. Each run stores its
strategy source with its results.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| spec | [SpecFile](#sbt2-protocol-v1-SpecFile) |  | The spec file table to validate and expand into runs. |
| strategy | [StrategyModule](#sbt2-protocol-v1-StrategyModule) |  | The uploaded module that defines the strategy named by spec.strategy. |






<a name="sbt2-protocol-v1-SubscribeJob"></a>

### SubscribeJob
Follows a job: one JobSubscribed reply, then JobUpdate pushes with request_id 0 and
the assigned subscription_id. Updates are sent at most four times a second; a large
update can use several messages. The final state ends the subscription. NOT_FOUND
means the job is unknown.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| job_id | [string](#string) |  | The identifier of a job in this server process. |






<a name="sbt2-protocol-v1-Unsubscribe"></a>

### Unsubscribe
Stops a subscription on this connection and answers one Unsubscribed. An unknown ID,
or an ID from another connection, is ignored. Only the common ClientMessage errors
apply.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| subscription_id | [uint64](#uint64) |  | The subscription identifier assigned on this connection. |






<a name="sbt2-protocol-v1-Unsubscribed"></a>

### Unsubscribed
Acknowledges an unsubscribe request, including an unknown subscription.








<a name="sbt2-protocol-v1-JobState"></a>

### JobState
The state of a job and its queue of runs.

| Name | Number | Description |
| ---- | ------ | ----------- |
| JOB_STATE_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| JOB_STATE_QUEUED | 1 | Checked, and waiting for the jobs before it. |
| JOB_STATE_CHECKING | 2 | Validating the submitted spec. |
| JOB_STATE_RUNNING | 3 | Execution is in progress. |
| JOB_STATE_FINISHED | 4 | All work completed successfully; final state. |
| JOB_STATE_FAILED | 5 | Execution failed; reason explains the cause. Final state. |
| JOB_STATE_CANCELLED | 6 | Execution was stopped or skipped after cancellation; final state. |



<a name="sbt2-protocol-v1-RunStatus"></a>

### RunStatus
The state of one run within a job.

| Name | Number | Description |
| ---- | ------ | ----------- |
| RUN_STATUS_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| RUN_STATUS_PENDING | 1 | Waiting for earlier runs in the job. |
| RUN_STATUS_RUNNING | 2 | Execution is in progress. |
| RUN_STATUS_FINISHED | 3 | All work completed successfully; final state. |
| RUN_STATUS_FAILED | 4 | Execution failed; reason explains the cause. Final state. |
| RUN_STATUS_CANCELLED | 5 | Execution was stopped or skipped after cancellation; final state. |










<a name="sbt2_protocol_v1_types-proto"></a>
<p align="right"><a href="#top">Top</a></p>

## sbt2/protocol/v1/types.proto



<a name="sbt2-protocol-v1-Error"></a>

### Error
Terminates the reply for its ServerMessage.request_id and invalidates any partial
chunks. The connection stays open. A malformed frame has request_id 0. This message
lives outside envelope.proto to avoid an import cycle.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| code | [ErrorCode](#sbt2-protocol-v1-ErrorCode) |  | The machine-readable reason for failure. |
| message | [string](#string) |  | A human-readable explanation; unexpected failures omit internal details. |
| details | [Error.DetailsEntry](#sbt2-protocol-v1-Error-DetailsEntry) | repeated | Additional string context; empty when the error has no extra context. |
| study_conflict | [StudyConflict](#sbt2-protocol-v1-StudyConflict) |  | Structured details when a submitted run conflicts with its study. |






<a name="sbt2-protocol-v1-Error-DetailsEntry"></a>

### Error.DetailsEntry



| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| key | [string](#string) |  |  |
| value | [string](#string) |  |  |






<a name="sbt2-protocol-v1-StudyConflict"></a>

### StudyConflict
Why a run does not fit the study it names; the code is ERROR_CODE_INVALID_ARGUMENT.


| Field | Type | Label | Description |
| ----- | ---- | ----- | ----------- |
| kind | [StudyConflictKind](#sbt2-protocol-v1-StudyConflictKind) |  | The study constraint that the submission violates. |
| context_keys | [string](#string) | repeated | CONTEXT only: the context keys whose values differ from the study&#39;s. |
| run_id | [string](#string) | optional | DUPLICATE_RUN only: the study&#39;s run with the same parameters. |








<a name="sbt2-protocol-v1-ErrorCode"></a>

### ErrorCode
A failed request or frame. Error.message gives the cause; clients should branch on
this code.

| Name | Number | Description |
| ---- | ------ | ----------- |
| ERROR_CODE_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| ERROR_CODE_INVALID_MESSAGE | 1 | The frame is not a ClientMessage, or its body is unset. |
| ERROR_CODE_INVALID_ARGUMENT | 2 | A field or selection is invalid. |
| ERROR_CODE_NOT_FOUND | 3 | A requested object or its required data is missing. |
| ERROR_CODE_UNIMPLEMENTED | 4 | The server does not handle this body. |
| ERROR_CODE_UNSUPPORTED_VERSION | 5 | Reserved for incompatible versions; the current Hello handler does not emit it. |
| ERROR_CODE_INTERNAL | 6 | An unexpected server failure; details are logged only on the server. |
| ERROR_CODE_RESOURCE_EXHAUSTED | 7 | One indivisible response record exceeds the maximum envelope size. |



<a name="sbt2-protocol-v1-StudyConflictKind"></a>

### StudyConflictKind
The rule a submitted run violates in a named study.

| Name | Number | Description |
| ---- | ------ | ----------- |
| STUDY_CONFLICT_KIND_UNSPECIFIED | 0 | No value selected; not a usable concrete choice. |
| STUDY_CONFLICT_KIND_CONTEXT | 1 | The run&#39;s context differs from the study&#39;s. |
| STUDY_CONFLICT_KIND_CODE | 2 | The strategy&#39;s source differs from the one the study pinned. |
| STUDY_CONFLICT_KIND_DUPLICATE_RUN | 3 | The study already holds a run with the same parameters. |










## Scalar Value Types

| .proto Type | Notes | C++ | Java | Python | Go | C# | PHP | Ruby |
| ----------- | ----- | --- | ---- | ------ | -- | -- | --- | ---- |
| <a name="double" /> double |  | double | double | float | float64 | double | float | Float |
| <a name="float" /> float |  | float | float | float | float32 | float | float | Float |
| <a name="int32" /> int32 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint32 instead. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="int64" /> int64 | Uses variable-length encoding. Inefficient for encoding negative numbers – if your field is likely to have negative values, use sint64 instead. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="uint32" /> uint32 | Uses variable-length encoding. | uint32 | int | int/long | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="uint64" /> uint64 | Uses variable-length encoding. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum or Fixnum (as required) |
| <a name="sint32" /> sint32 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int32s. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sint64" /> sint64 | Uses variable-length encoding. Signed int value. These more efficiently encode negative numbers than regular int64s. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="fixed32" /> fixed32 | Always four bytes. More efficient than uint32 if values are often greater than 2^28. | uint32 | int | int | uint32 | uint | integer | Bignum or Fixnum (as required) |
| <a name="fixed64" /> fixed64 | Always eight bytes. More efficient than uint64 if values are often greater than 2^56. | uint64 | long | int/long | uint64 | ulong | integer/string | Bignum |
| <a name="sfixed32" /> sfixed32 | Always four bytes. | int32 | int | int | int32 | int | integer | Bignum or Fixnum (as required) |
| <a name="sfixed64" /> sfixed64 | Always eight bytes. | int64 | long | int/long | int64 | long | integer/string | Bignum |
| <a name="bool" /> bool |  | bool | boolean | boolean | bool | bool | boolean | TrueClass/FalseClass |
| <a name="string" /> string | A string must always contain UTF-8 encoded or 7-bit ASCII text. | string | String | str/unicode | string | string | string | String (UTF-8) |
| <a name="bytes" /> bytes | May contain any arbitrary sequence of bytes. | string | ByteString | str | []byte | ByteString | string | String (ASCII-8BIT) |
