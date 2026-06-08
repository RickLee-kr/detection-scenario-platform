# Architecture Decision Records (ADR)

DSP의 주요 아키텍처 결정을 기록한다. 구현 전 Agent·개발자는 관련 ADR을 먼저 읽는다.

| ADR | Title | Status |
|-----|-------|--------|
| [0001](./0001-python-over-bash.md) | Python over Bash for DSP | Accepted |
| [0002](./0002-event-store-as-sot.md) | Event Store as Single Source of Truth | Accepted |
| [0003](./0003-scenario-plugin-architecture.md) | Scenario Plugin Architecture | Accepted |
| [0004](./0004-no-stdout-validation.md) | Prohibition of stdout/grep Validation | Accepted |
| [0005](./0005-sqlite-primary-storage.md) | SQLite as Primary Event Store | Accepted |
| [0006](./0006-execution-provider-architecture.md) | Execution Provider Architecture | Accepted |
| [0007](./0007-webshell-execution-provider-architecture.md) | Webshell Execution Provider Architecture | Accepted |

## Format

Each ADR follows:

- **Context** — 배경과 제약
- **Problem** — 해결할 문제
- **Alternatives Considered** — 검토한 대안
- **Decision** — 선택
- **Consequences** — 결과 (긍정·부정)

## Rules

- ADR는 `detection-scenario-platform/docs/adr/`에만 추가
- Accepted ADR 변경 시 새 ADR로 supersede (기존 ADR에 `Superseded by` 링크)
- 구현이 ADR와 불일치하면 구현이 잘못된 것 (ADR 먼저 수정)
