# DSP Remote Execution Completion Plan

**Design Date:** 2026-06-09  
**Scope:** G1 (`dsp-remote-scenario`) + G2 (RunManager Webshell Integration)  
**Constraint:** 현재 코드 최대 활용, 최소 변경, 신규 아키텍처·엔진·Provider·Orchestration Layer 없음  
**Status:** 설계 전용 — 구현 금지

---

## 0. 설계 목표

사용자 최종 동작을 **단일 진입점 `dsp run`** 으로 완성한다.

```
Local:  dsp run → Scenario → Traffic → Event Store → Evidence
Remote: dsp run --execution-provider webshell → Webshell → RemoteScenarioRunner
        → (remote) Traffic → Bundle → Import → Event Store → Evidence
```

**재사용 원칙:** `run_scenario()`, `create_execution_provider()`, `RemoteScenarioRunner`, `RemoteEventCollector`, `EventSyncBridge`, `ValidationEngine`, `EvidenceExporter` — 모두 기존 코드 그대로 연결.

---

## 1. Current Execution Flow Analysis (코드 기준)

### 1.1 Local Execution — `dsp run` / `RunManager`

```
dsp.runner.cli:main()
  └─ RunManager.run()                          [dsp/runner/run_manager.py]
       ├─ PluginLoader.discover_and_load()     [dsp/plugins/]
       ├─ EventStore.open_run()                 [dsp/event_store/store.py]
       ├─ RunContext + resolve_targets()      [dsp/engine/]
       ├─ create_execution_provider("local")  [dsp/execution/factory.py L169 고정]
       ├─ LocalExecutionProvider.prepare()    [dsp/execution/local_provider.py]
       ├─ for scenario:
       │    └─ LocalExecutionProvider.execute()
       │         └─ run_scenario()             [dsp/engine/orchestrator.py]
       │              └─ Scenario.prepare/execute/summarize
       │                   └─ EventStore.append() (protocol clients → live/mock traffic)
       ├─ ValidationEngine.validate_run()     [dsp/validation/engine.py]
       ├─ ReportingEngine.generate()          [dsp/reporting/]
       ├─ EventStore.export_jsonl()           [events.jsonl — bundle 형식 아님]
       └─ run.json / validation.json / report.md
```

**Evidence Package:** 이 경로에 **없음**. `EvidenceExporter`·`ManualVerificationPackageGenerator` 미호출.

### 1.2 Remote Execution — `operational_runner` (RunManager 우회)

```
scripts/run_dsp_release_1_0_lab_test.py
  └─ dsp.lab.operational_runner:main()
       └─ run_webshell_lab()                   [dsp/lab/operational_runner.py]
            ├─ create_execution_provider("webshell", ...)  [factory.py — webshell 분기 존재]
            ├─ WebshellExecutionProvider.prepare()         [dsp/execution/webshell_provider.py]
            ├─ provider.execute_command() × N  (preflight: whoami/hostname/pwd)
            ├─ RemoteScenarioRunner().run()    [dsp/execution/remote/runner.py]
            │    ├─ build_scenario_command()    [dsp/execution/remote/payload.py]
            │    │    → CommandRequest("dsp-remote-scenario", arguments=[JSON])
            │    └─ WebshellExecutionProvider.execute_command()
            │         └─ JspWebshellProvider / Php / Aspx → *Runtime.execute_command()
            │              └─ RealHttpTransport send_get/send_post  [delivery_only]
            ├─ RemoteEventCollector().collect() [dsp/execution/remote/collector.py]
            │    ├─ provider.download_file(remote_bundle_path)
            │    └─ EventSyncBridge.sync_bundle() [dsp/execution/webshell/event_sync/bridge.py]
            ├─ EvidenceExporter.export()        [dsp/evidence/exporter.py]
            └─ ManualVerificationPackageGenerator.generate()
```

**갭:** `RemoteScenarioRunner` 이후 원격 호스트에서 **실제 시나리오 실행체 없음**. E2E는 `tests/e2e/fixtures/webshell_test_server.py`가 합성 bundle 생성.

