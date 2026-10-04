# BS25 DDR 캐시와 드라이버

출력 코어 기본값은 64바이트 라인, 16KiB 데이터 캐시, 2-way입니다.
장면 셀 데이터는 DDR에 유지하고, 팔레트·타일 디렉터리와 자주 읽는 라인만
BRAM에 저장합니다. 자세에 따라 셀을 선택하는 투영은 RTL이 계속 수행합니다.
통합 실행의 기본 타일 분할은 M=16입니다.

상세 RTL 파라미터와 레지스터는
[출력 코어 캐시 문서](../hw/ip_repo/bosio_output_core_1.0/docs/CACHE_LINE.md)를
참고하세요. 파라미터는 합성 시 결정하며 변경 후 비트스트림을 다시 빌드합니다.
현재 어댑터는 AXI 32비트, demand read이며 타일 prefetch는 연결하지 않았습니다.

## 앱과 BoAYo

앱은 기존 BoAYo SDK 또는 BOSIO 창 API를 그대로 사용합니다. 캐시나 DDR
버퍼를 직접 관리할 필요가 없습니다. BoAYo 패널·앱 창·캡션은 기존처럼
BOSIO 창 레이어에서 함께 합성됩니다.

## 드라이버 사용

```python
from bosio_driver_v2 import BosioV2

core = BosioV2('bitstream/bosio_output_disp.bit', m=16)
core.upload(rgb_cells)     # shape=(20, 211, 256, 3), uint8
core.set_pose(0, 0, wait=False)
core.start()
print(core.status())
# 종료 전 모든 DDR 읽기를 중단하고 배출한 다음 버퍼를 해제합니다.
core.close()
```

`status()`의 `ddr_cache`, `cache_line_bytes`, `cache_bytes`, `cache_ways`,
`cache_hits`, `cache_misses`, `cache_stall_cycles`로 실행 중인 구조를 확인합니다.
BS24도 지원하며, 기존 BRAM 용량을 넘는 장면은 업로드 전에 거부합니다.

BS25 드라이버는 두 개의 지속적인 DDR 장면 버퍼를 사용합니다. 전체 갱신은
비활성 버퍼를 채우고 새 메타데이터를 로드합니다. BPT1 부분 갱신은 비활성
버퍼의 변경 타일만 수정합니다. 두 경우 모두 코어가 다음 프레임 경계에서
BASE를 바꾼 것을 `0x44`로 확인한 뒤 이전 버퍼를 다시 사용할 수 있습니다.
부분 갱신 후 이전 버퍼에도 변경 타일을 반영하므로 매번 전체 장면을 복사하지
않습니다. 타일 활성 상태나 팔레트가 바뀌면 전체 갱신으로 전환합니다.

초기 `upload()` 후 `start()`가 필요합니다. 출력이 꺼진 상태에서는 프레임
경계가 오지 않으므로 초기 업로드가 대기 중인 동안 두 번째 업로드를 하면
오류가 납니다. 활성 DDR 버퍼를 다른 프로세스에서 덮어쓰면 안 됩니다.

## 빌드와 검증

```sh
git submodule update --init --recursive
# 외부 rgb2dvi IP 배치는 기존 빌드 안내를 따릅니다.
vivado -mode batch -source hw/scripts/package_output_ip.tcl
vivado -mode batch -source hw/scripts/build_output_bitstream.tcl
sh sw/native/build_pynq.sh
PYTHONPATH=sw python3 -m unittest discover -s verification -v
```

비트스트림을 다시 로드하면 센서 허브도 초기화됩니다. GY-521는 초기 약
2.6초 동안 움직이지 않아야 자이로 영점 보정이 제대로 됩니다. 이 변경은
센서 보정 알고리즘 자체를 바꾸지 않습니다.

M=32 전체 구면의 4220타일을 패킹할 수 있도록 Python·네이티브 합성기의
출력 버퍼 상한도 확장했습니다. 실제 M=32 합성 속도와 화면 처리율은 별도
측정이 필요하며, 캐시 용량만으로 성능을 판단할 수 없습니다.

## 실제 보드 결과

PYNQ-Z2, M=16, 64바이트 라인·16KiB·2-way, 100MHz에서 확인했습니다.

| 항목 | 결과 |
|---|---:|
| 전체 구면 활성 타일 | 4,220 |
| DDR 장면 길이 | 274,560워드 / 1,098,240바이트 |
| 고정 자세 출력 스트림 | 59.92FPS (2초, 120프레임) |
| 센서 자세 출력 스트림 | 59.92FPS (2초, 120프레임) |
| 고정 자세 cache hit 비율 | 99.862% |
| 한 타일 부분 갱신 | 8회, 평균 15.0ms (프레임 경계 대기 포함) |
| 통합 BRAM 사용량 | 21.5/140개, 15.36% |
| WNS / WHS | +0.111ns / +0.019ns |

위 FPS는 RTL 출력 스트림의 프레임 카운터로 측정했습니다. 화면 전체를
새로 합성하는 소프트웨어 FPS와는 다릅니다. 같은 색으로 채운 전체 구면의
주소 패턴에서 얻은 cache hit 비율이므로 모든 앱·자세·M에서 같은 값이
나오는 것은 아닙니다. 캡처보드는 사용자가 사용 중이어서 점유하지 않았습니다.
BoAYo 서비스와 SDK 창 생성도 새 드라이버에서 오류 없이 확인했습니다.

원본은 [보드 측정 JSON](../verification/results/bosio_ddr_cache_board_validation.json),
[타이밍 보고서](../verification/results/bs25_timing_summary.rpt),
[자원 보고서](../verification/results/bs25_utilization.rpt)에 있습니다.
`verification/board_ddr_cache_probe.py`는 출력 서비스를 중지한 상태에서 실행하는
검증 도구이며 FPGA를 다시 로드합니다.
