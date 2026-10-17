# 변경 타일 투영과 창별 결과 재사용

> 보드 실측 당시의 실행 경로를 기록한 문서다. 저장소에서 실행하는 방법은
> [README.md](README.md), 고정된 IP 버전과 비트스트림 해시는
> `results/publication_manifest.json`을 참조한다.

2026-10-17. PYNQ-Z2에서 M=32 Output Core와 투영코어 2개를 유지하고,
SW–HW Co-Design의 정상 갱신 경로를 변경 타일 기반으로 수정해 배포했다.
기존 210ms는 전체 창을 다시 처리하던 경로의 값으로, 정상적인 부분 갱신의
성능 기준이 아니다. 비트스트림과 FPGA 리소스 사용량은 변경하지 않았다.

## 현재 동작

- PS는 창별 투영 결과, 기하 정보, coverage mask, 이전 원본 픽셀을 캐시한다.
- 원본의 실제 변경 픽셀을 비교하고 bilinear 샘플링 범위를 포함해 영향을 받는
  목적지 타일만 두 HW 투영코어에 보낸다. 변경 영역이 넓게 신고되어도 실제
  픽셀 변화에 맞춰 좁힌다.
- 그대로인 창은 겹쳐 있어도 투영 결과를 재사용한다. 순서 변경, 숨김/복원,
  제거, 커서 이동은 캐시된 레이어로 영향 타일만 재합성한다.
- 창 이동/크기 변경은 해당 창의 기하 정보와 투영을 갱신한다. 다른 창은
  재사용하며 이전 위치와 새 위치의 타일만 재합성한다.
- 최종 픽셀도 비교해 실제로 달라진 출력 타일만 전달한다. 변화가 없으면
  투영 작업 0개, 출력 전달 데이터 0개, 출력 버퍼 교체 0회다.
- 처음 표시, 형식 전환, 실패 복구에는 전체 snapshot을 사용한다. 투영 실패 시
  무효 타일을 유지하고, 출력 실패 시 캐시에서 전체 snapshot을 다시 보낸다.

정상 실행 위치는 `/home/xilinx/bosio_dual_incremental_20261017`이며 원본 런타임과
이전 `display/` 경로는 보존했다. 설계 원칙은 `AGENTS.md`에 기록했다.

## 최종 보드 실측

128×96 원본, 24°×24° 시험 창은 전체 투영 후보가 72타일이다. 아래는 최종
14개 연속 시험에서 각 동작을 한 번씩 측정한 값이다. 평균/최악 지연 보장은 아니다.
합성은 backend 시간이고, 합성+전달은 daemon의 `last_compose_ms + last_upload_ms`다.
후자는 입력 대기부터 실제 화면 픽셀 출력까지의 지연을 측정한 값이 아니다.

| 동작 | HW 투영 타일 | 바뀐 출력 타일 | 합성 | 합성+전달 |
|---|---:|---:|---:|---:|
| 변화 없음 | 0 | 0 | 1.90ms | 2.60ms (commit 없음) |
| 8×8 원본 수정 | 5 (3+2) | 3 | 21.02ms | 53.52ms |
| 겹친 창 아래 8×8 수정 | 5 (3+2) | 3 | 20.78ms | 40.39ms |
| 같은 픽셀 재업로드 | 0 | 0 | 2.15ms | 2.86ms (commit 없음) |
| 창 순서 변경 | 0 | 29 | 9.38ms | 46.54ms |
| 창 숨김 | 0 | 72 | 8.26ms | 67.88ms |
| 창 다시 표시 | 0 | 72 | 12.37ms | 77.38ms |
| 시험 창 최초 표시 | 72 | 72 | 330.34ms | 410.33ms |
| 시험 창 이동 | 72 | 135 | 325.69ms | 451.81ms |

8×8 수정의 출력 packet은 832 words (3,328 bytes)다. 이동 시험은 해당 창만
투영하고 다른 창 190타일을 재사용했으며 원본 texture 재업로드는 0 words였다.
최종 중앙 자세(yaw/pitch=0°, FOV 60°×45°) 출력은 3.003초간 180프레임,
59.94fps였고 센서 추적을 복원했다. 이는 완료된 장면의 출력 속도다.

출력 드라이버는 변경 데이터만 복사하고 인접한 cache flush 범위를 묶는다.
최종 시험의 숨김 전달은 59.37ms였고, 이전 개별 flush 버전에서는 약 125ms였다.
프레임 경계 대기와 실행 변동이 있으므로 이 비교를 고정적인 배속으로 해석하지 않는다.

## 출력 형식과 일관성

CPU 장면은 4,220타일의 고정 payload 슬롯을 사용한다. palette/directory header는
4,476 words, 타일당 payload는 256 words, 전체 padded snapshot은 1,084,800 words
(4,339,200 bytes)다. 검은 타일은 directory=`0xffffffff`로 설정해 불필요한
출력 DDR 읽기를 막는다. 검은 불투명 창의 레이어 coverage는 별도로 유지한다.

BPT2 packet (`0x42505432`)은 16-word header와 타일당 272-word record다.
header는 magic, tile_words=256, record_count, total_words를 담는다. 각 record의
word 0은 `tile_id*256` payload offset, word 1은 tile_id, word 2는 directory 값
(`tile_id*1024` bytes 또는 `0xffffffff`)이고 word 16부터 256-word payload다.
모든 record의 범위, 중복, offset과 directory를 검증한 뒤 버퍼를 수정한다.

비활성 출력 버퍼의 변경 부분을 반영한 후 기존 프레임 경계 승인 절차로 교체하고,
이전 버퍼에도 같은 변경을 반영한다. 표시 중인 버퍼는 교체 승인 전에 수정하지 않는다.
cache flush는 directory 블록 및 인접 payload 구간으로 합치지만 실제 데이터 복사는
변경 word에 한정한다. 투영 scratch는 출력 버퍼와 분리되어 있다.

## 검증과 남은 비용

- 호스트 13개 시험 통과: 독립 CPU 전체 투영과 부분 갱신 비교, bilinear 경계,
  겹침, 순서, 이동, 숨김/복원, 커서의 극점/경계, 검은 레이어, 실패 재시도,
  BPT2 오류 입력의 무수정 보장, 두 출력 버퍼 일치, flush 병합.
- 실제 보드 14개 시험 통과. HW 경로 13개에서는 매번 전체 4,220타일을 캐시된
  레이어로 다시 합성해 incremental 결과 및 실제 활성 DDR 버퍼와 비교했다.
  불일치 word는 모두 0이었다. 이 보드 reference는 투영 자체의 독립 모델이
  아니라 부분 재합성/출력 일관성 검증이며, 독립 투영 비교는 호스트 시험에서 수행한다.
- 최종 output error 없음, 두 서비스 active, 재시작 횟수 0. 시험 창을 제거하고
  기존 데스크톱과 센서 추적으로 복원했다.
- 새 창/이동의 기하 정보 및 mask 준비 비용은 아직 크다. 이번 시험의 합성은
  약 241~330ms였다. 부분 내용 갱신의 21ms를 모든 동작의 비용으로 볼 수 없다.
- shaped/decorated 창 등은 native fallback이다. 이번 fallback 시험의 daemon
  합성은 약 3.69초였다. 복귀 시 기존 HW 투영 캐시는 재사용하지만 출력 형식
  전환을 위해 전체 snapshot을 전달한다.

원시 결과: `results/incremental_results.json`, `incremental_health.json`,
`incremental_pose_results.json`. 요약: `results/incremental_summary.json`.
배포 파일 SHA-256: `results/incremental_deployed_hashes.json`.
