# Windows Golden Image — QCOW2 캡처 및 배포 아티팩트 가이드

> Sysprep로 **전원 off**된 Windows VM의 디스크를 **qcow2**로 정리하고, **압축·무결성·매니페스트 등록·(선택) 객체 스토리지 업로드**까지의 운영자 절차입니다.  
> 명령은 **appliance/KVM 호스트**에서 실행하는 것을 전제로 합니다(경로·VM 이름은 환경에 맞게 바꿉니다).

---

## 1. 사전 조건

- VM이 **`shut off`** 상태일 것(Sysprep `/shutdown` 직후가 이상적).  
- 게스트 파일시스템 일관성: 가능하면 **qemu-guest-agent**가 있었고 정상 종료되었는지 확인.  
- 호스트에 `qemu-img`, (선택) `zstd`, `sha256sum`, `virsh` 사용 가능.

---

## 2. VM 정상 종료 확인

```bash
virsh list --all
```

이미 꺼져 있으면 `shut off`로 표시됩니다. 켜져 있다면:

```bash
virsh shutdown <guest_name>
# 일정 시간 후에도 꺼지지 않으면(주의) 운영 정책에 따라 virsh destroy는 데이터 손상 위험이 있으므로
# 게스트 내 종료·Sysprep 완료 여부를 먼저 확인합니다.
```

---

## 3. 디스크 경로 확인

```bash
virsh domblklist <guest_name> --details
```

qcow2(또는 raw) **실제 파일 경로**를 메모합니다. 예: `/var/lib/libvirt/images/windows-victim.qcow2`.

---

## 4. qemu-img 로 복사·변환 (sparse 유지)

### 4.1 동일 포맷으로 복사(백업 스냅샷용)

```bash
qemu-img convert -p -O qcow2 -f qcow2 \
  /var/lib/libvirt/images/windows-victim.qcow2 \
  /tmp/windows-victim-golden.qcow2
```

- **Sparse**: `qcow2` 포맷은 기본적으로 **호스트에서 보이는 할당만** 사용합니다. `convert` 시 **할당되지 않은 영역은 sparse**로 유지되는 편입니다.  
- **`-p`**: 진행률 표시.

### 4.2 중간에 raw가 있다면

```bash
qemu-img convert -p -O qcow2 -f raw /path/to/disk.raw /tmp/windows-victim-golden.qcow2
```

---

## 5. (선택) qcow2 내부 압축

`qemu-img convert`에 **`-c`** 를 주면 **qcow2 내부의 copy-on-write 압축**을 시도합니다(버전에 따라 지원 확인).

```bash
qemu-img convert -p -O qcow2 -c -f qcow2 \
  /tmp/windows-victim-golden.qcow2 \
  /tmp/windows-victim-golden-compressed.qcow2
```

---

## 6. zstd로 아카이브 압축 (배포용)

대용량 이미지를 네트워크로 옮길 때 흔히 **zstd**를 사용합니다.

```bash
zstd -19 -T0 -o /tmp/windows-victim.qcow2.zst /tmp/windows-victim-golden.qcow2
```

- **`-19`**: 압축률↑, 시간↑ (환경에 맞게 `-10` 등으로 조정).  
- 원본 qcow2는 배포 정책에 따라 **보관 또는 삭제**.

---

## 7. SHA256 체크섬 생성

```bash
sha256sum /tmp/windows-victim.qcow2.zst | tee /tmp/windows-victim.qcow2.zst.sha256
```

배포 시 **동일 명령으로 검증**합니다:

```bash
sha256sum -c /tmp/windows-victim.qcow2.zst.sha256
```

---

## 8. `config/images-manifest.json` 등록 예시

`config/images-manifest.json`의 `windows-victim-golden` 항목을 **실제 URL·해시·크기**로 교체합니다.