### 1.3 이미 연결된 Remote 컴포넌트 (재사용 대상)

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| `ScenarioExecutionRequest` | `remote/models.py` | 원격 dispatch payload 스키마 |
| `build_scenario_command()` | `remote/payload.py` | JSON → `dsp-remote-scenario` 명령 인코딩 |
| `RemoteScenarioRunner` | `remote/runner.py` | Webshell에 명령 전달 |
| `WebshellExecutionProvider.execute()` | `webshell_provider.py` L148–171 | Runner 호출 래퍼 |
| `RemoteEventCollector` | `remote/collector.py` | download + import |
| `EventSyncBridge` | `event_sync/bridge.py` | append-only import |
| `load_jsonl_bundle()` | `event_sync/bundle.py` | bundle 파싱 (import 측) |

---

## 2. G1 Design — `dsp-remote-scenario`

### 2.1 정확히 무엇인가?

원격 호스트(DSP가 webshell로 명령을 전달하는 대상)에서 **로컬과 동일한 시나리오 executor**를 실행하고, 결과 이벤트를 **EventSyncBridge 호환 JSONL bundle**로 기록하는 **DSP 패키지 CLI entry point**.

원격 호스트에 `dsp` 패키지가 설치되어 있어야 한다 (시나리오 plugin·protocol client·EventStore 동일 코드베이스).

### 2.2 반드시 답변

#### 1) Python Script / CLI Entry Point / Package Command?

| 형태 | 판정 |
|------|------|
| Python Script (standalone .py) | **아님** |
| CLI Entry Point | **YES** — `pyproject.toml` `[project.scripts]` 등록 |
| Package Command | **YES** — `dsp` 패키지와 동일 wheel에 포함, `dsp-remote-scenario` 명령으로 설치 |

**근거:** `REMOTE_SCENARIO_COMMAND = "dsp-remote-scenario"` (`payload.py` L10)는 **셸에서 실행 가능한 명령 이름**을 전제. 현재 entry point는 `dsp`만 (`pyproject.toml` L16–17).

**설계:**

```toml
[project.scripts]
dsp = "dsp.runner.cli:main"
dsp-remote-scenario = "dsp.runner.remote_scenario_cli:main"
```

#### 2) 입력값 (실제 필요 항목만)

`RemoteScenarioRunner`가 이미 인코딩하는 JSON payload (`payload.py` L19–26) + bundle 경로.

| 필드 | 출처 | 필수 | 용도 |
|------|------|:----:|------|
| `scenario_id` | payload | YES | `PluginLoader` 시나리오 선택 |
| `scenario_params` | payload | NO (default `{}`) | executor volume/옵션 (`RunConfig.scenario_params`) |
| `run_id` | payload | YES | EventStore run 격리, bundle metadata |
| `target_net` | payload | YES | `resolve_targets()` |
| `dry_run` | payload | NO (default `false`) | live traffic 여부 |
| `execution_metadata.remote_bundle_path` | payload | YES* | bundle 출력 경로 |
| `execution_metadata.remote_work_dir` | payload | ALT | `resolve_remote_bundle_path(work_dir, run_id)` 로 bundle 경로 유도 |

\* `remote_bundle_path` 없으면 `remote_work_dir` + `run_id`로 `operational_runner.resolve_remote_bundle_path()` 와 동일 규칙 적용: `{work_dir}/{run_id}/events.jsonl`.

**불필요 (G1 입력에 포함하지 않음):** profile 이름(이미 `scenario_params`에 반영됨), webshell URL, Stellar 설정, detection 설정.

**CLI 인자 형태 (webshell transport 계약):**

```
dsp-remote-scenario '<json-payload>'
```

webshell `cmd` 파라미터로 전달되는 단일 JSON 문자열 1개 (`build_scenario_command` → `arguments=[encoded_payload]`).

#### 3) 출력

