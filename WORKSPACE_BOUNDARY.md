# Workspace Safety / Repository Boundary

**문서 버전:** 0.2.0 (Phase 0.1)  
**적용 범위:** `detection-scenario-platform/` 및 이를 구현하는 모든 후속 Phase

---

## 1. Context

현재 Cursor workspace(`xdr-lab-appliance`)에는 두 성격의 프로젝트가 공존한다.

| 프로젝트 | 역할 | Phase 0 조작 |
|----------|------|--------------|
| **XDR Lab Deployment Automation** | KVM, 네트워크, 센서 배포, CLI, bootstrap | **수정 금지** |
| **Detection Scenario Platform (DSP)** | Safe PoC 탐지 시나리오 생성·검증·리포트 | **본 디렉터리에만 작성** |

DSP는 PoC Traffic Generator 완료 후 deployment automation의 **공격 시나리오 실행 컴포넌트**로 통합될 예정이다.  
**Phase 0에서는 통합을 설계만 하고 구현하지 않는다.**

---

## 2. Absolute Rules

### 2.1 수정 금지 (Read-Only)

다음 영역의 **어떤 파일도** 생성·수정·삭제하지 않는다.

- XDR Lab Deployment Automation 코드 전반
- `appliance/`, `bootstrap/`, `installer/`, `config/`
- `scripts/` (deployment, VM, Caldera, NAT 등)
- `docs/specs/`, `docs/skills/` (기존 governance)
- Terraform, Ansible, Docker Compose (존재 시)
- `.github/workflows/` 및 CI/CD
- `requirements*.txt`, `setup.py`, `pyproject.toml`, `package.json`
- 루트 `README.md`, `xdr-lab.sh`, `aella_cli` 관련 파일
- 레거시 PoC: `stellar_poc*.sh` (읽기·분석만)

### 2.2 금지 작업

| 금지 | 이유 |
|------|------|
| 기존 자동화 플로우 변경 | deployment 안정성 |
| DSP ↔ deployment import/link/integration | Phase 0 비범위 |
| deployment에 hook 추가 | 조기 결합 방지 |
| 기존 디렉터리 구조 변경 | workspace 무결성 |
| 기존 README/config/workflow 덮어쓰기 | 운영 문서 보호 |

### 2.3 허용 작업 (Phase 0)

| 허용 | 위치 |
|------|------|
| 새 디렉터리 생성 | `detection-scenario-platform/` |
| 새 문서 파일 생성 | `detection-scenario-platform/*.md` |
| 레거시 Bash PoC 읽기·분석 | repo 전역 (read-only) |
| deployment automation 읽기 | repo 전역 (read-only) |

---

## 3. Canonical Source Rule

### 3.1 Single Source of Truth for DSP

| Location | Status | Agent Action |
|----------|--------|--------------|
| **`detection-scenario-platform/`** | **Canonical SOT** | 모든 문서·코드·테스트·ADR·설계·구현 |
| `docs/detection-scenario-platform/` | **Historical Draft** | **읽기만, 수정·삭제·동기화 금지** |
| Workspace 나머지 | Deployment + Legacy | **읽기만** |

> `docs/detection-scenario-platform/`는 Phase 0 초기 초안이며 **역사적 참고용**이다.  
> 내용이 canonical과 다를 경우 **`detection-scenario-platform/`이 항상 우선**한다.

### 3.2 What Must Live Under Canonical Root Only

| Artifact | Path (under canonical root) |
|----------|----------------------------|
| Spec documents | `*.md`, `docs/adr/` |
| Python package | `dsp/` (Phase 1+) |
| Scenario plugins | `scenarios/<id>/` |
| Detection adapters | `adapters/<vendor>/` (Phase 3+) |
| Tests | `tests/` |
| Cursor Skill (future) | `.cursor/skills/`는 repo root이나 **내용은 DSP spec에서 생성** |

**금지:** canonical 산출물을 `docs/detection-scenario-platform/`, `appliance/`, `scripts/` 등에 복제·미러링하여 이중 SOT 생성.

### 3.3 Canonical Project Root Layout

```
xdr-lab-appliance/                    ← workspace root (건드리지 않음)
├── appliance/                        ← READ ONLY
├── bootstrap/                        ← READ ONLY
├── scripts/                          ← READ ONLY
├── stellar_poc*.sh                   ← READ ONLY (분석 참고)
├── docs/detection-scenario-platform/ ← Historical Draft (READ ONLY, NOT canonical)
└── detection-scenario-platform/      ← **CANONICAL SOT (Phase 0+)**
    ├── README.md
    ├── WORKSPACE_BOUNDARY.md         ← 본 문서
    ├── PROJECT_CHARTER.md
    ├── ARCHITECTURE_SPEC.md
    ├── SCENARIO_FRAMEWORK_SPEC.md
    ├── EVENT_STORE_SPEC.md
    ├── SKILL_SPEC.md
    ├── DETECTION_CATALOG.md
    ├── docs/adr/
    └── (Phase 1+) dsp/, scenarios/, tests/
```

Phase 1 구현 시에도 Python 패키지·테스트·시나리오 플러그인은 **`detection-scenario-platform/` 하위에만** 추가한다.

---

## 4. Future Integration (Design Only, No Implementation)

통합은 **Phase 3 이후** 별도 승인 하에 진행한다. Phase 0–2 설계 방향:

```
[Future]
aella_cli poc run --engine dsp
        │
        ▼
detection-scenario-platform/dsp/runner   ← DSP 패키지 (독립)
        │
        ▼ (optional, future adapter)
xdr-lab deployment automation          ← VM up, target_net 제공만
```

**Phase 0–2에서 하지 않는 것:**

- `aella_cli` 서브커맨드 추가
- `appliance_cli.py` 수정
- bootstrap/installer에서 DSP 호출
- shared config 파일 (`config/*.json`) 수정

통합 시 필요한 **인터페이스**는 `ARCHITECTURE_SPEC.md` §9.3에 문서화되어 있으나 코드는 작성하지 않는다.

---

## 5. Agent / Cursor Compliance Checklist

작업 시작 전 확인:

- [ ] 수정 대상 경로가 `detection-scenario-platform/` 이하인가?
- [ ] deployment / bootstrap / installer 파일을 건드리지 않는가?
- [ ] 레거시 PoC 파일을 수정하지 않는가?
- [ ] import, hook, CI 변경을 포함하지 않는가?
- [ ] Phase 0–0.1에서 Python/requirements/docker 코드를 추가하지 않는가?
- [ ] `docs/detection-scenario-platform/` (Historical Draft)를 수정·삭제하지 않았는가?
- [ ] 산출물이 `detection-scenario-platform/` canonical root에만 있는가?

하나라도 해당되면 **작업 중단**.

---

## 6. Related Documents

- [PROJECT_CHARTER.md](./PROJECT_CHARTER.md) — §3.1 Repository Boundary
- [SKILL_SPEC.md](./SKILL_SPEC.md) — §16 Workspace Boundary
