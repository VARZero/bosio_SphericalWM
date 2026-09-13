허허.. 이건 진짜 LLM이 다 해줬습니다..  
출력코어 아이디어만 던져줬었거든여

# BOSIO 구면 윈도우 매니저

PYNQ-Z2에서 정이십면체 프레임버퍼 출력 코어를 사용하는 구면 윈도우
시스템입니다. 애플리케이션은 Unix domain socket IPC를 통해 창을 생성하고
RGB surface를 갱신합니다. 윈도우 매니저는 창 겹침, 포커스, z-order, 구면
마우스와 회전을 처리한 뒤 출력 코어용 장면을 생성합니다.

이 저장소에는 실제 개발 소스, 센서 허브 RTL, 시스템 Vivado 생성 스크립트,
테스트, 벤치마크 원본과 PYNQ-Z2용 사전 빌드 파일이 함께 들어 있습니다.
RTL 출력 코어는 Git submodule로 연결된 별도 저장소인
[VARZero/bosio_OutputCore](https://github.com/VARZero/bosio_OutputCore)에서
관리합니다.

## 처리 구조

```text
애플리케이션 ─ JSON IPC ─ 구면 윈도우 데몬 ─ C++/NEON dirty 합성
                                                   │
                                                   v
                            BPT1 부분 타일 DMA ─ BS23 출력 코어 ─ HDMI
                                                   ^
GY-521 ─ I²C 센서 허브 ─ 96-bit AXI4-Stream ─ yaw/pitch/roll 자세 엔진
PYNQ BTN0..3 ─ 독립 AXI GPIO ─ Linux 버튼 입력 ─ 데몬 전역 이벤트 기록
```

창 surface의 변경 영역은 dirty rectangle로 합쳐집니다. 네이티브 합성기는
투영 LUT에서 이 영역을 참조하는 셀만 다시 계산하고, 실제 색이 바뀐 구면
타일만 `BPT1` 패킷으로 전송합니다. 창 이동, 포커스, z-order 또는 타일 활성
구조가 바뀌면 전체 snapshot으로 자동 전환합니다.

## 저장소 구성

```text
sw/
  bosio_wm_daemon.py          # system daemon과 JSON IPC 서버
  bosio_window_manager.py     # 창, 포커스, 구면 포인터 모델
  bosio_wm_client.py          # 애플리케이션용 Python SDK
  bosio_native_compositor.py  # C++ 합성기 ctypes 바인딩
  native/                     # C++17/ARM NEON 개발 소스와 빌드 스크립트
  bosio_driver_v2.py          # BS23 출력 코어 PYNQ 드라이버
  bosio_geometry_v2.py        # 정이십면체 장면 형식과 자세 계수
  bosio_mouse_input.py        # Linux evdev 마우스 입력
  bosio_buttons.py            # 독립 /dev/mem 버튼 입력과 디바운스
  bosio_wm_demo.py            # 네 개의 예제 창
  bosio_wm_image_demo.py      # 1초마다 이미지 변경·클릭 좌표 예제
  bosio_wm_benchmark.py       # 실제 보드 성능 측정 도구
  bosio-window-manager.service
  install_bosio_boot.sh       # 부팅 자동 실행 설치 및 상태 검사
  bitstream/                  # 검증된 PYNQ-Z2 bitstream/HWH
docs/                         # 설계, IPC, 설치, 성능 문서
verification/                 # 단위 테스트와 보드 벤치마크 원본
hw/
  ip_repo/bosio_sensor_hub_mpu6050_1.0/  # GY-521 직접 I²C/AXI4-Stream RTL
  ip_repo/bosio_output_core_1.0/          # 출력 코어 Git submodule
  scripts/                                # Vivado IP 패키징 및 시스템 빌드 Tcl
  constrs/                                # PYNQ-Z2 HDMI·Pmod·버튼 핀 제약
```

Vivado 프로젝트 캐시, SDK 임시 파일, 캡처 이미지, 개인 배포 스크립트와 접속
정보는 저장소에 포함하지 않습니다.

## PYNQ-Z2 설치

저장소를 보드로 복제한 뒤 다음을 실행합니다.

```bash
git clone --recursive https://github.com/VARZero/bosio_SphericalWM.git
cd bosio_SphericalWM/sw
sudo sh ./install_bosio_boot.sh
```

설치 스크립트는 파일을 `/home/xilinx/bosio_v2`에 배치하고
`bosio-window-manager.service`를 활성화합니다. 다음 부팅부터 PYNQ의
`bootpy.service`가 완료된 뒤 데몬이 `BS23` bitstream을 PL에 내려받습니다.

```bash
systemctl is-enabled bosio-window-manager.service
systemctl is-active bosio-window-manager.service
journalctl -b -u bosio-window-manager.service --no-pager
```

예제 창은 데몬과 별도 프로세스로 실행합니다.

```bash
cd /home/xilinx/bosio_v2
python3 bosio_wm_demo.py --center-elevation -59
```

가장 간단한 애플리케이션 예제는 1초마다 이미지를 바꾸고 창 안을 클릭했을
때 상대 좌표를 터미널에 출력합니다.

```bash
python3 bosio_wm_image_demo.py
```

출력 예:

```text
image frame=3
click button=left pressed=True u=0.4219 v=0.6350 pixel=(135,127) zone=content
```

## 애플리케이션 예제

```python
import numpy as np
from bosio_wm_client import BosioWMClient

with BosioWMClient("example") as wm:
    window = wm.create_window(
        "HELLO", azimuth=0, elevation=0,
        width_deg=36, height_deg=24,
        surface_width=320, surface_height=200,
    )
    image = np.zeros((200, 320, 3), dtype=np.uint8)
    image[:, :] = (32, 120, 220)
    wm.update_surface(window["window_id"], image)
```

국소 갱신은 같은 API에서 작은 배열과 좌표를 전달합니다.

```python
patch = np.full((16, 16, 3), (255, 80, 20), dtype=np.uint8)
wm.update_surface(window["window_id"], patch, x=40, y=32)
```

IPC 전체 사양은 [구면 윈도우 매니저 문서](docs/BOSIO_SPHERICAL_WINDOW_MANAGER.md),
측정 조건과 결과는 [성능 문서](docs/BOSIO_WM_PERFORMANCE.md)를 참고하십시오.
애플리케이션을 처음 작성한다면 [애플리케이션 빠른 시작](docs/BOSIO_APPLICATION_QUICKSTART.md)부터
읽으면 됩니다.
[PYNQ-Z2 버튼 입력](docs/BOSIO_BUTTONS.md)은 Linux 직접 판독과 데몬 이벤트 API를 설명합니다.

## 개발과 검증

ARM NEON 라이브러리는 PYNQ-Z2에서 빌드합니다.

```bash
cd sw
sh native/build_pynq.sh
```

호스트에서 하드웨어 비의존 단위 테스트를 실행할 수 있습니다.

```bash
python -m unittest discover -s verification -p "test_*.py" -v
python -m py_compile sw/*.py
```

전체 PYNQ-Z2 bitstream은 Vivado 2020.2에서 생성합니다. Digilent `rgb2dvi`
IP를 `hw/ip_repo/rgb2dvi`에 준비한 뒤 실행하십시오.

```powershell
vivado -mode batch -source hw/scripts/package_output_ip.tcl
vivado -mode batch -source hw/scripts/package_mpu6050_sensor_hub_ip.tcl
vivado -mode batch -source hw/scripts/build_output_bitstream.tcl
```

생성된 `.bit`와 `.hwh`는 `sw/bitstream/`에 저장됩니다. 출력 코어를 수정한
뒤에는 submodule 저장소에서 먼저 검증·커밋하고, 이 저장소의 submodule
commit을 갱신합니다.

실제 PYNQ-Z2 검증에서는 16×16 국소 변경을 평균 496워드의 부분 패킷으로
전송했고, 60 Hz paced test에서 유효 패치 58.4회/초와 HDMI 58.47 FPS를
확인했습니다.

## 호환성

- 보드: PYNQ-Z2 / Zynq-7020
- 출력 코어 ABI: `BS23`, signature `0x42533233`
- 타일 셀 분할: 기본 `M=16`, RTL 지원 `M=8/16/32`
- 출력: 1280×720 RGB24 AXI4-Stream
- 자세 입력: signed milliradian yaw/pitch/roll, 96-bit AXI4-Stream

## 라이선스와 기여

Apache License 2.0으로 배포합니다. 개발 기여와 AI 지원 내역은
[CONTRIBUTORS.md](CONTRIBUTORS.md)에 기록했습니다.