| 출력 | 형태 | 필수 |
|------|------|:----:|
| **Bundle** | EventSyncBridge JSONL (`_bundle_metadata` 헤더 + event rows) | YES |
| **Logs** | stderr/stdout (진단용, SOT 아님) | optional |
| **Events (SOT)** | bundle 파일 내 event rows | YES |
| SQLite `events.db` | 원격 임시 파일 | 내부용 (bundle 작성 후 삭제 가능) |

Bundle 경로: `execution_metadata.remote_bundle_path` (convention: `/tmp/dsp/<run_id>/events.jsonl` — `RELEASE_1_0_LAB_GUIDE.md` L262, `bundle_helpers.py` L76–77).

Bundle 형식 (`bundle.py` L31–34, `validation.py` L14–22):

- Line 1: `{"_bundle_metadata": true, "run_id", "scenario_id", "scenario_version", "generated_at", "event_count", "schema_version"}`
- Line 2+: event dict (`run_id`, `scenario_id`, `timestamp`, `stage`, `event`, `status` 필수)

#### 4) `RemoteScenarioRunner`와 연결

```
[DSP Host]
WebshellExecutionProvider.execute()
  → RemoteScenarioRunner.run(request, provider)
       → build_scenario_command(request)
            → CommandRequest("dsp-remote-scenario", arguments=[json])
       → provider.execute_command(command)
            → HTTP → [Remote Host webshell]

[Remote Host]
webshell이 cmd 실행
  → dsp-remote-scenario '{...json...}'
       → (G1 신규) 시나리오 실행 + bundle 작성
```

**변경 없음:** `RemoteScenarioRunner`, `build_scenario_command`, `WebshellExecutionProvider.execute()` — G1은 **수신측 실행체**만 추가.

#### 5) `RemoteEventCollector`와 연결

```
[DSP Host — G2 이후 RunManager 또는 기존 operational_runner]
RemoteEventCollector.collect(
    RemoteEventCollectionRequest(
        remote_execution_id=...,
        remote_bundle_path=...,  # G1이 쓴 경로와 동일
    ),
    webshell_provider,
    event_store,
)
  → download_file(remote_bundle_path)
  → EventSyncBridge.sync_bundle(local_path, event_store)
```

**변경 없음:** `RemoteEventCollector`, `EventSyncBridge`. G1은 collector가 **download할 파일**을 원격에 생성하는 역할.

#### 6) 재사용 가능 구성요소

| 구성요소 | 재사용 방식 |
|----------|-------------|
| `PluginLoader` + `PluginRecord` | 시나리오 로드 |
| `run_scenario()` | `orchestrator.py` — Local과 **동일** 실행 경로 |
| `resolve_targets()` | target host 선정 |
| `RunContext` / `RunConfig` | payload에서 구성 |
| `EventStore` | 원격 임시 SQLite (`/tmp/dsp/<run_id>/events.db` 또는 in-memory) |
| `ScenarioExecutionRequest.from_dict()` | payload 파싱 |
| `resolve_remote_bundle_path()` | bundle 출력 경로 (현재 `operational_runner.py` L87–90 → 공용 모듈로 추출) |
| Bundle metadata 스키마 | `event_sync/bundle.py`, `validation.py` |
| `tests/e2e/fixtures/bundle_helpers.write_bundle()` | **로직 추출** → production `write_jsonl_bundle()` (테스트 helper와 동일 형식) |

**신규 최소 코드 (G1):**

1. `dsp/runner/remote_scenario_cli.py` — `main()`, payload 파싱, run_scenario 호출, bundle export, exit code
2. `dsp/execution/webshell/event_sync/bundle_export.py` (또는 `bundle.py`에 함수 추가) — `EventStore.list_events()` → bundle JSONL 작성
3. `dsp/execution/remote/paths.py` — `resolve_remote_bundle_path()` 공용화 (`operational_runner`에서 import 변경)
4. `pyproject.toml` — entry point 1줄

