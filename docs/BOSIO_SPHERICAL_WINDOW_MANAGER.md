# BOSIO 구면 윈도우 매니저

## 목적

`bosio-wm`은 PYNQ-Z2에서 별도 프로세스로 실행되는 사용자 공간 윈도우
데몬이다. 애플리케이션은 출력 코어나 정이십면체 장면 메모리를 직접 다루지
않고 Unix domain socket IPC를 통해 창을 만들고 표면을 갱신한다.

창과 마우스 위치는 2차원 데스크톱 좌표 대신 구면의 방위각과 고도각으로
저장된다. 방위각은 360°를 순환하고 고도각은 `-89.5°..+89.5°` 범위다.

```text
애플리케이션 A ─┐
애플리케이션 B ─┼─ JSON IPC ─ bosio-wm ─ 구면 합성 ─ 장면 DMA ─ 출력 코어 ─ HDMI
USB 마우스 ──────┘                 │                       ▲
                                   └─ 포커스·z 순서        └─ GY-521 자세 스트림
```

센서 자세는 카메라가 구면 공간을 바라보는 방향을 바꾼다. 창과 포인터의 구면
좌표는 그대로이므로 사용자가 고개를 돌리면 다른 방향에 놓인 창을 볼 수 있다.

## 구성 파일

| 파일 | 역할 |
|---|---|
| `bosio_window_manager.py` | 창 상태, z 순서, 포커스, hit-test, 구면 합성기 |
| `bosio_wm_daemon.py` | Unix socket 서버, 출력 코어 갱신 루프 |
| `bosio_wm_client.py` | 애플리케이션용 Python IPC SDK |
| `bosio_mouse_input.py` | Linux evdev 상대 좌표 마우스 입력 |
| `bosio_native_compositor.py` | C++/NEON 합성기 ctypes 바인딩 |
| `native/bosio_compositor.cpp` | LUT 합성·포인터·RGB332 네이티브 엔진 |
| `bosio_wm_demo.py` | 서로 겹치는 네 개 창 예제ㄷ |
| `bosio-window-manager.service` | systemd 서비스 예제 |

## 창 모델과 겹침

각 창은 다음 상태를 가진다.

- 소유 애플리케이션과 정수 `window_id`
- 중심 방위각·고도각과 창의 roll
- 각도 단위 너비·높이
- RGB888 애플리케이션 표면
- 표시 여부와 전역 z 순서

합성기는 낮은 z부터 높은 z까지 정이십면체의 모든 작은 삼각형 셀 중심을 창
평면에 역투영한다. 나중에 그린 창이 앞에 표시된다. 포인터 hit-test도 같은
투영식을 사용하므로 보이는 최상위 창과 입력을 받는 창이 일치한다.

창을 만들그것면 해당 창이 포커스를 받는다. 창 내부를 왼쪽 클릭하면 창이 앞으로
올라오고 포커스를 받는다. 제목 표시줄을 드래그하면 창 중심이 구면을 따라
이동한다. 포커스 창은 노란 테두리로 표시된다.

IPC 연결이 끊기면 그 연결의 애플리케이션이 소유한 창은 자동으로 제거된다.
다른 애플리케이션은 표면 변경이나 창 파괴를 할 수 없다.

## 구면 마우스

`--mouse auto`로 실행하면 `/dev/input/by-id/*-event-mouse` 또는 이름에
`mouse`가 포함된 evdev 장치를 찾는다. 상대 X 이동은 방위각, 상대 Y 이동은
고도각 변화로 변환한다. 방위각은 `+180°`와 `-180°` 경계를 이어서 이동하며,
고도각만 극점 직전에서 제한된다.

```bash
python3 bosio_wm_daemon.py \
  --bit bitstream/bosio_output_disp.bit \
  --m 16 --fps 12 --mouse auto --mouse-sensitivity 0.12 \
  --socket-group xilinx
```

PYNQ-Z2 자동 시작 서비스는 고DPI Logitech G102 마우스 실측에 맞춰
`--mouse-sensitivity 0.03`을 사용한다. 마우스가 서비스 시작 후 연결되었다면
`bosio-window-manager.service`와 `boayo-desktop.service`를 다시 시작해야
evdev 입력 장치가 연결된다. 다른 마우스는 이 값을 조정할 수 있다.

마우스 장치가 없더라도 IPC의 `pointer_warp()`와 `pointer_move()`는 사용할 수
있다. 포인터는 구면 공간에 남아 있고 센서로 시점을 돌려 다시 볼 수 있다.

## 애플리케이션 API

```python
import numpy as np
from bosio_wm_client import BosioWMClient

with BosioWMClient("my-app") as wm:
    win = wm.create_window(
        "MY WINDOW", azimuth=35, elevation=8,
        width_deg=32, height_deg=22,
        surface_width=320, surface_height=200,
    )
    window_id = win["window_id"]

    image = np.zeros((200, 320, 3), dtype=np.uint8)
    image[..., 1] = 160
    wm.update_surface(window_id, image)

    wm.configure_window(window_id, azimuth=50, elevation=12)
    wm.focus_window(window_id)

    while True:
        for event in wm.poll_events():
            print(event)
```

주요 SDK 메서드는 다음과 같다.

