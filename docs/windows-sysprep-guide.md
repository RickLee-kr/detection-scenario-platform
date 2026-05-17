# Windows Sysprep — Golden Image 일반화 가이드

> Golden Image를 **다른 하드웨어 프로필/새 SID**로 배포하기 위해 `sysprep`을 수행할 때의 운영자 체크리스트와 주의사항입니다.  
> CALDERA 에이전트, Defender, 로컬 계정은 **일반화 순간의 상태**가 최종 디스크에 반영됩니다.

---

## 1. Sysprep이 하는 일 (요약)

- **일반화(generalize)**: SID, 하드웨어 드라이버 정보 등 “기계 고유” 성격을 제거(또는 재생성 준비).  
- **OOBE**: 다음 부팅 시 OOBE(Out-of-Box Experience) 흐름을 태울지 여부를 제어(템플릿에 따라 `unattend.xml`과 조합).

본 랩에서는 운영자가 **수동 Sysprep GUI 또는 명령행**으로 수행하는 것을 전제로 합니다.

---

## 2. Sysprep 전 체크리스트

운영자가 순서대로 확인합니다.

- [ ] **Windows Update**: 정책에 맞는 수준까지 적용(또는 의도적으로 동결 버전 문서화).  
- [ ] **불필요한 장치/드라이버**: 제작용 ISO 마운트·임시 디스크 제거.  
- [ ] **비밀 정보**: RDP·SSH 키·브라우저에 저장된 실계정 토큰·클라우드 동기화 제거(랩용 계정만 유지).  
- [ ] **CALDERA Sandcat**: 일반화 **전**에 에이전트를 제거할지, OOBE 이후에 다시 설치할지 **표준을 정함** (아래 §4).  
- [ ] **Defender / Sysmon**: 의도한 최종 상태(실시간 보호 on, exclusion 최소화)인지 확인.  
- [ ] **로컬 계정**: 최종 랩에서 필요한 계정만 남기고, 비밀번호는 문서화된 랩 정책에 맞게 설정.  
- [ ] **BitLocker**: 켜져 있으면 일반화 전 상태·복구 키 처리 방침 확인(대부분 랩 Golden Image는 BitLocker off).  
- [ ] **앱 라이선스**: Office 등이 평가 만료 전인지, 재활성화 필요 여부 기록.  
- [ ] **시간대·언어**: `unattend.xml` 또는 OOBE에서 재적용할 값이면 현재 상태는 덜 중요.  
- [ ] **네트워크 정적 IP**: Sysprep 후 첫 부팅에서 DHCP로 바뀌는지, `unattend.xml`로 다시 고정할지 결정.

---

## 3. 일반화 시 일반 주의사항

1. **실행 중인 앱·백업 에이전트**를 최대한 종료합니다.  
2. **일반화는 되돌리기 어렵습니다.** 반드시 **스냅샷** 또는 **디스크 백업** 후 진행합니다.  
3. **도메인 가입 PC**는 일반화 전에 도메인에서 제거해야 하는 경우가 많습니다(랩 로컬 계정만 쓰면 해당 없음).  
4. **스토어 앱**이 깨진 상태면 Sysprep이 실패할 수 있으므로, 제작 중 설치한 UWP 앱을 점검합니다.

---

## 4. CALDERA Agent 관련 주의

| 전략 | 설명 |
|------|------|
| **A. Sysprep 전 제거** | 일반화된 이미지에 **고정 paw/호스트 ID**가 남지 않음. OOBE 완료 후 `bootstrap-windows.ps1`으로 재등록. **권장**에 가까움. |
| **B. 이미지에 에이전트 포함** | 재배포마다 동일 구성이 필요할 수 있으나, **SID/머신 ID 충돌**, CALDERA 측 **중복 agent** 이슈 가능. 비권장이 많음. |

운영 표준: **A**를 기본으로 하고, `docs/caldera-integration.md`의 agent deploy 절차를 OOBE 이후 첫 실행에 넣습니다.

---

## 5. Defender 관련 주의

- 일반화는 **Defender 구성 자체를 “삭제”하지 않습니다**만, OOBE/unattend에 따라 WIM 적용 순서가 바뀌면 초기 정책이 달라질 수 있습니다.  
- **Exclusion**을 이미지에 박아 넣었다면, 보안 검토와 문서화를 필수로 합니다.  
- Sysprep 실패 로그에 **Tamper Protection** 관련 메시지가 나오면, 일시적으로 정책 조정이 필요할 수 있습니다(조직 정책 준수).

---

## 6. 로컬 계정 관련 주의

- **Administrator** 활성화 여부, **자동 로그온** 설정은 보안상 랩에서만 제한적으로 사용합니다.  
- `CopyProfile` 등 레거시 옵션은 최신 OS에서 권장되지 않거나 동작이 달라질 수 있어 **문서화된 unattend만** 사용합니다.  
- **빈 암호** 로컬 계정은 RDP 등에서 막힐 수 있습니다.

---

## 7. Shutdown 옵션

- **`/shutdown`**: Sysprep 완료 후 **전원 off** — 가상화 환경에서 **디스크 일관성** 확보에 유리(캡처 직전에 자주 사용).  
- **`/reboot`**: 즉시 재부팅(다음 단계 자동화와 함께 쓸 때).

Golden Image **QCOW2 추출 직전**에는 보통 **`/shutdown`**을 선택합니다.

---

## 8. OOBE 옵션

- **`/oobe`**: 다음 부팅 시 OOBE를 실행 — **새 배포마다 이름·라이선스·첫 계정**을 다시 잡을 수 있음.  
- 랩에서 **완전 무인**을 원하면 `unattend.xml`로 OOBE를 자동화합니다(별도 작성·검증 필요).

---

## 9. 추천 Sysprep 명령 (수동 일반화)

관리자 **CMD**에서(경로는 환경에 맞게):

```cmd
cd /d C:\Windows\System32\Sysprep
sysprep /generalize /oobe /shutdown
```

- **GUI 사용 시**: System Preparation Tool → **Out-of-Box Experience**, **Generalize** 체크, **Shutdown** 선택.

---

## 10. Sysprep 실패 시 흔한 원인

| 증상/로그 | 가능 원인 | 조치 방향 |
|-----------|-----------|-----------|
| **Setupact.log**에 스토어 앱 오류 | 손상/비호환 UWP 패키지 | 문제 패키지 제거 후 재시도 |
| **도메인 가입 상태** | 도메인 멤버에서 generalize | 도메인 탈퇴 후 로컬만으로 일반화 |
| **디바이스 드라이버** | 특정 필터/가상화 드라이버 | 제작용 드라이버 제거·업데이트 |
| **클라우드 동기화/OneDrive** | 로그온된 사용자 프로필 잠금 | 동기화 중단·로그오프 후 sysprep |
| **최근 Windows 업데이트 미완료** | 재부팅 대기 | 업데이트 완료 및 재부팅 후 실행 |

로그 위치(참고): `C:\Windows\System32\Sysprep\Panther\` 등 — OS 빌드에 따라 세부 경로는 Microsoft 문서를 확인합니다.

---

## 11. Sysprep 이후 운영자 작업

1. VM 전원이 꺼진 상태에서 **디스크만 캡처** (`docs/windows-capture-qcow2.md`).  
2. 첫 배포 부팅 후: **네트워크 IP**, **호스트명**, **CALDERA agent 재배포** 여부를 체크리스트에 따라 검증.

---

## 12. 관련 문서

- `docs/windows-golden-image.md` — 전체 Golden Image 절차  
- `config/windows-golden-checklist.md` — `Sysprep completed` 항목 포함