**의도적 비재사용:** `RunManager`, `RemoteScenarioRunner`, webshell transport — G1은 원격 호스트에서 **로컬 executor만** 실행.

### 2.3 G1 원격 실행 내부 흐름

```
remote_scenario_cli.main(argv)
  ├─ json.loads(argv[1]) → ScenarioExecutionRequest.from_dict()
  ├─ bundle_path ← execution_metadata["remote_bundle_path"]
  │                 or resolve_remote_bundle_path(work_dir, run_id)
  ├─ PluginLoader.discover_and_load().get(scenario_id)
  ├─ EventStore(temp_db).open_run(run_id)
  ├─ RunContext(run_id, target_net, event_store, RunConfig(...))
  ├─ run_scenario(record, ctx, targets)     # traffic 생성 (source="local" on remote NIC)
  ├─ write_jsonl_bundle(bundle_path, store, scenario_id)
  ├─ exit 0 (scenario 완료) / exit 1 (config·실행 오류)
  └─ (optional) temp_db 삭제
```

**source 필드:** executor는 `source="local"` 기록. bundle export 시 `source="remote"` 로 변환 (import 측 의미 명확화, executor 코드 변경 없음).

**dry_run:** payload `dry_run=true` 시 원격에서도 mock traffic (lab 테스트용).

---

## 3. G2 Design — RunManager Webshell Integration

### 3.1 목표

`RunManager.run()` 에서 `create_execution_provider("local")` 고정 (L169)을 **`local` | `webshell` 선택**으로 확장하고, webshell 시나리오 후 **자동 bundle collect → 기존 validation/report/evidence** 경로 연결.

### 3.2 반드시 답변

#### 1) 수정 파일

| 파일 | 변경 |
|------|------|
| `dsp/runner/run_manager.py` | provider 선택, webshell config, post-execute collect, evidence export |
| `dsp/runner/cli.py` | `--execution-provider`, webshell 옵션 전달 |
| `dsp/lab/operational_runner.py` | `resolve_remote_bundle_path` import 경로 변경 (공용 모듈) |
| `pyproject.toml` | G1 entry point (G2와 동시) |

**수정 불필요 (연결만):**

- `dsp/execution/factory.py` — webshell 분기 이미 존재
- `dsp/execution/webshell_provider.py` — `execute()` 이미 `RemoteScenarioRunner` 호출
- `dsp/execution/remote/runner.py`, `collector.py`, `event_sync/bridge.py`

#### 2) 수정 함수

| 위치 | 함수 | 변경 내용 |
|------|------|-----------|
| `run_manager.py` | `RunManager.run()` | 파라미터 추가; provider 분기; per-scenario collect; evidence export |
| `run_manager.py` | (신규 private) `_create_provider()`, `_collect_remote_events()`, `_export_evidence()` | `operational_runner._export_artifacts()` 로직 이전·공유 |
| `cli.py` | `main()` | 새 CLI flags → `RunManager.run()` 전달 |

**`run_scenario()`, `RemoteScenarioRunner.run()`, `RemoteEventCollector.collect()` — 시그니처 변경 없음.**

#### 3) 새 인터페이스 필요 여부

**NO.**

- `ExecutionProvider` ABC 변경 없음
- `WebshellExecutionProvider` 이미 `ExecutionProvider` 구현
- `create_execution_provider(provider_type, **config)` 이미 webshell 지원

필요한 것은 `RunManager.run()` **파라미터** 확장뿐 (새 ABC·registry·orchestration layer 없음).

#### 4) Provider Factory 재사용

**YES — 100% 재사용.**

```python
# local (현재)
create_execution_provider("local")

# webshell (G2)
create_execution_provider(
    "webshell",
    webshell_family=webshell_family,      # factory: provider_type alias
    webshell_url=webshell_url,
    verify_tls=verify_tls,
    enable_healthcheck_on_connect=True,
)
```

`factory.py` L17–30 — 변경 없이 호출 방식만 RunManager에서 분기.

#### 5) CLI 변경

**YES — 최소 flags 추가 (`cli.py`):**

