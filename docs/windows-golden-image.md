# Windows Victim Golden Image — 운영자 가이드

> **목적**: VM 오케스트레이션이 아니라, XDR/NDR 탐지 품질을 높이기 위한 **현실적인 Windows Victim Golden Image** 제작 절차를 표준화합니다.  
> **범위**: 반복 가능한 구축 절차, PowerShell 부트스트랩(`bootstrap/windows-bootstrap.ps1`), 검증 체크리스트(`config/windows-golden-checklist.md`), Sysprep/QCOW2 캡처는 별도 문서와 함께 사용합니다.  
> **전제**: Windows 설치, GUI 기반 튜닝, 최종 “현실감(realism)” 판단은 **운영자가 직접** 수행합니다. 본 문서와 스크립트는 그 전후의 **표준화·자동화**를 담당합니다.

---

## 1. 권장 Windows 버전

| 우선순위 | 에디션 | 비고 |
|----------|--------|------|
| **권장** | **Windows 11 Pro** (x64) | 최신 엔드포인트 행태, 브라우저/스토어/Defender 업데이트 주기가 실제 기업 노트북과 유사 |
| 대안 | **Windows 10 Pro** (22H2 등, x64) | 하드웨어/라이선스 제약 시 fallback |

- **Home 에디션**은 도메인 가입·일부 GPO 대체 수단이 제한될 수 있어 Pro 이상을 권장합니다.  
- **평가판(Evaluation)** 사용 시 만료일·재활성화 정책을 운영 문서에 명시해 두세요.

---

## 2. VM 권장 스펙 (Golden Image 제작용)

Golden Image를 **만들 때**와 **런타임에서 복제해 돌릴 때** 모두 고려합니다.

| 항목 | 권장 (제작/일반 랩) | 메모 |
|------|---------------------|------|
| **vCPU** | 2~4 | Sysprep, 업데이트, Office 설치 시 2 vCPU는 다소 답답할 수 있음 |
| **RAM** | **8 GiB** (최소 4 GiB) | Windows 11 + 브라우저 + Defender 실시간 검사 동시 부하 |
| **디스크** | **80~120 GiB** (thin 프로비저닝 가능) | 업데이트·앱·로그 여유; QCOW2 sparse 활용 시 호스트 디스크는 단계적으로 증가 |

`config/lab-vms.json`의 `windows-victim` 예시는 **2 vCPU / 4 GiB / 60 GiB**로 되어 있으나, **이미지 제작 단계**에서는 위 권장에 가깝게 잡고 완성 후 필요 시 스펙을 낮춰도 됩니다.

---

## 3. 펌웨어: BIOS vs UEFI

| 모드 | 권장 |
|------|------|
| **UEFI** | **권장** — 최신 Windows·BitLocker·Secure Boot 시나리오와 정합 |
| Legacy BIOS | 구형 템플릿 호환만 필요할 때 |

KVM/QEMU에서는 OVF/템플릿 정책에 맞게 `ovmf` 사용 여부를 통일하세요.

---

## 4. 디스크 버스: SATA vs VirtIO

| 버스 | 장단 |
|------|------|
| **VirtIO (virtio-scsi 또는 virtio-blk)** | I/O 성능 좋음; **VirtIO 드라이버 ISO**를 설치 단계에서 미리 주입하는 것이 안전 |
| SATA (IDE/AHCI 에뮬) | 드라이버 추가 부담 적음; 성능은 상대적으로 낮음 |

**권장**: VirtIO + 설치 시 **Red Hat virtio-win** 게스트 드라이버 설치. Golden Image를 VirtIO로 고정하면 랩 런타임과 동일 구성을 유지하기 쉽습니다.

---

## 5. 네트워크 모델

- **브리지(br0)** 등 lab 브리지에 연결해 `10.10.10.0/24`와 동일 L2에 두는 구성을 전제로 합니다 (자세한 토폴로지는 `docs/specs/006-network-architecture/spec.md`, Reverse NAT는 `docs/specs/010-reverse-nat-policy/spec.md`).  
- DNS는 **랩 게이트웨이/리졸버**를 사용하는 패턴이 일반적입니다 (`config/lab-vms.json`의 `network.dns` 참고).