| 메서드 | 기능 |
|---|---|
| `create_window()` | 구면 위치, 각 크기, 표면 크기로 창 생성 |
| `destroy_window()` | 소유 창 제거 |
| `configure_window()` | 위치, roll, 각 크기, 제목, 표시 상태 변경 |
| `update_surface()` | 전체 또는 일부 RGB888 사각 영역 갱신 |
| `fill()` | 표면을 단색으로 채움 |
| `focus_window()` | 포커스 지정, 기본적으로 맨 앞으로 올림 |
| `raise_window()` / `lower_window()` | z 순서 변경 |
| `pointer_warp()` | 포인터의 절대 방위각·고도각 설정 |
| `pointer_move()` | 포인터를 각도 단위로 상대 이동 |
| `pointer_button()` | 마우스 버튼 상태 전달 |
| `poll_events()` | 포커스 및 포인터 이벤트 수신 |
| `get_state()` | 전체 창, 포커스, 포인터와 출력 코어 상태 조회 |
| `set_frame_limit()` | 합성기 최대 갱신률 설정; 벤치마크·관리용 |
| `reset_performance()` | 합성 및 DMA 누적 계측 초기화 |

이벤트의 `u`, `v`는 창의 좌상단 `(0,0)`, 우하단 `(1,1)`인 정규화 좌표다.
`zone`은 `title` 또는 `content`다. 이벤트 종류는 `focus`, `pointer_motion`,
`pointer_button`이다.

`get_state()`의 `pointer.left_press_serial`은 왼쪽 버튼을 새로 누를 때마다 증가한다.
`pointer.last_left_press`에는 그 클릭 순간의 구면 위치와 창 ID(빈 공간이면 `null`)가
남는다. 짧게 눌렀다 뗀 클릭도 다른 프로세스가 다음 상태 조회에서 감지할 수 있다.

## IPC 프로토콜

기본 소켓은 `/tmp/bosio-wm.sock`이다. 한 줄에 하나의 UTF-8 JSON 요청과 응답을
사용한다. 표면 픽셀은 RGB888 바이트를 base64로 인코딩한다. 요청 크기 제한은
8 MiB다.

```json
{"id":1,"app":"example:123:abcd","op":"pointer_warp","args":{"azimuth":90,"elevation":20}}
{"id":1,"ok":true,"result":{"azimuth":90.0,"elevation":20.0,"window_id":null}}
```

소켓 권한은 `0660`이다. `--socket-group`으로 GUI 애플리케이션이 속한 전용
그룹을 지정한다. 제공된 PYNQ 서비스는 `xilinx` 그룹을 사용한다.

## PYNQ-Z2 서비스 설치

파일을 `/home/xilinx/bosio_v2`에 복사한 뒤 다음과 같이 설치한다.

```bash
sudo cp bosio-window-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bosio-window-manager.service
sudo systemctl status bosio-window-manager.service
```

배포 묶음의 `sw/` 디렉터리를 보드에 복사했다면 다음 설치 스크립트가 필요한
파일을 `/home/xilinx/bosio_v2`에 배치하고 서비스를 활성화하며, IPC와 출력
코어 상태까지 확인한다.

```bash
cd <배포 묶음>/sw
sudo sh ./install_bosio_boot.sh
```

Zynq PL 설정은 전원을 끄면 사라진다. 부팅할 때 systemd가 데몬을 시작하고,
데몬의 PYNQ `Overlay` 호출이 `BS24` bitstream을 다시 내려받는다. 서비스는
bitstream, HWH, NEON 합성 라이브러리가 모두 있을 때만 시작하며 예기치 않게
종료되면 3초 뒤 재시작한다. PYNQ의 `bootpy.service`가 기본 overlay와 부팅
스크립트를 처리한 뒤 BOSIO 서비스를 시작하도록 순서를 지정해, 두 서비스가
동시에 PL을 설정하는 부팅 경합을 막는다.

재부팅 후에는 다음 명령으로 자동 시작 여부를 확인할 수 있다.

```bash
systemctl is-enabled bosio-window-manager.service
systemctl is-active bosio-window-manager.service
journalctl -u bosio-window-manager.service -b --no-pager
```

기존 `run_gy521_direct.py` 같은 프로세스와 동시에 같은 FPGA overlay를 제어하면
안 된다. 윈도우 데몬이 실행될 때는 데몬 하나만 bitstream과 장면 DMA를
소유한다. 소켓별 lock file이 두 번째 윈도우 데몬의 동시 실행을 차단한다.

예제 창은 별도 터미널에서 실행한다.

```bash
python3 bosio_wm_demo.py
```

## 현재 구현 범위

- 창 표면과 포인터는 작은 삼각형 셀 중심 단위로 샘플링된다.
- 창 surface의 국소 변경은 dirty rectangle으로 합친 뒤 캐시된 투영 LUT에서
  해당 source 영역을 참조하는 구면 셀만 다시 합성한다.
- 합성 결과의 변경 타일만 `BPT1` 패킷으로 출력 코어에 보내며, 코어는 두 BRAM
  bank에 패치를 적용하고 프레임 경계에서 원자적으로 교체한다.
- 창 이동·크기·포커스·z-order·포인터처럼 합성 구조가 달라지거나 타일 활성
  구조가 바뀌면 자동으로 전체 장면 업로드를 사용한다.
- 키보드 입력과 텍스트 입력 프로토콜은 아직 포함하지 않았다.
- 애플리케이션 표면은 RGB888이며 알파 혼합은 아직 포함하지 않았다.
- 구면의 모든 방향에 창을 배치할 수 있지만 한 창의 각 너비는 160°, 높이는
  120°로 제한한다.

실물 PYNQ-Z2의 조건별 HDMI FPS와 장면 갱신 FPS는
`BOSIO_WM_PERFORMANCE.md`에 정리했다.

PYNQ-Z2에서는 `native/build_pynq.sh`로 ARM 공유 라이브러리를 빌드한다.
라이브러리가 있으면 데몬 상태의 `compositor`가 `cpp-neon`, 없으면 `numpy`로
표시된다.