| Flag | Default | 설명 |
|------|---------|------|
| `--execution-provider` | `local` | `local` \| `webshell` |
| `--webshell-family` | — | `jsp` \| `php` \| `aspx` (webshell 시 필수) |
| `--webshell-url` | — | webshell endpoint (webshell 시 필수) |
| `--remote-work-dir` | `/tmp/dsp` | 원격 bundle 디렉터리 |
| `--verify-tls` | off | HTTP TLS 검증 |
| `--export-evidence` | on | Evidence + Manual Verification 생성 |

기존 flags 유지: `--scenarios`, `--target-net`, `--dry-run`, `--confirm-detection` (remote에서도 optional, 기본 success 경로 무관).

**사용 예 (완료 기준):**

```bash
dsp run --scenarios dns_tunnel \
  --execution-provider webshell \
  --webshell-family jsp \
  --webshell-url https://lab/shell.jsp \
  --target-net 10.10.10.0/24
```

#### 6) manifest 변경

**G2 1차: 필수 아님.** `RunManager`가 `remote_capable` 미검사로도 동작 가능 (operational_runner와 동일).

**G2 2차 (P1, 선택):** live traffic 시나리오 10개에 `remote_capable: true` 설정 + `RunManager`에서 `false` 시 CONFIG_ERROR. `dummy`/`dns_dummy`는 `false` 유지.

manifest 스키마 변경 없음 — 기존 `remote_capable` 필드만 값 업데이트.

### 3.3 RunManager webshell 분기 (의사코드)

```python
# run_manager.py — run() 내부, 기존 L169 대체

provider = create_execution_provider(
    execution_provider,
    **webshell_config,  # webshell일 때만
)
exec_ctx = ExecutionContext(...)

if execution_provider == "webshell":
    exec_ctx.execution_metadata["remote_work_dir"] = remote_work_dir
    exec_ctx.execution_metadata["remote_bundle_path"] = resolve_remote_bundle_path(
        remote_work_dir, run_id
    )

provider.prepare(exec_ctx)

for sid in scenario_ids:
    exec_ctx.scenario_id = sid
    provider.execute(exec_ctx, record, ctx, targets, snapshot_dir=run_dir)

    if execution_provider == "webshell":
        RemoteEventCollector().collect(
            RemoteEventCollectionRequest(
                remote_execution_id=exec_ctx.execution_metadata["remote_execution_id"],
                remote_bundle_path=exec_ctx.execution_metadata["remote_bundle_path"],
            ),
            provider,  # WebshellExecutionProvider
            store,
        )

provider.cleanup(exec_ctx)

# 기존: ValidationEngine → ReportingEngine (변경 없음)

if export_evidence:
    _export_evidence(store, run_id, run_dir)  # operational_runner L107-112 동일
```

**순서:** execute → collect → (다음 scenario) — 시나리오별 bundle 경로가 `run_id` 단위이므로 단일 시나리오 run이 기본. multi-scenario 시 `remote_bundle_path`를 scenario별 suffix로 확장하는 것은 **G2 범위 외** (1차: `--scenarios` 단일 ID 권장, 또는 run_id+scenario_id path 규칙 추가 — 최소 변경 시 단일 시나리오만 공식 지원).

### 3.4 `operational_runner`와의 관계

G2 완료 후 `operational_runner.run_webshell_lab()`는 **thin wrapper**로 `RunManager.run(..., export_evidence=True)` 호출하도록 정리 가능 (후속 리팩터, G2 필수 아님).

1차 G2: RunManager만 완성, operational_runner 중복 유지 허용.

---

## 4. Remote Bundle Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│ DSP Host                                                         │
│  RunManager.run(execution_provider=webshell)                     │
│    → WebshellExecutionProvider.execute()                         │
│         → RemoteScenarioRunner.run()                             │
│              → HTTP cmd: dsp-remote-scenario '{json}'            │
└────────────────────────────┬────────────────────────────────────┘
                             │ webshell transport (IMPLEMENTED)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ Remote Host                                                      │