---

## 6. 고정 IP / 게이트웨이 / DNS (본 가이드 기준)

본 문서의 **Golden Image 내부 정적 주소** 표준은 아래와 같습니다.

| 항목 | 값 |
|------|-----|
| **호스트 IP** | `10.10.10.30` |
| **서브넷 마스크** | `255.255.255.0` (`/24`) |
| **게이트웨이** | `10.10.10.1` |
| **DNS (기본)** | `10.10.10.1` (랩에서 제공하는 DNS/forwarder에 맞춤) |

### 6.1 `lab-vms.json`과의 정합성

`config/lab-vms.json`의 **`windows-victim.internal_ip`는 `10.10.10.30`**이 캐논입니다. Golden Image(게스트 OS)의 정적 IP·Reverse NAT DNAT 대상·문서는 모두 이 값과 **일치**해야 합니다.

| VM (역할) | `internal_ip` (캐논) |
|-----------|----------------------|
| `sensor-vm` | `10.10.10.10` |
| `linux-server` | `10.10.10.20` |
| `windows-victim` | `10.10.10.30` |

서브넷을 옮기거나 VM을 추가하면 `internal_ip`와 DNAT·게스트 네트워크 설정을 **한 세트**로 갱신합니다.

---

## 7. 원격 관리 채널

### 7.1 RDP

- 설정 → 시스템 → 원격 데스크톱 → **켜기**.  
- NLA(네트워크 수준 인증)는 랩 정책에 따라 유지(권장) 또는 테스트용으로 완화(비권장).  
- 외부에서 접근 시 appliance의 **Reverse NAT**에 선언된 호스트 포트(예: README의 `3389 → 10.10.10.30:3389`)를 사용합니다.

### 7.2 OpenSSH Server

- Windows Optional Feature **OpenSSH Server** 설치, `sshd` 자동 시작, 방화벽 규칙.  
- 자동화: `bootstrap/windows-bootstrap.ps1`.  
- (선택) Atomic Red Team 저장소·모듈만 올릴 때는 같은 디렉터리의 `bootstrap/atomic-red-team-windows.ps1` — Defender 끄지 않음, 기본 테스트 비실행.

- `Enable-PSRemoting`, WinRM 리스너, 방화벽 규칙.  
- HTTPS 리스너·인증서는 랩 보안 수준에 맞게 운영자가 구성(또는 HTTP + 제한된 네트워크만).  
- 자동화: 동일 부트스트랩 스크립트.

---

## 8. Windows Defender 유지 정책

- **Golden Image에서는 Defender를 끄지 않는 것**을 기본 원칙으로 합니다 (XDR/EDR 대비 시그널).  
- **예외(Exclusion)**는 테스트 시 오탐·시나리오 실패를 줄이기 위해 **최소 범위·명시적 경로**로만 추가하고, 문서에 사유를 남깁니다.  
- 부트스트랩 스크립트에는 **선택적 placeholder**만 포함되어 있으며, 실제 exclusion은 운영자 판단 하에 적용합니다.

---

## 9. Sysmon