```json
{
  "name": "windows-victim-golden",
  "vm_role": "windows-victim",
  "version": "2026.05.13-1",
  "url": "https://YOUR_BUCKET.r2.cloudflarestorage.com/xdr-lab/windows-victim.qcow2.zst",
  "compressed": true,
  "compression": "zst",
  "sha256": "<sha256_of_zst_file>",
  "size_bytes": 1234567890,
  "output_path": "images/windows/windows-victim.qcow2",
  "required": true,
  "keep_compressed_artifact": true
}
```

- **`size_bytes`**: `.zst` 파일의 바이트 크기(정수).  
- **`output_path`**: 압축 해제 후 최종 qcow2가 놓일 상대 경로(저장소 관례에 맞춤).  
- 매니페스트 상위의 `"enabled": true` 및 환경변수 `XDR_LAB_USE_IMAGE_MANIFEST` 등은 프로젝트 배포 문서를 따릅니다.

---

## 9. Cloudflare R2 업로드 예시

[R2는 S3 호환 API](https://developers.cloudflare.com/r2/api/s3/api/)를 제공합니다. 자격 증명은 **환경변수 또는 프로파일**로 주입하고, 버킷/엔드포인트는 조직 값으로 바꿉니다.

```bash
export AWS_ACCESS_KEY_ID='...'
export AWS_SECRET_ACCESS_KEY='...'
export AWS_ENDPOINT_URL='https://<ACCOUNT_ID>.r2.cloudflarestorage.com'

aws s3 cp /tmp/windows-victim.qcow2.zst \
  s3://YOUR_BUCKET/xdr-lab/windows-victim.qcow2.zst \
  --endpoint-url "$AWS_ENDPOINT_URL"

aws s3 cp /tmp/windows-victim.qcow2.zst.sha256 \
  s3://YOUR_BUCKET/xdr-lab/windows-victim.qcow2.zst.sha256 \
  --endpoint-url "$AWS_ENDPOINT_URL"
```

퍼블릭 다운로드 URL이 별도라면(커스텀 도메인·서명 URL), 그 URL을 `images-manifest.json`의 `url`에 넣습니다.

---

## 10. aria2c 다운로드 및 검증 예시

고속 병렬 다운로드 예:

```bash
aria2c -x 16 -s 16 -k 1M \
  -o windows-victim.qcow2.zst \
  'https://YOUR_BUCKET.r2.cloudflarestorage.com/xdr-lab/windows-victim.qcow2.zst'

# 체크섬 파일이 같은 베이스에 있으면
aria2c -x 16 -s 16 \
  -o windows-victim.qcow2.zst.sha256 \
  'https://YOUR_BUCKET.r2.cloudflarestorage.com/xdr-lab/windows-victim.qcow2.zst.sha256'

sha256sum -c windows-victim.qcow2.zst.sha256
```

압축 해제:

```bash
zstd -d windows-victim.qcow2.zst -o windows-victim.qcow2
sha256sum windows-victim.qcow2   # (선택) qcow2 자체의 기대 해시를 별도 보관한 경우에만 비교
```

---

## 11. 디스크 이미지 무결성(선택 고급)

조직 정책에 따라 **NBD 마운트 없이** `qemu-img check`로 qcow2 무결성만 확인할 수 있습니다:

```bash
qemu-img check /path/to/windows-victim.qcow2
```

---

## 12. 운영 메모

- **스냅샷이 있는 qcow2**를 그대로 복사하면 backing chain이 복잡해질 수 있어, **베이스만 flatten**이 필요한 경우 `qemu-img convert`로 **단일 파일**로 합치는 방식을 검토합니다.  
- 최종 아티팩트명에 **빌드 날짜·빌드 번호**를 넣어 추적 가능하게 합니다.

---

## 13. 관련 문서

- `docs/windows-golden-image.md`  
- `docs/windows-sysprep-guide.md`  
- `config/windows-golden-checklist.md` (`qcow2 exported` 항목)