│  webshell executes: dsp-remote-scenario '{json}'                 │
│    → run_scenario() → protocol I/O (traffic)          [G1 MISSING]│
│    → write_jsonl_bundle(path)                         [G1 MISSING]│
│  Output: /tmp/dsp/<run_id>/events.jsonl              [G1 MISSING]│
└────────────────────────────┬────────────────────────────────────┘
                             │ GET download ?remote_path=...
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ DSP Host                                                         │
│  RemoteEventCollector.collect()                      IMPLEMENTED │
│    → WebshellExecutionProvider.download_file()       IMPLEMENTED │
│    → EventSyncBridge.sync_bundle()                   IMPLEMENTED │
│    → EventStore.append() (imported events)           IMPLEMENTED │
│  ValidationEngine / ReportingEngine                  IMPLEMENTED │
│  EvidenceExporter (G2 추가)                            PARTIAL     │
└─────────────────────────────────────────────────────────────────┘
```

### 구현 상태 구분

| 단계 | 상태 |
|------|------|
| Webshell command delivery | **IMPLEMENTED** |
| `ScenarioExecutionRequest` encoding | **IMPLEMENTED** |
| Remote scenario execution (`run_scenario` on remote) | **NOT IMPLEMENTED** (G1) |
| Bundle JSONL write on remote | **NOT IMPLEMENTED** (G1 — test helper만 존재) |
| Bundle download | **IMPLEMENTED** |
| Bundle validate + import | **IMPLEMENTED** |
| RunManager orchestration | **NOT IMPLEMENTED** (G2) |
| Validation/Report after remote | **IMPLEMENTED** (RunManager에 연결만 필요) |
| Evidence after remote | **PARTIAL** (코드 존재, RunManager 미연결) |

### Bundle lifecycle 오류 (G2 최소 처리)

| 실패 | 동작 |
|------|------|
| 원격 `dsp-remote-scenario` 미설치 | command delivery OK, bundle 없음 → `BundleNotFoundError` on download |
| bundle 미생성 (timeout) | `RemoteEventCollector` 예외 → run `CODE_FAILURE` 또는 scenario FAILED |
| `run_id` mismatch | `EventSyncBridge` `BundleValidationError` (기존) |

1차: 기존 예외 전파. retry/healthcheck는 P1.

---

## 5. Evidence Flow

### 5.1 목표

Remote run 완료 후 Local과 **동일 산출물**:

- `events.db` (imported events 포함)
- `validation.json`, `report.md`, `report.json`
- `events.jsonl` (RunManager 기존 export)
- `run_<run_id>.json`, `run_<run_id>.md` (EvidenceExporter)
- Manual verification: checklist, investigation notes, evidence summary

### 5.2 재사용 (코드 변경 최소)

`operational_runner._export_artifacts()` (L101–122) 로직을 RunManager에 복제 또는 `dsp/runner/artifacts.py`로 **추출 1회**:

```python
EvidenceExporter(store).export(EvidenceExportRequest(run_id=run_id, output_directory=run_dir))
ManualVerificationPackageGenerator(store).generate(ManualVerificationRequest(...))
```

**조건:** `EventStore`에 import 완료 후 호출 (RemoteEventCollector 이후, ValidationEngine 이전/이후 모두 가능 — evidence는 raw events 기준이므로 **Validation 전**이 자연스러움).

**권장 순서 (Remote):**

```
execute → collect → ValidationEngine → ReportingEngine → export_jsonl → EvidenceExporter
```

Local과 동일하게 Validation/Report가 evidence 내용에 영향 없음 (Event Store SOT 유지).

---

## 6. Minimal Change Strategy

| 금지 | 준수 방법 |
|------|-----------|
| 새 아키텍처 | 기존 Mode B (webshell) 경로 완성만 |
| 새 엔진 | `run_scenario()` 재사용 |
| 새 Provider | `WebshellExecutionProvider` 재사용 |
| 새 Orchestration Layer | `RunManager.run()` 분기만 확장 |

**변경 요약:**

1. 원격: CLI entry point 1개 + bundle writer 1개 + path helper 추출
2. DSP Host: `RunManager` + `cli.py` 파라미터 확장 + evidence 호출 추가
3. **총 신규 파일 2–3개**, 수정 파일 3–4개

---

## 7. File Impact Analysis

| 파일 | 분류 | 이유 |
|------|------|------|
| `dsp/runner/remote_scenario_cli.py` | **신규** | G1 entry point |
| `dsp/execution/webshell/event_sync/bundle_export.py` | **신규** | production bundle writer |
| `dsp/execution/remote/paths.py` | **신규** | `resolve_remote_bundle_path` 공용 |
| `dsp/runner/run_manager.py` | **수정** | G2 |
| `dsp/runner/cli.py` | **수정** | CLI flags |
| `pyproject.toml` | **수정** | entry point |
| `dsp/lab/operational_runner.py` | **수정** | path import 경로만 |
| `dsp/execution/factory.py` | **수정 불필요** | |
| `dsp/execution/webshell_provider.py` | **수정 불필요** | |
| `dsp/execution/remote/runner.py` | **수정 불필요** | |
| `dsp/execution/remote/collector.py` | **수정 불필요** | |
| `dsp/execution/remote/payload.py` | **수정 불필요** | |
| `dsp/engine/orchestrator.py` | **수정 불필요** | |
| `scenarios/*/manifest.yaml` | **선택 수정** | `remote_capable` (P1) |
| `tests/e2e/fixtures/bundle_helpers.py` | **수정 불필요** | (선택: production writer 위임) |
| `tests/e2e/fixtures/webshell_test_server.py` | **수정 불필요** | mock은 유지 |

**삭제 가능:** 없음 (operational_runner는 G2 후에도 lab script 호환용 유지).

---

## 8. Implementation Roadmap

### Step 1 — Bundle export + path helper (G1 선행 기반)

**작업:**
- `resolve_remote_bundle_path()` → `dsp/execution/remote/paths.py`
- `write_jsonl_bundle(event_store, path, scenario_id)` → `bundle_export.py`
- Unit test: round-trip `write` → `load_jsonl_bundle` → `validate_bundle`

**완료 조건:** production 코드로 EventSyncBridge 호환 bundle 생성 가능 (test helper와 형식 동일).

### Step 2 — `dsp-remote-scenario` CLI (G1)

**작업:**
- `remote_scenario_cli.py`: payload 파싱 → `run_scenario()` → bundle write
- `pyproject.toml` entry point
- Unit test: dry_run payload로 bundle 파일 생성, metadata/event_count 일치

**완료 조건:** 로컬 셸에서 `dsp-remote-scenario '{"scenario_id":"dummy",...}'` 실행 시 `/tmp/dsp/<run_id>/events.jsonl` 생성.

### Step 3 — RunManager webshell 분기 (G2 core)

**작업:**
- `RunManager.run()` provider 분기 + `RemoteEventCollector` per-scenario 호출
- `execution_metadata`에 `remote_bundle_path` 설정
- Config validation (webshell 시 family/url 필수)

**완료 조건:** Python API로 `RunManager.run(execution_provider="webshell", ...)` 시 import된 events가 `events.db`에 존재 (mock webshell server 또는 lab).

### Step 4 — CLI + Evidence (G2 완결)

**작업:**
- `cli.py` flags
- `_export_evidence()` RunManager 통합
- `export_evidence` default on

**완료 조건:** `dsp run --execution-provider webshell ...` 한 명령으로 run dir에 evidence + manual verification 파일 존재.

### Step 5 — E2E harness 갱신

**작업:**
- `webshell_test_server.py`: 합성 bundle 대신 `dsp-remote-scenario` subprocess 호출 (선택) 또는 유지 + 별도 integration test
- `test_release_1_0_webshell_flow.py`: RunManager 경로 테스트 추가

**완료 조건:** pytest e2e marker 통과, mock HTTP server + real `dsp-remote-scenario` subprocess 경로 검증.

### Step 6 — (P1) manifest `remote_capable` + operational_runner 정리

**완료 조건:** `remote_capable: false` 시나리오 webshell run 시 CONFIG_ERROR.

---

## 9. Test Strategy

### Unit

| 대상 | 검증 |
|------|------|
| `write_jsonl_bundle()` | metadata header, required fields, event_count |
| `remote_scenario_cli.main()` | invalid JSON → exit 1; valid dry_run → bundle |
| `resolve_remote_bundle_path()` | path 규칙 |
| `RunManager` webshell config validation | missing url → CONFIG_ERROR |

### Integration

| 대상 | 검증 |
|------|------|
| `create_execution_provider("webshell")` + `RemoteScenarioRunner` | 기존 test 유지 |
| `RunManager.run(webshell)` + mock server | collect → event count > 0 → validation.json |
| Bundle round-trip | remote CLI write → `EventSyncBridge.sync_bundle` → count match |

### Remote E2E

| 대상 | 검증 |
|------|------|
| `tests/e2e/test_release_1_0_webshell_flow.py` | RunManager 경로로 전환 |
| `WebshellTestServer` + subprocess `dsp-remote-scenario` | command delivery → real executor → real bundle (dry_run) |

### Live Traffic

| 대상 | 검증 |
|------|------|
| Lab manual (`RELEASE_1_0_LAB_GUIDE.md`) | real webshell + `dsp-remote-scenario` + live `dns_tunnel` |
| Opt-in pytest marker `@pytest.mark.live_lab` | CI 기본 제외 |

**기존 테스트:** `test_remote_scenario_runner.py`, `test_remote_event_collector.py`, `test_webshell_execution_provider.py` — 회귀 유지 (변경 없음 전제).

---

## 10. Completion Criteria (G1 + G2 Done)

다음이 **모두** 충족되면 G1/G2 완료:

| # | 기준 |
|---|------|
| 1 | `dsp-remote-scenario`가 pyproject entry point로 설치됨 |
| 2 | 원격 호스트에서 payload 수신 → `run_scenario()` 실행 → EventSyncBridge 호환 bundle 작성 |
| 3 | `dsp run --execution-provider webshell --webshell-family jsp --webshell-url <url> --scenarios <id>` 실행 가능 |
| 4 | Remote command delivery (`RemoteScenarioRunner`) → 원격 실행 → bundle download → `events_imported > 0` |
| 5 | Import된 Event Store에 대해 `ValidationEngine` + `report.md` 생성 |
| 6 | `EvidenceExporter` + `ManualVerificationPackageGenerator` 산출물 run dir에 존재 |
| 7 | `--confirm-detection` 없이 exit code가 ValidationResult만 반영 (기존 동작 유지) |
| 8 | Unit + Integration + E2E (mock) pytest 통과 |

**범위 외 (완료 조건 아님):** live lab Stellar 관찰, multi-scenario single remote run, `dns_dummy` live, SMB real auth.

---

## 11. 최종 요약

| Gap | 해결책 | 변경 규모 |
|-----|--------|-----------|
| **G1** | `dsp-remote-scenario` = 패키지 CLI entry point. 입력 = `ScenarioExecutionRequest` JSON. 출력 = EventSyncBridge bundle. 내부 = `run_scenario()` + `write_jsonl_bundle()` | 신규 2파일 + pyproject 1줄 |
| **G2** | `RunManager.run()`에서 `create_execution_provider("webshell")` + per-scenario `RemoteEventCollector` + evidence export. `cli.py` flags | 수정 2파일 + path helper 추출 |

**핵심:** 새 orchestration을 만들지 않고, **이미 있는 Remote 파이프라인의 빈 칸(원격 실행체 + RunManager 연결)** 만 채운다.

---

*본 문서는 저장소 코드 기준 설계이며, 구현·코드 변경을 포함하지 않는다.*