- [Sysinternals Sysmon](https://learn.microsoft.com/sysinternals/downloads/sysmon) + 검증된 XML 구성(예: SwiftOnSecurity 등 커뮤니티 규칙, 또는 사내 표준)을 권장합니다.  
- 설치 후 **이벤트 로그 `Microsoft-Windows-Sysmon/Operational`**에서 이벤트 수신 확인.  
- 부트스트랩: `-SysmonInstallerPath`와 **`-SysmonConfigPath`(필수)** 를 함께 주면 `Sysmon.exe -accepteula -i <xml>`로 설치, 미지정 시 건너뜀.

---

## 10. 브라우저 / Office / PDF

| 구분 | 권장 |
|------|------|
| **브라우저** | Microsoft Edge(기본) + **Chrome 또는 Firefox** 중 1개 이상(실제 기업 패턴) |
| **Office** | Microsoft 365 Apps 또는 Office 2019/2021 **평가/볼륨** 정책에 맞는 설치; **매크로·보호된 보기** 기본값 유지 권장 |
| **PDF** | Edge PDF + **Adobe Reader** 또는 대체 뷰어(첨부파일 시나리오용) |

라이선스·오프라인 설치 미디어는 조직 정책에 따릅니다.

---

## 11. 테스트용 로컬 사용자

| 용도 | 예시 (이름은 예시일 뿐, 비밀번호는 강제 변경) |
|------|------------------------------------------------|
| 일반 사용자 | `labuser` |
| 로컬 관리자(별도) | `labadmin` (필요 시) |

- 비밀번호는 **랩 전용 강도**로 통일하고, **문서/비밀관리소**에만 보관합니다.  
- Sysprep 일반화 시 **내장 Administrator 외 계정** 동작은 `docs/windows-sysprep-guide.md`를 따릅니다.

---

## 12. SMB 활성화 범위

- **목적**: lateral movement / NDR 시그널(445, 이름 파이프 등)을 위해 **제한적으로** 파일 공유를 켤 수 있습니다.  
- **권장 범위**: `10.10.10.0/24` 등 **랩 서브넷만** 바인딩/방화벽 허용(전 인터넷 개방 금지).  
- 공유 폴더는 `C:\XdrLab\shares\` 등 명확한 루트 아래에 두고, 더미 문서를 배치합니다.  
- 부트스트랩: `-EnableLabSmb` 시 최소 공유 생성(운영자가 최종 ACL·범위 검증).

---

## 13. Windows Update 정책

- **제작 단계**: 최신 누적 업데이트까지 적용한 뒤 Sysprep하는 것이 일반적입니다.  
- **랩 고정 이미지**: 시나리오 재현을 위해 **특정 시점으로 동결**할 수 있으나, Defender 서명·취약점 시나리오와 트레이드오프가 있습니다.  
- 조직에서 WSUS/업데이트 링을 쓰면 Golden Image에도 동일 정책을 반영해 “현실적인 업데이트 지연”을 재현할 수 있습니다.

---

## 14. 로그 정책 (감사·보존)

- **고급 감사 정책**(로그온, 객체 액세스 등)은 시나리오·센서 스펙에 맞게 켭니다.  
- 이벤트 로그 **최대 크기**를 기본값보다 크게(예: 100MB 이상) 잡아 순환 시 데이터 유실을 줄입니다.  
- **PowerShell** 모듈/스크립트 블록 로깅은 랩에서 시그널이 중요하면 활성화 검토.

---

## 15. Event Viewer 확인 위치 (요약)

| 로그 / 채널 | 확인 내용 |
|-------------|-----------|
| **Windows Logs → Security** | 로그온(4624/4625), Kerberos, 특권 사용 등 |
| **Windows Logs → System** | 드라이버, 서비스, 장치 |
| **Windows Logs → Application** | 애플리케이션 오류 |
| **Applications and Services Logs → Microsoft → Windows → PowerShell/Operational** | 스크립트 실행 |
| **Microsoft-Windows-Sysmon/Operational** | 프로세스·네트워크·레지스트리 등 |

---

## 16. CALDERA Agent (Sandcat) 부트스트랩

1. appliance 호스트에서 `aella_cli lab scenario agent deploy` 실행.  
2. 생성물: `runtime/caldera-agent/bootstrap-windows.ps1` (경로는 `docs/caldera-integration.md` 참고).  
3. Windows Victim에서 **관리자 PowerShell**로 해당 스크립트 실행.  
4. CALDERA UI → Agents에서 **beacon** 확인.  
5. `config/caldera-lab.json`의 `agent_vm_map.windows-victim.host_substrings`에 실제 호스트명 패턴이 포함되는지 확인.

`bootstrap/windows-bootstrap.ps1`은 **CALDERA 서버에 직접 연결하지 않으며**, 위 절차를 안내하는 헬퍼 파일을 남깁니다.

---

## 17. Atomic Red Team (선택)

- [Atomic Red Team](https://github.com/redcanaryco/atomic-red-team)을 설치하면 CALDERA 외 **재현 가능한 원자 테스트**를 WinRM/로컬에서 실행하기 좋습니다.  
- 실행은 `Invoke-AtomicTest` 등으로 제한된 시나리오만 선택하고, **랩 격리**를 전제로 합니다.

---

## 18. noVNC / Web Console 검증

- 호스트에 **noVNC + websockify** 등(예: `installer/lab-host-web-console-deps.sh` 참고)이 설치되어 있어야 합니다.  
- 권장 포트맵: `XDR_LAB_WEB_CONSOLE_PORT_MAP="windows-build=6081,windows-victim=6082"`  
  (QEMU VNC는 `127.0.0.1:5901` / `5902`, 외부 노출은 websockify만)
- 기동 후 브라우저 접속:
  - `http://127.0.0.1:6081/` — windows-build  
  - `http://127.0.0.1:6082/` — windows-victim  
- 검증: `aella_cli lab web-console verify windows-victim`,  
  `${XDR_ROOT}/bootstrap/validate-web-console.sh`  
- 상세: `docs/web-console.md`, `scripts/vnc_proxy_helpers.sh`

---

## 19. 스냅샷 테스트

- Golden Image **완성 직후** “클린 베이스라인” 스냅샷 1개.  
- 시나리오 실행 후 **revert**하여 동일 초기 상태로 복귀하는지 확인.  
- 스냅샷 명명 규칙 예: `golden-baseline-YYYYMMDD`, `pre-caldera-YYYYMMDD`.

---

## 20. 실제 XDR / NDR 탐지 확인 포인트

운영자·센서 제품에 따라 항목을 조정합니다.

| 영역 | 확인 아이디어 |
|------|----------------|
| **EDR/XDR (호스트)** | 악성/의심 프로세스, LSASS 접근, 스크립트 인터프리터 자식 프로세스, WMI/PowerShell 원격, 새 서비스 등록 |
| **네트워크 (NDR)** | DNS 이상, 비정상 TLS SNI, SMB 세션, 긴 세션·비정상 포트 스캔 |
| **CALDERA 시나리오** | `aella_cli lab scenario run …` 후 `scenario status`, 미러 포트/센서 콘솔에서 동일 타임윈도우 이벤트 상관 |
| **로그 소스** | Defender, Sysmon, Security, PowerShell 통합 |

---

## 21. 현실감(Realism) 가이드 — 운영 팁

**Sysprep 전**에, 운영자가 GUI로 다음을 **어느 정도** 채워 두는 것이 NDR/XDR 탐지 평가에 유리한 경우가 많습니다(과도한 개인정보·실데이터는 금지).

- **바탕화면·작업 표시줄**: 자주 쓰는 앱 아이콘, 고정된 브라우저·파일 탐색기.  
- **브라우저 기록·즐겨찾기**: 사내 포털 더미 URL, 내부 문서 링크(가짜), 검색 몇 건.  
- **최근 파일 / 빠른 실행**: Office·PDF 샘플을 열어 MRU 생성.  
- **사용자 폴더 구조**: `Documents`, `Downloads`, `Desktop`에 현실적인 디렉터리·파일명.  
- **Office 문서 / PDF**: 매크로 없는 샘플, 표·이미지 포함 보고서 흉내.  
- **설치된 앱**: 유틸(압축툴, 메모장 대체, 메신저 흉내 앱 등)을 **과하지 않게** 추가.  
- **알림·트레이**: 업데이트 대기·OneDrive(사용 시) 등 “쓰는 PC” 느낌.

최종 “충분히 현실적인가”는 **운영자 판단**이며, 본 레포는 절차와 자동화만 제공합니다.

---

## 22. 부트스트랩 스크립트 실행

관리자 PowerShell에서 저장소의 스크립트를 VM으로 복사한 뒤:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine -Force
cd C:\path\to\xdr-lab-appliance\bootstrap
.\windows-bootstrap.ps1
```

매개변수(Chocolatey, 브라우저, Sysmon, SMB 등)는 `windows-bootstrap.ps1` 상단 주석과 `Get-Help .\windows-bootstrap.ps1 -Full`을 참고합니다.

---

## 23. 다음 문서

| 문서 | 내용 |
|------|------|
| `docs/windows-sysprep-guide.md` | 일반화 전후 체크리스트, CALDERA/Defender/계정 주의 |
| `docs/windows-capture-qcow2.md` | qcow2 변환·압축·해시·매니페스트·배포 |
| `config/windows-golden-checklist.md` | 통합 검증 체크리스트 |
